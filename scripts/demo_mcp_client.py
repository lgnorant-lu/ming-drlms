import asyncio
import os
import sys
from dotenv import load_dotenv

# Load env for PQC support
load_dotenv(".env.local")

# Add src to path just in case we need to import server directly for stdio transport simulation
# But idea is to use `mcp` client to connect to the command `ming-drlms mcp serve`
sys.path.insert(0, os.path.abspath("src"))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


async def run_mcp_demo():
    print("🤖 Agent connecting to Ming-DRLMS MCP via Stdio...")

    server_params = StdioServerParameters(
        command=sys.executable, args=["-m", "ming_drlms.mcp"], env=os.environ.copy()
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # 2. Initialize
            await session.initialize()

            # 3. List Tools
            print("\n📋 Listing Available Tools:")
            tools = await session.list_tools()
            for tool in tools.tools:
                print(f"  - {tool.name}: {tool.description[:50]}...")

            # 4. Call 'list_identities' Tool (Diagnostic)
            print("\n🧠 Invoking Tool: list_identities()")
            result = await session.call_tool("list_identities", arguments={})

            # 5. Display Result
            print("\n✅ Tool Output:")
            # Parse the text content from the result
            for content in result.content:
                if content.type == "text":
                    print(content.text)

            # 6. Call 'store_secret' Tool (Test encryption and upload)
            print("\n🧠 Invoking Tool: store_secret(bob, 'Debug Test')")
            result = await session.call_tool(
                "store_secret",
                arguments={
                    "recipient_x25519_hex": "248d4ace1f7e38e7764511482367e59dd9e5e33e9b59d3b5eb623767ed216b0b",
                    "secret_content": "Debug Test",
                    "ttl_hours": 24,
                },
            )

            # 7. Display store_secret Result
            print("\n✅ Tool Output:")
            for content in result.content:
                if content.type == "text":
                    print(content.text)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_mcp_demo())
