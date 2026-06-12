"""Core invoicing engine for INVOCTL.

Real logic: money math with cents-precision rounding, a JSON file ledger
with atomic writes, payment-link generation, and a minimal valid PDF
writer built from scratch (no third-party libs).
"""
from __future__ import annotations

import json
import os
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List


class InvoctlError(Exception):
    """Raised for any recoverable invoicing error."""


def _money(value: Any) -> Decimal:
    """Coerce a value to a 2-decimal-place Decimal, rounding half up."""
    try:
        d = Decimal(str(value))
    except Exception as exc:  # noqa: BLE001
        raise InvoctlError(f"invalid money value: {value!r}") from exc
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _f(d: Decimal) -> float:
    return float(d)


@dataclass
class LineItem:
    description: str
    quantity: Decimal
    unit_price: Decimal

    def __post_init__(self) -> None:
        if not self.description:
            raise InvoctlError("line item description is required")
        self.quantity = Decimal(str(self.quantity))
        if self.quantity <= 0:
            raise InvoctlError("line item quantity must be > 0")
        self.unit_price = _money(self.unit_price)
        if self.unit_price < 0:
            raise InvoctlError("line item unit_price must be >= 0")

    @property
    def amount(self) -> Decimal:
        return _money(self.quantity * self.unit_price)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "quantity": _f(self.quantity),
            "unit_price": _f(self.unit_price),
            "amount": _f(self.amount),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LineItem":
        return cls(
            description=d["description"],
            quantity=d["quantity"],
            unit_price=d["unit_price"],
        )


@dataclass
class Invoice:
    number: str
    client: str
    items: List[LineItem]
    currency: str = "USD"
    tax_rate: Decimal = Decimal("0")  # percent, e.g. 8.25
    discount: Decimal = Decimal("0")  # flat amount off subtotal
    issued: str = field(default_factory=lambda: date.today().isoformat())
    due_days: int = 30
    notes: str = ""
    status: str = "draft"  # draft | sent | paid

    def __post_init__(self) -> None:
        if not self.number:
            raise InvoctlError("invoice number is required")
        if not self.client:
            raise InvoctlError("client is required")
        if not self.items:
            raise InvoctlError("invoice needs at least one line item")
        self.tax_rate = Decimal(str(self.tax_rate))
        self.discount = _money(self.discount)
        if self.tax_rate < 0:
            raise InvoctlError("tax_rate must be >= 0")
        if self.discount < 0:
            raise InvoctlError("discount must be >= 0")
        if self.status not in ("draft", "sent", "paid"):
            raise InvoctlError(f"invalid status: {self.status}")

    @property
    def due(self) -> str:
        issued = datetime.strptime(self.issued, "%Y-%m-%d").date()
        return (issued + timedelta(days=self.due_days)).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        totals = compute_totals(self)
        return {
            "number": self.number,
            "client": self.client,
            "currency": self.currency,
            "issued": self.issued,
            "due": self.due,
            "due_days": self.due_days,
            "tax_rate": _f(self.tax_rate),
            "discount": _f(self.discount),
            "notes": self.notes,
            "status": self.status,
            "items": [it.to_dict() for it in self.items],
            **totals,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Invoice":
        return cls(
            number=d["number"],
            client=d["client"],
            items=[LineItem.from_dict(i) for i in d["items"]],
            currency=d.get("currency", "USD"),
            tax_rate=d.get("tax_rate", 0),
            discount=d.get("discount", 0),
            issued=d.get("issued", date.today().isoformat()),
            due_days=d.get("due_days", 30),
            notes=d.get("notes", ""),
            status=d.get("status", "draft"),
        )


def compute_totals(inv: Invoice) -> Dict[str, float]:
    """Subtotal, discount, tax, and grand total in cents-accurate math."""
    subtotal = _money(sum((it.amount for it in inv.items), Decimal("0")))
    discount = _money(min(inv.discount, subtotal))
    taxable = subtotal - discount
    tax = _money(taxable * inv.tax_rate / Decimal("100"))
    total = _money(taxable + tax)
    return {
        "subtotal": _f(subtotal),
        "discount_applied": _f(discount),
        "tax": _f(tax),
        "total": _f(total),
    }


def payment_link(inv: Invoice, base_url: str = "https://pay.invoctl.local/checkout") -> str:
    """Build a deterministic, shareable payment URL with query params.

    No network call; this encodes the invoice into a checkout URL that a
    payment processor endpoint could consume.
    """
    totals = compute_totals(inv)
    params = {
        "invoice": inv.number,
        "client": inv.client,
        "amount": f"{totals['total']:.2f}",
        "currency": inv.currency,
        "due": inv.due,
    }
    query = urllib.parse.urlencode(params)
    return f"{base_url}?{query}"


def render_text(inv: Invoice) -> str:
    """Human-readable plaintext invoice."""
    t = compute_totals(inv)
    lines = []
    lines.append(f"INVOICE {inv.number}    [{inv.status.upper()}]")
    lines.append(f"Bill To: {inv.client}")
    lines.append(f"Issued: {inv.issued}    Due: {inv.due}")
    lines.append("-" * 56)
    lines.append(f"{'Description':<30}{'Qty':>6}{'Unit':>10}{'Amount':>10}")
    for it in inv.items:
        lines.append(
            f"{it.description[:30]:<30}{_f(it.quantity):>6g}"
            f"{_f(it.unit_price):>10.2f}{_f(it.amount):>10.2f}"
        )
    lines.append("-" * 56)
    lines.append(f"{'Subtotal':>46}{t['subtotal']:>10.2f}")
    if t["discount_applied"]:
        lines.append(f"{'Discount':>46}{-t['discount_applied']:>10.2f}")
    lines.append(f"{'Tax (' + format(_f(inv.tax_rate), 'g') + '%)':>46}{t['tax']:>10.2f}")
    lines.append(f"{'TOTAL ' + inv.currency:>46}{t['total']:>10.2f}")
    if inv.notes:
        lines.append("")
        lines.append(f"Notes: {inv.notes}")
    return "\n".join(lines)


def _pdf_escape(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def render_pdf(inv: Invoice, path: str) -> str:
    """Write a minimal but valid single-page PDF of the invoice.

    Builds the PDF byte structure by hand (objects + xref table) so it
    opens in any PDF reader without external dependencies.
    """
    text_lines = render_text(inv).split("\n")

    # Build the content stream: one Tj per line, 14pt leading.
    content_parts = ["BT", "/F1 10 Tf", "14 TL", "50 760 Td"]
    for ln in text_lines:
        content_parts.append(f"({_pdf_escape(ln)}) Tj")
        content_parts.append("T*")
    content_parts.append("ET")
    content = "\n".join(content_parts).encode("latin-1", "replace")

    objects: List[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
    )
    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"
    )
    objects.append(
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
        + content + b"\nendstream"
    )

    out = bytearray()
    out += b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"

    xref_pos = len(out)
    n = len(objects) + 1
    out += f"xref\n0 {n}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {n} /Root 1 0 R >>\nstartxref\n{xref_pos}\n"
        "%%EOF\n"
    ).encode()

    with open(path, "wb") as fh:
        fh.write(bytes(out))
    return path


class Ledger:
    """JSON-file invoice ledger with atomic writes."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._data: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                self._data = raw.get("invoices", {})
            except (json.JSONDecodeError, OSError) as exc:
                raise InvoctlError(f"corrupt ledger at {self.path}: {exc}") from exc

    def _save(self) -> None:
        payload = {"invoices": self._data}
        d = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def add(self, inv: Invoice) -> Invoice:
        if inv.number in self._data:
            raise InvoctlError(f"invoice {inv.number} already exists")
        self._data[inv.number] = inv.to_dict()
        self._save()
        return inv

    def get(self, number: str) -> Invoice:
        if number not in self._data:
            raise InvoctlError(f"invoice {number} not found")
        return Invoice.from_dict(self._data[number])

    def set_status(self, number: str, status: str) -> Invoice:
        inv = self.get(number)
        inv.status = status
        Invoice.__post_init__(inv)  # revalidate status
        self._data[number] = inv.to_dict()
        self._save()
        return inv

    def list(self) -> List[Dict[str, Any]]:
        return sorted(self._data.values(), key=lambda r: r["number"])

    def summary(self) -> Dict[str, Any]:
        rows = self.list()
        outstanding = sum(
            r["total"] for r in rows if r["status"] != "paid"
        )
        paid = sum(r["total"] for r in rows if r["status"] == "paid")
        return {
            "count": len(rows),
            "outstanding": round(outstanding, 2),
            "collected": round(paid, 2),
        }
