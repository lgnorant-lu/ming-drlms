"""
对比 nostr.build vs nostr.download 的响应
查看两个服务器的行为差异
"""

import sys
from pathlib import Path
import httpx
import hashlib
import json
import base64
import time

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv(".env.local")


def test_server(server_url):
    """测试特定服务器"""

    from ming_drlms.core.identity_manager import IdentityManager
    from ming_drlms.core.nostr_derivation import generate_mnemonic
    from ming_drlms.core.e2ee_store import LocalKeyStore

    # 创建临时身份
    class EphemeralKeyStore(LocalKeyStore):
        def __init__(self) -> None:
            self._path = Path(":memory:")
            self._data: dict = {"users": {}}
            self._loaded = True
            import threading

            self._lock = threading.Lock()

        def _persist(self) -> None:
            pass

    mnemonic = generate_mnemonic()
    username = f"test-{int(time.time())}"
    keystore = EphemeralKeyStore()

    manager = IdentityManager.from_mnemonic(mnemonic, username, keystore=keystore)
    signer = manager.get_nostr_signer()

    # 测试数据
    test_data = b"Server comparison test"
    blob_sha256 = hashlib.sha256(test_data).hexdigest()

    # 生成认证头
    created_at = int(time.time())
    event = {
        "pubkey": signer.get_pubkey_hex(),
        "created_at": created_at,
        "kind": 24242,
        "tags": [
            ["t", "upload"],
            ["x", blob_sha256],
            ["expiration", str(created_at + 3600)],
        ],
        "content": "Server comparison",
    }

    event_id = signer._compute_event_id(event)
    signature = signer.sign_event(event)

    full_event = event.copy()
    full_event["id"] = event_id
    full_event["sig"] = signature

    event_json = json.dumps(full_event, separators=(",", ":"), ensure_ascii=False)
    b64_event = base64.b64encode(event_json.encode("utf-8")).decode("ascii")
    auth_header = f"Nostr {b64_event}"

    # 上传
    url = f"{server_url.rstrip('/')}/upload"
    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/octet-stream",
    }

    print(f"\n{'=' * 70}")
    print(f"测试服务器: {server_url}")
    print(f"{'=' * 70}")
    print(f"URL: {url}")
    print(f"Data size: {len(test_data)} bytes")
    print(f"SHA256: {blob_sha256}")
    print()

    response = httpx.put(url, content=test_data, headers=headers, timeout=30.0)

    print(f"Status: {response.status_code}")
    print(f"Content-Type: {response.headers.get('content-type')}")
    print()
    print("Headers:")
    for key, value in response.headers.items():
        print(f"  {key}: {value}")
    print()
    print("Body (first 500 chars):")
    print(response.text[:500])
    print()

    # JSON 解析
    try:
        data = response.json()
        print("✅ JSON 解析成功！")
        print(json.dumps(data, indent=2))
        return True
    except Exception as e:
        print(f"❌ JSON 解析失败: {e}")
        if "<!DOCTYPE" in response.text or "<html" in response.text:
            print("⚠️  响应是 HTML 页面！")
        return False


if __name__ == "__main__":
    servers = [
        "https://nostr.build",
        "https://nostr.download",
        "https://cdn.nostr.build",
    ]

    for server in servers:
        try:
            test_server(server)
        except Exception as e:
            print(f"\n❌ Exception: {e}\n")

        time.sleep(1)  # 避免过快请求
