import os
import unittest
from unittest.mock import MagicMock, patch, mock_open

# Adjust path to import src
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from ming_drlms.core import compression
from ming_drlms.cli.services.room_service import RoomService
from ming_drlms.core.relay_client import RelayHTTPClient
from ming_drlms.proto.schema.v2 import room_pb2


class TestCompressionFlow(unittest.TestCase):
    def test_e2ee_compression_flag(self):
        """Test that compression_type is correctly set in room.proto objects."""
        # This tests protocol definition availability
        payload = room_pb2.SignalEncryptedPayload()
        payload.compression_type = 1  # ZLIB
        self.assertEqual(payload.compression_type, 1)

        meta = room_pb2.RoomFileMetadata()
        meta.compression_type = 2  # ZSTD
        self.assertEqual(meta.compression_type, 2)

    @patch("ming_drlms.cli.services.room_service.config.load_config")
    @patch("ming_drlms.core.compression.compress_file")
    def test_room_service_publish_uses_compression(self, mock_compress, mock_config):
        """Test RoomService.publish_file attempts compression."""
        mock_config.return_value = {}
        # Setup mocks
        mock_compress.return_value = (True, compression.CompressionAlgo.ZSTD)

        client_ctx = MagicMock()
        client = MagicMock()
        client_ctx.__enter__.return_value = client

        # Fake file
        with patch("pathlib.Path.exists", return_value=True), patch(
            "pathlib.Path.stat"
        ) as mock_stat, patch("builtins.open", mock_open(read_data=b"data")):
            mock_stat.return_value.st_size = 100

            service = RoomService()
            # Manual instance mock
            service._client_factory = MagicMock(return_value=client_ctx)

            # We mock tempfile to return a specific path we can 'open'
            with patch("tempfile.mkstemp", return_value=(99, "temp.zst")), patch(
                "os.close"
            ):
                service.publish_file(
                    host="localhost",
                    port=8080,
                    user="alice",
                    room="test",
                    file_path="test.txt",
                )

        # Verify compress_file called
        mock_compress.assert_called_once()

        # Verify client.publish_file_begin called with compression_type
        client.publish_file_begin.assert_called_once()
        _, kwargs = client.publish_file_begin.call_args
        self.assertEqual(
            kwargs.get("compression_type"), compression.CompressionAlgo.ZSTD
        )

    @patch("ming_drlms.core.compression.decompress_file")
    def test_room_service_download_uses_decompression(self, mock_decompress):
        """Test RoomService.download_file uses decompression if type > 0."""
        client_ctx = MagicMock()
        client = MagicMock()
        client_ctx.__enter__.return_value = client

        service = RoomService()
        service._client_factory = MagicMock(return_value=client_ctx)

        with patch("builtins.open", mock_open()), patch(
            "tempfile.mkstemp", return_value=(99, "temp.zst")
        ), patch("os.close"):
            service.download_file(
                host="localhost",
                port=8080,
                user="alice",
                room="test",
                event_id=123,
                output_path="out.txt",
                compression_type=compression.CompressionAlgo.ZSTD,
            )

        mock_decompress.assert_called_once()
        args, _ = mock_decompress.call_args
        # args[0] is source (temp), args[1] is dest (out.txt), args[2] is type
        self.assertEqual(args[2], compression.CompressionAlgo.ZSTD)

    @patch("httpx.Client")
    def test_relay_client_upload_header(self, mock_httpx):
        """Test RelayHTTPClient sends X-DRLMS-Compression header."""
        import tempfile
        import os as real_os

        # Create a real test file with compressible content
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False) as f:
            f.write(b"A" * 2000)  # Highly compressible
            test_file = f.name

        try:
            # Mock the httpx client
            http_instance = mock_httpx.return_value
            http_instance.post.return_value = MagicMock(
                json=lambda: {"url": "http://relay/files/123"},
                raise_for_status=lambda: None,
            )

            # Create client - this will use the real config.load_config
            # which will return default/empty config if no file exists
            client = RelayHTTPClient("http://relay")

            try:
                client.upload_file(test_file, "room_id")
            except Exception:
                pass  # Ignore errors from the actual HTTP call

            # Verify post was called
            http_instance.post.assert_called()
            call_args = http_instance.post.call_args
            headers = call_args[1].get("headers", {})

            # Verify compression header exists (value should be >= 0)
            self.assertIn("X-DRLMS-Compression", headers)
            comp_type = int(headers.get("X-DRLMS-Compression", "-1"))
            self.assertGreaterEqual(comp_type, 0)

        finally:
            # Cleanup
            if real_os.path.exists(test_file):
                real_os.unlink(test_file)


if __name__ == "__main__":
    unittest.main()
