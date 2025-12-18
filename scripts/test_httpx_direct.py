"""
直接使用 httpx 测试 Blossom 上传
对比 BlossomClient 的实现
"""

import sys
from pathlib import Path
import hashlib
import json
import base64
import time
import httpx

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv(".env.local")


def test_httpx_upload():
    """直接使用 httpx 测试上传"""

    from ming_drlms.core.identity_manager import IdentityManager
    from ming_drlms.core.nostr_derivation import generate_mnemonic
    from ming_drlms.core.e2ee_store import LocalKeyStore

    # 1. 创建临时身份
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
    username = f"httpx-test-{int(time.time())}"
    keystore = EphemeralKeyStore()

    manager = IdentityManager.from_mnemonic(mnemonic, username, keystore=keystore)
    signer = manager.get_nostr_signer()
    pubkey = signer.get_pubkey_hex()

    print(f"✅ Nostr identity: {pubkey[:32]}...")

    #  2. 测试数据
    test_data = b"Test from httpx direct call"
    blob_sha256 = hashlib.sha256(test_data).hexdigest()

    print(f"✅ Data SHA256: {blob_sha256}")

    # 3. 生成认证头
    created_at = int(time.time())
    event = {
        "pubkey": pubkey,
        "created_at": created_at,
        "kind": 24242,
        "tags": [
            ["t", "upload"],
            ["x", blob_sha256],
            ["expiration", str(created_at + 3600)],
        ],
        "content": "Upload from httpx test",
    }

    event_id = signer._compute_event_id(event)
    signature = signer.sign_event(event)

    full_event = event.copy()
    full_event["id"] = event_id
    full_event["sig"] = signature

    event_json = json.dumps(full_event, separators=(",", ":"), ensure_ascii=False)
    b64_event = base64.b64encode(event_json.encode("utf-8")).decode("ascii")
    auth_header = f"Nostr {b64_event}"

    print(f"✅ Auth header generated ({len(auth_header)} chars)")

    # 4. 测试 1: 使用 httpx with content parameter
    print("\n" + "=" * 70)
    print("测试 1: httpx.put() with content= parameter")
    print("=" * 70)

    url = "https://nostr.download/upload"
    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/octet-stream",
    }

    try:
        response = httpx.put(url, content=test_data, headers=headers, timeout=30.0)

        print(f"Status: {response.status_code}")
        print(f"Headers: {dict(response.headers)}")
        print(f"Body: {response.text[:200]}")

        if response.status_code == 200:
            print("✅ SUCCESS with content= parameter!")
            result = response.json()
            print(f"   URL: {result.get('url')}")
        else:
            print(f"❌ FAILED with status {response.status_code}")

    except Exception as e:
        print(f"❌ Exception: {e}")

    # 5. 测试 2: 使用 httpx with data parameter
    print("\n" + "=" * 70)
    print("测试 2: httpx.put() with data= parameter")
    print("=" * 70)

    test_data2 = b"Test from httpx direct call (data param)"
    blob_sha256_2 = hashlib.sha256(test_data2).hexdigest()

    # 重新生成认证
    event["tags"][1] = ["x", blob_sha256_2]
    event_id_2 = signer._compute_event_id(event)
    signature_2 = signer.sign_event(event)

    full_event_2 = event.copy()
    full_event_2["id"] = event_id_2
    full_event_2["sig"] = signature_2

    event_json_2 = json.dumps(full_event_2, separators=(",", ":"), ensure_ascii=False)
    b64_event_2 = base64.b64encode(event_json_2.encode("utf-8")).decode("ascii")
    auth_header_2 = f"Nostr {b64_event_2}"

    headers_2 = {
        "Authorization": auth_header_2,
        "Content-Type": "application/octet-stream",
    }

    try:
        response = httpx.put(url, data=test_data2, headers=headers_2, timeout=30.0)

        print(f"Status: {response.status_code}")
        print(f"Headers: {dict(response.headers)}")
        print(f"Body: {response.text[:200]}")

        if response.status_code == 200:
            print("✅ SUCCESS with data= parameter!")
            result = response.json()
            print(f"   URL: {result.get('url')}")
        else:
            print(f"❌ FAILED with status {response.status_code}")

    except Exception as e:
        print(f"❌ Exception: {e}")

    # 6. 测试 3: 使用 BlossomClient
    print("\n" + "=" * 70)
    print("测试 3: 使用 BlossomClient class")
    print("=" * 70)

    from ming_drlms.core.blossom import BlossomClient

    client = BlossomClient(identity_manager=manager)
    test_data3 = b"Test from BlossomClient"

    try:
        result = client.upload_blob(test_data3)
        print("✅ BlossomClient SUCCESS!")
        print(f"   URL: {result.get('url')}")
        print(f"   SHA256: {result.get('sha256')}")
    except Exception as e:
        print(f"❌ BlossomClient FAILED: {e}")


if __name__ == "__main__":
    test_httpx_upload()
