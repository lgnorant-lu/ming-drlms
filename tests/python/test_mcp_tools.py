"""Phase 28: MCP Tools Unit Tests.

Tests for MCP tool implementations using in-memory transport.
Updated for Phase 28 Ultimate (Blossom Mock).
"""

import pytest
import os


# Standard BIP39 test mnemonic
TEST_MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"


class TestMCPTools:
    """Tests for MCP tool functions."""

    def test_hello_world(self):
        """hello_world should return greeting."""
        from ming_drlms.mcp.tools import hello_world

        result = hello_world("Claude")
        assert "Hello, Claude!" in result
        assert "Phase 28 Ultimate" in result

    def test_generate_identity_flow(self, tmp_path):
        """Test generate_identity and verify return structure."""
        os.environ["MING_DRLMS_CONFIG_DIR"] = str(tmp_path)

        from ming_drlms.mcp.tools import generate_identity

        # 1. Generate Identity
        result = generate_identity(username="alice", security_level="quantum")

        assert result["username"] == "alice"
        assert result["security_level"] == "quantum"
        assert len(result["pubkey_hex"]) == 64
        assert "fingerprint" in result
        assert result["created"] is True

    def test_blossom_flow(self, tmp_path):
        """Test the full Agent-to-Agent flow: Identity -> Store -> Retrieve."""
        os.environ["MING_DRLMS_CONFIG_DIR"] = str(tmp_path)

        from ming_drlms.mcp.tools import (
            generate_identity,
            store_secret,
            retrieve_secret,
        )

        # 1. Setup Identity (Receive)
        id_res = generate_identity("bob")
        bob_pubkey = id_res["pubkey_hex"]

        # 2. Store Secret (Sender -> Bob)
        secret_msg = "The eagle flies at midnight"
        uri = store_secret(
            recipient_pubkey=bob_pubkey, secret_content=secret_msg, ttl_hours=1
        )

        assert uri.startswith("blossom://")

        # 3. Retrieve Secret (Bob retrieves)
        # Note: In real life Bob uses his private key. Here we verify 'bob' exists locally.
        result = retrieve_secret(blossom_uri=uri, recipient_username="bob")

        assert result["success"] is True
        assert result["secret_content"] == secret_msg
        assert result["encryption_status"] == "none (Phase 28.1 pending)"


class TestMCPServerIntegration:
    """Integration tests using MCP client session."""

    @pytest.fixture
    def anyio_backend(self):
        return "asyncio"

    @pytest.mark.asyncio
    async def test_server_tools_list(self):
        """Server should list registered tools."""
        from mcp.shared.memory import create_connected_server_and_client_session
        from ming_drlms.mcp.server import mcp
        from ming_drlms.mcp import tools  # noqa: F401 - registers tools

        async with create_connected_server_and_client_session(
            mcp._mcp_server
        ) as session:
            await session.initialize()

            result = await session.list_tools()
            tool_names = [t.name for t in result.tools]

            assert "hello_world" in tool_names
            assert "generate_identity" in tool_names
            assert "store_secret" in tool_names
            assert "retrieve_secret" in tool_names

    @pytest.mark.asyncio
    async def test_call_blossom_flow(self, tmp_path):
        """Should be able to execute the full flow via MCP protocol."""
        import os

        os.environ["MING_DRLMS_CONFIG_DIR"] = str(tmp_path)

        from mcp.shared.memory import create_connected_server_and_client_session
        from ming_drlms.mcp.server import mcp
        from ming_drlms.mcp import tools  # noqa: F401

        async with create_connected_server_and_client_session(
            mcp._mcp_server
        ) as session:
            await session.initialize()

            # 1. Generate Identity
            res1 = await session.call_tool(
                "generate_identity", {"username": "agent_smith"}
            )
            assert isinstance(res1.content, list)
            # FastMCP returns text content, usually JSON string if return type was dict?
            # Wait, FastMCP automatically serializes dict return to JSON text in content?
            # Or does it return a TextContent object?
            # Let's inspect content in debug or assume standard MCP behavior.
            # Standard MCP Python SDK: call_tool returns CallToolResult.
            # content is list of TextContent | ImageContent.

            # Since my tool returns dict, FastMCP likely json.dumps it into TextContent.
            import json

            data1 = json.loads(res1.content[0].text)
            pubkey = data1["pubkey_hex"]

            # 2. Store Secret
            res2 = await session.call_tool(
                "store_secret",
                {
                    "recipient_pubkey": pubkey,
                    "secret_content": "matrix_code",
                    "ttl_hours": 24,
                },
            )
            uri = res2.content[0].text
            assert "blossom://" in uri

            # 3. Retrieve Secret
            res3 = await session.call_tool(
                "retrieve_secret",
                {"blossom_uri": uri, "recipient_username": "agent_smith"},
            )
            data3 = json.loads(res3.content[0].text)
            assert data3["secret_content"] == "matrix_code"
