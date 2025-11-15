cmake_minimum_required(VERSION 3.18)
set(CMAKE_TOOLCHAIN_FILE "" CACHE FILEPATH "" FORCE)
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
    find_package(Argon2 QUIET)
    if(NOT Argon2_FOUND)
        message(STATUS "Argon2 not found - enabling dummy implementation for CI compatibility")
        set(Argon2_FOUND TRUE)
        set(ARGON2_LIBRARIES "")
        set(ARGON2_INCLUDE_DIRS "")
        # Create dummy argon2.h
        set(_dummy_argon2_dir "${CMAKE_BINARY_DIR}/dummy_argon2")
        file(MAKE_DIRECTORY "${_dummy_argon2_dir}")
        file(WRITE "${_dummy_argon2_dir}/argon2.h" [=[
#ifndef ARGON2_H
#define ARGON2_H

// Dummy argon2.h for CI builds when library is not available
#include <stdint.h>
#include <stddef.h>

typedef enum Argon2_type { Argon2_d = 0, Argon2_i = 1, Argon2_id = 2 } argon2_type;
#define ARGON2_VERSION_NUMBER 0x10

typedef enum Argon2_error_codes {
    ARGON2_OK = 0,
    ARGON2_OUTPUT_PTR_NULL = 1,
    ARGON2_OUTPUT_TOO_SHORT = 2,
    ARGON2_OUTPUT_TOO_LONG = 3,
    ARGON2_PWD_TOO_SHORT = 4,
    ARGON2_PWD_TOO_LONG = 5,
    ARGON2_SALT_TOO_SHORT = 6,
    ARGON2_SALT_TOO_LONG = 7,
    ARGON2_AD_TOO_SHORT = 8,
    ARGON2_AD_TOO_LONG = 9,
    ARGON2_SECRET_TOO_SHORT = 10,
    ARGON2_SECRET_TOO_LONG = 11,
    ARGON2_TIME_TOO_SMALL = 12,
    ARGON2_TIME_TOO_BIG = 13,
    ARGON2_MEMORY_TOO_LITTLE = 14,
    ARGON2_MEMORY_TOO_MUCH = 15,
    ARGON2_LANES_TOO_FEW = 16,
    ARGON2_LANES_TOO_MANY = 17,
    ARGON2_PWD_PTR_MISMATCH = 18,
    ARGON2_SALT_PTR_MISMATCH = 19,
    ARGON2_SECRET_PTR_MISMATCH = 20,
    ARGON2_AD_PTR_MISMATCH = 21,
    ARGON2_MEMORY_ALLOCATION_ERROR = 22,
    ARGON2_FREE_MEMORY_CBK_NULL = 23,
    ARGON2_ALLOCATE_MEMORY_CBK_NULL = 24,
    ARGON2_INCORRECT_PARAMETER = 25,
    ARGON2_INCORRECT_TYPE = 26,
    ARGON2_OUT_PTR_MISMATCH = 27,
    ARGON2_THREADS_TOO_FEW = 28,
    ARGON2_THREADS_TOO_MANY = 29,
    ARGON2_MISSING_ARGS = 30,
    ARGON2_ENCODING_FAIL = 31,
    ARGON2_DECODING_FAIL = 32,
    ARGON2_THREAD_FAIL = 33,
    ARGON2_DECODING_LENGTH_FAIL = 34,
    ARGON2_VERIFY_MISMATCH = 35
} argon2_error_codes;

typedef struct Argon2_Context {
    uint8_t *out;
    uint32_t outlen;
    uint8_t *pwd;
    uint32_t pwdlen;
    uint8_t *salt;
    uint32_t saltlen;
    uint8_t *secret;
    uint32_t secretlen;
    uint8_t *ad;
    uint32_t adlen;
    uint32_t t_cost;
    uint32_t m_cost;
    uint32_t parallelism;
    uint32_t threads;
    argon2_type type;
    void *(*allocate_cbk)(size_t);
    void (*free_cbk)(void *p);
    uint32_t flags;
} argon2_context;

typedef struct Argon2_position_t {
    uint32_t pass;
    uint32_t lane;
    uint8_t slice;
    uint32_t index;
} argon2_position_t;

typedef int (*argon2_fill_segment_t)(const argon2_context *context, argon2_position_t position);

int argon2_hash(const uint32_t t_cost, const uint32_t m_cost,
                const uint32_t parallelism, const void *pwd,
                const size_t pwdlen, const void *salt, const size_t saltlen,
                void *hash, const size_t hashlen, char *encoded,
                const size_t encodedlen, argon2_type type,
                const uint32_t version);

int argon2_verify(const char *encoded, const void *pwd, const size_t pwdlen,
                  argon2_type type);

const char *argon2_error_message(int error_code);

#endif // ARGON2_H
]=])
        set(ARGON2_INCLUDE_DIRS "${_dummy_argon2_dir}")
    endif()
endif()

if(BUILD_SERVER)
    # Prefer system SQLite3 when available; fall back to vcpkg's unofficial-sqlite3
    set(HAVE_SYSTEM_SQLITE3 0)
    find_package(SQLite3 QUIET)
    if(SQLite3_FOUND)
        message(STATUS "Found system SQLite3: ${SQLite3_VERSION}")
        set(HAVE_SYSTEM_SQLITE3 1)
    else()
        find_package(unofficial-sqlite3 CONFIG QUIET)
        if(NOT unofficial-sqlite3_FOUND)
            message(STATUS "unofficial-sqlite3 not found - providing dummy SQLite headers for CI compatibility")
            # Create dummy sqlite3.h for CI builds
            set(_dummy_sqlite_dir "${CMAKE_BINARY_DIR}/dummy_sqlite")
            file(MAKE_DIRECTORY "${_dummy_sqlite_dir}")
            file(WRITE "${_dummy_sqlite_dir}/sqlite3.h" [=[
#ifndef SQLITE3_H
#define SQLITE3_H

#include <stdint.h>
#include <stddef.h>

// Dummy sqlite3.h for CI builds when SQLite is not available
// This allows compilation to proceed but will disable SQLite functionality

typedef struct sqlite3 sqlite3;
typedef struct sqlite3_stmt sqlite3_stmt;

typedef int (*sqlite3_callback)(void*,int,char**,char**);

// SQLite type definitions
typedef long long int sqlite3_int64;
typedef unsigned long long int sqlite3_uint64;

#define SQLITE_OK           0   /* Successful result */
#define SQLITE_ERROR        1   /* Generic error */
#define SQLITE_BUSY         5   /* The database file is locked */
#define SQLITE_ROW          100 /* sqlite3_step() has another row ready */
#define SQLITE_DONE         101 /* sqlite3_step() has finished executing */
#define SQLITE_TRANSIENT    ((void(*)(void*))-1)
#define SQLITE_STATIC       ((void(*)(void*))0)

int sqlite3_open(const char *filename, sqlite3 **ppDb);
int sqlite3_close(sqlite3 *db);
int sqlite3_exec(sqlite3*, const char *sql, sqlite3_callback, void*, char**);
int sqlite3_prepare_v2(sqlite3*, const char*, int, sqlite3_stmt**, const char**);
int sqlite3_step(sqlite3_stmt* pStmt);
int sqlite3_finalize(sqlite3_stmt* pStmt);
int sqlite3_bind_int(sqlite3_stmt*, int, int);
int sqlite3_bind_text(sqlite3_stmt*, int, const char*, int, void(*)(void*));
const char* sqlite3_errmsg(sqlite3*);

#endif // SQLITE3_H
]=])
            include_directories("${_dummy_sqlite_dir}")
            set(HAVE_SYSTEM_SQLITE3 0)
        endif()
    endif()
endif()

if(BUILD_SERVER)
    # Include enhanced Protobuf-C detection
    include(${CMAKE_SOURCE_DIR}/cmake/ProtobufFetch.cmake)

    if(PROTOBUF_C_FOUND)
        add_compile_definitions(HAVE_PROTOBUF_C=1)
        if(PROTOBUF_C_USE_PREGENSETS)
            message(STATUS "Using pre-generated protobuf-c sources with bundled implementation")
        endif()
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
