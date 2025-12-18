"""测试不同 Blossom 服务器的认证"""

import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv(".env.local")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402
import json  # noqa: E402

# 要测试的服务器列表
SERVERS_TO_TEST = [
    "https://cdn.nostr.build",
    "https://blossom.primal.net",
    "https://nostr.build",
    "https://nostr.download",  # 当前默认
]


async def test_server(server_url: str, recipient_pubkey: str):
    """测试特定服务器"""
    print(f"\n{'=' * 70}")
    print(f"🧪 测试服务器: {server_url}")
    print(f"{'=' * 70}")

    # 临时修改环境变量
    original_server = os.environ.get("MING_DRLMS_BLOSSOM_SERVER")
    os.environ["MING_DRLMS_BLOSSOM_SERVER"] = server_url

    server_params = StdioServerParameters(
        command=sys.executable, args=["-m", "ming_drlms.mcp"], env=os.environ.copy()
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool(
                    "store_secret",
                    arguments={
                        "recipient_x25519_hex": recipient_pubkey,
                        "secret_content": f"测试消息 - 服务器: {server_url}",
                        "ttl_hours": 24,
                    },
                )

                response = result.content[0].text
                print("✅ 成功！")
                print(f"返回: {response[:200]}")

                # 检查是否真的成功
                if "401" in response or "Unauthorized" in response:
                    print("⚠️  警告: 响应中包含 401/Unauthorized")
                    return False
                elif "uri" in response or "blossom://" in response:
                    print("🎉 成功上传！")
                    return True
                else:
                    print("❓ 未知状态")
                    return False

    except Exception as e:
        print(f"❌ 失败: {e}")
        return False
    finally:
        # 恢复原始环境变量
        if original_server:
            os.environ["MING_DRLMS_BLOSSOM_SERVER"] = original_server


async def main():
    print("🔍 Blossom 服务器兼容性测试")
    print("=" * 70)

    # 首先获取一个测试用接收者公钥
    print("\n📋 获取测试身份...")
    server_params = StdioServerParameters(
        command=sys.executable, args=["-m", "ming_drlms.mcp"], env=os.environ.copy()
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("list_identities", arguments={})
            identities = json.loads(result.content[0].text)

            if not identities:
                print("❌ 错误：没有找到身份，请先运行 generate_identity")
                return

            recipient = identities[0]
            recipient_pubkey = recipient["pubkey_hex"]
            print(f"✅ 使用身份: {recipient['username']}")
            print(f"   公钥: {recipient_pubkey[:32]}...")

    # 测试每个服务器
    results = {}
    for server in SERVERS_TO_TEST:
        success = await test_server(server, recipient_pubkey)
        results[server] = success
        await asyncio.sleep(1)  # 避免请求过快

    # 总结
    print("\n" + "=" * 70)
    print("📊 测试总结")
    print("=" * 70)

    for server, success in results.items():
        status = "✅ 成功" if success else "❌ 失败"
        print(f"{status} - {server}")

    successful_servers = [s for s, success in results.items() if success]
    if successful_servers:
        print(f"\n🎯 推荐使用: {successful_servers[0]}")
        print("\n请在 .env.local 中设置:")
        print(f"MING_DRLMS_BLOSSOM_SERVER={successful_servers[0]}")
    else:
        print("\n⚠️  所有服务器都失败，问题可能在 NIP-98 实现")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
