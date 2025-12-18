"""
诊断 Blossom 上传响应
查看服务器实际返回了什么
"""

import sys
from pathlib import Path
import httpx
import hashlib

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv(".env.local")


def diagnose_upload_response():
    """测试上传并查看实际响应"""

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

    import time

    mnemonic = generate_mnemonic()
    username = f"diag-{int(time.time())}"
    keystore = EphemeralKeyStore()

    manager = IdentityManager.from_mnemonic(mnemonic, username, keystore=keystore)
    signer = manager.get_nostr_signer()

    # 测试数据
    test_data = b"Diagnostic test content"
    blob_sha256 = hashlib.sha256(test_data).hexdigest()

    # 生成认证头
    import json
    import base64

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
        "content": "Diagnostic upload",
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
    url = "https://nostr.build/upload"
    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/octet-stream",
    }

    print("=" * 70)
    print("上传请求")
    print("=" * 70)
    print(f"URL: {url}")
    print(f"Data size: {len(test_data)} bytes")
    print(f"SHA256: {blob_sha256}")
    print()

    response = httpx.put(url, content=test_data, headers=headers, timeout=30.0)

    print("=" * 70)
    print("响应详情")
    print("=" * 70)
    print(f"Status: {response.status_code}")
    print(f"Content-Type: {response.headers.get('content-type')}")
    print(f"Content-Length: {response.headers.get('content-length')}")
    print()
    print("Headers:")
    for key, value in response.headers.items():
        print(f"  {key}: {value}")
    print()
    print("Body (first 1000 chars):")
    print(response.text[:1000])
    print()

    # 尝试解析为 JSON
    print("=" * 70)
    print("JSON 解析尝试")
    print("=" * 70)
    try:
        data = response.json()
        print("✅ JSON 解析成功！")
        print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"❌ JSON 解析失败: {type(e).__name__}: {e}")
        print()
        print("这可能意味着服务器返回的是 HTML 或纯文本")

    # 检查是否是 HTML
    if "<!DOCTYPE" in response.text or "<html" in response.text:
        print("\n⚠️  响应是 HTML 页面！")


if __name__ == "__main__":
    diagnose_upload_response()
