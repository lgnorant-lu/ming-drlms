import os
import tempfile
import pytest
import zlib
from pathlib import Path
from unittest.mock import patch

import ming_drlms.core.compression as compression


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def sample_compressible_data():
    """Data that compresses well (repeated patterns)."""
    return b"A" * 2000


@pytest.fixture
def sample_incompressible_data():
    """High-entropy data that compresses poorly."""
    return os.urandom(2000)


# ============================================================================
# Basic Compression Tests
# ============================================================================


class TestCompressFileBasic:
    """Basic functionality tests for compress_file."""

    def test_file_too_small_is_skipped(self, temp_dir):
        """Files below min_size should not be compressed."""
        f_in = temp_dir / "small.txt"
        f_out = temp_dir / "small.zst"
        f_in.write_bytes(b"tiny")  # 4 bytes

        success, algo = compression.compress_file(
            str(f_in), str(f_out), min_size=10, min_ratio=0.9
        )

        assert success is False
        assert algo == compression.CompressionAlgo.NONE
        assert not f_out.exists()

    def test_successful_compression_with_zstd(self, temp_dir, sample_compressible_data):
        """Compressible data should be successfully compressed with Zstd if available."""
        f_in = temp_dir / "data.txt"
        f_out = temp_dir / "data.zst"
        f_in.write_bytes(sample_compressible_data)

        success, algo = compression.compress_file(
            str(f_in), str(f_out), min_size=100, min_ratio=0.1
        )

        assert success is True
        assert f_out.exists()
        assert f_out.stat().st_size < len(sample_compressible_data)

        if compression.HAS_ZSTD:
            assert algo == compression.CompressionAlgo.ZSTD
        else:
            assert algo == compression.CompressionAlgo.ZLIB

    def test_zlib_fallback_when_zstd_unavailable(
        self, temp_dir, sample_compressible_data
    ):
        """When Zstd is not available, should fall back to Zlib."""
        f_in = temp_dir / "zlib_data.txt"
        f_out = temp_dir / "data.zlib"
        f_in.write_bytes(sample_compressible_data)

        with patch("ming_drlms.core.compression._ZSTD_AVAILABLE", False):
            success, algo = compression.compress_file(
                str(f_in), str(f_out), min_size=100, min_ratio=0.9
            )

        assert success is True
        assert algo == compression.CompressionAlgo.ZLIB
        assert f_out.exists()
        assert f_out.stat().st_size < len(sample_compressible_data)


# ============================================================================
# Compression Ratio Tests
# ============================================================================


class TestCompressFileRatio:
    """Tests for compression ratio threshold behavior."""

    def test_poor_ratio_skips_compression(self, temp_dir):
        """When compression doesn't save enough, it should be skipped."""
        f_in = temp_dir / "random.bin"
        f_out = temp_dir / "random.zst"

        # Use incompressible data
        data = os.urandom(2048)
        f_in.write_bytes(data)

        # Request impossibly high ratio (99.99% reduction required)
        # Even highly compressible data can't achieve this
        success, algo = compression.compress_file(
            str(f_in), str(f_out), min_size=100, min_ratio=0.9999
        )

        # With such a strict ratio, no real-world compression can succeed
        assert success is False
        assert algo == compression.CompressionAlgo.NONE
        # Output file should not exist (or be deleted) when ratio check fails
        # Note: Current implementation may leave file; check logic

    def test_compressible_data_passes_moderate_ratio(self, temp_dir):
        """Highly compressible data should pass a reasonable ratio threshold."""
        f_in = temp_dir / "compressible.txt"
        f_out = temp_dir / "compressible.zst"

        # Repeated patterns compress extremely well (often >90% reduction)
        data = b"ABCDEFGH" * 500  # 4000 bytes, very compressible
        f_in.write_bytes(data)

        success, algo = compression.compress_file(
            str(f_in),
            str(f_out),
            min_size=100,
            min_ratio=0.8,  # 80% reduction
        )

        assert success is True
        assert algo != compression.CompressionAlgo.NONE
        assert f_out.exists()

        # Verify actual ratio achieved
        ratio = 1.0 - (f_out.stat().st_size / f_in.stat().st_size)
        assert ratio >= 0.8, f"Expected ratio >= 0.8, got {ratio}"

    def test_exact_ratio_boundary(self, temp_dir):
        """Test behavior at exact ratio boundary."""
        f_in = temp_dir / "boundary.txt"
        f_out = temp_dir / "boundary.zst"

        # Create data that compresses to approximately known ratio
        # Repeated patterns compress very well
        data = b"ABCD" * 500  # 2000 bytes, should compress to ~100 bytes
        f_in.write_bytes(data)

        success, algo = compression.compress_file(
            str(f_in),
            str(f_out),
            min_size=100,
            min_ratio=0.9,  # 90% reduction
        )

        # This should succeed as repeated data compresses very well
        assert success is True
        assert algo != compression.CompressionAlgo.NONE


# ============================================================================
# Decompression Tests
# ============================================================================


class TestDecompressFile:
    """Tests for decompress_file functionality."""

    def test_decompress_zstd(self, temp_dir, sample_compressible_data):
        """Zstd compressed data should decompress correctly."""
        if not compression.HAS_ZSTD:
            pytest.skip("Zstd not available")

        f_in = temp_dir / "orig.txt"
        f_enc = temp_dir / "enc.zst"
        f_dec = temp_dir / "dec.txt"
        f_in.write_bytes(sample_compressible_data)

        # Compress
        success, algo = compression.compress_file(str(f_in), str(f_enc))
        assert success and algo == compression.CompressionAlgo.ZSTD

        # Decompress
        compression.decompress_file(str(f_enc), str(f_dec), algo)

        assert f_dec.exists()
        assert f_dec.read_bytes() == sample_compressible_data

    def test_decompress_zlib(self, temp_dir, sample_compressible_data):
        """Zlib compressed data should decompress correctly."""
        f_in = temp_dir / "orig_zlib.txt"
        f_enc = temp_dir / "enc.zlib"
        f_dec = temp_dir / "dec_zlib.txt"
        f_in.write_bytes(sample_compressible_data)

        # Force Zlib compression
        with patch("ming_drlms.core.compression._ZSTD_AVAILABLE", False):
            success, algo = compression.compress_file(str(f_in), str(f_enc))
            assert success and algo == compression.CompressionAlgo.ZLIB

        # Decompress
        compression.decompress_file(
            str(f_enc), str(f_dec), compression.CompressionAlgo.ZLIB
        )

        assert f_dec.exists()
        assert f_dec.read_bytes() == sample_compressible_data

    def test_decompress_with_wrong_algo_raises(self, temp_dir):
        """Using wrong decompression algorithm should raise an error."""
        f_enc = temp_dir / "fake.bin"
        f_dec = temp_dir / "bad.txt"
        f_enc.write_bytes(b"not compressed data")

        with pytest.raises(Exception):
            compression.decompress_file(
                str(f_enc), str(f_dec), compression.CompressionAlgo.ZLIB
            )


# ============================================================================
# Edge Cases
# ============================================================================


class TestEdgeCases:
    """Edge case and error handling tests."""

    def test_compress_nonexistent_file(self, temp_dir):
        """Compressing a missing file should raise OSError."""
        with pytest.raises(OSError):
            compression.compress_file(
                str(temp_dir / "missing.txt"), str(temp_dir / "out.zst")
            )

    def test_compress_empty_file(self, temp_dir):
        """Empty files should be skipped (size < min_size)."""
        f_in = temp_dir / "empty.txt"
        f_out = temp_dir / "empty.zst"
        f_in.write_bytes(b"")

        success, algo = compression.compress_file(
            str(f_in), str(f_out), min_size=1, min_ratio=0.9
        )

        assert success is False
        assert algo == compression.CompressionAlgo.NONE

    def test_decompress_empty_file(self, temp_dir):
        """Decompressing empty compressed file (edge case)."""
        f_enc = temp_dir / "empty.zlib"
        f_dec = temp_dir / "empty_out.txt"

        # Create a valid empty zlib stream
        f_enc.write_bytes(zlib.compress(b""))

        compression.decompress_file(
            str(f_enc), str(f_dec), compression.CompressionAlgo.ZLIB
        )

        assert f_dec.exists()
        assert f_dec.read_bytes() == b""

    def test_decompress_truncated_file(self, temp_dir):
        """Truncated compressed file should raise error."""
        f_enc = temp_dir / "truncated.zlib"
        f_dec = temp_dir / "truncated_out.txt"

        # Create truncated zlib data
        full_data = zlib.compress(b"A" * 1000)
        f_enc.write_bytes(full_data[: len(full_data) // 2])

        with pytest.raises(Exception):
            compression.decompress_file(
                str(f_enc), str(f_dec), compression.CompressionAlgo.ZLIB
            )

    def test_decompress_corrupted_file(self, temp_dir):
        """Corrupted compressed file should raise error."""
        f_enc = temp_dir / "corrupted.zlib"
        f_dec = temp_dir / "corrupted_out.txt"

        # Create corrupted zlib data
        valid_data = zlib.compress(b"A" * 1000)
        corrupted = bytearray(valid_data)
        corrupted[len(corrupted) // 2] ^= 0xFF  # Flip bits in middle
        f_enc.write_bytes(bytes(corrupted))

        with pytest.raises(Exception):
            compression.decompress_file(
                str(f_enc), str(f_dec), compression.CompressionAlgo.ZLIB
            )

    def test_compress_to_existing_output_overwrites(
        self, temp_dir, sample_compressible_data
    ):
        """Compressing to existing output path should overwrite."""
        f_in = temp_dir / "input.txt"
        f_out = temp_dir / "output.zst"

        f_in.write_bytes(sample_compressible_data)
        f_out.write_bytes(b"old content")

        success, algo = compression.compress_file(str(f_in), str(f_out))

        assert success is True
        assert f_out.read_bytes() != b"old content"


# ============================================================================
# Configuration Tests
# ============================================================================


class TestCompressionConfiguration:
    """Tests for compression configuration handling."""

    def test_default_min_size(self, temp_dir):
        """Test default min_size parameter (should be 128)."""
        f_in = temp_dir / "small.txt"
        f_out = temp_dir / "small.zst"
        f_in.write_bytes(b"A" * 100)  # Below default 128

        success, algo = compression.compress_file(str(f_in), str(f_out))

        # With default min_size=128, 100 bytes should be skipped
        assert success is False

    def test_default_min_ratio(self, temp_dir, sample_compressible_data):
        """Test default min_ratio parameter."""
        f_in = temp_dir / "data.txt"
        f_out = temp_dir / "data.zst"
        f_in.write_bytes(sample_compressible_data)

        success, algo = compression.compress_file(str(f_in), str(f_out))

        # Compressible data with default ratio should succeed
        assert success is True


# ============================================================================
# Algorithm Detection Tests
# ============================================================================


class TestAlgorithmDetection:
    """Tests for algorithm availability detection."""

    def test_has_zstd_constant_matches_availability(self):
        """HAS_ZSTD constant should match actual availability."""
        import importlib.util

        zstd_available = importlib.util.find_spec("zstandard") is not None
        assert compression.HAS_ZSTD is zstd_available

    def test_compression_algo_enum_values(self):
        """Verify CompressionAlgo enum values match protocol definition."""
        assert compression.CompressionAlgo.NONE == 0
        assert compression.CompressionAlgo.ZLIB == 1
        assert compression.CompressionAlgo.ZSTD == 2


# ============================================================================
# Integration-style Tests
# ============================================================================


class TestRoundTrip:
    """Round-trip compression/decompression tests."""

    @pytest.mark.parametrize("size", [200, 1024, 10240, 102400])
    def test_roundtrip_various_sizes(self, temp_dir, size):
        """Test roundtrip for various file sizes."""
        data = b"X" * size
        f_in = temp_dir / f"input_{size}.txt"
        f_enc = temp_dir / f"enc_{size}.zst"
        f_dec = temp_dir / f"dec_{size}.txt"
        f_in.write_bytes(data)

        success, algo = compression.compress_file(
            str(f_in), str(f_enc), min_size=100, min_ratio=0.1
        )
        assert success is True

        compression.decompress_file(str(f_enc), str(f_dec), algo)
        assert f_dec.read_bytes() == data

    @pytest.mark.parametrize(
        "algo_to_use",
        [
            compression.CompressionAlgo.ZLIB,
            compression.CompressionAlgo.ZSTD,
        ],
    )
    def test_roundtrip_each_algorithm(
        self, temp_dir, sample_compressible_data, algo_to_use
    ):
        """Test roundtrip for each compression algorithm."""
        if algo_to_use == compression.CompressionAlgo.ZSTD and not compression.HAS_ZSTD:
            pytest.skip("Zstd not available")

        f_in = temp_dir / "input.txt"
        f_enc = temp_dir / "enc.bin"
        f_dec = temp_dir / "dec.txt"
        f_in.write_bytes(sample_compressible_data)

        # Force specific algorithm
        if algo_to_use == compression.CompressionAlgo.ZLIB:
            with patch("ming_drlms.core.compression._ZSTD_AVAILABLE", False):
                success, algo = compression.compress_file(str(f_in), str(f_enc))
        else:
            success, algo = compression.compress_file(str(f_in), str(f_enc))

        assert success is True
        assert algo == algo_to_use

        compression.decompress_file(str(f_enc), str(f_dec), algo)
        assert f_dec.read_bytes() == sample_compressible_data


# ============================================================================
# MIME Type Skip Tests
# ============================================================================


class TestMimeTypeSkip:
    """Tests for should_skip_compression MIME type handling."""

    @pytest.mark.parametrize(
        "mime_type",
        [
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/webp",
            "video/mp4",
            "video/webm",
            "audio/mpeg",
            "audio/ogg",
            "application/zip",
            "application/gzip",
        ],
    )
    def test_incompressible_mime_types_are_skipped(self, mime_type):
        """Known incompressible MIME types should be skipped."""
        assert compression.should_skip_compression(1000, mime_type) is True

    @pytest.mark.parametrize(
        "mime_type",
        [
            "text/plain",
            "text/html",
            "application/json",
            "application/xml",
            "text/css",
            "application/javascript",
        ],
    )
    def test_compressible_mime_types_are_not_skipped(self, mime_type):
        """Compressible MIME types should not be skipped."""
        assert compression.should_skip_compression(1000, mime_type) is False

    def test_uncompressed_media_formats_not_skipped(self):
        """BMP, WAV, SVG should not be skipped (uncompressed formats)."""
        assert compression.should_skip_compression(1000, "image/bmp") is False
        assert compression.should_skip_compression(1000, "audio/wav") is False
        assert compression.should_skip_compression(1000, "image/svg+xml") is False

    def test_none_mime_type_not_skipped(self):
        """None MIME type should not trigger skip."""
        assert compression.should_skip_compression(1000, None) is False

    def test_min_size_respected_with_mime(self):
        """MIME type check should still respect min_size."""
        # Even compressible MIME, but too small
        assert (
            compression.should_skip_compression(50, "text/plain", min_size=100) is True
        )


# ============================================================================
# In-Memory Compress/Decompress Tests
# ============================================================================


class TestInMemoryCompression:
    """Tests for the in-memory compress() and decompress() functions."""

    def test_compress_returns_original_when_too_small(self):
        """Small data should return original unchanged."""
        data = b"hi"
        result, algo = compression.compress(data, min_size=10)
        assert result == data
        assert algo == compression.CompressionAlgo.NONE

    def test_compress_with_incompressible_mime(self):
        """Incompressible MIME should return original."""
        data = b"A" * 1000
        result, algo = compression.compress(data, mime_type="image/jpeg")
        assert result == data
        assert algo == compression.CompressionAlgo.NONE

    def test_compress_success_returns_smaller_data(self):
        """Compressible data should return smaller result."""
        data = b"X" * 1000
        result, algo = compression.compress(data, min_size=100, min_ratio=0.1)
        assert len(result) < len(data)
        assert algo != compression.CompressionAlgo.NONE

    def test_decompress_none_returns_original(self):
        """Decompress with NONE algo returns data unchanged."""
        data = b"original"
        result = compression.decompress(data, compression.CompressionAlgo.NONE)
        assert result == data

    def test_decompress_invalid_algo_raises(self):
        """Unknown algorithm ID should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown compression algorithm"):
            compression.decompress(b"data", 99)

    def test_decompress_zstd_unavailable_raises(self):
        """Zstd decompress should fail gracefully when unavailable."""
        with patch("ming_drlms.core.compression._ZSTD_AVAILABLE", False), patch(
            "ming_drlms.core.compression.zstd_lib", None
        ):
            with pytest.raises(ValueError, match="zstandard.*not available"):
                compression.decompress(b"data", compression.CompressionAlgo.ZSTD)

    def test_decompress_corrupted_zlib_raises(self):
        """Corrupted zlib data should raise ValueError."""
        with pytest.raises(ValueError, match="Zlib decompression failed"):
            compression.decompress(b"not valid zlib", compression.CompressionAlgo.ZLIB)

    def test_roundtrip_in_memory(self):
        """Compress then decompress should restore original."""
        data = b"Hello " * 500
        compressed, algo = compression.compress(data, min_size=100, min_ratio=0.1)
        assert algo != compression.CompressionAlgo.NONE

        decompressed = compression.decompress(compressed, algo)
        assert decompressed == data


# ============================================================================
# Decompress File Edge Cases
# ============================================================================


class TestDecompressFileEdgeCases:
    """Edge cases for decompress_file function."""

    def test_decompress_file_none_algo_copies(self, temp_dir):
        """NONE algorithm should just copy the file."""
        src = temp_dir / "src.txt"
        dst = temp_dir / "dst.txt"
        src.write_bytes(b"original content")

        compression.decompress_file(
            str(src), str(dst), compression.CompressionAlgo.NONE
        )

        assert dst.exists()
        assert dst.read_bytes() == b"original content"

    def test_decompress_file_unknown_algo_raises(self, temp_dir):
        """Unknown algorithm ID should raise ValueError."""
        src = temp_dir / "src.txt"
        dst = temp_dir / "dst.txt"
        src.write_bytes(b"data")

        with pytest.raises(ValueError, match="Unknown compression algorithm"):
            compression.decompress_file(str(src), str(dst), 99)

    def test_decompress_file_zstd_unavailable_raises(self, temp_dir):
        """Zstd decompress_file should fail gracefully when unavailable."""
        src = temp_dir / "src.zst"
        dst = temp_dir / "dst.txt"
        src.write_bytes(b"fake zstd data")

        with patch("ming_drlms.core.compression._ZSTD_AVAILABLE", False), patch(
            "ming_drlms.core.compression.zstd_lib", None
        ):
            with pytest.raises(ValueError, match="Zstd library not available"):
                compression.decompress_file(
                    str(src), str(dst), compression.CompressionAlgo.ZSTD
                )


# ============================================================================
# Compress File Edge Cases
# ============================================================================


class TestCompressFileEdgeCases:
    """Edge cases for compress_file function."""

    def test_compress_file_nonexistent_source_raises(self, temp_dir):
        """Compressing nonexistent file should raise OSError."""
        with pytest.raises(OSError):
            compression.compress_file(
                str(temp_dir / "nonexistent.txt"), str(temp_dir / "out.zst")
            )

    def test_compress_file_zlib_fallback_on_zstd_error(self, temp_dir):
        """If Zstd fails, should fall back to Zlib."""
        src = temp_dir / "data.txt"
        dst = temp_dir / "data.zst"
        src.write_bytes(b"B" * 2000)

        # Mock Zstd to raise an exception
        with patch("ming_drlms.core.compression._ZSTD_AVAILABLE", True), patch(
            "ming_drlms.core.compression.zstd_lib"
        ) as mock_zstd:
            mock_zstd.ZstdCompressor.return_value.copy_stream.side_effect = Exception(
                "Zstd error"
            )

            success, algo = compression.compress_file(str(src), str(dst))

            assert success is True
            assert algo == compression.CompressionAlgo.ZLIB

    def test_compress_file_both_fail_returns_none(self, temp_dir):
        """If both Zstd and Zlib fail, should return NONE."""
        src = temp_dir / "data.txt"
        dst = temp_dir / "data.zst"
        src.write_bytes(b"C" * 2000)

        with patch("ming_drlms.core.compression._ZSTD_AVAILABLE", True), patch(
            "ming_drlms.core.compression.zstd_lib"
        ) as mock_zstd, patch("zlib.compress") as mock_zlib:
            mock_zstd.ZstdCompressor.return_value.copy_stream.side_effect = Exception(
                "Zstd error"
            )
            mock_zlib.side_effect = Exception("Zlib error")

            success, algo = compression.compress_file(str(src), str(dst))

            assert success is False
            assert algo == compression.CompressionAlgo.NONE


# ============================================================================
# Exception Logging Path Tests (Coverage Enhancement)
# ============================================================================


class TestExceptionLoggingPaths:
    """Tests to cover exception logging paths in compression module."""

    def test_compress_zstd_exception_logs_and_falls_back(self):
        """When Zstd compress raises, should log warning and fall back to Zlib."""
        data = b"X" * 1000

        with patch("ming_drlms.core.compression._ZSTD_AVAILABLE", True), patch(
            "ming_drlms.core.compression.zstd_lib"
        ) as mock_zstd:
            mock_zstd.ZstdCompressor.return_value.compress.side_effect = Exception(
                "Zstd compress failed"
            )

            result, algo = compression.compress(data, min_size=100, min_ratio=0.1)

            # Should fall back to Zlib
            assert algo == compression.CompressionAlgo.ZLIB
            assert len(result) < len(data)

    def test_compress_both_fail_returns_original(self):
        """When both Zstd and Zlib compress fail, should return original."""
        data = b"Y" * 1000

        with patch("ming_drlms.core.compression._ZSTD_AVAILABLE", True), patch(
            "ming_drlms.core.compression.zstd_lib"
        ) as mock_zstd, patch("zlib.compress") as mock_zlib:
            mock_zstd.ZstdCompressor.return_value.compress.side_effect = Exception(
                "Zstd error"
            )
            mock_zlib.side_effect = Exception("Zlib error")

            result, algo = compression.compress(data, min_size=100, min_ratio=0.1)

            assert algo == compression.CompressionAlgo.NONE
            assert result == data

    def test_decompress_zstd_exception_raises_valueerror(self):
        """Zstd decompress exception should raise ValueError with message."""
        if not compression.HAS_ZSTD:
            pytest.skip("Zstd not available")

        with patch("ming_drlms.core.compression.zstd_lib") as mock_zstd:
            mock_zstd.ZstdDecompressor.return_value.decompress.side_effect = Exception(
                "Corrupted data"
            )

            with pytest.raises(ValueError, match="Zstd decompression failed"):
                compression.decompress(b"fake", compression.CompressionAlgo.ZSTD)

    def test_decompress_file_zstd_exception_raises_valueerror(self, temp_dir):
        """Zstd decompress_file exception should raise ValueError."""
        if not compression.HAS_ZSTD:
            pytest.skip("Zstd not available")

        src = temp_dir / "bad.zst"
        dst = temp_dir / "out.txt"
        src.write_bytes(b"not real zstd data")

        with patch("ming_drlms.core.compression.zstd_lib") as mock_zstd:
            mock_zstd.ZstdDecompressor.return_value.copy_stream.side_effect = Exception(
                "Copy stream failed"
            )

            with pytest.raises(ValueError, match="Zstd file decompression failed"):
                compression.decompress_file(
                    str(src), str(dst), compression.CompressionAlgo.ZSTD
                )

    def test_decompress_file_zlib_exception_raises_valueerror(self, temp_dir):
        """Zlib decompress_file exception should raise ValueError."""
        src = temp_dir / "bad.zlib"
        dst = temp_dir / "out.txt"
        src.write_bytes(b"not valid zlib stream")

        with pytest.raises(ValueError, match="Zlib file decompression failed"):
            compression.decompress_file(
                str(src), str(dst), compression.CompressionAlgo.ZLIB
            )
