# MCP Server Entry Point
# 1. Auto-load .env.local for PQC configuration (LIBOQS_DIR)
try:
    from dotenv import load_dotenv

    # Look for .env.local in current working directory
    load_dotenv(".env.local")
except ImportError:
    pass

from .server import run_server

if __name__ == "__main__":
    run_server()
