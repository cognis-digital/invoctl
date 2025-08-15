"""INVOCTL MCP server — exposes scan() as an MCP tool for Cognis.Studio."""
from __future__ import annotations
from invoctl.core import scan, to_json

def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-invoctl[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print("Install the MCP extra: pip install 'cognis-invoctl[mcp]'")
        return 1
    app = FastMCP("invoctl")

    @app.tool()
    def invoctl_scan(target: str) -> str:
        """CLI invoicing + payment-link generator with PDF and a local ledger. Returns JSON findings."""
        return to_json(scan(target))

    app.run()
    return 0
