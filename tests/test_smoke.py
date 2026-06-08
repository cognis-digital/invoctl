"""Smoke tests for INVOCTL. No network, stdlib only."""
import json
import os
import sys
import unittest
from io import StringIO
from contextlib import redirect_stdout
from tempfile import TemporaryDirectory

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from invoctl import TOOL_NAME, TOOL_VERSION  # noqa: E402
from invoctl.core import (  # noqa: E402
    Invoice,
    LineItem,
    Ledger,
    InvoctlError,
    compute_totals,
    payment_link,
    render_pdf,
    render_text,
)
from invoctl.cli import main  # noqa: E402


def _sample() -> Invoice:
    return Invoice(
        number="INV-1001",
        client="Acme Robotics LLC",
        items=[
            LineItem("Backend development (hrs)", 32, "95.00"),
            LineItem("Architecture consult (flat)", 1, "500.00"),
        ],
        tax_rate="8.25",
        discount="50",
        due_days=14,
    )


class TestCore(unittest.TestCase):
    def test_meta(self):
        self.assertEqual(TOOL_NAME, "invoctl")
        self.assertTrue(TOOL_VERSION)

    def test_totals_cents_accurate(self):
        t = compute_totals(_sample())
        self.assertEqual(t["subtotal"], 3540.00)
        self.assertEqual(t["discount_applied"], 50.00)
        self.assertEqual(t["tax"], 287.93)
        self.assertEqual(t["total"], 3777.93)

    def test_discount_capped_at_subtotal(self):
        inv = Invoice("X", "C", [LineItem("a", 1, "10")], discount="999")
        t = compute_totals(inv)
        self.assertEqual(t["discount_applied"], 10.00)
        self.assertEqual(t["total"], 0.00)

    def test_due_date(self):
        inv = _sample()
        inv.issued = "2026-01-01"
        self.assertEqual(inv.due, "2026-01-15")

    def test_payment_link(self):
        link = payment_link(_sample())
        self.assertIn("invoice=INV-1001", link)
        self.assertIn("amount=3777.93", link)
        self.assertTrue(link.startswith("https://"))

    def test_validation_errors(self):
        with self.assertRaises(InvoctlError):
            Invoice("N", "C", [])
        with self.assertRaises(InvoctlError):
            LineItem("a", 0, "10")
        with self.assertRaises(InvoctlError):
            LineItem("a", 1, "-5")

    def test_pdf_is_valid(self):
        with TemporaryDirectory() as d:
            out = os.path.join(d, "inv.pdf")
            render_pdf(_sample(), out)
            with open(out, "rb") as fh:
                data = fh.read()
            self.assertTrue(data.startswith(b"%PDF-1.4"))
            self.assertIn(b"%%EOF", data)
            self.assertIn(b"/Type /Catalog", data)

    def test_ledger_roundtrip(self):
        with TemporaryDirectory() as d:
            led = Ledger(os.path.join(d, "l.json"))
            led.add(_sample())
            got = led.get("INV-1001")
            self.assertEqual(got.client, "Acme Robotics LLC")
            with self.assertRaises(InvoctlError):
                led.add(_sample())  # duplicate
            led.set_status("INV-1001", "paid")
            s = led.summary()
            self.assertEqual(s["count"], 1)
            self.assertEqual(s["collected"], 3777.93)
            self.assertEqual(s["outstanding"], 0.0)

    def test_render_text(self):
        txt = render_text(_sample())
        self.assertIn("INVOICE INV-1001", txt)
        self.assertIn("3777.93", txt)


class TestCLI(unittest.TestCase):
    def _run(self, argv):
        buf = StringIO()
        with redirect_stdout(buf):
            code = main(argv)
        return code, buf.getvalue()

    def test_create_show_json(self):
        with TemporaryDirectory() as d:
            ledger = os.path.join(d, "l.json")
            code, _ = self._run([
                "--ledger", ledger, "create",
                "--number", "INV-1", "--client", "Acme",
                "--item", "Work:2:100", "--tax-rate", "10",
            ])
            self.assertEqual(code, 0)
            code, out = self._run(["--ledger", ledger, "--format", "json", "show", "INV-1"])
            self.assertEqual(code, 0)
            data = json.loads(out)
            self.assertEqual(data["total"], 220.00)
            self.assertEqual(data["number"], "INV-1")

    def test_missing_invoice_nonzero(self):
        with TemporaryDirectory() as d:
            ledger = os.path.join(d, "l.json")
            code, _ = self._run(["--ledger", ledger, "show", "NOPE"])
            self.assertEqual(code, 1)

    def test_bad_item_nonzero(self):
        with TemporaryDirectory() as d:
            ledger = os.path.join(d, "l.json")
            code, _ = self._run([
                "--ledger", ledger, "create",
                "--number", "X", "--client", "C", "--item", "bad-spec",
            ])
            self.assertEqual(code, 1)

    def test_pay_link_and_status_cli(self):
        with TemporaryDirectory() as d:
            ledger = os.path.join(d, "l.json")
            self._run([
                "--ledger", ledger, "create",
                "--number", "INV-9", "--client", "C", "--item", "A:1:50",
            ])
            code, out = self._run(["--ledger", ledger, "--format", "json", "pay-link", "INV-9"])
            self.assertEqual(code, 0)
            self.assertIn("payment_link", json.loads(out))
            code, _ = self._run(["--ledger", ledger, "status", "INV-9", "paid"])
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
