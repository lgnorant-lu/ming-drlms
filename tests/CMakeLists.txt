add_executable(test_ipc_suite test_ipc_suite.c)



add_dependencies(test_ipc_suite ipc_static)

target_include_directories(test_ipc_suite PRIVATE
    ${PROJECT_SOURCE_DIR}/src/libipc
    ${PROJECT_SOURCE_DIR}/src/platform/include)

set(TEST_LIBS
    ipc_static
    OpenSSL::Crypto
    Threads::Threads
    platform
)

if(UNIX AND NOT APPLE)
    list(APPEND TEST_LIBS rt)
endif()

if(ENABLE_COVERAGE AND COVERAGE_LIBS)
    list(APPEND TEST_LIBS ${COVERAGE_LIBS})
endif()

if(WIN32)
    list(APPEND TEST_LIBS ws2_32 bcrypt)
endif()

target_link_libraries(test_ipc_suite PRIVATE ${TEST_LIBS})

add_test(NAME ipc_suite COMMAND test_ipc_suite)

# M-Proto-v2 Integration Tests (requires protobuf-c and Python)
if(PROTOBUF_C_FOUND)
    find_program(PYTHON_EXECUTABLE python3 python)
    if(PYTHON_EXECUTABLE)
        # Create M-Proto-v2 test wrapper script
        set(MP2_TEST_WRAPPER "${CMAKE_BINARY_DIR}/mp2_test_wrapper.sh")
        file(WRITE ${MP2_TEST_WRAPPER} "#!/bin/bash\n")
        file(APPEND ${MP2_TEST_WRAPPER} "set -euo pipefail\n\n")
        file(APPEND ${MP2_TEST_WRAPPER} "# M-Proto-v2 Test Wrapper - Auto-manages server lifecycle\n")
        file(APPEND ${MP2_TEST_WRAPPER} "TEST_SCRIPT=\"$1\"\n")
        file(APPEND ${MP2_TEST_WRAPPER} "shift\n\n")
        file(APPEND ${MP2_TEST_WRAPPER} "# Configuration\n")
        file(APPEND ${MP2_TEST_WRAPPER} "MP2_PORT=19093\n")
        file(APPEND ${MP2_TEST_WRAPPER} "MP2_DATA_DIR=\"${CMAKE_BINARY_DIR}/mp2_test_data\"\n")
        file(APPEND ${MP2_TEST_WRAPPER} "SERVER_BIN=\"${CMAKE_BINARY_DIR}/log_collector_server\"\n")
        file(APPEND ${MP2_TEST_WRAPPER} "MP2_HASH='\$argon2id\$v=19\$m=65536,t=2,p=1\$iTXfEYiQzYkCz2ijoOUL6Q\$fd0CGDYDEeZEJUjqP8YMfUlRg5RScaSaYvi/ldNpTHI'\n\n")
        file(APPEND ${MP2_TEST_WRAPPER} "# Cleanup function\n")
        file(APPEND ${MP2_TEST_WRAPPER} "cleanup() {\n")
        file(APPEND ${MP2_TEST_WRAPPER} "    if [ -n \"\${SERVER_PID:-}\" ]; then\n")
        file(APPEND ${MP2_TEST_WRAPPER} "        kill \"\$SERVER_PID\" 2>/dev/null || true\n")
        file(APPEND ${MP2_TEST_WRAPPER} "        wait \"\$SERVER_PID\" 2>/dev/null || true\n")
        file(APPEND ${MP2_TEST_WRAPPER} "    fi\n")
        file(APPEND ${MP2_TEST_WRAPPER} "    rm -rf \"\$MP2_DATA_DIR\" 2>/dev/null || true\n")
        file(APPEND ${MP2_TEST_WRAPPER} "}\n")
        file(APPEND ${MP2_TEST_WRAPPER} "trap cleanup EXIT\n\n")
        file(APPEND ${MP2_TEST_WRAPPER} "# Setup test environment\n")
        file(APPEND ${MP2_TEST_WRAPPER} "mkdir -p \"\$MP2_DATA_DIR\"\n")
        file(APPEND ${MP2_TEST_WRAPPER} "echo \"alice::\$MP2_HASH\" > \"\$MP2_DATA_DIR/users.txt\"\n\n")
    file(APPEND ${MP2_TEST_WRAPPER} "# Start M-Proto-v2 server\n")
    file(APPEND ${MP2_TEST_WRAPPER} "DRLMS_ENABLE_MPROTO_V2=1 DRLMS_JWT_SECRET=cmake-test-secret DRLMS_PORT=\"\$MP2_PORT\" DRLMS_DATA_DIR=\"\$MP2_DATA_DIR\" \\\n")
    file(APPEND ${MP2_TEST_WRAPPER} "    \"\$SERVER_BIN\" >/dev/null 2>&1 &\n")
        file(APPEND ${MP2_TEST_WRAPPER} "SERVER_PID=\$!\n\n")
    file(APPEND ${MP2_TEST_WRAPPER} "# Wait for server to start (poll port readiness)\n")
    file(APPEND ${MP2_TEST_WRAPPER} "READY=0\nfor i in $(seq 1 200); do\n")
    file(APPEND ${MP2_TEST_WRAPPER} "  (echo > /dev/tcp/127.0.0.1/\"$MP2_PORT\") >/dev/null 2>&1 && READY=1 && break\n")
    file(APPEND ${MP2_TEST_WRAPPER} "  sleep 0.05\n")
    file(APPEND ${MP2_TEST_WRAPPER} "done\n")
    file(APPEND ${MP2_TEST_WRAPPER} "if [ \"$READY\" -ne 1 ]; then echo '[ERROR] server not ready' >&2; exit 1; fi\n\n")
    file(APPEND ${MP2_TEST_WRAPPER} "# Run the actual test\n")
    file(APPEND ${MP2_TEST_WRAPPER} "\"${PYTHON_EXECUTABLE}\" \"$TEST_SCRIPT\" --host 127.0.0.1 --port \"$MP2_PORT\" --password-hash \"$MP2_HASH\" \"$@\"\n")
        
        # Make wrapper executable
        file(APPEND ${MP2_TEST_WRAPPER} "")
        execute_process(COMMAND chmod +x ${MP2_TEST_WRAPPER})
        
        # M-Proto-v2 Authentication Test
    add_test(NAME mp2_auth_test 
         COMMAND ${MP2_TEST_WRAPPER} ${CMAKE_SOURCE_DIR}/scripts/test_mp2_auth.py)
        
        # M-Proto-v2 Room Operations Test
    add_test(NAME mp2_rooms_test 
         COMMAND ${MP2_TEST_WRAPPER} ${CMAKE_SOURCE_DIR}/scripts/test_mp2_rooms.py
                         --room mp2-cmake-test --message "CMake test message")
        
        # M-Proto-v2 Dual Client Test
    add_test(NAME mp2_dual_client_test 
         COMMAND ${MP2_TEST_WRAPPER} ${CMAKE_SOURCE_DIR}/scripts/test_mp2_dual_client.py
                         --room mp2-cmake-dual --message "CMake dual client test")
        
        # M-Proto-v2 History Replay Test
    add_test(NAME mp2_history_test 
         COMMAND ${MP2_TEST_WRAPPER} ${CMAKE_SOURCE_DIR}/scripts/test_mp2_history.py
                         --room mp2-cmake-history --since-id 1)
        
        # Set test dependencies to ensure server is built first
        set_tests_properties(mp2_auth_test mp2_rooms_test mp2_dual_client_test mp2_history_test
                             PROPERTIES DEPENDS log_collector_server)
        
        message(STATUS "M-Proto-v2 tests enabled with auto-managed server lifecycle")
    else()
        message(WARNING "Python executable not found; M-Proto-v2 tests disabled")
    endif()
else()
    message(STATUS "protobuf-c not found; M-Proto-v2 tests disabled")
endif()
