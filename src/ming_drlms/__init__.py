try:
    from ._version import __version__ as __version__  # type: ignore
except Exception:  # pragma: no cover - fallback for dev/tests without scm file
    __version__ = "0.0.0"
