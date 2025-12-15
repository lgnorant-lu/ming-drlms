from __future__ import annotations

import os
from typing import Dict


# Lightweight pseudo-i18n: centralize help texts; Chinese as primary.
# Future: add language switch if needed.

zh_texts: Dict[str, str] = {
    # App Global
    "HELP.APP.DESC": "ming-drlms: DRLMS 项目命令行工具",
    "HELP.OPT.VERSION": "显示版本信息并退出",
    "HELP.OPT.LOG_LEVEL": "覆盖本次运行的日志级别",
    "HELP.OPT.LOG_DIR": "覆盖本次运行的日志目录",
    "HELP.OPT.LOG_CONSOLE": "启用/禁用本次运行的控制台日志",
    # Common Options
    "HELP.OPT.USER": "用户名",
    "HELP.OPT.HOST": "服务器主机",
    "HELP.OPT.PORT": "服务器端口",
    "HELP.OPT.TIMEOUT": "socket 超时时间（秒）",
    "HELP.OPT.TOKEN_STORE": "覆盖 token 缓存路径（默认: ~/.drlms/tokens.json）",
    # Auth Specific
    "HELP.AUTH.LOGIN": "登录到 DRLMS 服务器并缓存 token",
    "HELP.AUTH.LOGOUT": "撤销用户会话的缓存 token",
    "HELP.OPT.PWD_HASH": "预计算的 Argon2 哈希（覆盖 --password-hash-file）",
    "HELP.OPT.PWD_HASH_FILE": "包含 Argon2 哈希的文件路径",
    "HELP.OPT.USERS_FILE": "用于验证 Argon2 哈希的 users.txt 位置",
    # User
    "HELP.USER.DESC": "用户管理 (add/del/passwd/list - 需要 Admin 权限)",
    # Help
    "HELP.TOPIC": "显示特定主题的帮助信息 (user, server, room...)",
    # TUI
    "HELP.CMD.TUI": "启动 Textual TUI 终端界面（实验性）",
    # XEdDSA
    "HELP.CMD.XEDDSA": "使用本地keystore身份运行 XEdDSA 签名/验证自测",
    "HELP.OPT.KEYSTORE_USER": "keystore 查找用户名",
    # Server
    "HELP.SERVER.DESC": "服务器管理 (up/down/status/logs)",
    "HELP.SERVER.UP": "后台启动服务器并进行健康检查\n\n示例:\n  ming-drlms server-up -p 15035 -d server_files --no-strict\n",
    "HELP.SERVER.DOWN": "通过 PID 文件停止服务器；如失败则回退到 pkill\n\n示例:\n  ming-drlms server-down\n",
    "HELP.SERVER.STATUS": "显示服务器状态和最近日志\n\n示例:\n  ming-drlms server-status -p 15035\n",
    "HELP.SERVER.LOGS": "显示服务器日志尾部\n\n示例:\n  ming-drlms server-logs -n 20\n",
    "HELP.SERVER.OPT.VERBOSE": "显示服务器输出",
    # Room
    "HELP.ROOM.DESC": "[MP2模式] 房间管理 (需要 MP2 服务器连接)",
    "HELP.ROOM.INFO": "查询房间信息\n\n示例:\n  ming-drlms room info --room demo --user $DRLMS_USER\n",
    "HELP.ROOM.SUB": "通过 M-Proto-v2 订阅房间并打印事件\n\n示例:\n  ming-drlms room sub --room demo --user $DRLMS_USER --limit 10\n  ming-drlms room sub --room demo --user $DRLMS_USER --json\n",
    "HELP.ROOM.CMD.JOIN": "加入/订阅房间（sub 的别名，方便习惯传统命名的用户）",
    "HELP.ROOM.PUB": "通过 M-Proto-v2 向房间发布文本或二进制消息\n\n示例:\n  ming-drlms room pub --room demo --user $DRLMS_USER --text 'hello world'\n  ming-drlms room pub --room demo --user $DRLMS_USER --file payload.bin --ephemeral\n",
    "HELP.ROOM.CREATE": "创建房间，可指定阅后即焚模式",
    "HELP.ROOM.SETPOLICY": "设置房间策略（仅房主）\n\n示例:\n  ming-drlms room set-policy --room demo --policy delegate --user $DRLMS_USER\n",
    "HELP.ROOM.SET_STORAGE": "设置房间存储策略",
    "HELP.ROOM.TRANSFER": "转让房间所有权（仅房主）\n\n示例:\n  ming-drlms room transfer --room demo --new-owner newowner --user $DRLMS_USER\n",
    "HELP.ROOM.MEMBERS": "查看房间成员列表",
    "HELP.ROOM.DOWNLOAD": "下载房间文件",
    "HELP.ROOM.CLEAR_OWNER": "清空房间owner（回归系统所有）",
    "HELP.ROOM.LOCAL_HISTORY": "显示本地存储的历史消息（离线可用）",
    "HELP.ROOM.OPT.ROOM": "房间名",
    "HELP.ROOM.OPT.SINCE": "从指定 event_id 开始",
    "HELP.ROOM.OPT.LIMIT": "最多接收事件数量 (0 表示不限)",
    "HELP.ROOM.OPT.JSON": "以 JSON 输出事件",
    "HELP.ROOM.OPT.JSON_OUT": "以 JSON 方式输出",
    "HELP.ROOM.OPT.JSON_OUTPUT": "JSON格式输出",
    "HELP.ROOM.OPT.E2EE_STORE": "端到端密钥仓库路径 (默认 ~/.drlms/e2ee_keys.json)",
    "HELP.ROOM.OPT.TEXT": "发送文本内容",
    "HELP.ROOM.OPT.FILE": "发送文件",
    "HELP.ROOM.OPT.STDIN": "从标准输入读取内容",
    "HELP.ROOM.OPT.EPHEMERAL": "使用阅后即焚事件",
    "HELP.ROOM.OPT.EPHEMERAL_CREATE": "使用阅后即焚存储策略",
    "HELP.ROOM.OPT.POLICY": "策略名",
    "HELP.ROOM.OPT.STORAGE_POLICY": "存储策略",
    "HELP.ROOM.OPT.NEW_OWNER": "新的拥有者用户名",
    "HELP.ROOM.OPT.EVENT_ID": "文件事件ID",
    "HELP.ROOM.OPT.OUTPUT": "输出文件路径",
    "HELP.ROOM.OPT.USER": "执行者用户名",
    "HELP.ROOM.OPT.LIMIT_ALT": "最大返回数量",
    "HELP.ROOM.OPT.SINCE_SEQ": "从指定 server_seq 之后开始",
    "HELP.ROOM.OPT.COMPRESSION": "压缩类型 (0=None, 1=Zlib, 2=Zstd)",
    # Relay Rooms (Relay Native)
    "HELP.R_ROOM.DESC": "[Relay模式] Relay-native 房间管理 (create/list/join/leave/invite)",
    "HELP.R_ROOM.CREATE": "创建新房间",
    "HELP.R_ROOM.LIST": "列出已加入的房间",
    "HELP.R_ROOM.INVITE": "生成房间邀请链接",
    "HELP.R_ROOM.JOIN": "通过邀请链接加入房间",
    "HELP.R_ROOM.LEAVE": "离开房间",
    "HELP.R_ROOM.DISCOVER": "发现公开房间",
    "HELP.R_ROOM.INFO": "显示房间详情",
    # Relay Room Options
    "HELP.R_ROOM.OPT.NAME": "房间名称",
    "HELP.R_ROOM.OPT.DESC": "房间描述",
    "HELP.R_ROOM.OPT.VISIBILITY": "可见性: private, unlisted, public",
    "HELP.R_ROOM.OPT.RELAYS": "Relay 列表 (逗号分隔)",
    "HELP.R_ROOM.OPT.VISIBILITY_FILTER": "按可见性过滤: private, unlisted, public",
    "HELP.R_ROOM.OPT.ID": "房间 ID 或前缀",
    "HELP.R_ROOM.OPT.INVITE": "邀请链接",
    "HELP.R_ROOM.OPT.FORCE": "跳过确认",
    # Config
    "HELP.CONFIG.DESC": "配置管理命令 (get/set/list/init)",
    "HELP.CONFIG.INIT": "将配置模板写入指定路径\n\n示例:\n  ming-drlms config init --path drlms.yaml\n",
    "HELP.CONFIG.INIT_TUI": "初始化 TUI 配置文件模板 (config.toml)",
    "HELP.CONFIG.INIT_CLI": "初始化服务器 CLI 配置文件 (drlms.yaml)",
    "HELP.CONFIG.APPLY_CLI": "应用本地配置(.drlms/drlms.yaml) 到用户配置目录 (需确认)",
    "HELP.CONFIG.APPLY_TUI": "应用本地项目配置 ./.drlms/config.toml 到用户配置 ~/.drlms/config.toml (需确认)",
    "HELP.CONFIG.SHOW": "显示原始/生效的配置视图",
    "HELP.CONFIG.VALIDATE": "验证配置的最低要求",
    "HELP.CONFIG.PATH": "显示配置文件路径",
    # Config Get/Set/List/Reset
    "HELP.CONFIG.GET": "获取配置项的值",
    "HELP.CONFIG.GET.KEY": "配置键 (例如: backend.mode, backend.relay.urls)",
    "HELP.CONFIG.GET.EFFECTIVE": "显示生效值(含环境变量覆盖)还是仅文件值",
    "HELP.CONFIG.SET": "设置配置项的值",
    "HELP.CONFIG.SET.KEY": "配置键 (例如: backend.mode)",
    "HELP.CONFIG.SET.VALUE": "配置值",
    "HELP.CONFIG.LIST": "列出所有配置项",
    "HELP.CONFIG.LIST.SECTION": "仅显示指定分区 (general, backend, identity, trust, logging)",
    "HELP.CONFIG.LIST.VERBOSE": "显示详细信息",
    "HELP.CONFIG.RESET": "重置配置项为默认值",
    "HELP.CONFIG.RESET.KEY": "要重置的配置键 (留空重置所有)",
    "HELP.CONFIG.RESET.CONFIRM": "跳过确认",
    # Config Options
    "HELP.CONFIG.OPT.TARGET": "写入目标位置: local (项目根目录), home (用户目录), both (两者)",
    "HELP.CONFIG.OPT.OVERWRITE": "覆盖现有用户配置",
    # Coverage
    "HELP.COVERAGE.RUN": "运行覆盖率工作流以生成覆盖率文件\n\n示例:\n  ming-drlms coverage run\n",
    "HELP.COVERAGE.SHOW": "显示覆盖率 gcov 输出的开头部分\n\n示例:\n  ming-drlms coverage show\n",
    # Test
    "HELP.TEST.IPC": "运行 IPC 单元测试\n\n示例:\n  ming-drlms test ipc\n",
    "HELP.TEST.INTEGRATION": "运行协议集成测试\n\n示例:\n  ming-drlms test integration --host 127.0.0.1 --port 15035\n",
    "HELP.TEST.ALL": "运行所有测试 (ipc + integration)\n\n示例:\n  ming-drlms test all\n",
    # Dist
    "HELP.DIST.BUILD": "通过 Makefile 构建分发包\n\n示例:\n  ming-drlms dist build\n",
    "HELP.DIST.INSTALL": "通过 Makefile 安装 (可选 sudo)\n\n示例:\n  ming-drlms dist install\n",
    "HELP.DIST.UNINSTALL": "通过 Makefile 卸载 (可选 sudo)\n\n示例:\n  ming-drlms dist uninstall\n",
    # Collect
    "HELP.COLLECT.ARTIFACTS": "将日志/覆盖率/元数据打包到 --out 目录下的 tar.gz\n\n示例:\n  ming-drlms collect artifacts --out artifacts\n",
    "HELP.COLLECT.RUN": "运行最小覆盖率流程然后打包产物\n\n示例:\n  ming-drlms collect run --out artifacts\n",
    # Dev group (new)
    "HELP.DEV.TEST": "开发者: 运行测试 (ipc/integration/all)\n\n示例:\n  ming-drlms dev test ipc\n  ming-drlms dev test integration --host 127.0.0.1 --port 15035\n  ming-drlms dev test all\n",
    "HELP.DEV.COVERAGE": "开发者: 覆盖率工具 (run/show)\n\n示例:\n  ming-drlms dev coverage run\n  ming-drlms dev coverage show\n",
    "HELP.DEV.PKG": "开发者: 包构建/安装/卸载\n\n示例:\n  ming-drlms dev pkg build\n  ming-drlms dev pkg install --sudo\n  ming-drlms dev pkg uninstall --sudo\n",
    "HELP.DEV.ARTIFACTS": "开发者: 收集产物 (logs/coverage/meta)\n\n示例:\n  ming-drlms dev artifacts run --out artifacts\n",
    # IPC
    "HELP.IPC.DESC": "[独立工具] 进程间通信 (IPC) - 基于共享内存的消息传递工具",
    "HELP.IPC.EPILOG": "注意: IPC 是独立的实验性功能，用于本地进程间通信，不依赖网络协议。",
    "HELP.IPC.SEND": "通过共享内存发送消息（包装 ipc_sender）",
    "HELP.IPC.OPT.MESSAGE": "要发送的文本消息",
    "HELP.IPC.OPT.FILE": "要发送的文件",
    "HELP.IPC.OPT.KEY": "共享内存键值 (十六进制)",
    "HELP.IPC.OPT.CHUNK": "块大小 (0=自动)",
    "HELP.IPC.LISTEN": "监听共享内存消息（包装 log_consumer）",
    "HELP.IPC.FILE_SEND": "发送文件（含元信息）到共享内存（实验五）",
    "HELP.IPC.FILE_SEND.ARG": "要发送的文件路径",
    "HELP.IPC.FILE_RECEIVE": "接收文件（含元信息）从共享内存（实验五）",
    "HELP.IPC.OPT.OUTPUT_DIR": "输出目录",
    # Demo
    "HELP.DEMO.DESC": "演示脚本",
    "HELP.DEMO.QUICKSTART": "运行快速演示: 启动服务器、基本客户端操作、测试、关闭",
    # Identity
    "HELP.IDENTITY.DESC": "[Relay模式] 本地身份管理 (create/show/fingerprint/export/import)",
    "HELP.IDENTITY.CREATE": "创建新的本地身份",
    "HELP.IDENTITY.OPT.NAME": "显示名称",
    "HELP.IDENTITY.OPT.USER": "用户名（用于 LocalKeyStore 兼容）",
    "HELP.IDENTITY.OPT.FORCE": "强制覆盖已有身份",
    "HELP.IDENTITY.SHOW": "显示当前身份信息",
    "HELP.IDENTITY.FINGERPRINT": "显示指纹（用于手动验证）",
    "HELP.IDENTITY.OPT.FORMAT": "格式: groups, compact, lines, numeric, emoji",
    "HELP.IDENTITY.EXPORT": "导出身份到文件",
    "HELP.IDENTITY.OPT.OUTPUT": "输出文件路径（默认: ~/.drlms/identity_backup.json）",
    "HELP.IDENTITY.IMPORT": "从文件导入身份",
    "HELP.IDENTITY.OPT.INPUT": "身份备份文件路径",
    "HELP.IDENTITY.QR": "生成身份验证二维码数据",
    # Relay Debug
    "HELP.RELAY.DESC": "[高级/实验] Relay 底层调试命令 (post/sync/identity - 开发者使用)",
    "HELP.RELAY.POST_SIMPLE": "发布消息 (使用 IdentityManager)",
    "HELP.RELAY.OPT.ROOM": "目标房间",
    "HELP.RELAY.OPT.CONTENT": "消息内容",
    "HELP.RELAY.OPT.USER": "用于身份查找的用户名",
    "HELP.RELAY.POST_MULTI": "发布消息到多个 Relay",
    "HELP.RELAY.OPT.CIPHERTEXT": "Base64 密文",
    "HELP.RELAY.OPT.HASH": "客户端事件哈希",
    "HELP.RELAY.OPT.CONFIG": "relays.toml 路径（可选）",
    "HELP.RELAY.SYNC_MULTI": "从多个 Relay 同步",
    "HELP.RELAY.IDENTITY": "管理客户端身份 (XEdDSA)",
    "HELP.RELAY.ARG.ACTION": "操作: show, create, export",
    # E2EE
    "HELP.E2EE.DESC": "[MP2模式] E2EE 密钥管理 (需要 MP2 服务器)",
    "HELP.E2EE.GENERATE_KEYS": "为用户生成端到端密钥",
    "HELP.E2EE.PREKEY_BUNDLE": "获取用户的预密钥包",
    "HELP.E2EE.OPT.TARGET_USER": "生成密钥的用户（默认与 --user 相同）",
    "HELP.E2EE.OPT.FORCE": "强制重新生成密钥",
    # Trust
    "HELP.TRUST.DESC": "[Relay模式] 联系人信任管理 (TOFU: 联系人在首次通信时自动添加)",
    "HELP.TRUST.EPILOG": "提示: 联系人通过收发消息自动发现 (Trust On First Use)。使用 'trust list' 查看已知联系人。",
    "HELP.TRUST.LIST": "列出所有联系人信任状态",
    "HELP.TRUST.SHOW": "显示联系人详细信任信息",
    "HELP.TRUST.VERIFY": "手动验证联系人（指纹比对）",
    "HELP.TRUST.ANCHOR": "通过外部锚定验证联系人",
    "HELP.TRUST.ACCEPT": "接受联系人密钥变更",
    "HELP.TRUST.REVOKE": "撤销联系人信任",
    "HELP.TRUST.BLOCK": "屏蔽联系人",
    "HELP.TRUST.UNBLOCK": "取消屏蔽联系人",
    "HELP.TRUST.OPT.ALL_LEVELS": "显示所有信任级别（包括 UNKNOWN）",
    "HELP.TRUST.OPT.BLOCKED": "包含已屏蔽联系人",
    "HELP.TRUST.ARG.PUBKEY": "联系人公钥 (hex) 或指纹前缀",
    "HELP.TRUST.OPT.FINGERPRINT": "期望的指纹（用于自动比对）",
    "HELP.TRUST.OPT.ANCHOR_TYPE": "锚定类型: dns, https, github",
    "HELP.TRUST.OPT.ANCHOR_ID": "锚定标识: 域名、URL 或 GitHub 用户名",
    "HELP.TRUST.OPT.REASON": "屏蔽原因",
    # Chat
    "HELP.CHAT.DESC": "[Relay模式] Relay 模式聊天命令 (send/recv/publish-bundle)",
    "HELP.CHAT.SEND": "发送加密消息",
    "HELP.CHAT.OPT.TO": "接收者公钥 (hex) 或指纹前缀",
    "HELP.CHAT.OPT.MESSAGE": "消息内容",
    "HELP.CHAT.OPT.ROOM_OPTIONAL": "房间 ID (可选)",
    "HELP.CHAT.RECV": "接收消息",
    "HELP.CHAT.OPT.ROOM": "房间 ID",
    "HELP.CHAT.OPT.LIMIT": "消息数量限制",
    "HELP.CHAT.OPT.SINCE": "起始序号",
    "HELP.CHAT.PUBLISH_BUNDLE": "发布密钥包",
}


def t(key: str, **kwargs) -> str:
    _lang = os.environ.get("DRLMS_LANG", "zh").lower()
    # Use Chinese as primary; switch table reserved for future
    mapping = zh_texts
    val = mapping.get(key, key)
    try:
        return val.format(**kwargs)
    except Exception:
        return val
