"""Legacy Relay HTTP Client.

DEPRECATED: This module uses httpx.Client which may have proxy issues on Windows.
For Phase 16+, prefer using ming_drlms.relay.RelayManager which uses urllib.request
for better Windows compatibility and supports multi-relay features.

This module is kept for backward compatibility with:
- CLI commands that haven't migrated to RelayManager
- Tests that specifically test RelayHTTPClient behavior

Migration path: Replace RelayHTTPClient usage with RelayManager.post_event()
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import httpx


class RelayHTTPClient:
    def __init__(self, base_url: str, *, timeout: float = 10.0) -> None:
        self._base = base_url.rstrip("/")
        # Do not inherit system proxy settings here; Relay is usually on localhost
        # and going through a corporate proxy may lead to 502/Bad Gateway.
        self._client = httpx.Client(timeout=timeout, trust_env=False)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def post_event(
        self,
        *,
        room: str,
        ciphertext: str,
        content_len: Optional[int] = None,
        client_event_hash: Optional[str] = None,
        client_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "room": room,
            "ciphertext": ciphertext,
        }
        if content_len is not None:
            payload["content_len"] = int(content_len)
        if client_event_hash is not None:
            payload["client_event_hash"] = client_event_hash
        if client_ts is not None:
            payload["client_ts"] = int(client_ts)
        r = self._client.post(f"{self._base}/events", json=payload)
        r.raise_for_status()
        return r.json()

    def get_events(
        self, *, room: str, since_seq: int = 0, limit: int = 100
    ) -> List[Dict[str, Any]]:
        params = {"room": room, "since_seq": int(since_seq), "limit": int(limit)}
        r = self._client.get(f"{self._base}/events", params=params)
        r.raise_for_status()
        return r.json()

    def upload_file(self, file_path: str, room: str) -> str:
        """Upload a file to the relay. Returns the file URL."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        # Phase 23: Compression Strategy
        from . import compression
        import tempfile
        import os
        from ming_drlms import config

        # Load config - may return CLIConfig (dataclass) or None
        # For Phase 23 compression, we use sensible defaults if not configured
        enabled = True
        min_size = 128
        min_ratio = 0.1

        try:
            cfg = config.load_config(None)
            if cfg is not None:
                # Check if cfg has compression attribute (newer config format)
                if hasattr(cfg, "compression"):
                    comp_cfg = cfg.compression
                    if comp_cfg is not None:
                        enabled = getattr(comp_cfg, "enabled", True)
                        min_size = getattr(comp_cfg, "min_size", 128)
                        min_ratio = getattr(comp_cfg, "min_ratio", 0.1)
                elif isinstance(cfg, dict):
                    # Fallback for dict-based config
                    comp_cfg = cfg.get("compression", {})
                    enabled = comp_cfg.get("enabled", True)
                    min_size = comp_cfg.get("min_size", 128)
                    min_ratio = comp_cfg.get("min_ratio", 0.1)
        except Exception:
            pass  # Use defaults

        final_path = path
        comp_type = compression.CompressionAlgo.NONE
        temp_file = None

        if enabled:
            try:
                fd, temp_path = tempfile.mkstemp(prefix="relay_up_", suffix=".zst")
                os.close(fd)
                temp_file = Path(temp_path)

                success, algo = compression.compress_file(
                    str(path), str(temp_file), min_size=min_size, min_ratio=min_ratio
                )

                if success:
                    final_path = temp_file
                    comp_type = algo
                else:
                    if temp_file.exists():
                        temp_file.unlink()
                    temp_file = None
            except Exception:
                if temp_file and temp_file.exists():
                    try:
                        temp_file.unlink()
                    except OSError:
                        pass
                temp_file = None
                comp_type = compression.CompressionAlgo.NONE

        try:
            url = f"{self._base}/files"  # Changed from /upload to /files to match existing API

            # Prepare headers
            # Note: We don't set Content-Type here, requests sets it for multipart
            # We add custom header for compression
            headers = {"X-DRLMS-Compression": str(int(comp_type))}

            with open(final_path, "rb") as f:
                files = {"file": (path.name, f)}  # Keep original filename
                data = {"room": room}
                response = self._client.post(
                    url, files=files, data=data, headers=headers
                )
                response.raise_for_status()
                result = response.json()
                return result["url"]  # Assuming the relay returns a URL
        finally:
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass

    def download_file(self, file_id: int) -> Iterable[bytes]:
        """Download a file from the relay."""
        # Note: This yields RAW bytes (potentially compressed).
        # Wrapper logic (TUI/Client) must handle decompression.
        with self._client.stream("GET", f"{self._base}/files/{int(file_id)}") as r:
            r.raise_for_status()
            yield from r.iter_bytes()

    def head_file(self, file_id: int) -> Dict[str, Any]:
        r = self._client.head(f"{self._base}/files/{int(file_id)}")
        if r.status_code == 404:
            raise httpx.HTTPStatusError("not found", request=r.request, response=r)
        r.raise_for_status()
        h = r.headers
        meta: Dict[str, Any] = {
            "filename": h.get("X-DRLMS-Filename"),
            "size_bytes": int(h.get("X-DRLMS-Size", "0") or 0),
            "sha256_hex": h.get("X-DRLMS-SHA256"),
            "ephemeral": (h.get("X-DRLMS-Ephemeral", "0") == "1"),
            "compression_type": int(h.get("X-DRLMS-Compression", "0") or 0),  # Phase 23
        }
        return meta


def _default_client_db_path() -> str:
    """Get default client DB path: DRLMS_DB_PATH > ~/.drlms/events.db"""
    if p := os.environ.get("DRLMS_DB_PATH"):
        return p
    config_dir = os.environ.get("MING_DRLMS_CONFIG_DIR")
    if config_dir:
        return os.path.join(config_dir, "events.db")
    return os.path.join(os.path.expanduser("~"), ".drlms", "events.db")


class LocalEventStore:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or _default_client_db_path()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_last_seen_seq(self, room: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT last_seen_seq FROM client_sync_state WHERE room = ?",
                (room,),
            )
            row = cur.fetchone()
            return int(row[0]) if row is not None else 0

    def set_last_seen_seq(self, room: str, seq: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO client_sync_state(room, last_seen_seq) VALUES(?, ?)\n"
                "ON CONFLICT(room) DO UPDATE SET last_seen_seq=excluded.last_seen_seq",
                (room, int(seq)),
            )

    def insert_clear_event(
        self,
        *,
        room: str,
        server_seq: Optional[int],
        ts: int,
        sender_id: str,
        device_id: int,
        content_type: str,
        content_bytes: Optional[bytes],
        signature: bytes,
        verified: bool,
        client_hash: Optional[str] = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO client_events(
                    room, server_seq, ts, sender_id, device_id, content_type,
                    content_bytes, signature, verified, client_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    room,
                    int(server_seq) if server_seq is not None else None,
                    int(ts),
                    sender_id,
                    int(device_id),
                    content_type,
                    content_bytes,
                    signature,
                    1 if verified else 0,
                    client_hash,
                ),
            )


class RelaySyncManager:
    def __init__(
        self,
        *,
        http: RelayHTTPClient,
        store: LocalEventStore,
        decrypt_and_verify: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
    ) -> None:
        self._http = http
        self._store = store
        self._dec = decrypt_and_verify

    def sync_once(self, room: str, *, limit: int = 100) -> int:
        last = self._store.get_last_seen_seq(room)
        items = self._http.get_events(room=room, since_seq=last, limit=limit)
        if not items:
            return 0
        max_seq = last
        wrote = 0
        for item in items:
            clear = self._dec(item)
            if not clear:
                continue
            if not clear.get("verified", False):
                continue
            self._store.insert_clear_event(
                room=room,
                server_seq=int(item.get("server_seq"))
                if item.get("server_seq") is not None
                else None,
                ts=int(clear["ts"]),
                sender_id=str(clear["sender_id"]),
                device_id=int(clear.get("device_id", 1)),
                content_type=str(clear["content_type"]),
                content_bytes=clear.get("content_bytes"),
                signature=clear["signature"],
                verified=True,
                client_hash=item.get("client_hash"),
            )
            wrote += 1
            if item.get("server_seq") and int(item["server_seq"]) > max_seq:
                max_seq = int(item["server_seq"])
        if max_seq > last:
            self._store.set_last_seen_seq(room, max_seq)
        return wrote
