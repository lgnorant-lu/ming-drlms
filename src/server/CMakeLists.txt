set(SERVER_SOURCES
    log_collector_server.c
    rooms.c
    sqlite_storage.c
)

add_executable(log_collector_server ${SERVER_SOURCES})

target_include_directories(log_collector_server
    PRIVATE
        ${PROJECT_SOURCE_DIR}/src/libipc
        ${PROJECT_SOURCE_DIR}/src/platform/include
        ${SQLite3_INCLUDE_DIRS}
        ${ARGON2_INCLUDE_DIRS}
)

set(SERVER_LIBS
    ipc_static
    Threads::Threads
    ${SQLite3_LIBRARIES}
    ${ARGON2_LIBRARIES}
    OpenSSL::Crypto
    platform
)

if(UNIX AND NOT APPLE)
    list(APPEND SERVER_LIBS rt)
endif()

if(ENABLE_COVERAGE AND COVERAGE_LIBS)
    list(APPEND SERVER_LIBS ${COVERAGE_LIBS})
endif()

target_link_libraries(log_collector_server PRIVATE ${SERVER_LIBS})
