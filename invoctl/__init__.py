"""INVOCTL - single-binary freelancer invoicing CLI.

Generate invoices, payment links, and PDF documents backed by a local
JSON ledger. Zero SaaS, zero dependencies, standard library only.
"""
from invoctl.core import (
    Invoice,
    LineItem,
    Ledger,
    InvoctlError,
    compute_totals,
    payment_link,
    render_pdf,
    render_text,
)

TOOL_NAME = "invoctl"
TOOL_VERSION = "1.0.0"

__all__ = [
    "Invoice",
    "LineItem",
    "Ledger",
    "InvoctlError",
    "compute_totals",
    "payment_link",
    "render_pdf",
    "render_text",
    "TOOL_NAME",
    "TOOL_VERSION",
]
