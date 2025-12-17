"""Phase 28: MCP CLI Commands.

Provides CLI interface for running the MCP (Model Context Protocol) server.

Commands:
    ming-drlms mcp serve    Start MCP server (stdio transport)
"""

from __future__ import annotations

import typer

from ..i18n import t

mcp_app = typer.Typer(
    help=t("HELP.MCP.DESC"),
    context_settings={"help_option_names": ["-h", "--help"]},
)


@mcp_app.command("serve", help=t("HELP.MCP.SERVE"))
def cli_mcp_serve():
    """Start the MCP server using stdio transport.

    This starts a JSON-RPC 2.0 server that communicates via stdin/stdout.
    Use this with Claude Desktop, Cursor, or other MCP-compatible AI tools.

    Example Claude Desktop configuration:

        {
          "mcpServers": {
            "ming-drlms": {
              "command": "ming-drlms",
              "args": ["mcp", "serve"]
            }
          }
        }
    """
    from rich import print
    import sys

    # Redirect logging to stderr BEFORE importing mcp module
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    print("[dim]Starting MCP server (stdio transport)...[/dim]", file=sys.stderr)

    try:
        from ..mcp.server import run_server

        run_server()
    except ImportError as e:
        print(f"[red]MCP dependencies not installed[/red]: {e}", file=sys.stderr)
        print("Install with: pip install mcp>=1.0.0", file=sys.stderr)
        raise typer.Exit(code=1)
    except Exception as e:
        print(f"[red]MCP server error[/red]: {e}", file=sys.stderr)
        raise typer.Exit(code=2)


@mcp_app.command("list-tools", help=t("HELP.MCP.LIST_TOOLS"))
def cli_mcp_list_tools():
    """List all registered MCP tools with their descriptions."""
    from rich import print
    from rich.table import Table

    try:
        from ..mcp import tools  # noqa: F401 - registers tools

        table = Table(title="MCP Tools")
        table.add_column("Tool", style="cyan")
        table.add_column("Description", style="dim")

        # Get registered tools from FastMCP
        for tool_name in [
            "hello_world",
            "generate_identity",
            "store_secret",
            "retrieve_secret",
        ]:
            tool_fn = getattr(tools, tool_name, None)
            if tool_fn:
                doc = tool_fn.__doc__ or "No description"
                # Get first line of docstring
                first_line = doc.split("\n")[0].strip()
                table.add_row(tool_name, first_line)

        print(table)

    except ImportError as e:
        print(f"[red]MCP module not available[/red]: {e}")
        raise typer.Exit(code=1)


__all__ = ["mcp_app"]
