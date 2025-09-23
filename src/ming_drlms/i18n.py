from __future__ import annotations

import os
from typing import Dict


# Lightweight pseudo-i18n: centralize help texts; currently only English.
# Future: add zh_texts and a language switch.

en_texts: Dict[str, str] = {
    # Server
    "HELP.SERVER.UP": "Start server in background with health check.\n\nExamples:\n  ming-drlms server-up -p 8080 -d server_files --no-strict\n",
    "HELP.SERVER.DOWN": "Stop server via PID file; fallback to pkill.\n\nExamples:\n  ming-drlms server-down\n",
    "HELP.SERVER.STATUS": "Show server status and recent log tail.\n\nExamples:\n  ming-drlms server-status -p 8080\n",
    # User
    "HELP.USER.ADD": "Create a new user with Argon2id password (interactive or stdin).\n\nSecurity: avoid plain passwords in shell history; prefer stdin.\nExamples:\n  echo 'p@ss' | ming-drlms user add alice -d server_files -x\n",
    "HELP.USER.PASSWD": "Change password for an existing user (Argon2id).\n\nSecurity: avoid plain passwords in shell history; prefer stdin.\nExamples:\n  echo 'new' | ming-drlms user passwd alice -d server_files -x\n",
    "HELP.USER.LIST": "List users and formats (argon2/legacy).\n\nExamples:\n  ming-drlms user list -d server_files --json\n",
    "HELP.USER.DEL": "Delete a user. Use --force to ignore missing.\n\nExamples:\n  ming-drlms user del alice -d server_files\n  ming-drlms user del ghost -d server_files --force\n",
    # Space
    "HELP.SPACE.JOIN": "Subscribe to a room and tail events (with resume).\n\nExamples:\n  ming-drlms space join -r demo -H 127.0.0.1 -p 8080 -R -j\n",
    "HELP.SPACE.SEND": "Publish text or file into a room.\n\nExamples:\n  ming-drlms space send -r demo -t 'hello'\n  ming-drlms space send -r demo -f /path/to/file\n",
    "HELP.SPACE.HISTORY": "Fetch historical events for a room.\n\nExamples:\n  ming-drlms space history -r demo -n 10 -s 0\n",
    "HELP.SPACE.LEAVE": "Unsubscribe from a room.\n\nExamples:\n  ming-drlms space leave -r demo -H 127.0.0.1 -p 8080 -u alice -P password\n",
    "HELP.SPACE.CHAT": "Interactive room chat: stdout tails, stdin publishes.\n\nExamples:\n  ming-drlms space chat --room demo -H 127.0.0.1 -p 8080 -u alice -P password\n",
    # IPC
    "HELP.IPC.SEND": "Send one message via shared memory (ipc_sender).\n\nExamples:\n  echo 'hi' | ming-drlms ipc send\n  ming-drlms ipc send --file /tmp/file.txt\n",
    "HELP.IPC.TAIL": "Tail messages via shared memory (log_consumer).\n\nExamples:\n  ming-drlms ipc tail -n 3\n",
    # Teaching help
    "HELP.TOPIC": "Show rich help for a topic (user|space|server|ipc).\n\nExamples:\n  ming-drlms help user\n",
    # Client
    "HELP.CLIENT.LIST": "List files on server (LOGIN -> LIST).\n\nExamples:\n  ming-drlms client list -H 127.0.0.1 -p 8080 -u alice -P password\n",
    "HELP.CLIENT.UPLOAD": "Upload a file to server (LOGIN -> UPLOAD).\n\nExamples:\n  ming-drlms client upload README.md -H 127.0.0.1 -p 8080 -u alice -P password\n",
    "HELP.CLIENT.DOWNLOAD": "Download a file from server (LOGIN -> DOWNLOAD).\n\nExamples:\n  ming-drlms client download README.md -o /tmp/README.md -H 127.0.0.1 -p 8080 -u alice -P password\n",
    "HELP.CLIENT.LOG": "Send a single LOG message.\n\nExamples:\n  ming-drlms client log "
    "hello"
    " -H 127.0.0.1 -p 8080 -u alice -P password\n",
    # Room
    "HELP.ROOM.INFO": "Query room info (ROOMINFO).\n\nExamples:\n  ming-drlms space room info -r demo -H 127.0.0.1 -p 8080 -u alice -P password\n",
    "HELP.ROOM.SETPOLICY": "Set room policy (owner only).\n\nExamples:\n  ming-drlms space room set-policy -r demo --policy delegate -H 127.0.0.1 -p 8080 -u alice -P password\n",
    "HELP.ROOM.TRANSFER": "Transfer room ownership (owner only).\n\nExamples:\n  ming-drlms space room transfer -r demo -n bob -H 127.0.0.1 -p 8080 -u alice -P password\n",
    # Config
    "HELP.CONFIG.INIT": "Write config template to a path.\n\nExamples:\n  ming-drlms config init --path drlms.yaml\n",
    # Server logs
    "HELP.SERVER.LOGS": "Show server log tail.\n\nExamples:\n  ming-drlms server-logs -n 20\n",
    # Coverage
    "HELP.COVERAGE.RUN": "Run coverage workflow to produce coverage files.\n\nExamples:\n  ming-drlms coverage run\n",
    "HELP.COVERAGE.SHOW": "Show coverage gcov output head.\n\nExamples:\n  ming-drlms coverage show -\n",
    # Test
    "HELP.TEST.IPC": "Run IPC unit test.\n\nExamples:\n  ming-drlms test ipc\n",
    "HELP.TEST.INTEGRATION": "Run protocol integration test.\n\nExamples:\n  ming-drlms test integration --host 127.0.0.1 --port 8080\n",
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
    "HELP.DEV.TEST": "Developer: run tests (ipc/integration/all).\n\nExamples:\n  ming-drlms dev test ipc\n  ming-drlms dev test integration --host 127.0.0.1 --port 8080\n  ming-drlms dev test all\n",
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
