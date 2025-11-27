import sys
from pathlib import Path

# Ensure src is in path
sys.path.insert(0, str(Path("src").resolve()))

from ming_drlms.core.mproto_v2_client import MP2Client, TokenStore, login_flow
from ming_drlms.users import generate_argon2id_hash, read_auth_params_from_env

# Assuming server is running on 15035
HOST = "127.0.0.1"
PORT = 15035


def get_password_hash(password: str) -> str:
    params = read_auth_params_from_env()
    return generate_argon2id_hash(
        password,
        time_cost=params["time_cost"],
        memory_cost=params["memory_cost"],
        parallelism=params["parallelism"],
        hash_len=params["hash_len"],
        salt_len=params["salt_len"],
    )


def test_upload():
    print("Checking for existing token...")
    store = TokenStore()
    record = store.load("bob", HOST, PORT)

    if not record:
        print("No token found, attempting login...")
        try:
            # Try legitimate login with password reset
            pwd_hash = get_password_hash("password123")
            record = login_flow(HOST, PORT, "bob", password_hash=pwd_hash)
            print(f"Got new token for {record.username}")
            store.store(record)
        except Exception as e:
            print(f"Login failed: {e}")
            return
    else:
        print(f"Using existing token for {record.username}")

    with MP2Client(HOST, PORT, token_store=store, timeout=60.0) as client:
        # Create room if not exists (idempotentish)
        try:
            client.create_room(record.username, "UploadTest")
        except Exception:
            pass  # Maybe exists

        # Try publish begin
        print("Attempting publish_file_begin...")
        try:
            upload_id = client.publish_file_begin(
                record.username,
                "FinalTest",
                "test.txt",
                123,  # size
                "00" * 32,  # dummy sha256
                ephemeral=False,
            )
            print(f"SUCCESS: Got upload_id: {upload_id}")
        except Exception as e:
            print(f"FAILURE: {e}")


if __name__ == "__main__":
    test_upload()
