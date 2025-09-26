#!/usr/bin/env bash
# 测试环境初始化脚本
# 提供可扩展、可持久化的测试环境管理

set -euo pipefail

# 测试环境配置
TEST_DATA_DIR="${TEST_DATA_DIR:-/tmp/drlms_test_env_$$}"
TEST_PORT="${TEST_PORT:-8080}"
TEST_HOST="${TEST_HOST:-127.0.0.1}"

# 测试用户配置
declare -A TEST_USERS=(
    ["owner1"]="password"
    ["sub1"]="password"
    ["testuser"]="testpass"
    ["alice"]="password"
    ["bob"]="password"
)

# 测试房间配置
declare -A TEST_ROOMS=(
    ["demo"]="owner1"
    ["test_room"]="testuser"
    ["integration_room"]="owner1"
)

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 清理函数
cleanup() {
    log_info "Cleaning up test environment..."
    if [[ -f "/tmp/drlms_test_srv.pid" ]]; then
        local pid=$(cat /tmp/drlms_test_srv.pid)
        if kill -0 "$pid" 2>/dev/null; then
            log_info "Stopping test server (PID: $pid)"
            kill -TERM "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
        rm -f /tmp/drlms_test_srv.pid
    fi
    
    if [[ "${KEEP_TEST_DATA:-0}" != "1" ]]; then
        rm -rf "$TEST_DATA_DIR"
        log_info "Test data directory removed: $TEST_DATA_DIR"
    else
        log_info "Test data directory preserved: $TEST_DATA_DIR"
    fi
}

# 注册清理函数
trap cleanup EXIT

# 检查依赖
check_dependencies() {
    log_info "Checking dependencies..."
    
    local missing_deps=()
    
    if ! command -v ming-drlms >/dev/null 2>&1; then
        missing_deps+=("ming-drlms")
    fi
    
    if ! command -v nc >/dev/null 2>&1; then
        missing_deps+=("netcat")
    fi
    
    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        log_error "Missing dependencies: ${missing_deps[*]}"
        log_info "Please install missing dependencies and retry"
        exit 1
    fi
    
    log_success "All dependencies available"
}

# 创建测试数据目录
setup_test_data_dir() {
    log_info "Setting up test data directory: $TEST_DATA_DIR"
    
    mkdir -p "$TEST_DATA_DIR"
    mkdir -p "$TEST_DATA_DIR/rooms"
    
    # 创建空的用户文件（非严格模式）
    touch "$TEST_DATA_DIR/users.txt"
    
    log_success "Test data directory created"
}

# 创建测试用户
create_test_users() {
    log_info "Creating test users..."
    
    for user in "${!TEST_USERS[@]}"; do
        local password="${TEST_USERS[$user]}"
        log_info "Creating user: $user"
        
        if ! ming-drlms user add "$user" -d "$TEST_DATA_DIR" --password-from-stdin <<< "$password" >/dev/null 2>&1; then
            log_warning "Failed to create user $user (may already exist)"
        else
            log_success "User $user created"
        fi
    done
}

# 启动测试服务器
start_test_server() {
    log_info "Starting test server on $TEST_HOST:$TEST_PORT"
    
    # 确保端口可用
    if nc -z "$TEST_HOST" "$TEST_PORT" 2>/dev/null; then
        log_warning "Port $TEST_PORT is already in use"
        return 1
    fi
    
    # 启动服务器
    DRLMS_AUTH_STRICT=0 \
    DRLMS_DATA_DIR="$TEST_DATA_DIR" \
    DRLMS_PORT="$TEST_PORT" \
    LD_LIBRARY_PATH=. \
    ./log_collector_server > "$TEST_DATA_DIR/server.log" 2>&1 &
    
    local server_pid=$!
    echo "$server_pid" > /tmp/drlms_test_srv.pid
    
    # 等待服务器启动
    local max_attempts=20
    local attempt=0
    
    while [[ $attempt -lt $max_attempts ]]; do
        if nc -z "$TEST_HOST" "$TEST_PORT" 2>/dev/null; then
            log_success "Test server started (PID: $server_pid)"
            return 0
        fi
        sleep 0.2
        ((attempt++))
    done
    
    log_error "Test server failed to start"
    return 1
}

# 验证测试环境
verify_test_environment() {
    log_info "Verifying test environment..."
    
    # 测试基本连接
    if ! nc -z "$TEST_HOST" "$TEST_PORT" 2>/dev/null; then
        log_error "Server is not responding"
        return 1
    fi
    
    # 测试用户登录
    for user in "${!TEST_USERS[@]}"; do
        local password="${TEST_USERS[$user]}"
        log_info "Testing login for user: $user"
        
        if ! echo -e "LOGIN|$user|$password\nQUIT\n" | nc -w 5 "$TEST_HOST" "$TEST_PORT" | grep -q "OK|WELCOME"; then
            log_error "Login failed for user: $user"
            return 1
        fi
    done
    
    log_success "Test environment verification passed"
    return 0
}

# 显示测试环境信息
show_test_info() {
    log_info "Test Environment Information:"
    echo "  Data Directory: $TEST_DATA_DIR"
    echo "  Server: $TEST_HOST:$TEST_PORT"
    echo "  Users: ${!TEST_USERS[*]}"
    echo "  Rooms: ${!TEST_ROOMS[*]}"
    echo "  Server PID: $(cat /tmp/drlms_test_srv.pid 2>/dev/null || echo 'N/A')"
    echo ""
    log_info "Environment variables for tests:"
    echo "  export TEST_DATA_DIR='$TEST_DATA_DIR'"
    echo "  export TEST_PORT='$TEST_PORT'"
    echo "  export TEST_HOST='$TEST_HOST'"
    echo ""
}

# 主函数
main() {
    log_info "Initializing test environment..."
    
    # 解析命令行参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            --keep-data)
                export KEEP_TEST_DATA=1
                shift
                ;;
            --port)
                TEST_PORT="$2"
                shift 2
                ;;
            --data-dir)
                TEST_DATA_DIR="$2"
                shift 2
                ;;
            --help)
                echo "Usage: $0 [OPTIONS]"
                echo "Options:"
                echo "  --keep-data     Keep test data directory after exit"
                echo "  --port PORT     Use specific port (default: 8080)"
                echo "  --data-dir DIR  Use specific data directory"
                echo "  --help          Show this help message"
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    # 执行初始化步骤
    check_dependencies
    setup_test_data_dir
    create_test_users
    start_test_server
    verify_test_environment
    show_test_info
    
    log_success "Test environment initialization completed!"
    log_info "Use 'export TEST_DATA_DIR=\"$TEST_DATA_DIR\"' in your test scripts"
    
    # 如果设置了保持数据，则等待用户输入
    if [[ "${KEEP_TEST_DATA:-0}" == "1" ]]; then
        log_info "Press Enter to stop the test server and exit..."
        read -r
    fi
}

# 如果直接执行此脚本
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
