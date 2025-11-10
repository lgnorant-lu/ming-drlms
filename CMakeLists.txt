cmake_minimum_required(VERSION 3.18)
project(ming_drlms C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(WIN32)
    add_compile_definitions(_WIN32_WINNT=0x0601 WIN32_LEAN_AND_MEAN NOMINMAX)
endif()

include(CTest)

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})

option(ENABLE_TESTS "Build C-based test binaries" ON)
option(BUILD_SERVER "Build server and its dependencies" ON)
option(ENABLE_COVERAGE "Enable coverage instrumentation" OFF)

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")

set(COVERAGE_LIBS "")
if(ENABLE_COVERAGE)
    if(MSVC)
        message(STATUS "Coverage instrumentation is not supported with MSVC; skipping coverage flags.")
    else()
        add_compile_options(--coverage)
        add_link_options(--coverage)

        if(CMAKE_C_COMPILER_ID STREQUAL "GNU")
            list(APPEND COVERAGE_LIBS gcov)
        elseif(CMAKE_C_COMPILER_ID STREQUAL "Clang" AND NOT APPLE)
            # Some non-Apple Clang toolchains still provide libgcov compatibility.
            list(APPEND COVERAGE_LIBS gcov)
        endif()
    endif()
endif()
set(COVERAGE_LIBS "${COVERAGE_LIBS}" CACHE INTERNAL "Coverage runtime libraries" FORCE)

if(MSVC)
    add_compile_options(/utf-8 /W4 /WX /wd4996)
else()
    add_compile_options(-Wall -Wextra -Werror -Wno-deprecated-declarations)
endif()

find_package(Threads REQUIRED)
find_package(OpenSSL REQUIRED)

# If we are building only the Signal spike tool, skip server deps by default
if(DEFINED ENABLE_SIGNAL_SPIKE AND ENABLE_SIGNAL_SPIKE)
    set(BUILD_SERVER OFF CACHE BOOL "Build server and its dependencies" FORCE)
endif()

if(BUILD_SERVER)
    find_package(Argon2 REQUIRED)
endif()

if(BUILD_SERVER)
    # Prefer system SQLite3 when available; fall back to vcpkg's unofficial-sqlite3
    set(HAVE_SYSTEM_SQLITE3 0)
    find_package(SQLite3 QUIET)
    if(SQLite3_FOUND)
        message(STATUS "Found system SQLite3: ${SQLite3_VERSION}")
        set(HAVE_SYSTEM_SQLITE3 1)
    else()
        find_package(unofficial-sqlite3 CONFIG REQUIRED)
    endif()
endif()

if(BUILD_SERVER)
    # Protobuf-C (for protoc-c generated C stubs)
    find_package(PkgConfig QUIET)
    if(PKG_CONFIG_FOUND)
        pkg_check_modules(PROTOBUF_C QUIET libprotobuf-c)
    endif()
    if(NOT PROTOBUF_C_FOUND)
        # Fallback: try to link by name; some distros don't provide pkg-config files
        find_library(PROTOBUF_C_LIBRARY NAMES protobuf-c)
        if(PROTOBUF_C_LIBRARY)
            set(PROTOBUF_C_LIBRARIES ${PROTOBUF_C_LIBRARY})
            set(PROTOBUF_C_FOUND TRUE)
            message(STATUS "Found protobuf-c library (fallback): ${PROTOBUF_C_LIBRARY}")
        endif()
    endif()

    if(PROTOBUF_C_FOUND)
        message(STATUS "Found protobuf-c via pkg-config: ${PROTOBUF_C_VERSION}")
        add_compile_definitions(HAVE_PROTOBUF_C=1)
    endif()
endif()

add_subdirectory(src/platform)
add_subdirectory(src/libipc)
if(BUILD_SERVER)
    add_subdirectory(src/server)
    add_subdirectory(src/agent)
endif()
add_subdirectory(src/tools)

if(ENABLE_TESTS AND BUILD_SERVER)
    add_subdirectory(tests)
endif()

# Convenience target that mirrors the legacy Makefile coverage workflow.
add_custom_target(coverage
    COMMAND ${CMAKE_COMMAND} -E env PROJECT_ROOT=${CMAKE_SOURCE_DIR} ${CMAKE_SOURCE_DIR}/scripts/run_coverage.sh
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
    COMMENT "Generating combined C/Python coverage report" )
