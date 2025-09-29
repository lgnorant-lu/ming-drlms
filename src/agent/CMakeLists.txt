add_executable(log_agent log_agent.c)

target_include_directories(log_agent
    PRIVATE
        ${PROJECT_SOURCE_DIR}/src/platform/include
)

set(LOG_AGENT_LIBS
    OpenSSL::Crypto
    Threads::Threads
    platform
)

if(ENABLE_COVERAGE AND COVERAGE_LIBS)
    list(APPEND LOG_AGENT_LIBS ${COVERAGE_LIBS})
endif()

target_link_libraries(log_agent PRIVATE ${LOG_AGENT_LIBS})
