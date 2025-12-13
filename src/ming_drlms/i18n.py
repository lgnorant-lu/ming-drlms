from __future__ import annotations

import os
from typing import Dict


# Lightweight pseudo-i18n: centralize help texts; currently only English.
# Future: add zh_texts and a language switch.

en_texts: Dict[str, str] = {
    # Server
    "HELP.SERVER.UP": "Start server in background with health check.\n\nExamples:\n  ming-drlms server-up -p 15035 -d server_files --no-strict\n",
    "HELP.SERVER.DOWN": "Stop server via PID file; fallback to pkill.\n\nExamples:\n  ming-drlms server-down\n",
    "HELP.SERVER.STATUS": "Show server status and recent log tail.\n\nExamples:\n  ming-drlms server-status -p 15035\n",
    # Auth
    "HELP.AUTH.LOGIN": "Authenticate using M-Proto-v2 challenge/response and cache tokens locally.\n\nExamples:\n  ming-drlms login -u $DRLMS_USER -H 127.0.0.1 -p 5000 --users-file server_files/users.txt\n  ming-drlms login -u myuser --password-hash-file myuser.hash\n",
    "HELP.AUTH.LOGOUT": "Revoke cached tokens for a user session.\n\nExamples:\n  ming-drlms logout -u myuser -H 127.0.0.1 -p 15035\n",
    # User
    "HELP.USER.ADD": "Create a new user with Argon2id password (interactive or stdin).\n\nSecurity: avoid plain passwords in shell history; prefer stdin.\nExamples:\n  echo 'p@ss' | ming-drlms user add myuser -d server_files -x\n",
    "HELP.USER.PASSWD": "Change password for an existing user (Argon2id).\n\nSecurity: avoid plain passwords in shell history; prefer stdin.\nExamples:\n  echo 'new' | ming-drlms user passwd myuser -d server_files -x\n",
    "HELP.USER.LIST": "List users and formats (argon2/legacy).\n\nExamples:\n  ming-drlms user list -d server_files --json\n",
    "HELP.USER.DEL": "Delete a user. Use --force to ignore missing.\n\nExamples:\n  ming-drlms user del myuser -d server_files\n  ming-drlms user del ghost -d server_files --force\n",
    # IPC
    "HELP.IPC.SEND": "Send one message via shared memory (ipc_sender).\n\nExamples:\n  echo 'hi' | ming-drlms ipc send\n  ming-drlms ipc send --file /tmp/file.txt\n",
    "HELP.IPC.TAIL": "Tail messages via shared memory (log_consumer).\n\nExamples:\n  ming-drlms ipc tail -n 3\n",
    # Teaching help
    "HELP.TOPIC": "Show rich help for a topic (user|server|ipc).\n\nExamples:\n  ming-drlms help user\n",
    # Room
    "HELP.ROOM.INFO": "Query room info.\n\nExamples:\n  ming-drlms room info --room demo --user $DRLMS_USER\n",
    "HELP.ROOM.SUB": "Subscribe to a room via M-Proto-v2 and print events.\n\nExamples:\n  ming-drlms room sub --room demo --user $DRLMS_USER --limit 10\n  ming-drlms room sub --room demo --user $DRLMS_USER --json\n",
    "HELP.ROOM.PUB": "Publish a text or binary payload into a room using M-Proto-v2.\n\nExamples:\n  ming-drlms room pub --room demo --user $DRLMS_USER --text 'hello world'\n  ming-drlms room pub --room demo --user $DRLMS_USER --file payload.bin --ephemeral\n",
    "HELP.ROOM.SETPOLICY": "Set room policy (owner only).\n\nExamples:\n  ming-drlms room set-policy --room demo --policy delegate --user $DRLMS_USER\n",
    "HELP.ROOM.TRANSFER": "Transfer room ownership (owner only).\n\nExamples:\n  ming-drlms room transfer --room demo --new-owner newowner --user $DRLMS_USER\n",
    # Config
    "HELP.CONFIG.INIT": "Write config template to a path.\n\nExamples:\n  ming-drlms config init --path drlms.yaml\n",
    # Server logs
    "HELP.SERVER.LOGS": "Show server log tail.\n\nExamples:\n  ming-drlms server-logs -n 20\n",
    # Coverage
    "HELP.COVERAGE.RUN": "Run coverage workflow to produce coverage files.\n\nExamples:\n  ming-drlms coverage run\n",
    "HELP.COVERAGE.SHOW": "Show coverage gcov output head.\n\nExamples:\n  ming-drlms coverage show -\n",
    # Test
    "HELP.TEST.IPC": "Run IPC unit test.\n\nExamples:\n  ming-drlms test ipc\n",
    "HELP.TEST.INTEGRATION": "Run protocol integration test.\n\nExamples:\n  ming-drlms test integration --host 127.0.0.1 --port 15035\n",
    "HELP.TEST.ALL": "Run all tests (ipc + integration).\n\nExamples:\n  ming-drlms test all -\n",
    # Dist
    "HELP.DIST.BUILD": "Build distribution artifacts via Makefile.\n\nExamples:\n  ming-drlms dist build\n",
    "HELP.DIST.INSTALL": "Install artifacts via Makefile (optional sudo).\n\nExamples:\n  ming-drlms dist install\n",
    "HELP.DIST.UNINSTALL": "Uninstall artifacts via Makefile (optional sudo).\n\nExamples:\n  ming-drlms dist uninstall\n",
    # Demo
    "HELP.DEMO.QUICKSTART": "Run a quick demo: server up, basic client ops, tests, down.\n\nExamples:\n  ming-drlms demo quickstart\n",
    # Collect
    "HELP.COLLECT.ARTIFACTS": "Pack logs/coverage/meta into a tar.gz under --out directory.\n\nExamples:\n  ming-drlms collect artifacts --out artifacts\n",
    "HELP.COLLECT.RUN": "Run minimal coverage flow then pack artifacts.\n\nExamples:\n  ming-drlms collect run --out artifacts\n",
    # Dev group (new)
    "HELP.DEV.TEST": "Developer: run tests (ipc/integration/all).\n\nExamples:\n  ming-drlms dev test ipc\n  ming-drlms dev test integration --host 127.0.0.1 --port 15035\n  ming-drlms dev test all\n",
    "HELP.DEV.COVERAGE": "Developer: coverage helpers (run/show).\n\nExamples:\n  ming-drlms dev coverage run\n  ming-drlms dev coverage show -\n",
    "HELP.DEV.PKG": "Developer: package build/install/uninstall.\n\nExamples:\n  ming-drlms dev pkg build\n  ming-drlms dev pkg install --sudo\n  ming-drlms dev pkg uninstall --sudo\n",
    "HELP.DEV.ARTIFACTS": "Developer: collect artifacts (logs/coverage/meta).\n\nExamples:\n  ming-drlms dev artifacts run --out artifacts\n",
}


def t(key: str, **kwargs) -> str:
    _lang = os.environ.get("DRLMS_LANG", "en").lower()
    # Only English for now; switch table reserved for future
    mapping = en_texts
    val = mapping.get(key, key)
    try:
        return val.format(**kwargs)
    except Exception:
        return val
