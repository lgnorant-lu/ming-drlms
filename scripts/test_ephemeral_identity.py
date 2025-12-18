"""简化测试：直接测试临时身份创建"""

import sys
import os
from pathlib import Path
import logging

# Setup logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(".env.local")


def test_ephemeral_identity():
    """测试临时身份创建和Nostr签名"""

    print("\n" + "=" * 60)
    print("Phase 1: 导入模块")
    print("=" * 60)

    from ming_drlms.core.identity_manager import IdentityManager
    from ming_drlms.core.nostr_derivation import generate_mnemonic
    from ming_drlms.core.e2ee_store import LocalKeyStore

    # Define EphemeralKeyStore inline (避免相对导入问题)
    class EphemeralKeyStore(LocalKeyStore):
        """In-memory key store for testing"""

        def __init__(self) -> None:
            self._path = Path(":memory:")
            self._data: dict = {"users": {}}
            self._loaded = True
            import threading

            self._lock = threading.Lock()

        def _persist(self) -> None:
            pass  # No disk I/O

    print("✅ 模块导入成功")

    print("\n" + "=" * 60)
    print("Phase 2: 创建临时身份")
    print("=" * 60)

    mnemonic = generate_mnemonic()
    username = f"test-ephemeral-{os.urandom(4).hex()}"
    ephemeral_store = EphemeralKeyStore()

    print(f"助记词生成: {str(mnemonic).split()[0]} ... (12 words)")
    print(f"用户名: {username}")
    print(f"临时 KeyStore 初始状态: {ephemeral_store._data}")

    print("\n创建身份中...")
    try:
        manager = IdentityManager.from_mnemonic(
            mnemonic, username, keystore=ephemeral_store
        )
        print("✅ 身份创建成功")
    except Exception as e:
        print(f"❌ 身份创建失败: {e}")
        import traceback

        traceback.print_exc()
        return False

    print(
        f"临时 KeyStore 更新后: {list(ephemeral_store._data.get('users', {}).keys())}"
    )

    print("\n" + "=" * 60)
    print("Phase 3: 获取 Nostr Signer")
    print("=" * 60)

    try:
        signer = manager.get_nostr_signer()
        pubkey = signer.get_pubkey_hex()
        print("✅ Nostr Signer 获取成功")
        print(f"   Public Key: {pubkey}")
    except Exception as e:
        print(f"❌ Nostr Signer 获取失败: {e}")
        import traceback

        traceback.print_exc()
        return False

    print("\n" + "=" * 60)
    print("Phase 4: 测试事件签名")
    print("=" * 60)

    test_event = {
        "pubkey": pubkey,
        "created_at": 1234567890,
        "kind": 24242,
        "tags": [["t", "test"]],
        "content": "Test Event",
    }

    try:
        signature = signer.sign_event(test_event)
        print("✅ 事件签名成功")
        print(f"   Signature: {signature[:32]}...")
    except Exception as e:
        print(f"❌ 事件签名失败: {e}")
        import traceback

        traceback.print_exc()
        return False

    print("\n" + "=" * 60)
    print("✅ 所有测试通过！")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = test_ephemeral_identity()
    sys.exit(0 if success else 1)
