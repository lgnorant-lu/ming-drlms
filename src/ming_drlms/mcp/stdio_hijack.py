"""Phase 28: Standard Output Hijacking Defense (Transparent Proxy).
Replaces sys.stdout with a proxy that has .buffer pointing to our traffic channel.
This ensures mcp.server.stdio.stdio_server uses our channel transparently.
"""

import sys
import os
import logging
from io import RawIOBase

# Use file-based logging since console is hijacked
_hijack_logger = logging.getLogger("ming_drlms.mcp.stdio_hijack")

# Add file handler if not already present
_LOG_FILE = r"D:\dogepy\pythonProject1\schoolworks\DRLMS\.drlms\logs\hijack.log"
if not any(
    isinstance(h, logging.FileHandler) and h.baseFilename == _LOG_FILE
    for h in _hijack_logger.handlers
):
    _fh = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    _hijack_logger.addHandler(_fh)
    _hijack_logger.setLevel(logging.INFO)


def _debug(msg: str) -> None:
    """Log message to file at INFO level."""
    _hijack_logger.info(msg)


class TrafficBuffer(RawIOBase):
    """A binary buffer that writes to the REAL stdout FD."""

    def __init__(self, original_buffer):
        self._original = original_buffer
        _debug(f"TrafficBuffer created with original: {original_buffer}")

    def write(self, b):
        """Write bytes to the real stdout, filtering out Windows CR."""
        # [CRITICAL Fix] Windows TextIOWrapper adds \r\n. Windsurf hates \r.
        # We intercept binary stream and strip \r before writing to raw FD.
        if b:
            b = b.replace(b"\r\n", b"\n")

        _debug(f"TrafficBuffer.write({len(b)} bytes)")
        result = self._original.write(b)
        self._original.flush()
        return result

    def readable(self):
        return False

    def writable(self):
        return True

    def fileno(self):
        return self._original.fileno()

    def flush(self):
        self._original.flush()


class FakeStdout:
    """Fake stdout that is actually devnull but has .buffer pointing to traffic channel."""

    def __init__(self, traffic_buffer, devnull):
        self.buffer = traffic_buffer
        self._devnull = devnull
        self.encoding = "utf-8"
        self.errors = "strict"
        self.newlines = None
        self.mode = "w"
        self.name = "<stdout>"
        _debug(f"FakeStdout created: buffer={traffic_buffer}, devnull={devnull}")

    def write(self, s):
        """All text writes go to devnull (silence)."""
        return self._devnull.write(s)

    def flush(self):
        self._devnull.flush()

    def fileno(self):
        # Return the traffic FD so MCP can check it's a TTY
        return self.buffer.fileno()

    def isatty(self):
        return False

    def readable(self):
        return False

    def writable(self):
        return True

    def seekable(self):
        return False

    def close(self):
        pass

    def __getattr__(self, name):
        # Delegate unknown attributes to devnull
        return getattr(self._devnull, name)


def install_hijack() -> None:
    """Install the transparent proxy hijack."""

    _debug("=== install_hijack() START (Transparent Proxy) ===")

    # Prevent double-install
    if isinstance(sys.stdout, FakeStdout):
        _debug("Already installed (FakeStdout detected)")
        return

    try:
        # 1. Get the REAL original stdout buffer
        original_stdout = sys.__stdout__
        _debug(f"sys.__stdout__ = {original_stdout}")

        if original_stdout is None:
            _debug("sys.__stdout__ is None, using sys.stdout")
            original_stdout = sys.stdout

        if not hasattr(original_stdout, "buffer"):
            _debug("No buffer attribute, cannot proceed")
            return

        original_buffer = original_stdout.buffer
        _debug(f"original_buffer = {original_buffer}")

        # 2. Force Binary Mode on Windows
        if sys.platform == "win32":
            try:
                import msvcrt

                fd = original_buffer.fileno()
                _debug(f"Setting binary mode on FD {fd}")
                msvcrt.setmode(fd, os.O_BINARY)
                _debug("Binary mode set successfully")
            except Exception as e:
                _debug(f"Binary mode failed: {e}")

        # 3. Create the traffic buffer (wraps original)
        traffic_buffer = TrafficBuffer(original_buffer)

        # 4. Open devnull for silencing
        devnull = open(os.devnull, "w")
        _debug(f"Opened devnull: {devnull}")

        # 5. Create fake stdout with traffic buffer
        fake_stdout = FakeStdout(traffic_buffer, devnull)

        # 6. Replace sys.stdout and sys.stderr
        sys.stdout = fake_stdout
        sys.stderr = devnull
        _debug("Replaced sys.stdout with FakeStdout, sys.stderr with devnull")

        _debug("=== install_hijack() COMPLETE (Transparent Proxy) ===")

    except Exception as e:
        _debug(f"!!! install_hijack() FAILED: {e}")
        import traceback

        _debug(traceback.format_exc())


# Auto-install
install_hijack()
