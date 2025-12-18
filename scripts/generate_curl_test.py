"""
手动 curl 测试脚本 - 验证 Blossom 认证
生成可用于 curl/PowerShell 的测试命令
"""

import sys
from pathlib import Path
import hashlib
import json
import base64
import time

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv(".env.local")


def generate_curl_test():
    """生成 curl 测试命令"""

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
    username = f"curl-test-{int(time.time())}"
    keystore = EphemeralKeyStore()

    manager = IdentityManager.from_mnemonic(mnemonic, username, keystore=keystore)
    signer = manager.get_nostr_signer()
    pubkey = signer.get_pubkey_hex()

    print(f"✅ Nostr身份创建: {pubkey}")

    # 2. 创建测试文件内容
    test_data = b"Hello from ming-drlms curl test!"
    blob_sha256 = hashlib.sha256(test_data).hexdigest()

    print(f"✅ 测试数据 SHA256: {blob_sha256}")

    # 3. 生成认证事件
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
        "content": "Upload from curl test",
    }

    # 4. 签名
    event_id = signer._compute_event_id(event)
    signature = signer.sign_event(event)

    full_event = event.copy()
    full_event["id"] = event_id
    full_event["sig"] = signature

    # 5. Base64 编码
    event_json = json.dumps(full_event, separators=(",", ":"), ensure_ascii=False)
    b64_event = base64.b64encode(event_json.encode("utf-8")).decode("ascii")
    auth_header = f"Nostr {b64_event}"

    print("✅ Authorization Header 生成完成")
    print()

    # 6. 生成 PowerShell 命令
    test_file = Path(__file__).parent.parent / "test_blob.bin"
    test_file.write_bytes(test_data)

    print("=" * 70)
    print("PowerShell 测试命令")
    print("=" * 70)
    print()
    print("# 1. 切换到项目目录")
    print(f"cd '{Path(__file__).parent.parent}'")
    print()
    print("# 2. 执行上传")
    powershell_cmd = f'''$headers = @{{
    "Authorization" = "{auth_header}"
    "Content-Type" = "application/octet-stream"
}}

Invoke-WebRequest `
    -Uri "https://nostr.download/upload" `
    -Method PUT `
    -Headers $headers `
    -InFile "test_blob.bin" `
    -Verbose'''

    print(powershell_cmd)
    print()
    print("=" * 70)
    print("Linux/Mac curl 命令")
    print("=" * 70)
    print()
    curl_cmd = f"""curl -X PUT \\
  -H "Authorization: {auth_header}" \\
  -H "Content-Type: application/octet-stream" \\
  --data-binary "@test_blob.bin" \\
  https://nostr.download/upload \\
  -v"""

    print(curl_cmd)
    print()
    print("=" * 70)
    print("📋 测试文件信息")
    print("=" * 70)
    print(f"文件路径: {test_file.absolute()}")
    print(f"文件内容: {test_data.decode('utf-8')}")
    print(f"SHA256: {blob_sha256}")
    print()
    print("=" * 70)
    print("📋 事件详情 (可用于调试)")
    print("=" * 70)
    print(json.dumps(full_event, indent=2))
    print()

    # 保存到文件以便复制粘贴
    script_file = Path(__file__).parent.parent / "test_upload.ps1"
    with open(script_file, "w", encoding="utf-8") as f:
        f.write(powershell_cmd)

    print(f"✅ PowerShell 脚本已保存到: {script_file}")
    print("   可以直接运行: powershell -File test_upload.ps1")


if __name__ == "__main__":
    generate_curl_test()
