"""诊断脚本：测试 store_secret MCP 工具"""

import asyncio
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Load environment
from dotenv import load_dotenv

load_dotenv(".env.local")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


async def diagnose_store_secret():
    """诊断 store_secret 工具调用"""
    print("🔍 开始诊断 store_secret...")

    server_params = StdioServerParameters(
        command=sys.executable, args=["-m", "ming_drlms.mcp"], env=os.environ.copy()
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Step 1: 列出身份
                print("\n📋 Step 1: 列出身份...")
                result = await session.call_tool("list_identities", arguments={})
                identities = result.content[0].text
                print(f"身份列表: {identities[:200]}...")

                # 解析第一个身份的公钥
                import json

                users = json.loads(identities)
                if not users:
                    print("❌ 错误：没有找到任何身份！请先运行 generate_identity")
                    return

                first_user = users[0]
                recipient_pubkey = first_user["pubkey_hex"]
                print(f"✅ 使用接收者公钥: {recipient_pubkey[:16]}...")

                # Step 2: 调用 store_secret
                print("\n🔐 Step 2: 调用 store_secret...")
                try:
                    result = await session.call_tool(
                        "store_secret",
                        arguments={
                            "recipient_x25519_hex": recipient_pubkey,
                            "secret_content": "机密代码 ABC123 - 诊断测试",
                            "ttl_hours": 24,
                        },
                    )

                    print("✅ store_secret 调用成功！")
                    print(f"返回结果: {result.content[0].text}")

                except Exception as e:
                    print("❌ store_secret 调用失败！")
                    print(f"错误类型: {type(e).__name__}")
                    print(f"错误信息: {str(e)}")
                    import traceback

                    traceback.print_exc()

    except Exception as e:
        print(f"❌ 连接 MCP 服务器失败: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(diagnose_store_secret())
