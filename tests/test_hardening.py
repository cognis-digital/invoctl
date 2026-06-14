"""Hardening tests — edge cases, bad input, and error-path coverage."""
from __future__ import annotations

import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from tempfile import TemporaryDirectory

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from invoctl.core import (  # noqa: E402
    Invoice,
    InvoctlError,
    Ledger,
    LineItem,
    payment_link,
    render_pdf,
)
from invoctl.cli import main  # noqa: E402


# ---------------------------------------------------------------------------
# core.py hardening
# ---------------------------------------------------------------------------


class TestLineItemFromDict(unittest.TestCase):
    def test_missing_description_raises(self):
        with self.assertRaises(InvoctlError):
            LineItem.from_dict({"quantity": 1, "unit_price": "10"})

    def test_missing_unit_price_raises(self):
        with self.assertRaises(InvoctlError):
            LineItem.from_dict({"description": "x", "quantity": 1})

    def test_missing_quantity_raises(self):
        with self.assertRaises(InvoctlError):
            LineItem.from_dict({"description": "x", "unit_price": "10"})


class TestInvoiceFromDict(unittest.TestCase):
    def test_missing_number_raises(self):
        with self.assertRaises(InvoctlError):
            Invoice.from_dict(
                {
                    "client": "C",
                    "items": [
                        {"description": "x", "quantity": 1, "unit_price": "10"}
                    ],
                }
            )

    def test_missing_items_raises(self):
        with self.assertRaises(InvoctlError):
            Invoice.from_dict({"number": "N", "client": "C"})

    def test_corrupted_issued_date_raises(self):
        inv = Invoice("N", "C", [LineItem("x", 1, "5")])
        inv.issued = "not-a-date"
        with self.assertRaises(InvoctlError):
            _ = inv.due

    def test_negative_due_days_raises(self):
        with self.assertRaises(InvoctlError):
            Invoice("N", "C", [LineItem("x", 1, "5")], due_days=-1)

    def test_invalid_tax_rate_raises(self):
        with self.assertRaises(InvoctlError):
            Invoice("N", "C", [LineItem("x", 1, "5")], tax_rate="not-a-number")

    def test_whitespace_only_number_raises(self):
        with self.assertRaises(InvoctlError):
            Invoice("   ", "C", [LineItem("x", 1, "5")])


class TestPaymentLink(unittest.TestCase):
    def test_empty_base_url_raises(self):
        inv = Invoice("N", "C", [LineItem("x", 1, "5")])
        with self.assertRaises(InvoctlError):
            payment_link(inv, base_url="")

    def test_whitespace_base_url_raises(self):
        inv = Invoice("N", "C", [LineItem("x", 1, "5")])
        with self.assertRaises(InvoctlError):
            payment_link(inv, base_url="   ")


class TestRenderPdfBadPath(unittest.TestCase):
    def test_unwritable_path_raises(self):
        inv = Invoice("N", "C", [LineItem("x", 1, "5")])
        with self.assertRaises(InvoctlError):
            # A path whose parent directory does not exist should raise.
            render_pdf(inv, "/no/such/directory/output.pdf")


class TestLedgerCorruptFile(unittest.TestCase):
    def test_corrupt_json_raises(self):
        with TemporaryDirectory() as d:
            path = os.path.join(d, "bad.json")
            with open(path, "w") as fh:
                fh.write("{not valid json")
            with self.assertRaises(InvoctlError):
                Ledger(path)

    def test_empty_file_raises(self):
        with TemporaryDirectory() as d:
            path = os.path.join(d, "empty.json")
            with open(path, "w") as fh:
                fh.write("")
            with self.assertRaises(InvoctlError):
                Ledger(path)


# ---------------------------------------------------------------------------
# cli.py hardening
# ---------------------------------------------------------------------------


class TestCLIHardening(unittest.TestCase):
    def _run(self, argv):
        out_buf = StringIO()
        err_buf = StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            code = main(argv)
        return code, out_buf.getvalue(), err_buf.getvalue()

    def test_bad_item_format_exits_nonzero_with_message(self):
        """Malformed --item spec should print a clear error and exit 1."""
        with TemporaryDirectory() as d:
            ledger = os.path.join(d, "l.json")
            code, _out, err = self._run([
                "--ledger", ledger, "create",
                "--number", "X", "--client", "C",
                "--item", "no-colons-here",
            ])
            self.assertEqual(code, 1)
            self.assertIn("error:", err)

    def test_negative_due_days_exits_2(self):
        """--due-days < 0 should exit 2 with message on stderr."""
        with TemporaryDirectory() as d:
            ledger = os.path.join(d, "l.json")
            code, _out, err = self._run([
                "--ledger", ledger, "create",
                "--number", "X", "--client", "C",
                "--item", "Work:1:50",
                "--due-days", "-5",
            ])
            self.assertEqual(code, 2)
            self.assertIn("due-days", err)

    def test_show_nonexistent_exits_1_with_message(self):
        """show on missing invoice should exit 1 with clear error."""
        with TemporaryDirectory() as d:
            ledger = os.path.join(d, "l.json")
            code, _out, err = self._run(["--ledger", ledger, "show", "MISSING"])
            self.assertEqual(code, 1)
            self.assertIn("error:", err)

    def test_pdf_unwritable_path_exits_1(self):
        """pdf to an unwritable path should exit 1, not crash."""
        with TemporaryDirectory() as d:
            ledger = os.path.join(d, "l.json")
            self._run([
                "--ledger", ledger, "create",
                "--number", "P1", "--client", "C",
                "--item", "Work:1:100",
            ])
            code, _out, err = self._run([
                "--ledger", ledger, "pdf", "P1",
                "--out", "/no/such/dir/out.pdf",
            ])
            self.assertEqual(code, 1)
            self.assertIn("error:", err)

    def test_summary_empty_ledger(self):
        """summary on an empty ledger should succeed and return zeros."""
        with TemporaryDirectory() as d:
            ledger = os.path.join(d, "l.json")
            code, out, _err = self._run(
                ["--ledger", ledger, "--format", "json", "summary"]
            )
            self.assertEqual(code, 0)
            data = json.loads(out)
            self.assertEqual(data["count"], 0)
            self.assertEqual(data["outstanding"], 0)
            self.assertEqual(data["collected"], 0)

    def test_list_empty_ledger_table(self):
        """list on an empty ledger should print (none) not crash."""
        with TemporaryDirectory() as d:
            ledger = os.path.join(d, "l.json")
            code, out, _err = self._run(["--ledger", ledger, "list"])
            self.assertEqual(code, 0)
            self.assertIn("(none)", out)

    def test_zero_value_item_allowed(self):
        """An item with unit_price=0 is valid (free/promotional line)."""
        with TemporaryDirectory() as d:
            ledger = os.path.join(d, "l.json")
            code, _out, _err = self._run([
                "--ledger", ledger, "create",
                "--number", "F1", "--client", "C",
                "--item", "Promo:1:0",
            ])
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
