"""Phase 28: FastMCP Server Entry Point.

This module creates the FastMCP server instance and provides the entry point
for running the MCP server via stdio transport.

IMPORTANT: All logging MUST go to stderr, not stdout.
stdout is reserved for JSON-RPC protocol messages.
"""

from __future__ import annotations

import logging
import sys

# --- HARDENING: Hijack stdout BEFORE anything else ---

from mcp.server.fastmcp import FastMCP

# Configure logging to stderr (CRITICAL: never log to stdout!)
# Note: stdio_hijack uses "ming_drlms.mcp.stdout_capture"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger("ming_drlms.mcp")


# Create the FastMCP server instance
# Note: FastMCP 1.24.0 only takes name parameter in constructor
mcp = FastMCP("ming-drlms")


def run_server() -> None:
    """Run the MCP server using stdio transport.

    This function is the main entry point for the MCP server.
    It should be called from the CLI when `ming-drlms --mcp` is invoked.
    """
    logger.info("Starting ming-drlms MCP server...")

    # Import tools to register them with the server
    from . import tools  # noqa: F401

    # Run the server
    mcp.run(transport="stdio")


# Allow running directly: python -m ming_drlms.mcp.server
if __name__ == "__main__":
    run_server()
