include(ExternalProject)

set(SIGNAL_INSTALL_PREFIX "${CMAKE_BINARY_DIR}/_deps/signal-install" CACHE PATH "libsignal-protocol-c install prefix")
set(SIGNAL_PROTO_REPO "https://github.com/signalapp/libsignal-protocol-c.git" CACHE STRING "libsignal-protocol-c repo")
set(SIGNAL_PROTO_TAG "v2.3.3" CACHE STRING "libsignal-protocol-c tag")

# Patch script to bump the minimum required CMake version to something modern.
set(_signal_patch_script "${CMAKE_BINARY_DIR}/_deps/patch_signal_protocol.cmake")
file(WRITE ${_signal_patch_script} [=[
if(NOT DEFINED SIGNAL_SRC_DIR)
    message(FATAL_ERROR "SIGNAL_SRC_DIR not provided to patch script")
endif()

set(_cmakelists "${SIGNAL_SRC_DIR}/CMakeLists.txt")
if(NOT EXISTS "${_cmakelists}")
    message(FATAL_ERROR "Expected CMakeLists.txt at ${_cmakelists}")
endif()

file(READ "${_cmakelists}" _content)
set(_needle "cmake_minimum_required(VERSION 2.8.4)")
string(FIND "${_content}" "${_needle}" _index)
message(STATUS "libsignal-protocol-c patch: needle index=${_index}")
if(_index EQUAL -1)
    message(STATUS "libsignal-protocol-c CMakeLists already patched; leaving as-is")
else()
    string(REPLACE "${_needle}" "cmake_minimum_required(VERSION 3.5)" _patched "${_content}")
    file(WRITE "${_cmakelists}" "${_patched}")
endif()

# MSVC requires compile-time constants for array lengths; adjust tests accordingly.
set(_fast_tests "${SIGNAL_SRC_DIR}/src/curve25519/ed25519/tests/internal_fast_tests.c")
if(EXISTS "${_fast_tests}")
    file(READ "${_fast_tests}" _fast_content)
    set(_needle_msg "const int MSG_LEN  = 200;")
    if(_fast_content MATCHES "${_needle_msg}")
        string(REPLACE "${_needle_msg}" "enum { MSG_LEN = 200 };" _fast_patched "${_fast_content}")
        file(WRITE "${_fast_tests}" "${_fast_patched}")
        message(STATUS "libsignal-protocol-c patch: converted MSG_LEN constant to enum for MSVC")
    endif()
endif()
]=])

set(_signal_cmake_args
    -DCMAKE_INSTALL_PREFIX=${SIGNAL_INSTALL_PREFIX}
    -DBUILD_SHARED_LIBS=OFF
    -DBUILD_TESTING=OFF
    -DCOVERAGE=OFF)

if(NOT CMAKE_CONFIGURATION_TYPES)
    # Single-config generators honour CMAKE_BUILD_TYPE
    list(APPEND _signal_cmake_args -DCMAKE_BUILD_TYPE=${CMAKE_BUILD_TYPE})
endif()

ExternalProject_Add(signal_protocol_ext
    PREFIX ${CMAKE_BINARY_DIR}/_deps/signal
    GIT_REPOSITORY ${SIGNAL_PROTO_REPO}
    GIT_TAG ${SIGNAL_PROTO_TAG}
    GIT_SHALLOW TRUE
    UPDATE_DISCONNECTED TRUE
    PATCH_COMMAND ${CMAKE_COMMAND} -DSIGNAL_SRC_DIR=<SOURCE_DIR> -P ${_signal_patch_script}
    CMAKE_ARGS ${_signal_cmake_args}
    INSTALL_DIR ${SIGNAL_INSTALL_PREFIX}
    LOG_DOWNLOAD ON
    LOG_CONFIGURE ON
    LOG_BUILD ON
    LOG_INSTALL ON)

file(MAKE_DIRECTORY "${SIGNAL_INSTALL_PREFIX}/include")
file(MAKE_DIRECTORY "${SIGNAL_INSTALL_PREFIX}/lib")

set(_signal_static_lib "${SIGNAL_INSTALL_PREFIX}/lib/${CMAKE_STATIC_LIBRARY_PREFIX}signal-protocol-c${CMAKE_STATIC_LIBRARY_SUFFIX}")
add_library(signal_protocol STATIC IMPORTED GLOBAL)
add_dependencies(signal_protocol signal_protocol_ext)
set_target_properties(signal_protocol PROPERTIES
    IMPORTED_LOCATION ${_signal_static_lib}
    INTERFACE_INCLUDE_DIRECTORIES "${SIGNAL_INSTALL_PREFIX}/include")

add_library(Signal::protocol ALIAS signal_protocol)

message(STATUS "Signal protocol external project configured (install prefix: ${SIGNAL_INSTALL_PREFIX})")


