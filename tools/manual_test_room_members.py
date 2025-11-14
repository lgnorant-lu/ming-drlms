#!/usr/bin/env python3
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ming_drlms.cli.mproto_runtime import create_mp2_client
from ming_drlms.core.token_store import TokenStore

# configure
host = "127.0.0.1"
port = int(os.environ.get("DRLMS_PORT", "15034"))

temp_dir = Path("/tmp/drlms_manual_test")
if not temp_dir.exists():
    temp_dir.mkdir(parents=True)
users_file = Path("users.txt")

# create token store path
token_file = temp_dir / "tokens.json"
store = TokenStore(token_file)

print("Logging in...")
client = create_mp2_client(host, port, token_store_path=token_file)
with client as c:
    # Login to get a valid token
    token_record = c.login("bob", users_file=users_file)
    print(
        f"Logged in as {token_record.username}, token expires at {token_record.access_expires_at}"
    )

    try:
        print("Requesting members...")
        members = c.get_room_members("bob", "test_manual")
        print("Members:", members)
    except Exception as e:
        print("Error:", e)

print("done")
