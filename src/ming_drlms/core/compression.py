"""
DRLMS Compression Abstraction Layer.
Handles zstd/zlib negotiation and Python 3.14 forward compatibility.
"""

import sys
import zlib
from enum import IntEnum
from typing import Tuple, Optional

from .. import log

logger = log.get_logger("core.compression")

try:
    if sys.version_info >= (3, 14):
        import compression.zstd as zstd_lib  # Future Python 3.14
    else:
        import zstandard as zstd_lib  # PyPI package
    _ZSTD_AVAILABLE = True
except ImportError:
    zstd_lib = None
    _ZSTD_AVAILABLE = False

HAS_ZSTD = _ZSTD_AVAILABLE


class CompressionAlgo(IntEnum):
    NONE = 0
    ZLIB = 1
    ZSTD = 2


# Helper: Incompressible MIME types
_INCOMPRESSIBLE_MIME = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "audio/mpeg",
    "audio/mp4",
    "audio/ogg",
    "application/zip",
    "application/gzip",
    "application/x-7z-compressed",
    "application/vnd.rar",
}


def should_skip_compression(
    data_len: int, mime_type: Optional[str] = None, min_size: int = 128
) -> bool:
    """Determine if compression should be skipped based on size and type."""
    if data_len < min_size:
        return True

    if mime_type:
        # Simple exact match check first
        if mime_type in _INCOMPRESSIBLE_MIME:
            return True
        # Prefix check for broader categories
        if (
            mime_type.startswith("image/")
            or mime_type.startswith("video/")
            or mime_type.startswith("audio/")
        ):
            # Assume media is already compressed unless we know otherwise (e.g. bmp/wav - rare in web context)
            if not (
                mime_type.endswith("bmp")
                or mime_type.endswith("wav")
                or mime_type.endswith("svg+xml")
            ):
                return True

    return False


def compress(
    data: bytes,
    mime_type: Optional[str] = None,
    min_size: int = 128,
    min_ratio: float = 0.1,
) -> Tuple[bytes, CompressionAlgo]:
    """Smart compress data using best available algorithm.

    Args:
        data: The bytes to compress.
        mime_type: Optional MIME type to help decide skipping.
        min_size: Minimum size in bytes to attempt compression.
        min_ratio: Minimum space saving ratio (0.1 = 10% saved).
                   If saving is less than this, returns original data.

    Returns:
        (compressed_bytes, algorithm_enum)
    """
    if should_skip_compression(len(data), mime_type, min_size):
        return data, CompressionAlgo.NONE

    original_len = len(data)

    # 1. Try Zstandard (Preferred)
    if _ZSTD_AVAILABLE and zstd_lib:
        try:
            # Level 3 is a good default for speed/ratio balance
            cctx = zstd_lib.ZstdCompressor(level=3)
            compressed = cctx.compress(data)

            # Check ratio
            saved_ratio = 1.0 - (len(compressed) / original_len)
            if saved_ratio >= min_ratio:
                return compressed, CompressionAlgo.ZSTD
        except Exception as e:
            logger.warning("Zstd compression failed, falling back: %s", e)

    # 2. Try Zlib (Fallback)
    try:
        compressed = zlib.compress(data, level=6)
        saved_ratio = 1.0 - (len(compressed) / original_len)
        if saved_ratio >= min_ratio:
            return compressed, CompressionAlgo.ZLIB
    except Exception as e:
        logger.warning("Zlib compression failed: %s", e)

    # 3. Give up
    return data, CompressionAlgo.NONE


def decompress(data: bytes, algo: int) -> bytes:
    """Decompress based on algorithm ID.

    Args:
        data: Compressed bytes (or original if algo is NONE).
        algo: compression type integer (see CompressionAlgo).

    Returns:
        Decompressed bytes.

    Raises:
        ValueError: If algo is unknown or library missing.
    """
    if algo == CompressionAlgo.NONE:
        return data

    if algo == CompressionAlgo.ZSTD:
        if not _ZSTD_AVAILABLE or zstd_lib is None:
            raise ValueError(
                "Received Zstd compressed data but 'zstandard' library is not available. "
                "Install with: pip install zstandard"
            )
        try:
            dctx = zstd_lib.ZstdDecompressor()
            return dctx.decompress(data)
        except Exception as e:
            raise ValueError(f"Zstd decompression failed: {e}") from e

    if algo == CompressionAlgo.ZLIB:
        try:
            return zlib.decompress(data)
        except Exception as e:
            raise ValueError(f"Zlib decompression failed: {e}") from e

    raise ValueError(f"Unknown compression algorithm ID: {algo}")


def compress_file(
    src_path: str, dst_path: str, min_size: int = 128, min_ratio: float = 0.1
) -> Tuple[bool, CompressionAlgo]:
    """Compress file to destination.

    Returns:
        (success, algo)
        If success is False, compression was skipped (e.g. ratio too low),
        and dst_path might not be valid or identical to src.
    """
    import os

    src_size = os.path.getsize(src_path)
    if should_skip_compression(src_size, None, min_size):
        return False, CompressionAlgo.NONE

    # Valid Zstd Logic
    if _ZSTD_AVAILABLE and zstd_lib:
        try:
            cctx = zstd_lib.ZstdCompressor(level=3)
            with open(src_path, "rb") as f_in, open(dst_path, "wb") as f_out:
                cctx.copy_stream(f_in, f_out)

            dst_size = os.path.getsize(dst_path)
            ratio = 1.0 - (dst_size / src_size)
            if ratio >= min_ratio:
                return True, CompressionAlgo.ZSTD
        except Exception as e:
            logger.warning("Zstd file compression failed: %s", e)

    # Zlib fallback (simple read/write)
    try:
        with open(src_path, "rb") as f_in, open(dst_path, "wb") as f_out:
            # Zlib doesn't have a simple copy_stream, read all or chunks
            data = f_in.read()
            compressed = zlib.compress(data, level=6)
            f_out.write(compressed)

        dst_size = os.path.getsize(dst_path)
        ratio = 1.0 - (dst_size / src_size)
        if ratio >= min_ratio:
            return True, CompressionAlgo.ZLIB
    except Exception as e:
        logger.warning("Zlib file compression failed: %s", e)

    return False, CompressionAlgo.NONE


def decompress_file(src_path: str, dst_path: str, algo: int) -> None:
    """Decompress file from src to dst."""
    if algo == CompressionAlgo.NONE:
        # Just copy
        import shutil

        shutil.copy2(src_path, dst_path)
        return

    if algo == CompressionAlgo.ZSTD:
        if not _ZSTD_AVAILABLE or zstd_lib is None:
            raise ValueError("Zstd library not available")
        try:
            dctx = zstd_lib.ZstdDecompressor()
            with open(src_path, "rb") as f_in, open(dst_path, "wb") as f_out:
                dctx.copy_stream(f_in, f_out)
            return
        except Exception as e:
            raise ValueError(f"Zstd file decompression failed: {e}") from e

    if algo == CompressionAlgo.ZLIB:
        try:
            with open(src_path, "rb") as f_in, open(dst_path, "wb") as f_out:
                data = f_in.read()
                decompressed = zlib.decompress(data)
                f_out.write(decompressed)
            return
        except Exception as e:
            raise ValueError(f"Zlib file decompression failed: {e}") from e

    raise ValueError(f"Unknown compression algorithm ID: {algo}")
