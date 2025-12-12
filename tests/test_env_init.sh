#!/usr/bin/env bash
# 测试环境初始化脚本
# 提供可扩展、可持久化的测试环境管理

set -euo pipefail

# Skip this script if running in MP2-only mode
if [[ "${DRLMS_ENABLE_MPROTO_V2:-}" == "1" ]]; then
    echo "SKIP: Environment init test skipped in MP2-only mode (legacy text protocol dependency)"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/lib/socket_helpers.sh
source "$SCRIPT_DIR/lib/socket_helpers.sh"

ensure_python

BIN_EXT=""
if [[ "${IS_WINDOWS}" -eq 1 ]]; then
    BIN_EXT=".exe"
fi

CLI_BIN="${CLI_BIN:-ming-drlms}"
CLI_CMD="$CLI_BIN"

set_test_data_dir() {
    local raw="$1"
    if [[ "${IS_WINDOWS}" -eq 1 ]]; then
        TEST_DATA_DIR_POSIX="$(to_posix_path "$raw")"
        TEST_DATA_DIR_NATIVE="$(to_win_path "$raw")"
    else
        TEST_DATA_DIR_POSIX="$raw"
        TEST_DATA_DIR_NATIVE="$raw"
    fi
    TEST_DATA_DIR="$TEST_DATA_DIR_POSIX"
}

TEST_DATA_DIR_DEFAULT="${TEST_DATA_DIR:-/tmp/drlms_test_env_$$}"
set_test_data_dir "$TEST_DATA_DIR_DEFAULT"
TEST_PORT="${TEST_PORT:-15035}"
TEST_HOST="${TEST_HOST:-127.0.0.1}"
START_SERVER=1

# 测试用户配置（使用兼容 Bash 3.2 的键值串）
TEST_USERS=(
    "owner1:password"
    "sub1:password"
    "testuser:testpass"
    "alice:password"
    "bob:password"
)

# 测试房间配置
TEST_ROOMS=(
    "demo:owner1"
    "test_room:testuser"
    "integration_room:owner1"
)

user_names() {
    local names=()
    local entry name
    for entry in "${TEST_USERS[@]}"; do
        IFS=':' read -r name _ <<<"$entry"
        names+=("$name")
    done
    printf '%s\n' "${names[@]}"
}

user_password() {
    local target="$1"
    local entry name pwd
    for entry in "${TEST_USERS[@]}"; do
        IFS=':' read -r name pwd <<<"$entry"
        if [[ "$name" == "$target" ]]; then
            printf '%s' "$pwd"
            return 0
        fi
    done
    return 1
}

room_names() {
    local rooms=()
    local entry room _
    for entry in "${TEST_ROOMS[@]}"; do
        IFS=':' read -r room _ <<<"$entry"
        rooms+=("$room")
    done
    printf '%s\n' "${rooms[@]}"
}

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
        log_info "Stopping test server (PID: $pid)"
        terminate_pid "$pid"
        rm -f /tmp/drlms_test_srv.pid
    fi
    
    if [[ "${KEEP_TEST_DATA:-0}" != "1" ]]; then
        if ! rm -rf "$TEST_DATA_DIR" 2>/dev/null; then
            log_warning "Failed to remove test data directory on first attempt; retrying shortly"
            sleep 1
            if ! rm -rf "$TEST_DATA_DIR" 2>/dev/null; then
                log_warning "Test data directory preserved due to removal failure: $TEST_DATA_DIR"
            else
                log_info "Test data directory removed after retry: $TEST_DATA_DIR"
            fi
        else
            log_info "Test data directory removed: $TEST_DATA_DIR"
        fi
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

    if command -v "$CLI_BIN" >/dev/null 2>&1; then
        CLI_CMD="$(command -v "$CLI_BIN")"
    elif [[ -x "$CLI_BIN" ]]; then
        CLI_CMD="$CLI_BIN"
    else
        missing_deps+=("$CLI_BIN")
    fi

    if ! command -v jq >/dev/null 2>&1; then
        log_warning "jq 未找到，跳过部分 JSON 诊断输出"
    fi
    if ! command -v sqlite3 >/dev/null 2>&1; then
        log_warning "sqlite3 未找到，将跳过数据库内部检查"
    fi

    if ((${#missing_deps[@]} > 0)); then
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

    local entry user password
    for entry in "${TEST_USERS[@]}"; do
        IFS=':' read -r user password <<<"$entry"
        log_info "Creating user: $user"

        if ! "$CLI_CMD" user add "$user" -d "$TEST_DATA_DIR" --password-from-stdin <<<"$password" >/dev/null 2>&1; then
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
    if port_is_open "$TEST_HOST" "$TEST_PORT"; then
        log_warning "Port $TEST_PORT is already in use"
        return 1
    fi

    local server_bin=""
    local -a candidates=()
    if [[ -n "${DRLMS_RUNTIME_BIN_DIR:-}" ]]; then
        local runtime_dir
        runtime_dir="${DRLMS_RUNTIME_BIN_DIR}"
        if [[ "${IS_WINDOWS}" -eq 1 ]]; then
            runtime_dir="$(to_posix_path "$runtime_dir")"
        fi
        candidates+=("${runtime_dir}/log_collector_server${BIN_EXT}")
    fi
    candidates+=("$PWD/log_collector_server${BIN_EXT}")
    if [[ -n "${DRLMS_CMAKE_BUILD_DIR:-}" ]]; then
        local build_root
        build_root="${DRLMS_CMAKE_BUILD_DIR}"
        if [[ "${IS_WINDOWS}" -eq 1 ]]; then
            build_root="$(to_posix_path "$build_root")"
        fi
        candidates+=("${build_root}/log_collector_server${BIN_EXT}")
        for cfg in RelWithDebInfo Release Debug MinSizeRel; do
            candidates+=("${build_root}/${cfg}/log_collector_server${BIN_EXT}")
        done
    fi
    for candidate in "${candidates[@]}"; do
        if [[ -n "$candidate" && -x "$candidate" ]]; then
            server_bin="$candidate"
            break
        fi
    done
    if [[ -z "$server_bin" ]]; then
        log_error "Unable to locate log_collector_server${BIN_EXT} (checked: ${candidates[*]})"
        return 1
    fi

    local server_dir
    server_dir="$(dirname "$server_bin")"

    local data_dir_env="$TEST_DATA_DIR"
    if [[ "${IS_WINDOWS}" -eq 1 ]]; then
        data_dir_env="$(to_win_path "$data_dir_env")"
    fi

    local -a env_vars=(
        "DRLMS_AUTH_STRICT=0"
        "DRLMS_DATA_DIR=$data_dir_env"
        "DRLMS_PORT=$TEST_PORT"
    )
    if [[ "${IS_WINDOWS}" -ne 1 ]]; then
        env_vars+=(
            "LD_LIBRARY_PATH=$server_dir"
            "DYLD_LIBRARY_PATH=$server_dir"
        )
    fi

    (
        cd "$server_dir"
        env "${env_vars[@]}" "./$(basename "$server_bin")" > "$TEST_DATA_DIR/server.log" 2>&1 &
        echo $! > /tmp/drlms_test_srv.pid
    )

    local server_pid
    server_pid=$(cat /tmp/drlms_test_srv.pid 2>/dev/null || true)
    if [[ -z "$server_pid" ]]; then
        log_error "Failed to capture server PID"
        return 1
    fi
    
    # 等待服务器启动
    if wait_for_port "$TEST_HOST" "$TEST_PORT" 40 0.25; then
        log_success "Test server started (PID: $server_pid)"
        return 0
    fi

    log_error "Test server failed to start"
    if [[ -f "$TEST_DATA_DIR/server.log" ]]; then
        log_error "Tail of server log:"
        tail -n 20 "$TEST_DATA_DIR/server.log" || true
    fi
    return 1
}

# 验证测试环境
verify_test_environment() {
    log_info "Verifying test environment..."

    # 测试基本连接
    if ! port_is_open "$TEST_HOST" "$TEST_PORT"; then
        log_error "Server is not responding"
        return 1
    fi

    # 测试用户登录
    local entry user password response
    for entry in "${TEST_USERS[@]}"; do
        IFS=':' read -r user password <<<"$entry"
        log_info "Testing login for user: $user"

        if ! response=$(printf 'LOGIN|%s|%s\nQUIT\n' "$user" "$password" | socket_request "$TEST_HOST" "$TEST_PORT"); then
            log_error "Login request failed for user: $user"
            return 1
        fi

        if [[ "$response" != *"OK|LOGIN|"* && "$response" != *"OK|WELCOME"* ]]; then
            log_error "Login failed for user: $user"
            log_error "Response: $response"
            return 1
        fi
    done

    log_success "Test environment verification passed"
    return 0
}

# 显示测试环境信息
show_test_info() {
    log_info "Test Environment Information:"
    local users_str=""
    local rooms_str=""
    local name
    while IFS= read -r name; do
        users_str+="$name "
    done < <(user_names)
    while IFS= read -r name; do
        rooms_str+="$name "
    done < <(room_names)

    echo "  Data Directory: $TEST_DATA_DIR"
    echo "  Server: $TEST_HOST:$TEST_PORT"
    echo "  Users: ${users_str%% }"
    echo "  Rooms: ${rooms_str%% }"
    echo "  Server PID: $(cat /tmp/drlms_test_srv.pid 2>/dev/null || echo 'N/A')"
    echo ""
    log_info "Environment variables for tests:"
    echo "  export TEST_DATA_DIR='$TEST_DATA_DIR'"
    echo "  export TEST_PORT='$TEST_PORT'"
    echo "  export TEST_HOST='$TEST_HOST'"
    echo ""
    log_info "Additional environment variables:"
    echo "  export DRLMS_MP2_HOST=127.0.0.1"
    echo "  export DRLMS_MP2_PORT=15035"
    echo "  export DRLMS_BACKEND_MODE=mp2"
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
            --no-server)
                START_SERVER=0
                shift
                ;;
            --help)
                echo "Usage: $0 [OPTIONS]"
                echo "Options:"
                echo "  --keep-data     Keep test data directory after exit"
                echo "  --port PORT     Use specific port (default: 15035)"
                echo "  --data-dir DIR  Use specific data directory"
                echo "  --no-server     Prepare data only (do not start server)"
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

    if [[ "$START_SERVER" == "1" ]]; then
        if ! start_test_server; then
            log_error "Failed to start server"
            exit 1
        fi

        if ! verify_test_environment; then
            log_error "Test environment verification failed"
            exit 1
        fi

        show_test_info
    else
        log_info "Skipping server startup (--no-server)"
        show_test_info
    fi
    
    log_success "Test environment initialization completed!"
    log_info "Use 'export TEST_DATA_DIR=\"$TEST_DATA_DIR\"' in your test scripts"
    
    # 如果设置了保持数据，则等待用户输入
    if [[ "$START_SERVER" == "1" && "${KEEP_TEST_DATA:-0}" == "1" ]]; then
        log_info "Press Enter to stop the test server and exit..."
        read -r
    fi
}

# 如果直接执行此脚本
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
