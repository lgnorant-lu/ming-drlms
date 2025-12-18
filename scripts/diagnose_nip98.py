"""深度诊断 NIP-98 认证头生成"""

import sys
from pathlib import Path
import json
import hashlib
import time
import base64

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv(".env.local")


def diagnose_nip98():
    """详细诊断 NIP-98 事件生成"""

    print("=" * 70)
    print("NIP-98 Blossom Authorization 深度诊断")
    print("=" * 70)

    # Step 1: 创建临时身份
    print("\n[1] 创建临时 Nostr 身份")
    print("-" * 70)

    from ming_drlms.core.identity_manager import IdentityManager
    from ming_drlms.core.nostr_derivation import generate_mnemonic
    from ming_drlms.core.e2ee_store import LocalKeyStore

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

    pubkey = signer.get_pubkey_hex()
    print(f"✅ Nostr 公钥: {pubkey}")

    # Step 2: 模拟 Blob SHA256
    print("\n[2] 模拟上传内容")
    print("-" * 70)

    test_data = b"Test blob content for NIP-98 diagnosis"
    blob_sha256 = hashlib.sha256(test_data).hexdigest()
    print(f"Blob SHA256: {blob_sha256}")
    print(f"Blob 大小: {len(test_data)} bytes")

    # Step 3: 构建 NIP-98 事件
    print("\n[3] 构建 Nostr Event (kind: 24242)")
    print("-" * 70)

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
        "content": "Upload Blob",
    }

    print(json.dumps(event, indent=2))

    # Step 4: 计算事件 ID
    print("\n[4] 计算事件 ID (SHA256)")
    print("-" * 70)

    event_id = signer._compute_event_id(event)
    print(f"Event ID: {event_id}")

    # 验证 ID 计算
    serialized = json.dumps(
        [
            0,
            event["pubkey"],
            event["created_at"],
            event["kind"],
            event["tags"],
            event["content"],
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    print("\n序列化内容 (JSON数组):")
    print(f"  {serialized[:100].decode('utf-8')}...")
    print(f"  Hash: {hashlib.sha256(serialized).hexdigest()}")

    # Step 5: 签名
    print("\n[5] BIP-340 Schnorr 签名")
    print("-" * 70)

    signature = signer.sign_event(event)
    print(f"Signature: {signature}")
    print(f"签名长度: {len(signature)} chars ({len(signature) // 2} bytes)")

    # Step 6: 构建完整事件
    print("\n[6] 完整 Nostr 事件")
    print("-" * 70)

    full_event = event.copy()
    full_event["id"] = event_id
    full_event["sig"] = signature

    print(json.dumps(full_event, indent=2))

    # Step 7: Base64 编码
    print("\n[7] Authorization Header")
    print("-" * 70)

    event_json = json.dumps(full_event, separators=(",", ":"), ensure_ascii=False)
    b64_event = base64.b64encode(event_json.encode("utf-8")).decode("ascii")
    auth_header = f"Nostr {b64_event}"

    print(f"JSON (压缩): {event_json[:80]}...")
    print(f"Base64 长度: {len(b64_event)} chars")
    print("\nAuthorization Header:")
    print(f"  {auth_header[:100]}...")

    # Step 8: 验证签名（可选）
    print("\n[8] 签名验证")
    print("-" * 70)

    try:
        from coincurve import PublicKey

        # 重新构建公钥进行验证
        pubkey_bytes = bytes.fromhex(pubkey)
        # 需要添加 0x02 前缀（偶数 y 坐标）
        compressed_pubkey = b"\x02" + pubkey_bytes
        pub = PublicKey(compressed_pubkey)

        sig_bytes = bytes.fromhex(signature)
        event_id_bytes = bytes.fromhex(event_id)

        is_valid = pub.verify(sig_bytes, event_id_bytes, hasher=None)
        print(f"✅ 签名验证: {'通过' if is_valid else '失败'}")
    except Exception as e:
        print(f"⚠️  签名验证跳过: {e}")

    # Step 9: 关键字段准确性检查
    print("\n[9] NIP-98 规范符合性检查")
    print("-" * 70)

    checks = [
        ("Event Kind", event["kind"] == 24242, "必须是 24242"),
        ("Pubkey 长度", len(pubkey) == 64, "必须是 64 字符 (32 bytes)"),
        ("Event ID 长度", len(event_id) == 64, "必须是 64 字符 (32 bytes)"),
        ("Signature 长度", len(signature) == 128, "必须是 128 字符 (64 bytes)"),
        ("Tag 't' 存在", ["t", "upload"] in event["tags"], "必须包含 ['t', 'upload']"),
        (
            "Tag 'x' 存在",
            any(t[0] == "x" for t in event["tags"]),
            "必须包含 Blob SHA256",
        ),
        ("Content 非空", bool(event["content"]), "Content 不能为空"),
    ]

    all_passed = True
    for name, passed, requirement in checks:
        status = "✅" if passed else "❌"
        print(f"  {status} {name}: {requirement}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 70)
    if all_passed:
        print("✅ 所有检查通过！NIP-98 事件格式正确")
        print("\n建议下一步:")
        print("1. 使用 curl 手动测试 Authorization 头")
        print("2. 检查服务器端日志（如果可访问）")
        print("3. 尝试不同的 Blob 内容和大小")
    else:
        print("❌ 发现格式问题，请修复后重试")

    print("=" * 70)

    # 返回用于后续测试的值
    return {
        "auth_header": auth_header,
        "blob_sha256": blob_sha256,
        "test_data": test_data,
    }


if __name__ == "__main__":
    result = diagnose_nip98()

    print("\n" + "=" * 70)
    print("📋 测试命令生成")
    print("=" * 70)
    print("\n可以使用以下 curl 命令手动测试：")
    print(f"""
curl -X PUT \\
  -H "Authorization: {result["auth_header"][:50]}..." \\
  -H "Content-Type: application/octet-stream" \\
  --data-binary "@test_blob.bin" \\
  https://nostr.download/upload
""")
    print("\n（注意：需要先创建 test_blob.bin 文件，内容与诊断中的 test_data 一致）")
