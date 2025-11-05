include(ExternalProject)

set(SIGNAL_INSTALL_PREFIX "${CMAKE_BINARY_DIR}/_deps/signal-install" CACHE PATH "libsignal-protocol-c install prefix")
set(SIGNAL_PROTO_REPO "https://github.com/signalapp/libsignal-protocol-c.git" CACHE STRING "libsignal-protocol-c repo")
set(SIGNAL_PROTO_TAG "v2.3.3" CACHE STRING "libsignal-protocol-c tag")

# Build libsignal-protocol-c from source via ExternalProject using CMake
ExternalProject_Add(
    signal_protocol_ext
    GIT_REPOSITORY ${SIGNAL_PROTO_REPO}
    GIT_TAG ${SIGNAL_PROTO_TAG}
    GIT_SHALLOW TRUE
    PREFIX ${CMAKE_BINARY_DIR}/_deps/signal
    CMAKE_ARGS
        -DCMAKE_INSTALL_PREFIX=${SIGNAL_INSTALL_PREFIX}
        -DCMAKE_BUILD_TYPE=Release
        -DBUILD_TESTING=OFF
        -DCOVERAGE=OFF
    LOG_DOWNLOAD ON
    LOG_CONFIGURE ON
    LOG_BUILD ON
    LOG_INSTALL ON
)

# Create directories first to avoid CMake configuration errors
file(MAKE_DIRECTORY "${SIGNAL_INSTALL_PREFIX}/include")
file(MAKE_DIRECTORY "${SIGNAL_INSTALL_PREFIX}/lib")

# Create imported target
add_library(signal_protocol STATIC IMPORTED GLOBAL)
add_dependencies(signal_protocol signal_protocol_ext)

set_target_properties(signal_protocol PROPERTIES
    IMPORTED_LOCATION "${SIGNAL_INSTALL_PREFIX}/lib/${CMAKE_STATIC_LIBRARY_PREFIX}signal-protocol-c${CMAKE_STATIC_LIBRARY_SUFFIX}"
    INTERFACE_INCLUDE_DIRECTORIES "${SIGNAL_INSTALL_PREFIX}/include"
)

add_library(Signal::protocol ALIAS signal_protocol)
message(STATUS "Building libsignal-protocol-c from source: ${SIGNAL_PROTO_TAG}")


