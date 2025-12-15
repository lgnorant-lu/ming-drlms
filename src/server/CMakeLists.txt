set(SERVER_SOURCES
    log_collector_main.c
    c_logging.c
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
    mp2_room_members.c
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
    mp2_e2ee.c
    e2ee_signal.c
    sqlite_e2ee.c
    # Phase 26: Redis ae.c-style event loop (Asymmetric Reactor)
    net_reactor.c
    server_core_reactor.c
    # Phase 26 Task D: Buffer management and non-blocking I/O
    connection.c
)

# Phase 26: Platform-specific event loop backends
if(UNIX AND NOT APPLE)
    # Linux: use epoll
    list(APPEND SERVER_SOURCES net_epoll.c)
    message(STATUS "Using epoll backend for event loop")
elseif(WIN32)
    # Windows: use select (IOCP would require Proactor pattern change)
    list(APPEND SERVER_SOURCES net_select.c)
    message(STATUS "Using select backend for event loop")
else()
    # macOS/other: use select as fallback (could add kqueue later)
    list(APPEND SERVER_SOURCES net_select.c)
    message(STATUS "Using select backend for event loop (fallback)")
endif()



# --- Enhanced Protobuf-C detection and fallback ---
# Include the new ProtobufFetch module
include(${CMAKE_SOURCE_DIR}/cmake/ProtobufFetch.cmake)
include(${CMAKE_SOURCE_DIR}/cmake/SignalFetch.cmake)
include(${CMAKE_SOURCE_DIR}/cmake/EnsureProtocVersion.cmake)

if(PROTOBUF_C_USE_BUNDLED_RUNTIME AND NOT PROTOBUF_C_USE_PREGENSETS)
    # Force disable bundled runtime to avoid conflict with system protoc-c
    message(STATUS "Disabling bundled protobuf-c runtime to prevent ABI mismatch")
endif()

# --- Protobuf-C code generation (Phase 1) ---
find_program(PROTOC_C_EXECUTABLE protoc-c)
drlms_require_protoc(PROTOC_EXECUTABLE)
if(NOT PROTOC_EXECUTABLE)
    message(FATAL_ERROR "Failed to locate protoc ${DRLMS_PROTOC_VERSION}")
endif()
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
    ${PROTO_DIR}/e2ee.proto
)

message(STATUS "PROTO_FILES=${PROTO_FILES}")

set(GENERATED_SRC)
set(GENERATED_HDR)
set(GENERATED_PY)

# Force use pre-generated sets to prevent version mismatch with bundled runtime
# set(PROTOBUF_C_USE_PREGENSETS TRUE)

# Prefer dynamic generation whenever protoc-c is available; only fall back to
# pre-generated sets when we do not have a working protoc-c.
if(PROTOBUF_C_USE_PREGENSETS AND NOT PROTOC_C_EXECUTABLE)
    # Manually populate GENERATED_SRC because PROTOBUF_C_SOURCES might be incomplete
    set(GENERATED_SRC)
    set(GENERATED_HDR)
    
    # Determine where the pre-generated files are (src/generated/schema/v2)
    set(PRE_GEN_DIR ${PROJECT_SOURCE_DIR}/src/generated/schema/v2)
    
    foreach(PF ${PROTO_FILES})
        get_filename_component(PBN ${PF} NAME_WE)
        list(APPEND GENERATED_SRC ${PRE_GEN_DIR}/${PBN}.pb-c.c)
        list(APPEND GENERATED_HDR ${PRE_GEN_DIR}/${PBN}.pb-c.h)
    endforeach()
    
    list(APPEND SERVER_SOURCES mp2_rooms_sub_pub.c)
    source_group("generated" FILES ${GENERATED_SRC} ${GENERATED_HDR})
    
    # Ensure include paths are correct for pre-generated files
    list(APPEND PROTOBUF_C_INCLUDE_DIRS 
        ${PROJECT_SOURCE_DIR}/src/generated
        ${PROJECT_SOURCE_DIR}/src/generated/schema/v2)
else()
        if(PROTOC_C_EXECUTABLE)
            foreach(PF ${PROTO_FILES})
                get_filename_component(PBN ${PF} NAME_WE)
                set(REL_SUBDIR schema/v2)
                set(OUT_DIR ${GENERATED_DIR}/${REL_SUBDIR})
                set(OUT_C ${OUT_DIR}/${PBN}.pb-c.c)
                set(OUT_H ${OUT_DIR}/${PBN}.pb-c.h)
                set(OUT_PY ${OUT_DIR}/${PBN}_pb2.py)
                if(WIN32)
                    add_custom_command(
                        OUTPUT ${OUT_C} ${OUT_H} ${OUT_PY}
                        COMMAND ${CMAKE_COMMAND} -E echo "[proto_gen] ${PF} -> ${OUT_C}"
                        COMMAND ${CMAKE_COMMAND} -E make_directory ${OUT_DIR}
                        COMMAND ${PROTOC_EXECUTABLE} --plugin=protoc-gen-c=${PROTOC_C_EXECUTABLE} --proto_path=${PROJECT_SOURCE_DIR} --proto_path=${PROJECT_SOURCE_DIR}/schema/v2 --c_out=${GENERATED_DIR} --python_out=${GENERATED_DIR} ${PF}
                        DEPENDS ${PF}
                        VERBATIM
                        COMMENT "Generating protobuf-c and python sources for ${PBN} (Windows plugin mode)"
                    )
                else()
                    add_custom_command(
                        OUTPUT ${OUT_C} ${OUT_H} ${OUT_PY}
                        COMMAND ${CMAKE_COMMAND} -E echo "[proto_gen] ${PF} -> ${OUT_C}"
                        COMMAND ${CMAKE_COMMAND} -E make_directory ${OUT_DIR}
                        COMMAND ${PROTOC_C_EXECUTABLE} --proto_path=${PROJECT_SOURCE_DIR} --proto_path=${PROJECT_SOURCE_DIR}/schema/v2 --c_out=${GENERATED_DIR} ${PF}
                        COMMAND ${PROTOC_EXECUTABLE} --proto_path=${PROJECT_SOURCE_DIR} --proto_path=${PROJECT_SOURCE_DIR}/schema/v2 --python_out=${GENERATED_DIR} ${PF}
                        DEPENDS ${PF}
                        VERBATIM
                        COMMENT "Generating protobuf-c (protoc-c CLI) and python sources for ${PBN}"
                    )
                endif()
                list(APPEND GENERATED_SRC ${OUT_C})
                list(APPEND GENERATED_HDR ${OUT_H})
                list(APPEND GENERATED_PY ${OUT_PY})
            endforeach()
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
            list(APPEND SERVER_SOURCES mp2_rooms_sub_pub.c)
            source_group("generated" FILES ${GENERATED_SRC} ${GENERATED_HDR})
            
            # 修复CI环境下的include路径问题
            # 当使用预生成文件时，需要将预生成目录加入include路径
            list(APPEND PROTOBUF_C_INCLUDE_DIRS 
                ${PROJECT_SOURCE_DIR}/src/generated
                ${PROJECT_SOURCE_DIR}/src/generated/schema/v2)
            set(PROTOBUF_C_USE_PREGENSETS TRUE)
        else()
            message(FATAL_ERROR "No pre-generated protobuf-c sources found at ${PRE_GEN_DIR}. Build cannot proceed.")
        endif()
    endif()
endif()

message(STATUS "Final GENERATED_SRC: ${GENERATED_SRC}")

# Create a static library for the generated protobuf sources and runtime
add_library(protobuf_generated_lib STATIC
    ${GENERATED_SRC}
    ${PROJECT_SOURCE_DIR}/src/external/protobuf-c/protobuf-c.c
)

# Set compile options for the library (same as executable to match runtime library)
if(MSVC)
    target_compile_options(protobuf_generated_lib PRIVATE /W0 /MD)
else()
    target_compile_options(protobuf_generated_lib PRIVATE -w)
endif()

target_include_directories(protobuf_generated_lib PRIVATE
    ${PROJECT_SOURCE_DIR}/src/external/protobuf-c/include
    ${PROJECT_SOURCE_DIR}/src/external/protobuf-c
    ${GENERATED_DIR}
    ${PROJECT_SOURCE_DIR}/src/generated
    ${PROTOBUF_C_INCLUDE_DIRS}
)

add_executable(log_collector_server ${SERVER_SOURCES})
target_link_libraries(log_collector_server PRIVATE protobuf_generated_lib)

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
        ${PROJECT_SOURCE_DIR}
        ${CMAKE_CURRENT_BINARY_DIR}
        ${GENERATED_DIR}
        ${PROJECT_SOURCE_DIR}/src/generated
    ${PROJECT_SOURCE_DIR}/src/external/protobuf-c/include
    ${PROJECT_SOURCE_DIR}/src/external/protobuf-c
        ${ARGON2_INCLUDE_DIRS}
    ${PROTOBUF_C_INCLUDE_DIRS}
    # Phase 15.5: Signal Protocol headers for XEdDSA verification
    ${SIGNAL_INSTALL_PREFIX}/include
)

set(SERVER_LIBS
    ipc_static
    Threads::Threads
    OpenSSL::Crypto
    platform
    Signal::protocol
)

if(TARGET argon2_dummy)
    list(APPEND SERVER_LIBS argon2_dummy)
elseif(ARGON2_LIBRARIES)
    list(APPEND SERVER_LIBS ${ARGON2_LIBRARIES})
endif()

if(HAVE_SYSTEM_SQLITE3)
    list(APPEND SERVER_LIBS SQLite::SQLite3)
elseif(TARGET unofficial::sqlite3::sqlite3)
    list(APPEND SERVER_LIBS unofficial::sqlite3::sqlite3)
elseif(TARGET sqlite3_dummy)
    list(APPEND SERVER_LIBS sqlite3_dummy)
else()
    message(WARNING "No SQLite3 library available - SQLite functionality will be disabled")
endif()

if(UNIX AND NOT APPLE)
    list(APPEND SERVER_LIBS rt m)
endif()

if(WIN32)
    list(APPEND SERVER_LIBS ws2_32 bcrypt)
endif()

# Enhanced protobuf-c linking with fallback support
if(PROTOBUF_C_FOUND)
    if(PROTOBUF_C_LIBRARIES)
        # list(APPEND SERVER_LIBS ${PROTOBUF_C_LIBRARIES})
        # message(STATUS "Linking protobuf-c libraries: ${PROTOBUF_C_LIBRARIES}")
    endif()
endif()

if(ENABLE_COVERAGE AND COVERAGE_LIBS)
    list(APPEND SERVER_LIBS ${COVERAGE_LIBS})
endif()

# Set RPATH for Signal Protocol library
if(APPLE)
    set_target_properties(log_collector_server PROPERTIES
        BUILD_WITH_INSTALL_RPATH TRUE
        INSTALL_RPATH "@executable_path/../lib;@executable_path/../../_deps/signal-install/lib"
        INSTALL_RPATH_USE_LINK_PATH TRUE
    )
elseif(UNIX)
    set_target_properties(log_collector_server PROPERTIES
        BUILD_WITH_INSTALL_RPATH TRUE
        INSTALL_RPATH "$ORIGIN/../lib:$ORIGIN/../../_deps/signal-install/lib"
        INSTALL_RPATH_USE_LINK_PATH TRUE
    )
endif()

target_link_libraries(log_collector_server PRIVATE ${SERVER_LIBS})

# --- Windows Long-Term Fix: Build drlms_signal_bridge.dll ---
if(WIN32)
    message(STATUS "Configuring drlms_signal_bridge DLL for Python client...")
    add_library(drlms_signal_bridge SHARED
        ${PROJECT_SOURCE_DIR}/src/ming_drlms/core/_pysignal_runtime.c
    )
    
    # Use the same include directories as server, mainly for Signal/OpenSSL headers
    target_include_directories(drlms_signal_bridge PRIVATE
        ${PROJECT_SOURCE_DIR}/src
        ${PROJECT_SOURCE_DIR}/src/server
        ${PROJECT_SOURCE_DIR}/src/platform/include
    )
    # Link against Signal Protocol and OpenSSL
    target_link_libraries(drlms_signal_bridge PRIVATE
        Signal::protocol
        OpenSSL::Crypto
    )
    # Build and embed the C logging backend into this DLL so LOG_DEBUG works
    target_sources(drlms_signal_bridge PRIVATE
        ${PROJECT_SOURCE_DIR}/src/server/c_logging.c
    )

    # Compile XEdDSA stubs/implementation into the bridge (future real impl)
    target_sources(drlms_signal_bridge PRIVATE
        ${PROJECT_SOURCE_DIR}/src/ming_drlms/core/drlms_xeddsa.c
    )
    
    # Ensure DLL is output to the same directory as the server executable for easy finding
    set_target_properties(drlms_signal_bridge PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/Release
    )
    
    # Export all non-static symbols from the DLL on Windows so CFFI can resolve drlms_* APIs
    set_target_properties(drlms_signal_bridge PROPERTIES
        WINDOWS_EXPORT_ALL_SYMBOLS ON
    )
    
    # On multi-config generators (like MSVC), the actual DLL will be placed in
    # a configuration subdirectory (e.g. ${CMAKE_BINARY_DIR}/Release/Release).
    # Python code expects to find drlms_signal_bridge.dll in build_win/Release,
    # so we add a POST_BUILD step to copy it there.
    add_custom_command(TARGET drlms_signal_bridge POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<TARGET_FILE:drlms_signal_bridge>"
            "${CMAKE_BINARY_DIR}/Release/drlms_signal_bridge.dll"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<TARGET_FILE:drlms_signal_bridge>"
            "${SIGNAL_INSTALL_PREFIX}/bin/drlms_signal_bridge.dll"
        COMMENT "Copying drlms_signal_bridge.dll to top-level Release directory"
    )
    
    message(STATUS "drlms_signal_bridge target added.")

    # --- Windows Long-Term Fix: Auto-copy ONLY essential dependencies ---
    
    # 1. Copy signal-protocol-c.dll from the correct location (_deps/signal-install/bin)
    # Note: Don't use EXISTS check here - it runs at configure time before the DLL is built
    set(_sig_dll_source "${CMAKE_BINARY_DIR}/_deps/signal-install/bin/signal-protocol-c.dll")
    add_custom_command(TARGET log_collector_server POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${_sig_dll_source}"
            "$<TARGET_FILE_DIR:log_collector_server>/signal-protocol-c.dll"
        COMMENT "Copying signal-protocol-c.dll from ${_sig_dll_source}"
    )

    # 2. Copy ONLY essential OpenSSL 3.x DLLs (libcrypto-3-x64.dll and libssl-3-x64.dll)
    # Avoid copying legacy 1.1 versions, test/provider DLLs to prevent DLL Hell
    set(_ssl_root "")
    
    # Find OpenSSL root from OPENSSL_INCLUDE_DIR
    if(OPENSSL_INCLUDE_DIR)
        get_filename_component(_ssl_root "${OPENSSL_INCLUDE_DIR}" DIRECTORY)
    endif()
    
    if(_ssl_root AND EXISTS "${_ssl_root}/bin")
        # Only copy the two essential DLLs, explicitly by name
        set(_essential_ssl_dlls 
            "${_ssl_root}/bin/libcrypto-3-x64.dll"
            "${_ssl_root}/bin/libssl-3-x64.dll"
        )
        
        foreach(_dll ${_essential_ssl_dlls})
            if(EXISTS "${_dll}")
                get_filename_component(_dll_name "${_dll}" NAME)
                add_custom_command(TARGET log_collector_server POST_BUILD
                    COMMAND ${CMAKE_COMMAND} -E copy_if_different
                        "${_dll}"
                        "$<TARGET_FILE_DIR:log_collector_server>/${_dll_name}"
                    COMMENT "Copying OpenSSL: ${_dll_name}"
                )
            endif()
        endforeach()
    else()
        message(WARNING "OpenSSL installation not found. Ensure C:/Program Files/OpenSSL-Win64/bin is in your PATH.")
    endif()
endif()

# --- Linux/macOS: Build libdrlms_signal_bridge.so ---
if(NOT WIN32)
    message(STATUS "Configuring drlms_signal_bridge shared library for Python client (Linux/macOS)...")
    add_library(drlms_signal_bridge SHARED
        ${PROJECT_SOURCE_DIR}/src/ming_drlms/core/_pysignal_runtime.c
        ${PROJECT_SOURCE_DIR}/src/ming_drlms/core/drlms_xeddsa.c
        ${PROJECT_SOURCE_DIR}/src/server/c_logging.c
    )
    
    target_include_directories(drlms_signal_bridge PRIVATE
        ${PROJECT_SOURCE_DIR}/src
        ${PROJECT_SOURCE_DIR}/src/server
        ${PROJECT_SOURCE_DIR}/src/platform/include
    )
    
    target_link_libraries(drlms_signal_bridge PRIVATE
        Signal::protocol
        OpenSSL::Crypto
    )
    
    # Output to signal-install/lib for easy discovery by Python
    set_target_properties(drlms_signal_bridge PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY ${SIGNAL_INSTALL_PREFIX}/lib
        INSTALL_RPATH "$ORIGIN"
    )
    
    # Also copy to build root for convenience
    add_custom_command(TARGET drlms_signal_bridge POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<TARGET_FILE:drlms_signal_bridge>"
            "${CMAKE_BINARY_DIR}/libdrlms_signal_bridge.so"
        COMMENT "Copying libdrlms_signal_bridge.so to build root"
    )
    
    message(STATUS "drlms_signal_bridge target added for Linux/macOS.")
endif()

# Add build info logging
if(PROTOC_C_EXECUTABLE AND NOT PROTOBUF_C_USE_PREGENSETS AND GENERATED_SRC)
    add_custom_target(proto_gen DEPENDS ${GENERATED_SRC} ${GENERATED_HDR} ${GENERATED_PY})
    add_dependencies(log_collector_server proto_gen)
    set(_PROTO_PY_BASE_DIRS
        "${GENERATED_DIR}/schema/v2"
        "${GENERATED_DIR}/schema/v2/v2"
    )
    set(_PROTO_PY_BASE_DIRS_FILE "${CMAKE_CURRENT_BINARY_DIR}/proto_py_base_dirs.txt")
    file(WRITE ${_PROTO_PY_BASE_DIRS_FILE} "")
    foreach(_dir IN LISTS _PROTO_PY_BASE_DIRS)
        file(APPEND ${_PROTO_PY_BASE_DIRS_FILE} "${_dir}\n")
    endforeach()
    add_custom_command(TARGET proto_gen POST_BUILD
        COMMAND ${CMAKE_COMMAND} -DPROTO_PY_BASE_DIR_FILE=${_PROTO_PY_BASE_DIRS_FILE} -DPROTO_PY_FILENAME=common_pb2.py -DPROTO_PY_DEST_DIR=${CMAKE_SOURCE_DIR}/src/ming_drlms/proto/schema/v2 -P ${CMAKE_SOURCE_DIR}/cmake/CopyGeneratedProtoPy.cmake
        COMMAND ${CMAKE_COMMAND} -DPROTO_PY_BASE_DIR_FILE=${_PROTO_PY_BASE_DIRS_FILE} -DPROTO_PY_FILENAME=room_pb2.py -DPROTO_PY_DEST_DIR=${CMAKE_SOURCE_DIR}/src/ming_drlms/proto/schema/v2 -P ${CMAKE_SOURCE_DIR}/cmake/CopyGeneratedProtoPy.cmake
        COMMAND ${CMAKE_COMMAND} -DPROTO_PY_BASE_DIR_FILE=${_PROTO_PY_BASE_DIRS_FILE} -DPROTO_PY_FILENAME=e2ee_pb2.py -DPROTO_PY_DEST_DIR=${CMAKE_SOURCE_DIR}/src/ming_drlms/proto/schema/v2 -P ${CMAKE_SOURCE_DIR}/cmake/CopyGeneratedProtoPy.cmake
        COMMAND ${CMAKE_COMMAND} -DPROTO_PY_BASE_DIR_FILE=${_PROTO_PY_BASE_DIRS_FILE} -DPROTO_PY_FILENAME=auth_pb2.py -DPROTO_PY_DEST_DIR=${CMAKE_SOURCE_DIR}/src/ming_drlms/proto/schema/v2 -P ${CMAKE_SOURCE_DIR}/cmake/CopyGeneratedProtoPy.cmake
        COMMAND ${CMAKE_COMMAND} -DPROTO_PY_BASE_DIR_FILE=${_PROTO_PY_BASE_DIRS_FILE} -DPROTO_PY_FILENAME=federation_pb2.py -DPROTO_PY_DEST_DIR=${CMAKE_SOURCE_DIR}/src/ming_drlms/proto/schema/v2 -P ${CMAKE_SOURCE_DIR}/cmake/CopyGeneratedProtoPy.cmake
        COMMENT "Copying generated Python protobuf files to client directory"
    )
endif()

message(STATUS "Server build configuration summary:")
message(STATUS "  protobuf-c found: ${PROTOBUF_C_FOUND}")
message(STATUS "  Detection method: ${PROTOBUF_C_DETECTION_METHOD}")
message(STATUS "  Include directories: ${PROTOBUF_C_INCLUDE_DIRS}")
message(STATUS "  Library files: ${PROTOBUF_C_LIBRARIES}")
