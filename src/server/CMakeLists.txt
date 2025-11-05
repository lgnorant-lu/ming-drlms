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
    mp2_rooms_sub_pub.c
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
if(PROTOC_C_EXECUTABLE)
    foreach(PF ${PROTO_FILES})
        get_filename_component(PBN ${PF} NAME_WE)
        # protoc-c preserves include-root relative path when -I points to project root,
        # so outputs land under generated/schema/v2/*.pb-c.c
        set(REL_SUBDIR schema/v2)
        set(OUT_C ${GENERATED_DIR}/${REL_SUBDIR}/${PBN}.pb-c.c)
        set(OUT_H ${GENERATED_DIR}/${REL_SUBDIR}/${PBN}.pb-c.h)
        add_custom_command(
            OUTPUT ${OUT_C} ${OUT_H}
            COMMAND ${CMAKE_COMMAND} -E echo "[proto_gen] ${PF} -> ${OUT_C}"
            COMMAND ${CMAKE_COMMAND} -E make_directory ${GENERATED_DIR}/${REL_SUBDIR}
            COMMAND ${PROTOC_C_EXECUTABLE} --c_out=${GENERATED_DIR} -I${PROJECT_SOURCE_DIR} -I${PROTO_DIR} ${PF}
            DEPENDS ${PF}
            BYPRODUCTS ${OUT_C} ${OUT_H}
            VERBATIM
            COMMENT "Generating protobuf-c sources for ${PBN}"
        )
        list(APPEND GENERATED_SRC ${OUT_C})
        list(APPEND GENERATED_HDR ${OUT_H})
    endforeach()
else()
    message(WARNING "protoc-c not found; using pre-generated sources from src/generated")
    foreach(PF ${PROTO_FILES})
        get_filename_component(PBN ${PF} NAME_WE)
        # Use pre-generated files from src/generated
        set(PRE_GEN_DIR ${PROJECT_SOURCE_DIR}/src/generated/schema/v2)
        set(OUT_C ${PRE_GEN_DIR}/${PBN}.pb-c.c)
        set(OUT_H ${PRE_GEN_DIR}/${PBN}.pb-c.h)
        list(APPEND GENERATED_SRC ${OUT_C})
        list(APPEND GENERATED_HDR ${OUT_H})
    endforeach()
endif()

list(APPEND SERVER_SOURCES ${GENERATED_SRC})
source_group("generated" FILES ${GENERATED_SRC} ${GENERATED_HDR})

add_executable(log_collector_server ${SERVER_SOURCES})

target_include_directories(log_collector_server
    PRIVATE
        ${PROJECT_SOURCE_DIR}/src/libipc
        ${PROJECT_SOURCE_DIR}/src/platform/include
        ${PROJECT_SOURCE_DIR}/src/generated
        ${CMAKE_CURRENT_BINARY_DIR}
        ${ARGON2_INCLUDE_DIRS}
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

# Link protobuf-c if available
if(PROTOBUF_C_FOUND)
    list(APPEND SERVER_LIBS ${PROTOBUF_C_LIBRARIES})
elseif(DEFINED PROTOBUF_C_LIBRARIES)
    list(APPEND SERVER_LIBS ${PROTOBUF_C_LIBRARIES})
else()
    # Try best-effort link name; build may still succeed if unused in Phase 1
    list(APPEND SERVER_LIBS protobuf-c)
endif()

if(ENABLE_COVERAGE AND COVERAGE_LIBS)
    list(APPEND SERVER_LIBS ${COVERAGE_LIBS})
endif()

target_link_libraries(log_collector_server PRIVATE ${SERVER_LIBS})

add_custom_target(proto_gen DEPENDS ${GENERATED_SRC} ${GENERATED_HDR})
# Ensure generated files are built before compiling server sources
add_dependencies(log_collector_server proto_gen)
target_sources(log_collector_server PRIVATE ${GENERATED_SRC})
