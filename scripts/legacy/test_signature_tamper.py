#!/usr/bin/env python3
"""Phase 15 签名篡改测试脚本

验证客户端的验证逻辑为：
1. 正常签名的消息能通过验证
2. 签名被篡改的消息会被拒绝
3. 只篡改 sender_pubkey_hex 时，如果存在 identity_resolver，
   则会先用 envelope 中的公钥验证，失败时回退到 resolver 的正确公钥，
   因此仍能通过验证。
   (无 resolver 的场景由 pytest tests/python/test_signature_tamper.py 覆盖)

用法:
    1. 启动 Relay 服务器: python -m uvicorn ming_drlms.relay.server:app --port 15019
    2. 运行此脚本: python scripts/test_signature_tamper.py
"""

import base64
import json
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ming_drlms.core.relay_client import RelayHTTPClient
from ming_drlms.core.relay_crypto import build_decrypt_and_verify
from ming_drlms.core.identity_manager import IdentityManager
from ming_drlms.core.relay_signer import RelaySigner


def create_test_identity(tmp_dir: Path, name: str) -> IdentityManager:
    """创建测试身份"""
    im = IdentityManager(tmp_dir / f"{name}_identity.json")
    im.create_identity(alias=name)
    return im


def post_event(client: RelayHTTPClient, room: str, envelope: dict) -> dict:
    """发送事件到 Relay"""
    ciphertext = base64.b64encode(json.dumps(envelope).encode("utf-8")).decode("ascii")
    return client.post_event(
        room=room,
        ciphertext=ciphertext,
        content_len=len(envelope.get("content_bytes_b64", "")),
    )


def run_tests():
    """运行签名篡改测试"""
    import tempfile

    tmp_dir = Path(tempfile.mkdtemp(prefix="drlms_tamper_test_"))
    print(f"临时目录: {tmp_dir}")

    base_url = os.environ.get("DRLMS_RELAY_BASE_URL", "http://127.0.0.1:15019")
    room = "TamperTest"

    try:
        # 创建测试身份
        print("\n=== 1. 创建测试身份 ===")
        im = create_test_identity(tmp_dir, "tamper-tester")
        print(f"公钥: {im.get_pubkey().hex()[:16]}...")

        # 创建签名器
        signer = RelaySigner(identity_manager=im, username="tamper-tester", device_id=1)

        # 创建 Relay 客户端
        client = RelayHTTPClient(base_url)

        # 测试 1: 正常签名的消息
        print("\n=== 2. 发送正常签名消息 ===")
        content = b"Normal signed message"
        envelope = signer.sign_event(
            room=room,
            content=content,
            content_type="text",
        )
        envelope_dict = envelope.to_dict()
        resp = post_event(client, room, envelope_dict)
        print(f"✓ 正常消息发送成功: seq={resp.get('server_seq')}")
        normal_seq = resp.get("server_seq", 0)

        # 测试 2: 篡改签名的消息
        print("\n=== 3. 发送篡改签名的消息 ===")
        content2 = b"Tampered signature message"
        envelope2 = signer.sign_event(
            room=room,
            content=content2,
            content_type="text",
        )
        tampered_dict = envelope2.to_dict()
        # 篡改签名（改变最后几位）
        original_sig = tampered_dict["signature_hex"]
        tampered_dict["signature_hex"] = original_sig[:-4] + "dead"
        resp2 = post_event(client, room, tampered_dict)
        tampered_sig_seq = resp2.get("server_seq", 0)
        print(f"  篡改签名消息发送成功（服务器不验证）: seq={tampered_sig_seq}")

        # 测试 3: 篡改公钥的消息
        print("\n=== 4. 发送篡改公钥的消息 ===")
        content3 = b"Tampered pubkey message"
        envelope3 = signer.sign_event(
            room=room,
            content=content3,
            content_type="text",
        )
        tampered_pk_dict = envelope3.to_dict()
        # 篡改公钥（改变前几位）
        tampered_pk_dict["sender_pubkey_hex"] = (
            "beef" + tampered_pk_dict["sender_pubkey_hex"][4:]
        )
        resp3 = post_event(client, room, tampered_pk_dict)
        tampered_pk_seq = resp3.get("server_seq", 0)
        print(f"  篡改公钥消息发送成功（服务器不验证）: seq={tampered_pk_seq}")

        # 测试 4: 客户端验证
        print("\n=== 5. 客户端验证测试 ===")

        # 创建验证器
        def identity_resolver(sender_id, device_id):
            # 返回正确的公钥用于验证
            return im.get_pubkey()

        decrypt_and_verify = build_decrypt_and_verify(
            engine_factory=None,
            identity_resolver=identity_resolver,
        )

        # 获取所有事件
        events = client.get_events(room=room, since_seq=0)
        print(f"  获取到 {len(events)} 条事件")

        verified_count = 0
        rejected_count = 0

        for evt in events:
            seq = evt.get("server_seq", 0)
            result = decrypt_and_verify(evt)

            if result is not None:
                verified_count += 1
                status = "✓ 验证通过"
            else:
                rejected_count += 1
                status = "✗ 验证失败/被拒绝"

            if seq == normal_seq:
                print(f"  seq={seq} 正常消息: {status}")
            elif seq == tampered_sig_seq:
                print(f"  seq={seq} 篡改签名: {status}")
            elif seq == tampered_pk_seq:
                print(f"  seq={seq} 篡改公钥: {status}")
            else:
                print(f"  seq={seq} 其他消息: {status}")

        print("\n=== 验证结果汇总 ===")
        print(f"  验证通过: {verified_count}")
        print(f"  验证失败: {rejected_count}")

        # 预期结果
        print("\n=== 预期行为 ===")
        print("  • 正常消息: 应验证通过 ✓")
        print("  • 篡改签名: 应验证失败 ✗")
        print(
            "  • 篡改公钥: 应验证通过 ✓（因为存在 identity_resolver，会回退到正确的公钥）"
        )

        client.close()

    finally:
        # 清理临时文件
        import shutil

        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass

    print("\n测试完成!")


if __name__ == "__main__":
    run_tests()
