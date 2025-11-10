if(NOT WIN32)
    add_executable(proc_launcher proc_launcher.c)

    target_include_directories(proc_launcher PRIVATE
        ${PROJECT_SOURCE_DIR}/src/platform/include)

    target_link_libraries(proc_launcher PRIVATE platform Threads::Threads)
endif()

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

# ------------------------------------------------------------
# E2EE Spike (libsignal-protocol-c) - isolated PoC target
# ------------------------------------------------------------
option(ENABLE_SIGNAL_SPIKE "Build Signal Protocol spike (libsignal-protocol-c)" OFF)
if(ENABLE_SIGNAL_SPIKE)
    include(${PROJECT_SOURCE_DIR}/cmake/SignalFetch.cmake)

    # Add the executable
    add_executable(test_signal_spike test_signal_spike.c)

    # Set include directories and linking
    target_include_directories(test_signal_spike PRIVATE ${PROJECT_SOURCE_DIR}/src)

    find_package(OpenSSL REQUIRED)
    target_link_libraries(test_signal_spike PRIVATE
        Signal::protocol
        OpenSSL::Crypto
    )

    # Add math library link for Linux to resolve ceil() function from libsignal-protocol-c
    if(UNIX)
        target_link_libraries(test_signal_spike PRIVATE m)
    endif()
endif()
