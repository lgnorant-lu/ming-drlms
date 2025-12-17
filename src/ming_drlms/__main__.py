# [CRITICAL] Early hijack to silence logs before application start
# This must run BEFORE 'from .main import main' which sets up logging
try:
    from ming_drlms.mcp import stdio_hijack  # noqa: F401
except ImportError:
    pass

# [DEBUG] Removed banner to prevent protocol corruption

from .main import main

if __name__ == "__main__":
    main()
