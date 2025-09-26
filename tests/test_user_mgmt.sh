#!/usr/bin/env bash
# 测试用户管理脚本
# 提供可扩展的用户创建、验证和管理功能

set -euo pipefail

# 默认配置
DEFAULT_DATA_DIR="${TEST_DATA_DIR:-server_files}"
DEFAULT_CLI="${CLI:-ming-drlms}"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 用户配置模板
declare -A USER_TEMPLATES=(
    ["basic"]="testuser:testpass"
    ["admin"]="admin:admin123"
    ["room_owner"]="owner1:password"
    ["room_sub"]="sub1:password"
    ["legacy"]="alice:password"
    ["argon2"]="bob:password"
)

# 创建单个用户
create_user() {
    local username="$1"
    local password="$2"
    local data_dir="${3:-$DEFAULT_DATA_DIR}"
    
    log_info "Creating user: $username"
    
    if ! "$DEFAULT_CLI" user add "$username" -d "$data_dir" --password-from-stdin <<< "$password" >/dev/null 2>&1; then
        log_warning "User $username may already exist or creation failed"
        return 1
    fi
    
    log_success "User $username created successfully"
    return 0
}

# 创建用户组
create_user_group() {
    local group_name="$1"
    local data_dir="${2:-$DEFAULT_DATA_DIR}"
    
    log_info "Creating user group: $group_name"
    
    case "$group_name" in
        "basic")
            create_user "testuser" "testpass" "$data_dir"
            ;;
        "room_test")
            create_user "owner1" "password" "$data_dir"
            create_user "sub1" "password" "$data_dir"
            ;;
        "legacy_test")
            create_user "alice" "password" "$data_dir"
            create_user "bob" "password" "$data_dir"
            ;;
        "all")
            for template in "${!USER_TEMPLATES[@]}"; do
                IFS=':' read -r user pass <<< "${USER_TEMPLATES[$template]}"
                create_user "$user" "$pass" "$data_dir" || true
            done
            ;;
        *)
            log_error "Unknown user group: $group_name"
            return 1
            ;;
    esac
}

# 验证用户
verify_user() {
    local username="$1"
    local password="$2"
    local host="${3:-127.0.0.1}"
    local port="${4:-8080}"
    
    log_info "Verifying user: $username"
    
    if echo -e "LOGIN|$username|$password\nQUIT\n" | nc -w 5 "$host" "$port" | grep -q "OK|WELCOME"; then
        log_success "User $username verification passed"
        return 0
    else
        log_error "User $username verification failed"
        return 1
    fi
}

# 列出用户
list_users() {
    local data_dir="${1:-$DEFAULT_DATA_DIR}"
    
    log_info "Listing users in: $data_dir"
    
    if [[ -f "$data_dir/users.txt" ]]; then
        echo "Users in $data_dir/users.txt:"
        cat "$data_dir/users.txt" | grep -v '^#' | grep -v '^$' | while IFS=':' read -r user salt hash; do
            if [[ -n "$user" ]]; then
                echo "  - $user"
            fi
        done
    else
        log_warning "No users.txt found in $data_dir"
    fi
}

# 清理用户
cleanup_users() {
    local data_dir="${1:-$DEFAULT_DATA_DIR}"
    
    log_info "Cleaning up users in: $data_dir"
    
    if [[ -f "$data_dir/users.txt" ]]; then
        rm -f "$data_dir/users.txt"
        log_success "Users file removed: $data_dir/users.txt"
    else
        log_warning "No users file to clean up"
    fi
}

# 显示帮助
show_help() {
    cat << EOF
Usage: $0 COMMAND [OPTIONS]

Commands:
    create USERNAME PASSWORD [DATA_DIR]     Create a single user
    group GROUP_NAME [DATA_DIR]             Create a user group
    verify USERNAME PASSWORD [HOST] [PORT]  Verify user login
    list [DATA_DIR]                         List existing users
    cleanup [DATA_DIR]                      Remove users file
    help                                    Show this help

User Groups:
    basic       - Basic test user (testuser:testpass)
    room_test   - Room testing users (owner1, sub1)
    legacy_test - Legacy format users (alice, bob)
    all         - All predefined users

Examples:
    $0 create testuser testpass
    $0 group room_test
    $0 verify testuser testpass
    $0 list
    $0 cleanup

Environment Variables:
    TEST_DATA_DIR - Default data directory (default: server_files)
    CLI           - CLI command (default: ming-drlms)
EOF
}

# 主函数
main() {
    local command="${1:-help}"
    
    case "$command" in
        "create")
            if [[ $# -lt 3 ]]; then
                log_error "Usage: $0 create USERNAME PASSWORD [DATA_DIR]"
                exit 1
            fi
            create_user "$2" "$3" "${4:-$DEFAULT_DATA_DIR}"
            ;;
        "group")
            if [[ $# -lt 2 ]]; then
                log_error "Usage: $0 group GROUP_NAME [DATA_DIR]"
                exit 1
            fi
            create_user_group "$2" "${3:-$DEFAULT_DATA_DIR}"
            ;;
        "verify")
            if [[ $# -lt 3 ]]; then
                log_error "Usage: $0 verify USERNAME PASSWORD [HOST] [PORT]"
                exit 1
            fi
            verify_user "$2" "$3" "${4:-127.0.0.1}" "${5:-8080}"
            ;;
        "list")
            list_users "${2:-$DEFAULT_DATA_DIR}"
            ;;
        "cleanup")
            cleanup_users "${2:-$DEFAULT_DATA_DIR}"
            ;;
        "help"|"--help"|"-h")
            show_help
            ;;
        *)
            log_error "Unknown command: $command"
            show_help
            exit 1
            ;;
    esac
}

# 如果直接执行此脚本
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
