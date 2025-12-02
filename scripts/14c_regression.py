import argparse
import hashlib
import os
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Ensure 'src' is importable when running from repo root
sys.path.insert(0, str(Path("src").resolve()))

from ming_drlms.proto.schema.v2 import auth_pb2, common_pb2  # type: ignore
from ming_drlms.core.mp2_transport import read_frame, write_frame  # type: ignore
from ming_drlms.core.e2ee_store import LocalKeyStore  # type: ignore
from ming_drlms.users import parse_users  # type: ignore
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # type: ignore
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat  # type: ignore


def _resolve_users_file(users_file: Optional[str | Path]) -> Path:
    if users_file is None:
        # default to repo-root users.txt
        return Path("users.txt").resolve()
    return Path(users_file).expanduser().resolve()


def _lookup_hash(users_file: Path, username: str) -> str:
    for name, _kind, enc in parse_users(users_file):
        if name == username:
            return enc
    raise RuntimeError(f"user not found in users file: {username} ({users_file})")


@dataclass(slots=True)
class HandshakeResult:
    ok: bool
    access_token: str | None
    refresh_token: str | None
    accepted_device_id: int | None
    recorded_identity: bool | None
    message: str


def perform_handshake(
    host: str,
    port: int,
    username: str,
    *,
    users_file: Path,
    add_clientinfo: bool,
    tamper_sig: bool = False,
    skew_seconds: Optional[int] = None,
    config_dir: Optional[Path] = None,
    timeout: float = 10.0,
) -> HandshakeResult:
    # Optional keystore base
    if config_dir is not None:
        os.environ["MING_DRLMS_CONFIG_DIR"] = str(config_dir.expanduser())

    stored_hash = _lookup_hash(users_file, username)

    # Connect
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        # 1) Challenge
        ch_req = auth_pb2.AuthChallengeRequest()
        ch_req.username = username
        write_frame(
            sock, common_pb2.MSG_TYPE_AUTH_CHALLENGE_REQUEST, ch_req.SerializeToString()
        )
        frame = read_frame(sock)
        if frame.msg_type != common_pb2.MSG_TYPE_AUTH_CHALLENGE_RESPONSE:
            return HandshakeResult(
                False, None, None, None, None, f"unexpected msg_type={frame.msg_type}"
            )
        ch_resp = auth_pb2.AuthChallengeResponse()
        ch_resp.ParseFromString(frame.payload)
        nonce = ch_resp.nonce
        server_salt = getattr(ch_resp, "server_salt", "") or ""
        if not nonce:
            return HandshakeResult(
                False, None, None, None, None, "missing nonce in challenge"
            )

        # 2) Auth
        digest = hashlib.sha256((stored_hash + nonce).encode()).hexdigest()
        auth_req = auth_pb2.AuthRequest()
        auth_req.username = username
        auth_req.response = digest

        if add_clientinfo:
            # Build ClientInfo from local keystore
            ks = LocalKeyStore()
            st = ks.load_state(username)
            if st is None or not getattr(st, "identity_key", None):
                return HandshakeResult(
                    False,
                    None,
                    None,
                    None,
                    None,
                    "no local E2EE identity; run e2ee-init first",
                )
            seed = st.identity_key.private_key
            seed_b = seed if isinstance(seed, (bytes, bytearray)) else bytes(seed)
            priv = Ed25519PrivateKey.from_private_bytes(seed_b[:32])
            pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
            ts = int(time.time())
            if isinstance(skew_seconds, int):
                # negative test: shift timestamp into past/future by skew_seconds
                ts = int(time.time()) - int(skew_seconds)
            parts = [
                b"MP2-LOGIN-V1",
                username.encode("utf-8"),
                str(int(getattr(st, "device_id", 0))).encode("ascii"),
                str(int(getattr(st, "registration_id", 0))).encode("ascii"),
                (nonce or "").encode("ascii"),
                (server_salt or "").encode("utf-8"),
                str(ts).encode("ascii"),
            ]
            binding = b"|".join(parts)
            sig = priv.sign(binding)
            if tamper_sig and sig:
                # flip one bit
                sig = bytes([sig[0] ^ 0x01]) + sig[1:]

            client = auth_pb2.ClientInfo()
            client.device_id = int(getattr(st, "device_id", 0))
            client.registration_id = int(getattr(st, "registration_id", 0))
            client.identity_pubkey = pub
            client.identity_sig = sig
            client.sig_ts = int(ts)
            try:
                client.platform = os.name
            except Exception:
                pass
            # Attach when field exists (py3 proto always has it here)
            try:
                auth_req.client.CopyFrom(client)
            except Exception:
                pass

        write_frame(
            sock, common_pb2.MSG_TYPE_AUTH_REQUEST, auth_req.SerializeToString()
        )
        frame = read_frame(sock)
        if frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
            # Decode error for context
            from ming_drlms.proto.schema.v2 import common_pb2 as c2  # type: ignore

            err = c2.ErrorResponse()
            err.ParseFromString(frame.payload)
            return HandshakeResult(
                False, None, None, None, None, f"{err.code}: {err.message}"
            )
        if frame.msg_type != common_pb2.MSG_TYPE_AUTH_RESPONSE:
            return HandshakeResult(
                False, None, None, None, None, f"unexpected msg_type={frame.msg_type}"
            )
        resp = auth_pb2.AuthResponse()
        resp.ParseFromString(frame.payload)
        if not resp.access_token or not resp.refresh_token:
            return HandshakeResult(
                False, None, None, None, None, "server did not return tokens"
            )
        return HandshakeResult(
            True,
            resp.access_token,
            resp.refresh_token,
            int(getattr(resp, "accepted_device_id", 0))
            if hasattr(resp, "accepted_device_id")
            else None,
            bool(getattr(resp, "recorded_identity", False))
            if hasattr(resp, "recorded_identity")
            else None,
            "ok",
        )
    finally:
        try:
            sock.close()
        except Exception:
            pass


def main() -> int:
    p = argparse.ArgumentParser(description="14C MP2 login regression (pos/neg)")
    p.add_argument(
        "subcmd",
        choices=["pos", "neg-missing-ci", "neg-tamper", "neg-skew"],
        help="which test to run",
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=15035)
    p.add_argument("--user", required=True)
    p.add_argument(
        "--users-file", dest="users_file", default=str(Path("users.txt").resolve())
    )
    p.add_argument(
        "--config-dir",
        dest="config_dir",
        default=str((Path.cwd() / ".drlms").resolve()),
    )
    p.add_argument("--timeout", type=float, default=10.0)
    args = p.parse_args()

    users_file = _resolve_users_file(args.users_file)
    config_dir = Path(args.config_dir).expanduser()

    if args.subcmd == "pos":
        res = perform_handshake(
            args.host,
            args.port,
            args.user,
            users_file=users_file,
            add_clientinfo=True,
            tamper_sig=False,
            skew_seconds=None,
            config_dir=config_dir,
            timeout=args.timeout,
        )
    elif args.subcmd == "neg-missing-ci":
        res = perform_handshake(
            args.host,
            args.port,
            args.user,
            users_file=users_file,
            add_clientinfo=False,
            tamper_sig=False,
            skew_seconds=None,
            config_dir=config_dir,
            timeout=args.timeout,
        )
    elif args.subcmd == "neg-tamper":
        res = perform_handshake(
            args.host,
            args.port,
            args.user,
            users_file=users_file,
            add_clientinfo=True,
            tamper_sig=True,
            skew_seconds=None,
            config_dir=config_dir,
            timeout=args.timeout,
        )
    elif args.subcmd == "neg-skew":
        # 1 hour skew (default server skew=300s) should fail under strict
        res = perform_handshake(
            args.host,
            args.port,
            args.user,
            users_file=users_file,
            add_clientinfo=True,
            tamper_sig=False,
            skew_seconds=3600,
            config_dir=config_dir,
            timeout=args.timeout,
        )
    else:
        print("unknown subcmd", file=sys.stderr)
        return 2

    status = "OK" if res.ok else "FAIL"
    print(
        f"[{status}] user={args.user} accepted_device_id={res.accepted_device_id} "
        f"recorded_identity={res.recorded_identity} msg={res.message}"
    )
    if res.access_token:
        print(
            f"access_token[0:8]={res.access_token[:8]}... refresh_token[0:8]={res.refresh_token[:8] if res.refresh_token else ''}..."
        )
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
