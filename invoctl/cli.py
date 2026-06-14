"""Command-line interface for INVOCTL."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, List, Optional

from invoctl import TOOL_NAME, TOOL_VERSION
from invoctl.core import (
    Invoice,
    LineItem,
    Ledger,
    InvoctlError,
    payment_link,
    render_pdf,
    render_text,
)


def _parse_item(spec: str) -> LineItem:
    """Parse an item spec 'Description:qty:unit_price'."""
    parts = spec.split(":")
    if len(parts) != 3:
        raise InvoctlError(
            f"bad --item {spec!r}; expected 'Description:qty:unit_price'"
        )
    desc, qty, price = parts
    return LineItem(description=desc.strip(), quantity=qty, unit_price=price)


def _emit(obj: Any, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(obj, indent=2, sort_keys=True))
        return
    # table / text
    if isinstance(obj, str):
        print(obj)
    elif isinstance(obj, list):
        if not obj:
            print("(none)")
            return
        cols = ["number", "client", "status", "total", "currency", "due"]
        print("  ".join(c.upper() for c in cols))
        for row in obj:
            print("  ".join(str(row.get(c, "")) for c in cols))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            print(f"{k}: {v}")
    else:
        print(obj)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="CLI invoicing + payment links",
    )
    p.add_argument("--version", action="version", version=f"{TOOL_NAME} {TOOL_VERSION}")
    p.add_argument("--ledger", default="invoctl_ledger.json", help="ledger JSON path")
    p.add_argument("--format", choices=["table", "json"], default="table")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("create", help="create a new invoice")
    c.add_argument("--number", required=True)
    c.add_argument("--client", required=True)
    c.add_argument("--item", action="append", required=True,
                   help="'Description:qty:unit_price' (repeatable)")
    c.add_argument("--currency", default="USD")
    c.add_argument("--tax-rate", default="0", help="percent, e.g. 8.25")
    c.add_argument("--discount", default="0", help="flat amount off subtotal")
    c.add_argument("--due-days", type=int, default=30)
    c.add_argument("--notes", default="")

    sh = sub.add_parser("show", help="show an invoice")
    sh.add_argument("number")

    sub.add_parser("list", help="list all invoices")
    sub.add_parser("summary", help="ledger summary (outstanding/collected)")

    pl = sub.add_parser("pay-link", help="generate a payment link")
    pl.add_argument("number")
    pl.add_argument("--base-url", default="https://pay.invoctl.local/checkout")

    pdf = sub.add_parser("pdf", help="render invoice to PDF")
    pdf.add_argument("number")
    pdf.add_argument("--out", required=True)

    st = sub.add_parser("status", help="set invoice status")
    st.add_argument("number")
    st.add_argument("value", choices=["draft", "sent", "paid"])

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    fmt = args.format

    try:
        ledger = Ledger(args.ledger)

        if args.command == "create":
            if args.due_days < 0:
                print(
                    "error: --due-days must be >= 0",
                    file=sys.stderr,
                )
                return 2
            items = [_parse_item(s) for s in args.item]
            inv = Invoice(
                number=args.number,
                client=args.client,
                items=items,
                currency=args.currency,
                tax_rate=args.tax_rate,
                discount=args.discount,
                due_days=args.due_days,
                notes=args.notes,
            )
            ledger.add(inv)
            _emit(inv.to_dict() if fmt == "json" else render_text(inv), fmt)

        elif args.command == "show":
            inv = ledger.get(args.number)
            _emit(inv.to_dict() if fmt == "json" else render_text(inv), fmt)

        elif args.command == "list":
            _emit(ledger.list(), fmt)

        elif args.command == "summary":
            _emit(ledger.summary(), fmt)

        elif args.command == "pay-link":
            inv = ledger.get(args.number)
            link = payment_link(inv, args.base_url)
            _emit(
                {"invoice": inv.number, "payment_link": link}
                if fmt == "json"
                else link,
                fmt,
            )

        elif args.command == "pdf":
            inv = ledger.get(args.number)
            out = render_pdf(inv, args.out)
            _emit(
                {"invoice": inv.number, "pdf": out}
                if fmt == "json"
                else f"wrote {out}",
                fmt,
            )

        elif args.command == "status":
            inv = ledger.set_status(args.number, args.value)
            _emit(
                {"invoice": inv.number, "status": inv.status}
                if fmt == "json"
                else f"{inv.number} -> {inv.status}",
                fmt,
            )

        else:  # pragma: no cover - argparse enforces this
            parser.error("unknown command")
            return 2

    except InvoctlError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:  # unexpected I/O error (permissions, full disk, etc.)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
