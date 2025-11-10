set(SERVER_SOURCES
    log_collector_main.c
    server_core.c
    time_utils.c
    fs_safety.c
    audit_log.c
    mp2_auth.c
    mp2_dispatcher.c
    mp2_protocol.c
    mp2_rooms_common.c
    mp2_rooms_history.c
    mp2_rooms_files.c
    mp2_rooms.c
    server_users.c
    rooms_utils.c
    rooms_social.c
    rooms_instance.c
    rooms_events.c
    rooms_history.c
    rooms_gc.c
    rooms_state.c
    rooms_sqlite_bridge.c
    rooms.c
    sqlite_utils.c
    sqlite_schema.c
    sqlite_events.c
    sqlite_rooms.c
    sqlite_social.c
    poetic_name.c
    federation.c
    federation_transport.c
    federation_registry.c
    federation_publish.c
)

# --- Enhanced Protobuf-C detection and fallback ---
# Include the new ProtobufFetch module
include(${CMAKE_SOURCE_DIR}/cmake/ProtobufFetch.cmake)

# --- Protobuf-C code generation (Phase 1) ---
find_program(PROTOC_C_EXECUTABLE protoc-c)
set(PROTO_DIR ${PROJECT_SOURCE_DIR}/schema/v2)
# Generate into the current binary dir to avoid source dir path issues
set(GENERATED_DIR ${CMAKE_CURRENT_BINARY_DIR}/generated)
file(MAKE_DIRECTORY ${GENERATED_DIR})
message(STATUS "PROTO_DIR=${PROTO_DIR}")
message(STATUS "GENERATED_DIR=${GENERATED_DIR}")

set(PROTO_FILES
    ${PROTO_DIR}/common.proto
    ${PROTO_DIR}/auth.proto
    ${PROTO_DIR}/room.proto
    ${PROTO_DIR}/federation.proto
)

set(GENERATED_SRC)
set(GENERATED_HDR)

if(PROTOBUF_C_USE_PREGENSETS)
    set(GENERATED_SRC ${PROTOBUF_C_SOURCES})
    set(GENERATED_HDR ${PROTOBUF_C_HEADERS})
    list(APPEND SERVER_SOURCES ${GENERATED_SRC})
    list(APPEND SERVER_SOURCES mp2_rooms_sub_pub.c)
    source_group("generated" FILES ${GENERATED_SRC} ${GENERATED_HDR})
else()
    if(PROTOC_C_EXECUTABLE)
        foreach(PF ${PROTO_FILES})
            get_filename_component(PBN ${PF} NAME_WE)
            set(REL_SUBDIR schema/v2)
            set(OUT_DIR ${GENERATED_DIR}/${REL_SUBDIR})
            set(OUT_C ${OUT_DIR}/${PBN}.pb-c.c)
            set(OUT_H ${OUT_DIR}/${PBN}.pb-c.h)
            add_custom_command(
                OUTPUT ${OUT_C} ${OUT_H}
                COMMAND ${CMAKE_COMMAND} -E echo "[proto_gen] ${PF} -> ${OUT_C}"
                COMMAND ${CMAKE_COMMAND} -E make_directory ${OUT_DIR}
                COMMAND ${PROTOC_C_EXECUTABLE} --c_out=${GENERATED_DIR} -I${PROJECT_SOURCE_DIR} -I${PROTO_DIR} ${PF}
                DEPENDS ${PF}
                BYPRODUCTS ${OUT_C} ${OUT_H}
                VERBATIM
                COMMENT "Generating protobuf-c sources for ${PBN}"
            )
            list(APPEND GENERATED_SRC ${OUT_C})
            list(APPEND GENERATED_HDR ${OUT_H})
        endforeach()
        list(APPEND SERVER_SOURCES ${GENERATED_SRC})
        list(APPEND SERVER_SOURCES mp2_rooms_sub_pub.c)
        source_group("generated" FILES ${GENERATED_SRC} ${GENERATED_HDR})
    else()
        message(WARNING "protoc-c not found; falling back to bundled pre-generated protobuf sources")
        set(PRE_GEN_DIR ${PROJECT_SOURCE_DIR}/src/generated/schema/v2)
        if(EXISTS "${PRE_GEN_DIR}/common.pb-c.c")
            foreach(PF ${PROTO_FILES})
                get_filename_component(PBN ${PF} NAME_WE)
                list(APPEND GENERATED_SRC ${PRE_GEN_DIR}/${PBN}.pb-c.c)
                list(APPEND GENERATED_HDR ${PRE_GEN_DIR}/${PBN}.pb-c.h)
            endforeach()
            list(APPEND SERVER_SOURCES ${GENERATED_SRC})
            list(APPEND SERVER_SOURCES mp2_rooms_sub_pub.c)
            source_group("generated" FILES ${GENERATED_SRC} ${GENERATED_HDR})
        else()
            message(FATAL_ERROR "No pre-generated protobuf-c sources found at ${PRE_GEN_DIR}. Build cannot proceed.")
        endif()
    endif()
endif()

add_executable(log_collector_server ${SERVER_SOURCES})

# 抑制protobuf-c编译警告，避免警告被当作错误
if(MSVC)
    # 完全关闭警告
    target_compile_options(log_collector_server PRIVATE /W0)
    # 或者只抑制特定警告但不关闭所有警告
    target_compile_options(log_collector_server PRIVATE
        /wd4146
        /wd4267
        /wd4244
        /wd4221
        /wd4054
        /wd4055
        /wd4100
        /wd4127
        /wd4702
        /wd4706
        /wd4709
        /wd4710
        /wd4711
        /wd4996
    )
else()
    target_compile_options(log_collector_server PRIVATE
        -w
    )
endif()

# 设置编译特性来降低警告严格度
set_target_properties(log_collector_server PROPERTIES
    C_STANDARD 11
    C_STANDARD_REQUIRED ON
    C_EXTENSIONS ON
)

target_include_directories(log_collector_server
    PRIVATE
        ${PROJECT_SOURCE_DIR}/src/libipc
        ${PROJECT_SOURCE_DIR}/src/platform/include
        ${PROJECT_SOURCE_DIR}/src
        ${CMAKE_CURRENT_BINARY_DIR}
        ${GENERATED_DIR}
        ${ARGON2_INCLUDE_DIRS}
        ${PROTOBUF_C_INCLUDE_DIRS}
)

set(SERVER_LIBS
    ipc_static
    Threads::Threads
    ${ARGON2_LIBRARIES}
    OpenSSL::Crypto
    platform
)

if(HAVE_SYSTEM_SQLITE3)
    list(APPEND SERVER_LIBS SQLite::SQLite3)
else()
    list(APPEND SERVER_LIBS unofficial::sqlite3::sqlite3)
endif()

if(UNIX AND NOT APPLE)
    list(APPEND SERVER_LIBS rt)
endif()

if(WIN32)
    list(APPEND SERVER_LIBS ws2_32 bcrypt)
endif()

# Enhanced protobuf-c linking with fallback support
if(PROTOBUF_C_FOUND)
    if(PROTOBUF_C_LIBRARIES)
        list(APPEND SERVER_LIBS ${PROTOBUF_C_LIBRARIES})
        message(STATUS "Linking protobuf-c libraries: ${PROTOBUF_C_LIBRARIES}")
    endif()
endif()

if(ENABLE_COVERAGE AND COVERAGE_LIBS)
    list(APPEND SERVER_LIBS ${COVERAGE_LIBS})
endif()

target_link_libraries(log_collector_server PRIVATE ${SERVER_LIBS})

# Add build info logging
if(PROTOC_C_EXECUTABLE AND NOT PROTOBUF_C_USE_PREGENSETS AND GENERATED_SRC)
    add_custom_target(proto_gen DEPENDS ${GENERATED_SRC} ${GENERATED_HDR})
    add_dependencies(log_collector_server proto_gen)
endif()

message(STATUS "Server build configuration summary:")
message(STATUS "  protobuf-c found: ${PROTOBUF_C_FOUND}")
message(STATUS "  Detection method: ${PROTOBUF_C_DETECTION_METHOD}")
message(STATUS "  Include directories: ${PROTOBUF_C_INCLUDE_DIRS}")
message(STATUS "  Library files: ${PROTOBUF_C_LIBRARIES}")
