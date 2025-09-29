add_executable(proc_launcher proc_launcher.c)

target_include_directories(proc_launcher PRIVATE
    ${PROJECT_SOURCE_DIR}/src/platform/include)

target_link_libraries(proc_launcher PRIVATE platform Threads::Threads)

add_executable(log_consumer log_consumer.c)

target_include_directories(log_consumer PRIVATE
    ${PROJECT_SOURCE_DIR}/src/libipc
    ${PROJECT_SOURCE_DIR}/src/platform/include)

set(LOG_CONSUMER_LIBS
    ipc_static
    Threads::Threads
    platform
)

if(UNIX AND NOT APPLE)
    list(APPEND LOG_CONSUMER_LIBS rt)
endif()

if(ENABLE_COVERAGE AND COVERAGE_LIBS)
    list(APPEND LOG_CONSUMER_LIBS ${COVERAGE_LIBS})
endif()

target_link_libraries(log_consumer PRIVATE ${LOG_CONSUMER_LIBS})

add_executable(ipc_sender ipc_sender.c)

target_include_directories(ipc_sender PRIVATE
    ${PROJECT_SOURCE_DIR}/src/libipc
    ${PROJECT_SOURCE_DIR}/src/platform/include)

set(IPC_SENDER_LIBS
    ipc_static
    Threads::Threads
    platform
)

if(UNIX AND NOT APPLE)
    list(APPEND IPC_SENDER_LIBS rt)
endif()

if(ENABLE_COVERAGE AND COVERAGE_LIBS)
    list(APPEND IPC_SENDER_LIBS ${COVERAGE_LIBS})
endif()

target_link_libraries(ipc_sender PRIVATE ${IPC_SENDER_LIBS})
