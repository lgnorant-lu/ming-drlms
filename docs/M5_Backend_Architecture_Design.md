# M5 后端架构设计文档

**版本**: 1.0  
**日期**: 2025-01-10  
**状态**: 设计阶段（Research & Planning）

---

## 执行摘要

本文档定义了 **ming-drlms M5 "瞬时相遇"战略转型** 所需的核心后端改造方案。设计灵感源自《光·遇》(Sky) 的社交哲学，将系统从传统的"永久聊天室"模式，演进为强调 **随机相遇、刻意连接、阅后即焚** 的独特社交平台。

**核心设计目标:**
1. **房间分片** ("平行宇宙"): 同一房间名下支持多个有容量限制的实例
2. **阅后即焚**: 房间默认临时存储，最后用户离开后自动销毁
3. **连接类型**: 匿名 → 点火(临时) → 好友(持久) 的三级连接体系
4. **无私聊**: 所有交互必须发生在房间公共空间内

---

### 工程基线与工具链

- 自 M-Infra 里程碑起，`ming-drlms` 的官方构建与测试统一采用 **CMake**。所有 M5 开发工作必须遵循以下流程：
  1. `cmake -S . -B build` 生成工程配置（必要时传入 `-D` 选项覆盖默认参数）。
  2. `cmake --build build --target <name>` 构建所需目标（例如 `log_collector_server`）。
  3. `ctest --test-dir build` 运行单元测试与集成测试。
- 任何遗留的 `make`、`ninja` 或手写编译脚本仅作为兼容层；在 M5 中不再维护或推荐。
- 配置变更（例如启用特性开关、调整默认容量）应通过 CMake 预设与外部配置文件协同完成，确保 CLI、GUI 与服务器在同一套参数下运行。

## 目录

1. [现有架构回顾](#1-现有架构回顾)
2. [M5 核心特性设计](#2-m5-核心特性设计)
   - 2.1 [房间分片机制](#21-房间分片机制-平行宇宙)
   - 2.2 [阅后即焚存储策略](#22-阅后即焚存储策略)
   - 2.3 [三级连接协议](#23-三级连接协议)
   - 2.4 [协议修改评估](#24-现有协议修改评估)
   - 2.5 [配置与运维控制](#25-配置与运维控制)
3. [SQLite Schema 变更](#3-sqlite-schema-变更)
4. [C 服务器数据结构](#4-c-服务器数据结构)
5. [网络协议规范](#5-网络协议规范)
6. [实现路线图](#6-实现路线图)

---

## 1. 现有架构回顾

### 1.1 核心组件

**C 服务器** (`log_collector_server.c`):
- 多线程 TCP 服务器，支持并发连接
- 房间管理系统 (`rooms.c/rooms.h`)
- SQLite 持久化存储 (`sqlite_storage.c`)
- Argon2id 用户认证

**房间模型**:
```c
struct Room {
    platform_mutex_t mu;
    Subscriber *subs;           // 订阅者列表
    size_t subs_len;
    size_t subs_cap;
    unsigned long long last_event_id;
    char owner[64];
    platform_socket_t owner_fd;
    int policy;                 // 0=retain, 1=delegate, 2=teardown
    time_t created_at;
};
```

### 1.2 现有协议概览

| 协议命令 | 格式 | 响应 | 功能 |
|---------|------|------|------|
| `LOGIN` | `LOGIN\|user\|password` | `OK\|LOGIN` | 用户认证 |
| `SUB` | `SUB\|room[\|since_id]` | 历史事件 + `OK\|SUB\|` | 订阅房间 |
| `UNSUB` | `UNSUB\|room` | `OK\|UNSUB\|` | 取消订阅 |
| `PUBT` | `PUBT\|room\|len\|sha` | `READY` → 发送内容 → `OK\|PUBT\|event_id` | 发送文本消息 |
| `ROOMINFO` | `ROOMINFO\|room` | `OK\|ROOMINFO\|room\|owner\|policy\|subs\|last_eid` | 查询房间信息 |
| `LISTROOMS` | `LISTROOMS[\|offset\|limit]` | `BEGIN\|ROOMS\|total` + 房间列表 + `END\|ROOMS` | 分页房间列表 |
| `SETPOLICY` | `SETPOLICY\|room\|slug` | `OK\|SETPOLICY` | 设置房间策略 |
| `TRANSFER` | `TRANSFER\|room\|new_owner` | `OK\|TRANSFER\|new_owner` | 转移所有者 |

**事件推送**:
- `EVT|TEXT|room|ts|user|event_id|len|sha` + payload bytes
- `EVT|USER_JOIN|room|ts|user`
- `EVT|USER_LEAVE|room|ts|user`

### 1.3 SQLite Schema (现有)

**rooms** 表:
```sql
CREATE TABLE rooms (
    name TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    policy INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_event_id INTEGER DEFAULT 0
);
```

**events** 表:
```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    user_name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    content_hash TEXT,
    content_length INTEGER,
    content BLOB,
    file_path TEXT,
    file_size INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**user_sessions** 表:
```sql
CREATE TABLE user_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_name TEXT NOT NULL,
    room_name TEXT NOT NULL,
    last_event_id INTEGER DEFAULT 0,
    joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_name, room_name)
);
```

---

## 2. M5 核心特性设计

### 2.1 房间分片机制 ("平行宇宙")

#### 2.1.1 核心概念

同一个房间名（如 `"general"`）下可以存在 **多个并行实例**，每个实例：
- 有独立的 `instance_id`（128-bit UUID v4）
- 有容量上限（默认 50 人，可通过房间配置调整）
- 独立的订阅者列表和事件流
- 用户 JOIN 时被随机分配到某个实例

**设计目标:**
- ✅ 创造"偶遇"体验（用户无法选择进入哪个实例）
- ✅ 防止单个房间人数过多导致信息过载
- ✅ 支持房间自动扩缩容

#### 2.1.2 Instance ID 设计

```c
typedef struct {
    unsigned char bytes[16];  // UUID v4 (128-bit)
} InstanceUUID;

// 字符串表示（用于协议传输）: 32-char hex (无破折号)
// 例如: "a1b2c3d4e5f6789012345678abcdef01"
```

**生成策略:**
- 使用 UUID v4 (随机生成)
- C 服务器端使用 `BCryptGenRandom` (Windows) 或 `/dev/urandom` (Unix)
- 确保全局唯一性（碰撞概率 ~2^-64）

#### 2.1.3 实例分配算法

**用户 SUB 请求时的分配流程:**

```
1. 解析房间名 (不含 instance_id)
2. 查询该房间名下的所有活跃实例
3. 过滤出未满员的实例（subs_len < max_capacity）
4. 如果没有可用实例 → 创建新实例
5. 从可用实例中随机选择一个
6. 将用户加入该实例的订阅者列表
7. 返回 OK|SUB|instance_id
```

**随机分配策略** (Phase 1):
```c
// 伪代码
candidate_instances = filter(instances, λ inst: inst.subs_len < inst.max_capacity)
if len(candidate_instances) == 0:
    new_instance = create_new_instance(room_name)
    candidate_instances = [new_instance]

selected = candidate_instances[random() % len(candidate_instances)]
```

**未来优化方向** (Phase 2+):
- **负载均衡**: 优先分配到人数较少的实例
- **地理亲和**: 根据用户 IP 分配到就近实例（延迟优化）
- **社交亲和**: 如果用户有好友在某实例，提高分配到该实例的权重（可配置）

#### 2.1.4 实例生命周期管理

**创建条件:**
- 用户尝试 SUB 某房间名，但所有实例都已满员
- 首次 SUB 某房间名时（不存在任何实例）

**销毁条件:**
1. **阅后即焚模式** (`storage_policy = ephemeral`):
   - 最后一个订阅者 UNSUB 后，立即销毁实例（包括内存中的所有事件）
   
2. **持久模式** (`storage_policy = persistent`):
   - 最后一个订阅者 UNSUB 后，实例进入"休眠"状态
   - 休眠超过 TTL（默认 24 小时）后，标记为可回收
   - 垃圾回收线程定期清理休眠实例

**实例状态机:**
```
[NULL] --SUB--> [ACTIVE] --last_user_leaves--> [IDLE] 
                                                  |
                   ephemeral: destroy immediately |
                   persistent: wait for TTL       |
                                                  v
                                              [DESTROYED]
```

#### 2.1.5 容量配置

所有容量与生命周期参数必须通过配置层解析，禁止在代码中写入硬编码默认值。解析顺序为：

1. `drlms.yaml`（详见 [2.5 配置与运维控制](#25-配置与运维控制)）中的 `rooms` 节点；
2. CMake 预设或 `-DROOMS_DEFAULT_INSTANCE_CAPACITY=` 等构建选项；
3. 运行时环境变量（例如 `DRLMS_DEFAULT_INSTANCE_CAPACITY`）。

示例：

```yaml
rooms:
  default_instance_capacity: 50
  max_instances_per_room: 20
  idle_ttl_seconds: 86400
```

**单个房间配置** 持久化在 SQLite 中，系统首次写入时会使用上述默认值：

```sql
ALTER TABLE rooms ADD COLUMN max_capacity_per_instance INTEGER DEFAULT 50;
ALTER TABLE rooms ADD COLUMN max_instances INTEGER DEFAULT 20;
```

---

### 2.2 阅后即焚存储策略

#### 2.2.1 Storage Policy 定义

引入新的房间属性 `storage_policy`（与现有 `policy` 字段独立）:

| 值 | 名称 | 描述 |
|----|------|------|
| `0` | `persistent` | 持久化存储（默认，兼容现有行为） |
| `1` | `ephemeral` | 临时存储（阅后即焚） |

**设计原则:**
- `storage_policy` 在房间创建时指定，后续不可更改（防止数据泄露）
- 与现有 `policy` (owner 离开行为) 正交，两者独立配置

#### 2.2.2 Ephemeral 模式实现

**内存事件缓冲区:**
```c
typedef struct EphemeralEvent {
    uint64_t event_id;
    time_t timestamp;
    char user[64];
    enum { EVT_TEXT, EVT_FILE } type;
    union {
        struct {
            unsigned char *data;
            size_t len;
            char sha_hex[65];
        } text;
        struct {
            char filename[256];
            size_t size;
            char sha_hex[65];
            char *temp_path;  // 临时文件路径
        } file;
    } payload;
    struct EphemeralEvent *next;
} EphemeralEvent;

typedef struct RoomInstance {
    // ... (existing fields)
    
    int storage_policy;              // 0=persistent, 1=ephemeral
    EphemeralEvent *event_head;      // 事件链表头
    EphemeralEvent *event_tail;      // 事件链表尾
    size_t event_count;              // 当前事件数
    size_t max_event_history;        // 最大保留事件数 (默认 1000)
} RoomInstance;
```

**存储策略路由:**
```c
int rooms_store_text(Room *room, const char *room_name, ...) {
    if (room->storage_policy == STORAGE_EPHEMERAL) {
        // 仅存入内存链表，不写 SQLite
        return ephemeral_store_text(room, ...);
    } else {
        // 现有逻辑: 写入 SQLite events 表
        return sqlite_store_text(&g_sqlite_storage, ...);
    }
}
```

**清理策略:**
1. **容量限制**: 当 `event_count > max_event_history` 时，从链表头删除最旧事件
2. **实例销毁**: 最后用户离开时，释放整个事件链表和临时文件

#### 2.2.3 混合模式考量

**用户体验平衡:**
- Ephemeral 房间不提供 `HISTORY` 命令（或仅返回有限历史，如最近 100 条）
- 订阅时推送的事件数量有上限（防止内存溢出）

**日志与审计:**
- Ephemeral 房间的事件 **不会** 写入 `events` 表
- 但 **必须** 记录到审计日志 `ops_audit.log`（合规要求）
- 审计字段需标记 `storage_policy=ephemeral` 以区分

---

### 2.3 三级连接协议

#### 2.3.1 连接状态模型

用户在房间内对其他用户的可见关系分为三级：

| 状态 | 名称 | 描述 | 其他成员所见 | 持久性 |
|------|------|------|-------------|--------|
| `0` | `stranger` | 陌生人（默认） | 沉默剪影 + 与内容长度匹配的 `…` 占位消息；不暴露任何标识符 | 无，离开房间即遗忘 |
| `1` | `ignited` | 点火连接（临时） | 对方的个性化外观、气泡与表情可见，但仍隐藏姓名 | 仅当前会话，任一方离开房间即失效 |
| `2` | `friend` | 星盘好友（持久） | 自动生成的诗意双人代号（如“自信的冥龙”）+ 个性化展示；可附加私人备注 | 永久，写入 SQLite；支持备注同步 |

#### 2.3.2 呈现与身份管理

- **Stranger:** 服务器不会返回任何 ID 或用户名，消息体被替换为等长的省略号（用于维持气泡尺寸）。UI 层使用统一的“黑色剪影”素材；日志与审计仍记录真实用户 ID，但不会透出给普通客户端。
- **Ignited:** 点火只解锁情绪表达与个性化外观，服务器仍然屏蔽姓名字段；事件载荷中 `display_token` 被标记为 `IGNITED_VISUAL`，客户端据此渲染。
- **Friend:** 建立好友关系时，后端调用 *Poetic Codename Generator*（参见 2.3.4）生成唯一的 `generated_name`，并在后续事件中返回该名称。用户可单向设置 `note_override`（备注），服务器在事件里同时返回 `generated_name` 与 `note_override`，客户端自行决定展示优先级。
- **协议兼容性:** 所有 `EVT`、`IGNITE_*`、`BEFRIEND_*` 响应增加 `display_token` 字段，用于携带占位剪影、装扮 ID、生成名字等呈现信息。旧版客户端在协商到 <5 的协议版本时仍可退化为旧逻辑。
- **账号解耦:** 登录使用的 `username` 仅用于认证与合规审计；社交呈现统一通过 `presence_token` / `display_token` / `generated_name` 完成，使玩家在不同房间和实例中保持沉浸式匿名体验。

#### 2.3.3 IGNITE 协议 (临时连接)

**客户端请求:**
```
IGNITE|room_name|instance_id|target_presence_token
```

其中 `target_presence_token` 是服务器为每位陌生人广播的不可逆随机句柄，仅用于指向“房间中的那位剪影”。该令牌在实例生命周期内有效，无法从中推导身份信息。

**服务器处理流程:**
1. 验证请求者与目标令牌均属于当前房间实例。
2. 若通过验证，向目标用户推送：
   ```
   EVT|IGNITE_REQUEST|room|instance_id|ts|requester_display_token|request_id
   ```
   其中 `requester_display_token` 包含对方此刻的剪影/动作信息。
3. 目标用户响应：
   ```
   IGNITE_ACCEPT|room_name|instance_id|request_id
   ```
   或 `IGNITE_REJECT|...`。
4. 成功后双方接收：
   ```
   EVT|IGNITE_ESTABLISHED|room|instance_id|ts|peer_display_token
   ```
   事件中仍不包含姓名，只表明双方可以互见装扮与情绪表达。

**存储:**
- `IgniteConnection { user_a, user_b, room_name, instance_id, established_at }` 仅存在于内存中。
- 任一方 `UNSUB` 或 `IGNITE_CANCEL` 即销毁该连接，并通知客户端回退到 `stranger` 状态。

#### 2.3.4 BEFRIEND 协议 (持久连接)

**前提条件:** 双方必须仍处于激活的 `ignite` 会话中。

**客户端请求:**
```
BEFRIEND|room_name|instance_id|target_presence_token
```

**服务器处理流程:**
1. 校验当前存在 `IgniteConnection(user_a, user_b)`，且令牌匹配。
2. 若通过验证，向目标推送：
   ```
   EVT|BEFRIEND_REQUEST|room|instance_id|ts|requester_display_token
   ```
3. 目标用户响应 `BEFRIEND_ACCEPT|request_id` 或 `BEFRIEND_REJECT|request_id`。
4. 当双方接受后：
   - 调用 Poetic Codename Generator 生成 `generated_name`；
   - 将 `friendships` 表写入：
     ```sql
     INSERT INTO friendships (user_a, user_b, generated_name)
     VALUES (?, ?, ?);
     ```
   - 初始化可选备注表（见 3.1.3）。
5. 服务器向双方广播：
   ```
   EVT|BEFRIEND_ESTABLISHED|room|instance_id|ts|generated_name|note_override
   ```
   其中 `note_override` 初始为空，客户端可后续通过 `SET_NOTE` 协议更新。
6. 后续在任何房间相遇，服务器都会直接提供 `generated_name` 与对方装扮；不再需要 `IGNITE` 前置步骤。

#### 2.3.5 消息可见性控制

**需求:** 未来可能支持 "只有 ignited/friend 能看到某些消息"

**协议扩展 (预留设计):**
```
PUBT|room|len|sha|visibility
```
其中 `visibility`:
- `public` (默认): 所有人可见
- `connected`: 仅与发送者有 ignite/friend 连接的用户可见
- `friends`: 仅好友可见

**服务器 fanout 逻辑:**
```c
void rooms_fanout_text_with_visibility(..., const char *visibility) {
    for (size_t i = 0; i < room->subs_len; i++) {
        Subscriber *sub = &room->subs[i];
        
        const char *display_token = compose_display_token(sender, sub, visibility);
        if (strcmp(visibility, "public") == 0) {
            send_event(sub->fd, display_token, ...);
        } else if (strcmp(visibility, "connected") == 0) {
            if (has_connection(sender, sub->real_user, room, instance_id)) {
                send_event(sub->fd, display_token, ...);
            }
        } else if (strcmp(visibility, "friends") == 0) {
            if (are_friends(sender, sub->real_user)) {
                send_event(sub->fd, display_token, ...);
            }
        }
    }
}
```

---

### 2.4 现有协议修改评估

#### 2.4.1 SUB 命令修改

**现有格式:**
```
SUB|room_name[|since_id]
```

**M5 新格式 (向后兼容):**
```
SUB|room_name[|since_id][|preferred_instance_id]
```

**响应修改:**
```
OK|SUB|instance_id|presence_token|display_token
```

**变更说明:**
- 如果客户端未提供 `preferred_instance_id`，服务器按分配算法自动选择
- 如果提供了 `preferred_instance_id` 但该实例已满或不存在，服务器忽略该参数并分配新实例
- 响应携带的 `presence_token` 用于后续 `IGNITE`/`BEFRIEND` 指令；`display_token` 用于初始陌生人呈现

#### 2.4.2 UNSUB 命令修改

**现有格式:**
```
UNSUB|room_name
```

**M5 新格式:**
```
UNSUB|room_name|instance_id
```

**向后兼容:**
- 如果客户端未提供 `instance_id`，服务器自动 UNSUB 该用户在该房间名下的所有实例订阅
- 建议客户端升级后始终提供 `instance_id`

#### 2.4.3 ROOMINFO 命令修改

**现有格式:**
```
ROOMINFO|room_name
```

**问题:** 房间分片后，单个房间名下有多个实例，如何响应？

**方案 A: 聚合信息** (推荐)
```
OK|ROOMINFO|room_name|total_instances|total_subs|storage_policy|max_capacity_per_instance

// 示例:
OK|ROOMINFO|general|3|127|1|50
// 表示: general 房间有 3 个实例，共 127 人，临时存储，每实例容量 50
```

**方案 B: 单实例查询** (精细化)
```
ROOMINFO|room_name|instance_id
→ OK|ROOMINFO|room_name|instance_id|owner|subs|last_eid|created_at
```

**建议:** 先实现方案 A（UI 友好），方案 B 作为调试接口

#### 2.4.4 LISTROOMS 命令修改

**现有响应格式:**
```
BEGIN|ROOMS|total
ROOM|name|owner|policy|subs|last_eid|created_at|updated_at
...
END|ROOMS
OK|ROOMS|returned|has_more
```

**M5 修改:**
- `ROOM` 行新增字段:
  ```
  ROOM|name|total_instances|total_subs|storage_policy|max_capacity|last_updated
  ```
- **去除 `owner` 字段** (因为分片后，owner 概念模糊化；后续可引入 "房间创建者" 概念)
- `last_updated`: 所有实例中的最新 `updated_at` 时间戳

**示例:**
```
BEGIN|ROOMS|5
ROOM|general|3|127|1|50|2025-01-10T14:32:00Z
ROOM|dev|1|8|0|50|2025-01-09T18:10:00Z
...
END|ROOMS
OK|ROOMS|5|0
```

#### 2.4.5 EVT 事件修改

**现有格式:**
```
EVT|TEXT|room|ts|user|event_id|len|sha
EVT|USER_JOIN|room|ts|user
EVT|USER_LEAVE|room|ts|user
```

**M5 修改:**
- 所有事件都携带 `instance_id` 与 `display_token`：
  ```
  EVT|TEXT|room|instance_id|ts|display_token|event_id|len|sha
  EVT|USER_JOIN|room|instance_id|ts|display_token
  EVT|USER_LEAVE|room|instance_id|ts|display_token
  ```
- `display_token` 根据状态不同代表剪影、装扮、生成名等信息；真实用户名仅在审计渠道可见。
- `render_hint`（可选字段）用于指示客户端如何处理省略号长度、灯光特效等。

**新增事件类型:**
```
EVT|IGNITE_REQUEST|room|instance_id|ts|requester_display_token
EVT|IGNITE_ESTABLISHED|room|instance_id|ts|peer_display_token
EVT|BEFRIEND_REQUEST|room|instance_id|ts|requester_display_token
EVT|BEFRIEND_ESTABLISHED|room|instance_id|ts|generated_name|note_override
EVT|NOTE_UPDATED|room|instance_id|ts|generated_name|note_override
```

---

### 2.5 配置与运维控制

| 维度 | 载体 | 示例键 | 调整主体 |
|------|------|--------|----------|
| 全局默认值 | `drlms.yaml` | `rooms.default_instance_capacity`、`encounter.poetic_word_bank` | SRE/运营 |
| 构建期覆盖 | `cmake -D` | `-DROOMS_IDLE_TTL_SECONDS=43200` | DevOps Pipeline |
| 运行时覆盖 | 环境变量 | `DRLMS_STORAGE_POLICY_DEFAULT=ephemeral` | 部署环境 |
| 实时调优 | Admin CLI/API | `admin:set-capacity general 64` | 值班管理员 |

- **统一加载链路:** 服务器启动时读取 `drlms.yaml` → 应用 CMake 生成的 `config.h` 默认值 → 应用环境变量 → 在运行期允许持有“管理权限”的帐号通过 Admin API 修改，并写回配置中心。
- **权限分层:**
  - SRE 负责全局默认值及灾备参数；
  - 运营可以通过 GUI 的“世界设置”页面在权限范围内调整房间容量、`storage_policy` 模板等；
  - 普通房主仅能在所管理房间内调低容量或切换装饰主题，无法突破 SRE 上限；
  - CLI 与 GUI 共用同一配置源，CLI 通过 `config show`、`config set <key> <value>` 等命令实现基本操作。
- **词库与命名:** `encounter.poetic_word_bank` 指向 JSON/YAML 词库文件，可按区域、节日热更新。词库更新后 CLI/GUI 需触发 `RELOAD_CONFIG` 指令以重新加载。
- **审计:** 所有配置变更写入 `ops_audit.log`，包含操作者、旧值、新值以及来源（文件/CLI/API）。

---

## 3. SQLite Schema 变更

### 3.1 新增表

#### 3.1.1 room_instances 表

```sql
CREATE TABLE room_instances (
    instance_id TEXT PRIMARY KEY,              -- UUID hex (32 chars)
    room_name TEXT NOT NULL,
    storage_policy INTEGER DEFAULT 0,          -- 0=persistent, 1=ephemeral
    max_capacity INTEGER DEFAULT 50,
    state INTEGER DEFAULT 0,                   -- 0=active, 1=idle, 2=destroyed
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_active_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    destroyed_at DATETIME,
    last_event_id INTEGER DEFAULT 0,
    
    FOREIGN KEY (room_name) REFERENCES rooms(name) ON DELETE CASCADE
);

CREATE INDEX idx_room_instances_name ON room_instances(room_name);
CREATE INDEX idx_room_instances_state ON room_instances(state);
```

**字段说明:**
- `instance_id`: 128-bit UUID v4 转 hex 字符串
- `storage_policy`: 继承自 `rooms.storage_policy_template`
- `state`: 0=活跃（有订阅者或最近有活动），1=空闲（等待回收），2=已销毁（仅日志）
- `last_active_at`: 每次有用户 SUB/UNSUB 或事件发生时更新

#### 3.1.2 friendships 表

```sql
CREATE TABLE friendships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_a TEXT NOT NULL,
    user_b TEXT NOT NULL,
    generated_name TEXT NOT NULL,
    word_bank_version TEXT,
    established_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(user_a, user_b),
    CHECK(user_a < user_b)
);

CREATE INDEX idx_friendships_user_a ON friendships(user_a);
CREATE INDEX idx_friendships_user_b ON friendships(user_b);
```

- `generated_name`: 诗意化组合词（Poetic Codename），双方共享。
- `word_bank_version`: 记录当次生成所使用的词库版本，便于复现与追溯。

**查询示例:**
```sql
SELECT generated_name
FROM friendships
WHERE (user_a = ? AND user_b = ?)
   OR (user_a = ? AND user_b = ?);
```

#### 3.1.3 friend_notes 表

```sql
CREATE TABLE friend_notes (
    friendship_id INTEGER NOT NULL,
    owner TEXT NOT NULL,
    note TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (friendship_id, owner),
    FOREIGN KEY (friendship_id)
        REFERENCES friendships(id)
            ON DELETE CASCADE
);
```

- 备注为单向关系，`owner` 必须是 `friendships.user_a` 或 `user_b`。
- `SET_NOTE` 协议更新此表，并向对端发送 `EVT|NOTE_UPDATED` 通知以刷新展示。

### 3.2 修改现有表

#### 3.2.1 rooms 表

```sql
-- 新增字段（通过 ALTER TABLE）
ALTER TABLE rooms ADD COLUMN storage_policy_template INTEGER DEFAULT 0;  
-- 0=persistent, 1=ephemeral; 新创建的实例继承此值

ALTER TABLE rooms ADD COLUMN max_capacity_per_instance INTEGER DEFAULT 50;
ALTER TABLE rooms ADD COLUMN max_instances INTEGER DEFAULT 20;
ALTER TABLE rooms ADD COLUMN total_instances INTEGER DEFAULT 0;  -- 当前活跃实例数
ALTER TABLE rooms ADD COLUMN total_subs INTEGER DEFAULT 0;       -- 所有实例订阅者总数
```

**迁移脚本 (Python):**
```python
def migrate_rooms_to_m5(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 添加新字段
    cursor.execute("""
        ALTER TABLE rooms ADD COLUMN IF NOT EXISTS storage_policy_template INTEGER DEFAULT 0;
    """)
    cursor.execute("""
        ALTER TABLE rooms ADD COLUMN IF NOT EXISTS max_capacity_per_instance INTEGER DEFAULT 50;
    """)
    cursor.execute("""
        ALTER TABLE rooms ADD COLUMN IF NOT EXISTS max_instances INTEGER DEFAULT 20;
    """)
    cursor.execute("""
        ALTER TABLE rooms ADD COLUMN IF NOT EXISTS total_instances INTEGER DEFAULT 0;
    """)
    cursor.execute("""
        ALTER TABLE rooms ADD COLUMN IF NOT EXISTS total_subs INTEGER DEFAULT 0;
    """)
    
    conn.commit()
    conn.close()
```

#### 3.2.2 events 表

**修改:** 新增 `instance_id` 字段

```sql
ALTER TABLE events ADD COLUMN instance_id TEXT;
CREATE INDEX idx_events_instance_id ON events(instance_id);
```

**注意:** Ephemeral 实例的事件 **不会** 写入此表，因此 `instance_id` 字段仅对 persistent 实例有效。

#### 3.2.3 user_sessions 表

**修改:** 新增 `instance_id` 字段，UNIQUE 约束改为 `(user_name, room_name, instance_id)`

```sql
-- 1. 创建新表
CREATE TABLE user_sessions_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_name TEXT NOT NULL,
    room_name TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    last_event_id INTEGER DEFAULT 0,
    joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(user_name, room_name, instance_id)
);

-- 2. 迁移数据 (为现有 session 生成默认 instance_id)
INSERT INTO user_sessions_new (user_name, room_name, instance_id, last_event_id, joined_at)
SELECT user_name, room_name, 'legacy-' || room_name, last_event_id, joined_at
FROM user_sessions;

-- 3. 删除旧表，重命名新表
DROP TABLE user_sessions;
ALTER TABLE user_sessions_new RENAME TO user_sessions;

-- 4. 重建索引
CREATE INDEX idx_user_sessions_user_room_instance 
ON user_sessions(user_name, room_name, instance_id);
```

#### 3.2.4 friendships 表扩展

```sql
ALTER TABLE friendships ADD COLUMN generated_name TEXT;
ALTER TABLE friendships ADD COLUMN word_bank_version TEXT;

-- 重新填充历史数据：
UPDATE friendships
SET generated_name = COALESCE(generated_name, 'Legacy Constellation'),
    word_bank_version = COALESCE(word_bank_version, 'legacy');
```

旧版本不会保存笔记，因此迁移脚本需创建 `friend_notes` 表并保持为空：

```sql
CREATE TABLE IF NOT EXISTS friend_notes (
    friendship_id INTEGER NOT NULL,
    owner TEXT NOT NULL,
    note TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (friendship_id, owner),
    FOREIGN KEY (friendship_id) REFERENCES friendships(id)
        ON DELETE CASCADE
);
```

---

## 4. C 服务器数据结构

### 4.1 核心结构定义

#### 4.1.1 RoomInstance

```c
typedef struct {
    unsigned char bytes[16];  // UUID v4
} InstanceUUID;

// 将 UUID 转为 32 字符 hex 字符串
void uuid_to_hex(const InstanceUUID *uuid, char *out_hex33);
// 从 hex 字符串解析 UUID
int uuid_from_hex(const char *hex32, InstanceUUID *out_uuid);

typedef struct EphemeralEvent {
    uint64_t event_id;
    time_t timestamp;
    char user[64];
    enum { EVT_TEXT, EVT_FILE } type;
    union {
        struct {
            unsigned char *data;
            size_t len;
            char sha_hex[65];
        } text;
        struct {
            char filename[256];
            size_t size;
            char sha_hex[65];
            char *temp_path;
        } file;
    } payload;
    struct EphemeralEvent *next;
} EphemeralEvent;

typedef struct IgniteConnection {
    char user_a[64];
    char user_b[64];
    time_t established_at;
    struct IgniteConnection *next;
} IgniteConnection;

typedef struct Subscriber {
    platform_socket_t fd;
    char real_user[64];             // 真实用户名（仅服务端使用）
    char presence_token[40];        // 面向客户端的不可逆引用
    char display_token[64];         // 当前呈现所需信息（剪影/装扮/生成名）
    char current_cosmetic_id[32];   // IGNITE 后展示的装扮/气泡 ID
    char generated_name[64];        // 好友状态下的诗意称谓
    int visibility_state;           // 0=stranger,1=ignited,2=friend
} Subscriber;

typedef struct RoomInstance {
    platform_mutex_t mu;
    
    InstanceUUID instance_id;
    char room_name[65];
    
    Subscriber *subs;
    size_t subs_len;
    size_t subs_cap;
    
    int storage_policy;          // 0=persistent, 1=ephemeral
    int state;                   // 0=active, 1=idle
    size_t max_capacity;
    
    uint64_t last_event_id;
    time_t created_at;
    time_t last_active_at;
    
    // Ephemeral 模式专用
    EphemeralEvent *event_head;
    EphemeralEvent *event_tail;
    size_t event_count;
    size_t max_event_history;    // 默认 1000
    
    // Ignite 连接（临时，不持久化）
    IgniteConnection *ignite_head;
    
    struct RoomInstance *next;   // 链表指针（同一 room_name 下的其他实例）
} RoomInstance;
```

#### 4.1.2 RoomMetadata (房间元信息)

```c
typedef struct RoomMetadata {
    char name[65];
    int storage_policy_template;     // 新实例继承此值
    size_t max_capacity_per_instance;
    size_t max_instances;
    size_t total_instances;          // 当前活跃实例数
    size_t total_subs;               // 所有实例订阅者总数
    time_t created_at;
    
    RoomInstance *instance_list;     // 该房间的所有实例链表
    struct RoomMetadata *next;
} RoomMetadata;
```

#### 4.1.3 全局管理结构

```c
static RoomMetadata *g_rooms = NULL;  // 房间元信息链表
static platform_mutex_t g_rooms_mu;

// 查找或创建房间元信息
RoomMetadata *rooms_get_or_create_metadata(const char *room_name);

// 为房间分配一个实例（自动选择或创建）
RoomInstance *rooms_assign_instance(const char *room_name, 
                                     const char *user,
                                     const char *preferred_instance_id);

// 查找特定实例
RoomInstance *rooms_find_instance(const char *room_name, 
                                   const InstanceUUID *instance_id);

// 销毁空闲实例
void rooms_destroy_instance(RoomInstance *instance);
```

### 4.2 关键算法实现

#### 4.2.1 Presence/Display Token 生成

```c
void generate_presence_token(const InstanceUUID *instance_id,
                             const char *real_user,
                             char out_token[40]) {
    // presence_token = base32( HMAC_SHA256(instance_id || real_user || nonce) )[0:30]
    unsigned char mac[32];
    unsigned char nonce[16];
    random_bytes(nonce, sizeof nonce);
    hmac_sha256(instance_id->bytes, sizeof instance_id->bytes,
                (const unsigned char *)real_user, strlen(real_user),
                nonce, sizeof nonce, mac);
    base32_encode(mac, sizeof mac, out_token, 40);
    out_token[30] = '\0';
}

void compose_display_token(const Subscriber *sender,
                           const Subscriber *receiver,
                           enum display_visibility visibility,
                           char out_token[64]) {
    switch (visibility) {
    case DISPLAY_STRANGER:
        snprintf(out_token, 64, "SILHOUETTE:%s", sender->presence_token);
        break;
    case DISPLAY_IGNITED:
        snprintf(out_token, 64, "IGNITED:%s:%s", sender->presence_token,
                 sender->current_cosmetic_id);
        break;
    case DISPLAY_FRIEND:
        snprintf(out_token, 64, "FRIEND:%s", sender->generated_name);
        break;
    }
}
```

- `presence_token` 为客户端引用陌生人的唯一手段，长度 30、不可逆。
- `display_token` 由服务端根据状态组合，客户端按前缀决定渲染策略。
- `display_visibility` 枚举定义如下：

```c
typedef enum {
    DISPLAY_STRANGER = 0,
    DISPLAY_IGNITED = 1,
    DISPLAY_FRIEND = 2
} display_visibility;
```

#### 4.2.2 好友关系查询

```c
int are_friends(const char *user_a, const char *user_b) {
    // 查询 SQLite friendships 表
    const char *sql = 
        "SELECT COUNT(*) FROM friendships "
        "WHERE (user_a = ? AND user_b = ?) "
        "   OR (user_a = ? AND user_b = ?)";
    
    sqlite3_stmt *stmt;
    sqlite3_prepare_v2(g_sqlite_storage.db, sql, -1, &stmt, NULL);
    
    // 确保 user_a < user_b 字典序
    const char *u1 = (strcmp(user_a, user_b) < 0) ? user_a : user_b;
    const char *u2 = (strcmp(user_a, user_b) < 0) ? user_b : user_a;
    
    sqlite3_bind_text(stmt, 1, u1, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, u2, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, u2, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, u1, -1, SQLITE_TRANSIENT);
    
    int result = 0;
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        result = sqlite3_column_int(stmt, 0) > 0;
    }
    sqlite3_finalize(stmt);
    return result;
}
```

---

## 5. 网络协议规范

### 5.1 新增协议命令

#### 5.1.1 IGNITE

**客户端请求:**
```
IGNITE|room_name|instance_id|target_presence_token
```

**服务器响应:**
```
OK|IGNITE|request_id
或
ERR|IGNITE|target_not_found
ERR|IGNITE|not_in_same_room
ERR|IGNITE|already_connected
```

**目标用户收到推送:**
```
EVT|IGNITE_REQUEST|room_name|instance_id|timestamp|requester_display_token|request_id
```

#### 5.1.2 IGNITE_ACCEPT / IGNITE_REJECT

**客户端响应:**
```
IGNITE_ACCEPT|room_name|instance_id|request_id
或
IGNITE_REJECT|room_name|instance_id|request_id
```

**服务器响应:**
```
OK|IGNITE_ACCEPT
```

**双方收到推送 (如果 ACCEPT):**
```
EVT|IGNITE_ESTABLISHED|room_name|instance_id|timestamp|peer_display_token
```

#### 5.1.3 BEFRIEND

**客户端请求:**
```
BEFRIEND|room_name|instance_id|target_presence_token
```

**服务器响应:**
```
OK|BEFRIEND|request_id
或
ERR|BEFRIEND|no_ignite_connection
ERR|BEFRIEND|already_friends
```

**目标用户收到推送:**
```
EVT|BEFRIEND_REQUEST|room_name|instance_id|timestamp|requester_display_token|request_id
```

#### 5.1.4 BEFRIEND_ACCEPT / BEFRIEND_REJECT

**客户端响应:**
```
BEFRIEND_ACCEPT|request_id
或
BEFRIEND_REJECT|request_id
```

**服务器响应:**
```
OK|BEFRIEND_ACCEPT
```

**双方收到推送 (如果 ACCEPT):**
```
EVT|BEFRIEND_ESTABLISHED|room_name|instance_id|timestamp|generated_name|note_override
```

**服务器持久化:** 写入 SQLite `friendships` 表

#### 5.1.5 SET_NOTE

**客户端请求:**
```
SET_NOTE|generated_name|note
```

**服务器响应:**
```
OK|SET_NOTE|generated_name
或
ERR|SET_NOTE|not_friends
```

**好友收到推送:**
```
EVT|NOTE_UPDATED|room_name|instance_id|timestamp|generated_name|note_override
```

### 5.2 修改后的协议命令

详见 [2.4 现有协议修改评估](#24-现有协议修改评估)

### 5.3 CLI 功能对等性要求

- 所有新协议必须提供 CLI 命令封装，确保纯终端环境也能完成点火与好友流程。
- 计划命令：
  - `rooms attach --room <name>`：返回 `instance_id`、`presence_token`、`display_token`。
  - `ignite send <presence_token>`、`ignite accept <request_id>`、`ignite reject <request_id>`。
  - `friend request <presence_token>`、`friend accept <request_id>`、`friend list`、`friend note set <generated_name> <note>`。
  - `config show` / `config set <key> <value>`：与 [2.5](#25-配置与运维控制) 的配置源同步。
- CLI 输出使用与 GUI 相同的 `display_token` 编码，便于跨端调试与自动化测试。

---

## 6. 实现路线图

### Phase 1: 基础设施与配置基线 (2 周)

**目标:** 打牢房间分片、配置框架与审计能力

- [ ] 实现 `InstanceUUID` 生成与解析，完善线程安全封装
- [ ] 重构 C 服务器房间管理: `RoomMetadata` + `RoomInstance`
- [ ] 实现实例分配算法（随机策略 + 容量上限检查）
- [ ] 引入 `drlms.yaml` 配置加载链路与环境变量覆盖机制
- [ ] 修改 `SUB`/`UNSUB`/`EVT` 协议支持 `instance_id`
- [ ] 更新 SQLite schema：创建 `room_instances` 表，扩展 `rooms` 字段
- [ ] 实现实例生命周期管理（创建、销毁、TTL 回收线程）
- [ ] 审计日志新增配置变更、实例创建销毁记录

**测试验证:**
- 单元测试: UUID 生成/解析、配置解析、房间并发分配
- 集成测试: 多客户端同时 SUB 同一房间，验证实例分配且与 CLI 协议兼容
- 压力测试: 单个房间名下创建 20+ 实例，验证 TTL 回收

### Phase 2: 阅后即焚 (1 周)

**目标:** 交付临时存储与 CLI 管理能力

- [ ] 实现 `EphemeralEvent` 链表和内存路由
- [ ] 修改 `rooms_store_text/file` 支持 ephemeral 分支
- [ ] 实现容量限制与历史长度配置化
- [ ] 实现实例销毁时的事件清理（含 CLI `rooms gc` 命令）
- [ ] 更新 `ROOMINFO` / `LISTROOMS` 展示 `storage_policy`
- [ ] CLI 增加 `rooms policy set`、`rooms info` 等管理命令

**测试验证:**
- 功能测试: 创建 ephemeral 房间，验证事件仅在内存存在
- 内存测试: 验证链表不超过配置限制
- 清理测试: 最后用户离开后内存完全释放，CLI 可观察状态变化

### Phase 3: 呈现体系与 IGNITE (1.5 周)

**目标:** 构建陌生人呈现、点火交互与 CLI 对等能力

- [ ] 实现 `presence_token`/`display_token` 分配器与回收器
- [ ] 重构 `Subscriber` 结构并落实 `display_token` fanout
- [ ] 更新 `EVT`/`IGNITE_*` 载荷以携带 `display_token`、`render_hint`
- [ ] 实现 `IGNITE` 协议（请求、接受、拒绝）与请求 ID 流程
- [ ] 实现 `IgniteConnection` 内存管理与失效检测
- [ ] CLI/G​UI 同步 `rooms attach`、`ignite send/accept/reject` 命令与 UI

**测试验证:**
- 功能测试: 陌生人仅展示剪影，消息自动转省略号
- 连接测试: IGNITE 成功后双方获得装扮展示但仍隐藏姓名
- CLI/GUI 对等性测试: 跨端完成点火流程
- 清理测试: 离开房间后连接失效

### Phase 4: BEFRIEND 持久连接 (1 周)

**目标:** 实现诗意命名、好友持久化与备注体系

- [ ] 实现 Poetic Codename Generator（词库加载、去重、语言包支持）
- [ ] 扩展 `friendships` 表：新增 `generated_name`、`word_bank_version`
- [ ] 实现 `BEFRIEND` 协议全流程与 `EVT|BEFRIEND_*`
- [ ] 引入 `friend_notes` 表与 `SET_NOTE`/`NOTE_UPDATED` 协议
- [ ] CLI/G​UI 同步 `friend list`、`friend note`、`friend remove` 功能

**测试验证:**
- 功能测试: BEFRIEND 成功后自动生成代号并持久化
- 跨房间测试: 好友在不同房间重逢仍看到相同生成名
- 备注测试: 双方备注互不影响，更新立即推送

### Phase 5: 客户端适配 (2 周)

**目标:** 更新 Python CLI 和 GUI 客户端

- [ ] 更新 `room_protocol.py` 以支持 presence/display token 与新事件格式
- [ ] `Session` 缓存 `instance_id`、`presence_token`、`generated_name`
- [ ] GUI: 实现剪影渲染、点火/好友交互按钮、备注编辑
- [ ] CLI: 对齐 [5.3](#53-cli-功能对等性要求) 中的命令集
- [ ] CLI/GUI: 加载 `drlms.yaml` 配置并支持热刷新（重用 Admin API）

**测试验证:**
- E2E 测试: 完整流程演示（陌生人 → 点火 → 好友）
- 兼容性测试: M5 客户端与旧服务器的降级行为
- 配置热刷新测试: 更改 YAML 后 CLI/GUI 能即时同步

### Phase 6: 优化与文档 (1 周)

**目标:** 性能优化和用户文档

- [ ] 实现实例垃圾回收线程（清理空闲实例）
- [ ] 实现负载均衡分配策略
- [ ] 性能基准测试（1000+ 实例场景）
- [ ] 撰写 M5 用户手册
- [ ] 撰写迁移指南（从 M3 升级到 M5）
- [ ] 更新 API 文档

---

## 7. Phase 3 实施状态对照

| 模块 | 设计参考章节 | 当前实现要点 | 差距与后续计划 |
|------|---------------|--------------|----------------|
| 匿名呈现体系 | §2.3.1, §2.4.5 | `rooms.c` 已对订阅者生成 `presence_token`/`display_token`，推送事件携带 `instance_id` 与显示令牌；CLI/GUI 已按新字段渲染，陌生人文本实时脱敏。 | 历史回放（ephemeral/SQLite）与 GUI 事件流仍需接入脱敏占位符，避免旧记录泄露。 |
| IGNITE 临时连接 | §2.3.3, §5.1.1 | `IGNITE`/`IGNITE_ACCEPT`/`IGNITE_REJECT` 指令全链路落地，新增 `DRLMS_IGNITE_PENDING_TTL` 与 `DRLMS_IGNITE_ACTIVE_TTL` 由 GC 线程治理生命周期。 | CLI/GUI 在主动退订或超时场景的 UI 反馈待补齐，需覆盖双方状态同步。 |
| 好友体系与备注 | §2.3.4, §5.1.3-§5.1.5 | 新增 SQLite `friendships`、`friend_notes` 表及 Poetic Codename 词库初始化，`BEFRIEND_*`、`SET_NOTE` 指令与事件推送均已实现，测试覆盖好友流程。 | `EVT|BEFRIEND_ESTABLISHED`/`EVT|NOTE_UPDATED` 仍未读取既有备注；房间列表 `LISTROOMS` 尚未切换为 Phase 3 字段格式。 |
| 登录协议协商 | 附录 A | 服务器登录响应已升级为 `OK|LOGIN|<协议版本>|<服务器版本>`，客户端保留旧版降级兼容逻辑并记录最近握手元数据。 | 无（已完成）。 |
| 消息风控 | §2.3.2 | `rooms_fanout_text` 针对非好友订阅者发送等长占位符并生成 0 哈希，防止陌生人获取正文。 | 需扩展 SQLite/ephemeral 历史存取及 CLI/GUI 消费路径，使所有回放与缓存也遵循脱敏。 |
| 测试覆盖 | §5.3, Phase 5 | `python -m pytest` 覆盖 82 项用例（75 通过，7 跳过），新增好友、点火、脱敏相关单元与集成测试。 | 待追加握手协商、房间列表改造及 IGNITE TTL 超时的专项回归脚本，并补齐 Shell 端到端测试。 |

**备注:** 上述状态基于 `feature/m5-core` 分支当前实现（截至最新提交前的工作区修改）。后续变更请同步更新该对照表，确保设计与实现保持一致。

---

## 附录

### A. 协议版本协商

为支持客户端与服务器的平滑升级，建议在 `LOGIN` 响应中添加协议版本号：

```
OK|LOGIN|protocol_version|server_version
例如: OK|LOGIN|5|0.5.0
```

客户端根据 `protocol_version` 决定使用哪些特性：
- `protocol_version < 5`: 不使用分片、匿名化等 M5 特性
- `protocol_version >= 5`: 启用完整 M5 功能

### B. 配置文件示例

`drlms.yaml` (服务器配置):
```yaml
server:
  port: 8080
  max_connections: 128

rooms:
  default_instance_capacity: 50
  max_instances_per_room: 20
  instance_gc_interval: 3600      # 每小时清理一次空闲实例
  instance_idle_ttl: 86400        # 实例空闲 24 小时后可回收

storage:
  default_policy: ephemeral       # 新房间默认临时存储
  max_ephemeral_events: 1000      # 临时实例最多保留 1000 条事件
```

### C. 术语表

| 术语 | 英文 | 定义 |
|-----|------|------|
| 房间分片 | Room Sharding | 同一房间名下存在多个并行实例 |
| 实例 | Instance | 房间的一个具体实例，有独立的订阅者和事件流 |
| 阅后即焚 | Ephemeral | 消息仅临时存储，房间销毁后自动清除 |
| 点火 | Ignite | 建立临时连接，双方可见真实用户名（仅当前会话有效） |
| 好友 | Friend | 持久连接，跨房间可识别 |
| 匿名 ID | Anonymous ID | 陌生人模式下显示的临时标识符，如 `User#A3F9` |

---

## 变更历史

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|---------|
| 1.0 | 2025-01-10 | Droid | 初始版本，完成核心设计 |

---

**审阅状态:** 🟡 待审阅  
**下一步行动:** 提交给 ME (Gemini) 和技术团队审阅，收集反馈后进入 Phase 1 实现阶段。
