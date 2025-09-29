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

target_link_libraries(test_ipc_suite PRIVATE ${TEST_LIBS})

add_test(NAME ipc_suite COMMAND test_ipc_suite)
