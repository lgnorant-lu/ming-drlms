import argparse
import os
import sys
from pathlib import Path

# Ensure 'src' is importable when running from repo root
sys.path.insert(0, str(Path("src").resolve()))

from ming_drlms.core.mproto_v2_client import MP2Client, AuthenticationError, MP2Error  # type: ignore
from ming_drlms.core.token_store import TokenStore  # type: ignore


def main() -> int:
    p = argparse.ArgumentParser(
        description="MP2 refresh-token flow regression (login + refresh + list_rooms)",
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=15035)
    p.add_argument("--user", required=True)
    p.add_argument(
        "--users-file",
        dest="users_file",
        default=str((Path("users.txt").resolve())),
    )
    p.add_argument(
        "--config-dir",
        dest="config_dir",
        default=str((Path.cwd() / ".drlms").resolve()),
    )
    p.add_argument("--timeout", type=float, default=10.0)
    args = p.parse_args()

    if args.config_dir:
        os.environ["MING_DRLMS_CONFIG_DIR"] = str(Path(args.config_dir).expanduser())

    host: str = args.host
    port: int = int(args.port)
    username: str = args.user
    users_file = Path(args.users_file).expanduser().resolve()

    store = TokenStore()
    client = MP2Client(host, port, timeout=args.timeout, token_store=store)
    try:
        # 1) Login to obtain initial access/refresh tokens
        rec = client.login(username, users_file=users_file)
        print(
            f"[LOGIN OK] user={username} "
            f"access[0:8]={rec.access_token[:8]} "
            f"refresh[0:8]={rec.refresh_token[:8]}"
        )

        # 2) Explicit refresh using refresh_token
        refreshed = client.refresh_token(rec)
        same_rt = refreshed.refresh_token == rec.refresh_token
        print(
            f"[REFRESH OK] user={username} "
            f"access[0:8]={refreshed.access_token[:8]} "
            f"refresh_same={same_rt}"
        )

        # 3) Use refreshed access token for a simple API call (list_rooms)
        rooms, total, has_more = client.list_rooms(username)
        print(f"[ROOMS OK] total={total} has_more={has_more}")
        return 0
    except AuthenticationError as e:
        print(f"[FAIL] auth error: {e}", file=sys.stderr)
        return 1
    except MP2Error as e:
        print(f"[FAIL] mp2 error: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # pragma: no cover - defensive
        print(f"[FAIL] unexpected: {e}", file=sys.stderr)
        return 1
    finally:
        try:
            client.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
