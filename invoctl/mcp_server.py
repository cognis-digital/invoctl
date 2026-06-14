"""INVOCTL MCP server — exposes ledger operations as MCP tools for Cognis.Studio."""
from __future__ import annotations

import json

from invoctl.core import InvoctlError, Ledger


def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-invoctl[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore[import]
    except Exception:  # noqa: BLE001
        print("Install the MCP extra: pip install 'cognis-invoctl[mcp]'")
        return 1
    app = FastMCP("invoctl")

    @app.tool()
    def invoctl_list(ledger_path: str = "invoctl_ledger.json") -> str:
        """List all invoices in the ledger as JSON."""
        try:
            led = Ledger(ledger_path)
            return json.dumps(led.list(), indent=2)
        except InvoctlError as exc:
            return json.dumps({"error": str(exc)})

    @app.tool()
    def invoctl_summary(ledger_path: str = "invoctl_ledger.json") -> str:
        """Return outstanding/collected summary for the ledger as JSON."""
        try:
            led = Ledger(ledger_path)
            return json.dumps(led.summary(), indent=2)
        except InvoctlError as exc:
            return json.dumps({"error": str(exc)})

    app.run()
    return 0
