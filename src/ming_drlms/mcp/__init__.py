"""Phase 28: MCP (Model Context Protocol) Server Module.

This module provides AI Agent integration via the Model Context Protocol,
allowing Claude Desktop, Cursor, and other MCP-compatible tools to interact
with ming-drlms cryptographic functions.

Usage:
    ming-drlms --mcp           # Start MCP server
    ming-drlms mcp serve       # Start MCP server (alternative)

Components:
    - server.py: FastMCP server instance and entry point
    - tools.py: MCP tool implementations
"""

from .server import mcp, run_server

__all__ = ["mcp", "run_server"]
