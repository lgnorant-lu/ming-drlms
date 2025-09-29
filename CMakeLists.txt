cmake_minimum_required(VERSION 3.18)
project(ming_drlms C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

include(CTest)

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})

option(ENABLE_TESTS "Build C-based test binaries" ON)
option(ENABLE_COVERAGE "Enable coverage instrumentation" OFF)

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")

set(COVERAGE_LIBS "")
if(ENABLE_COVERAGE)
    add_compile_options(--coverage)
    add_link_options(--coverage)

    if(CMAKE_C_COMPILER_ID STREQUAL "GNU")
        list(APPEND COVERAGE_LIBS gcov)
    elseif(CMAKE_C_COMPILER_ID STREQUAL "Clang" AND NOT APPLE)
        # Some non-Apple Clang toolchains still provide libgcov compatibility.
        list(APPEND COVERAGE_LIBS gcov)
    endif()
endif()
set(COVERAGE_LIBS "${COVERAGE_LIBS}" CACHE INTERNAL "Coverage runtime libraries" FORCE)

add_compile_options(-Wall -Wextra -Werror -Wno-deprecated-declarations)

find_package(Threads REQUIRED)
find_package(OpenSSL REQUIRED)
find_package(SQLite3 REQUIRED)
find_package(Argon2 REQUIRED)

add_subdirectory(src/platform)
add_subdirectory(src/libipc)
add_subdirectory(src/server)
add_subdirectory(src/agent)
add_subdirectory(src/tools)

if(ENABLE_TESTS)
    add_subdirectory(tests)
endif()

# Convenience target that mirrors the legacy Makefile coverage workflow.
add_custom_target(coverage
    COMMAND ${CMAKE_COMMAND} -E env PROJECT_ROOT=${CMAKE_SOURCE_DIR} ${CMAKE_SOURCE_DIR}/scripts/run_coverage.sh
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
    COMMENT "Generating combined C/Python coverage report" )
