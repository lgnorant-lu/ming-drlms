"""
Blossom End-to-End Verification Script
验证从上传到下载的完整链路，证明 API 是工作的
"""

import sys
import os
import time
from pathlib import Path

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ming_drlms.core.blossom import BlossomClient
from ming_drlms.core.identity_manager import IdentityManager
from ming_drlms.core.nostr_derivation import generate_mnemonic
from ming_drlms.core.e2ee_store import LocalKeyStore

# 强制使用 nostr.download
os.environ["MING_DRLMS_BLOSSOM_SERVER"] = "https://nostr.download"


def verify_end_to_end():
    print(f"\n{'=' * 60}")
    print("🚀 Blossom End-to-End Verification (nostr.download)")
    print(f"{'=' * 60}\n")

    # 1. 准备数据
    secret_content = f"Ming-DRLMS Verification Token [{int(time.time())}]"
    print(f"📦 准备上传数据: '{secret_content}'")

    # 2. 创建临时身份
    print("🔑 创建临时身份中...")

    class MemoryStore(LocalKeyStore):
        def __init__(self):
            self._path = Path(":memory:")
            self._data = {"users": {}}
            self._loaded = True
            import threading

            self._lock = threading.Lock()

        def _persist(self):
            pass

    mnemonic = generate_mnemonic()
    username = "verifier"
    manager = IdentityManager.from_mnemonic(mnemonic, username, keystore=MemoryStore())

    # 3. 初始化客户端
    client = BlossomClient(identity_manager=manager)
    print(f"🌐 目标服务器: {client.server_url}")

    # 4. 执行上传
    print("\n📤 正在上传 (PUT /upload)...")
    try:
        result = client.upload_blob(
            secret_content.encode("utf-8"), content_type="text/plain"
        )
        print("\n✅ 上传成功!")
        print(f"   URL: {result['url']}")
        print(f"   SHA256: {result['sha256']}")

        # 5. 执行下载验证
        print("\n📥 正在下载验证 (GET)...")
        # 等待一秒以确保 CDN/Server 处理完成
        time.sleep(1)

        # download_blob handles blossom:// or http:// URLs
        downloaded_bytes = client.download_blob(result["url"])
        downloaded_text = downloaded_bytes.decode("utf-8")

        print(f"   下载内容: '{downloaded_text}'")

        if downloaded_text == secret_content:
            print("\n✨ 验证通过! 内容完全匹配! ✨")
            return True
        else:
            print(f"\n❌ 内容不匹配!\n期望: {secret_content}\n实际: {downloaded_text}")
            return False

    except Exception as e:
        print(f"\n❌ 操作失败: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = verify_end_to_end()
    sys.exit(0 if success else 1)
