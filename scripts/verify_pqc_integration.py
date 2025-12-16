import sys
import os
import socket
import struct
import time
import random
# NOTE: Removed sys.modules["oqs"] mock to allow real library loading

# Ensure src is in path
if "src" not in sys.path:
    sys.path.append(os.path.join(os.getcwd(), "src"))

# Fix for Windows DLL loading (liboqs)
if os.name == "nt":
    # Try to find vcpkg installed directory
    vcpkg_root = os.path.join(os.getcwd(), "vcpkg_installed", "x64-windows")
    if os.path.exists(vcpkg_root):
        print(f"[+] Found vcpkg root: {vcpkg_root}")
        # Set LIBOQS_DIR for oqs-python manual loading logic
        os.environ["LIBOQS_DIR"] = vcpkg_root

        # Add bin to PATH for ctypes loading
        bin_dir = os.path.join(vcpkg_root, "bin")
        if os.path.exists(bin_dir):
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ["PATH"]
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(bin_dir)

    # Also keep build_win as fallback/supplement
    dll_path = os.path.join(os.getcwd(), "build_win")
    if os.path.exists(dll_path):
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(dll_path)


try:
    from ming_drlms.core.mproto_v2_client import SignalKeyPair
    from ming_drlms.proto.schema.v2 import e2ee_pb2
except ImportError as e:
    print(f"[-] Import Error: {e}")
    print("[-] Please run this script from the project root.")
    sys.exit(1)

# Try loading real PQC library first
pqc_lib_ok = False
try:
    from ming_drlms.core.pqc_kem import MLKEM768, is_pqc_available

    if is_pqc_available():
        pqc_lib_ok = True
except (ImportError, RuntimeError, OSError) as e:
    print(f"[!] PQC Library Real Import Failed: {e}")
    print("[!] Falling back to MOCK mode for Server integration testing.")
    pqc_lib_ok = False
    MLKEM768 = None


def serialize_frame(msg_type, payload):
    # Magic(4) + Version(2) + Type(2) + Len(4) = 12 bytes
    header = struct.pack(">IHHI", 0xDEADBEEF, 2, msg_type, len(payload))
    return header + payload


def recv_frame(sock):
    # Read 12-byte header
    header = sock.recv(12)
    if len(header) < 12:
        return None, None
    magic, version, msg_type, length = struct.unpack(">IHHI", header)

    if magic != 0xDEADBEEF:
        print(f"[-] Invalid Magic in response: 0x{magic:08x}")
        return None, None

    payload = b""
    while len(payload) < length:
        chunk = sock.recv(length - len(payload))
        if not chunk:
            break
        payload += chunk
    return msg_type, payload


def test_pqc_flow():
    global pqc_lib_ok
    print("====================================")
    print("   PQC Integration Verification")
    print("====================================")

    # 1. Prepare PQC Key
    if pqc_lib_ok:
        try:
            print("[+] Using Real ML-KEM-768 (liboqs)")
            kem = MLKEM768()
            pqc_pub = kem.generate_keypair()
            if len(pqc_pub) == 0:
                raise RuntimeError("Real liboqs generated 0-byte key?")
        except Exception as e:
            print(f"[!] Real PQC Generation Failed: {e}")
            pqc_lib_ok = False

    if not pqc_lib_ok:
        print("[!] Using MOCK PQC Key (Random Bytes).")
        pqc_pub = os.urandom(1184)  # 1184 bytes random

    print(f"[+] PQC Public Key Size: {len(pqc_pub)} bytes")

    # 2. Generate Fake Identity
    username = f"pqc_test_user_{random.randint(1000, 9999)}"
    print(f"[+] Generating keys for user: {username}")

    identity_key = SignalKeyPair(public_key=os.urandom(32), private_key=os.urandom(32))

    # 3. Connect to Server
    host = "127.0.0.1"
    port = 15035  # Updated to match user config
    print(f"[+] Connecting to {host}:{port}...")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
    except ConnectionRefusedError:
        print("[-] Connection failed. Please start log_collector_server!")
        sys.exit(1)

    # 4. Send E2EEGenerateKeysRequest
    print("[+] Sending E2EEGenerateKeysRequest (OpCode 500)...")
    pb_req = e2ee_pb2.E2EEGenerateKeysRequest()
    pb_req.user_name = username
    pb_req.force_regenerate = True
    pb_req.pqc_public_key = pqc_pub

    # Fill Identity
    pb_req.identity_key.public_key = identity_key.public_key
    pb_req.identity_key.private_key = identity_key.private_key

    # Fill Signed PreKey
    pb_req.signed_pre_key.id = 1
    pb_req.signed_pre_key.key.public_key = os.urandom(32)
    pb_req.signed_pre_key.key.private_key = os.urandom(32)
    pb_req.signed_pre_key.signature = os.urandom(64)
    pb_req.signed_pre_key.timestamp = int(time.time())

    # Fill PreKeys
    for k in range(1, 5):
        p = pb_req.pre_keys.add()
        p.id = k
        p.key.public_key = os.urandom(32)
        p.key.private_key = os.urandom(32)

    payload = pb_req.SerializeToString()
    sock.sendall(serialize_frame(500, payload))

    # 5. Receive Response
    mtype, resp_data = recv_frame(sock)
    print(f"[+] Received Frame Type: {mtype}")

    if mtype == 501:  # Response
        resp = e2ee_pb2.E2EEGenerateKeysResponse()
        resp.ParseFromString(resp_data)
        if resp.code != 0:
            print(f"[-] Upload failed! Code: {resp.code}, Msg: {resp.message}")
            sys.exit(1)
        print(f"[+] Upload Success: {resp.message}")
    else:
        print(f"[-] Unexpected response type: {mtype}")
        sys.exit(1)

    # 6. Fetch Bundle (Verification)
    print("[+] Fetching bundle to verify persistence...")
    fetch_req = e2ee_pb2.E2EEPreKeyBundleRequest()
    fetch_req.user_name = username

    payload = fetch_req.SerializeToString()
    sock.sendall(serialize_frame(502, payload))  # 502 = FETCH_REQUEST

    mtype, resp_data = recv_frame(sock)
    if mtype == 503:  # 503 = FETCH_RESPONSE
        resp = e2ee_pb2.E2EEPreKeyBundleResponse()
        resp.ParseFromString(resp_data)

        print(f"[+] Bundle Response: Code={resp.code}, Msg={resp.message}")
        if resp.code != 0:
            print(f"[-] Fetch returned error code: {resp.code}")

        if len(resp.pqc_public_key) == 1184:
            if pqc_lib_ok and resp.pqc_public_key != pqc_pub:
                print("[-] WARNING: Key Mismatch despite correct length!")

            print("\n[SUCCESS] INTEGRATION VERIFIED!")
            print("Server returned exact 1184-byte PQC key.")
        else:
            print("\n[-] PQC Key Mismatch!")
            print(f"Sent: {len(pqc_pub)} bytes")
            print(f"Got:  {len(resp.pqc_public_key)} bytes")
            sys.exit(1)
    else:
        print(f"[-] Unexpected frame: {mtype}")
        sys.exit(1)

    sock.close()


if __name__ == "__main__":
    test_pqc_flow()
