# 测试环境管理文档

## 概述

本文档描述了DRLMS项目的测试环境管理系统，提供了可扩展、可持久化的测试基础设施。

## 核心组件

### 1. 测试环境初始化脚本 (`test_env_init.sh`)

**功能**：
- 自动创建测试数据目录
- 启动测试服务器
- 创建预定义测试用户
- 验证测试环境

**使用方法**：
```bash
# 基本使用
./tests/test_env_init.sh

# 自定义配置
./tests/test_env_init.sh --port 8081 --data-dir /tmp/my_test --keep-data

# 查看帮助
./tests/test_env_init.sh --help
```

**环境变量**：
- `TEST_DATA_DIR`: 测试数据目录
- `TEST_PORT`: 测试服务器端口
- `TEST_HOST`: 测试服务器主机

### 2. 用户管理脚本 (`test_user_mgmt.sh`)

**功能**：
- 创建单个用户或用户组
- 验证用户登录
- 列出和清理用户

**使用方法**：
```bash
# 创建单个用户
./tests/test_user_mgmt.sh create testuser testpass

# 创建用户组
./tests/test_user_mgmt.sh group room_test

# 验证用户
./tests/test_user_mgmt.sh verify testuser testpass

# 列出用户
./tests/test_user_mgmt.sh list

# 清理用户
./tests/test_user_mgmt.sh cleanup
```

**预定义用户组**：
- `basic`: 基础测试用户 (testuser:testpass)
- `room_test`: 房间测试用户 (owner1, sub1)
- `legacy_test`: 传统格式用户 (alice, bob)
- `all`: 所有预定义用户

### 3. 集成测试脚本 (`integration_space.sh`)

**功能**：
- 房间策略集成测试
- 支持测试环境变量
- 向后兼容性

**环境变量支持**：
- `TEST_HOST`: 测试主机
- `TEST_PORT`: 测试端口
- `TEST_DATA_DIR`: 测试数据目录

## 测试流程

### 1. 手动测试流程

```bash
# 1. 初始化测试环境
./tests/test_env_init.sh --keep-data

# 2. 运行特定测试
export TEST_DATA_DIR="/tmp/drlms_test_env_12345"
./tests/integration_space.sh

# 3. 清理（可选）
./tests/test_user_mgmt.sh cleanup "$TEST_DATA_DIR"
```

### 2. 自动化测试流程

```bash
# 使用Makefile运行完整测试套件
make coverage

# 快速测试（跳过复杂房间策略测试）
FAST=1 make coverage
```

## 配置管理

### 1. 测试用户配置

在 `test_env_init.sh` 中定义：
```bash
declare -A TEST_USERS=(
    ["owner1"]="password"
    ["sub1"]="password"
    ["testuser"]="testpass"
    ["alice"]="password"
    ["bob"]="password"
)
```

### 2. 测试房间配置

在 `test_env_init.sh` 中定义：
```bash
declare -A TEST_ROOMS=(
    ["demo"]="owner1"
    ["test_room"]="testuser"
    ["integration_room"]="owner1"
)
```

## 扩展指南

### 1. 添加新的测试用户

1. 在 `test_env_init.sh` 的 `TEST_USERS` 数组中添加用户
2. 在 `test_user_mgmt.sh` 的 `USER_TEMPLATES` 中添加模板
3. 更新相关测试脚本

### 2. 添加新的测试场景

1. 创建新的测试脚本
2. 使用环境变量进行配置
3. 在Makefile中添加调用

### 3. 自定义测试环境

1. 继承 `test_env_init.sh` 的功能
2. 重写特定配置
3. 保持环境变量兼容性

## 故障排除

### 1. 常见问题

**问题**: 测试用户创建失败
**解决**: 检查CLI工具是否正确安装，数据目录是否可写

**问题**: 服务器启动失败
**解决**: 检查端口是否被占用，权限是否正确

**问题**: 登录验证失败
**解决**: 检查用户是否存在，密码是否正确

### 2. 调试技巧

```bash
# 启用详细输出
set -x

# 检查服务器状态
nc -z 127.0.0.1 8080

# 查看服务器日志
tail -f /tmp/drlms_server.log

# 手动测试登录
echo -e "LOGIN|testuser|testpass\nQUIT\n" | nc 127.0.0.1 8080
```

## 最佳实践

### 1. 测试隔离

- 使用独立的测试数据目录
- 避免使用生产数据
- 测试后清理资源

### 2. 环境变量

- 优先使用环境变量进行配置
- 提供合理的默认值
- 保持向后兼容性

### 3. 错误处理

- 提供清晰的错误信息
- 实现优雅的失败处理
- 记录详细的日志

### 4. 性能优化

- 使用FAST模式跳过复杂测试
- 并行化测试执行
- 缓存测试环境

## 维护指南

### 1. 定期维护

- 更新测试用户密码
- 清理过期的测试数据
- 更新依赖版本

### 2. 版本兼容性

- 保持向后兼容性
- 标记废弃的功能
- 提供迁移指南

### 3. 文档更新

- 及时更新使用文档
- 记录配置变更
- 维护故障排除指南
