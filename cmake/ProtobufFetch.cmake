# Protobuf-c detection helper
# Tries pkg-config -> system library -> vcpkg -> bundled pre-generated sources

if(NOT DEFINED DRLMS_FORCE_BUNDLED_PROTOBUF_C)
    option(DRLMS_FORCE_BUNDLED_PROTOBUF_C "Always compile against the bundled protobuf-c runtime" ON)
endif()

set(PROTOBUF_C_FOUND FALSE)
set(PROTOBUF_C_LIBRARIES "")
set(PROTOBUF_C_INCLUDE_DIRS "")
set(PROTOBUF_C_DETECTION_METHOD "")
set(PROTOBUF_C_SOURCES "")
set(PROTOBUF_C_HEADERS "")
set(PROTOBUF_C_USE_PREGENSETS FALSE)
set(PROTOBUF_C_USE_BUNDLED_RUNTIME FALSE)

message(STATUS "Configuring protobuf-c support")

# 1) pkg-config (Linux/macOS preferred)
find_package(PkgConfig QUIET)
if(PKG_CONFIG_FOUND)
    foreach(_pkg_name IN ITEMS libprotobuf-c protobuf-c libprotobuf-c-dev)
        if(PROTOBUF_C_FOUND)
            break()
        endif()
        pkg_check_modules(_PROTOBUF_C QUIET ${_pkg_name})
        if(_PROTOBUF_C_FOUND)
            find_library(_PROTOBUF_C_LIB
                NAMES protobuf-c libprotobuf-c
                HINTS ${_PROTOBUF_C_LIBRARY_DIRS}
            )
            if(_PROTOBUF_C_LIB AND _PROTOBUF_C_INCLUDE_DIRS)
                set(PROTOBUF_C_FOUND TRUE)
                set(PROTOBUF_C_LIBRARIES ${_PROTOBUF_C_LIB})
                set(PROTOBUF_C_INCLUDE_DIRS ${_PROTOBUF_C_INCLUDE_DIRS})
                set(PROTOBUF_C_VERSION ${_PROTOBUF_C_VERSION})
                set(PROTOBUF_C_DETECTION_METHOD "pkg-config (${_pkg_name})")

                set(_protobuf_pregen_dir "${PROJECT_SOURCE_DIR}/src/generated/schema/v2")
                if(EXISTS "${_protobuf_pregen_dir}/common.pb-c.c")
                    message(STATUS "Found pre-generated protobuf files, using them with local implementation")
                    set(PROTOBUF_C_USE_PREGENSETS TRUE)
                    set(PROTOBUF_C_SOURCES
                        "${_protobuf_pregen_dir}/common.pb-c.c"
                        "${_protobuf_pregen_dir}/auth.pb-c.c"
                        "${_protobuf_pregen_dir}/room.pb-c.c"
                        "${_protobuf_pregen_dir}/federation.pb-c.c"
                        "${_protobuf_pregen_dir}/e2ee.pb-c.c"
                        "${PROJECT_SOURCE_DIR}/src/external/protobuf-c/protobuf-c.c")
                    set(PROTOBUF_C_HEADERS
                        "${_protobuf_pregen_dir}/common.pb-c.h"
                        "${_protobuf_pregen_dir}/auth.pb-c.h"
                        "${_protobuf_pregen_dir}/room.pb-c.h"
                        "${_protobuf_pregen_dir}/federation.pb-c.h"
                        "${_protobuf_pregen_dir}/e2ee.pb-c.h")
                    list(APPEND PROTOBUF_C_INCLUDE_DIRS 
                        ${_protobuf_pregen_dir}
                        "${PROJECT_SOURCE_DIR}/src")
                endif()
            endif()
        endif()
    endforeach()
endif()

# 2) Manual system lookup
if(NOT PROTOBUF_C_FOUND)
    # Handle Windows environment variables with parentheses properly
    # CMake cannot directly parse ENV{ProgramFiles(x86)} due to parentheses
    # So we use a different approach: try common paths without relying on problematic env vars
    
    find_path(PROTOBUF_C_INCLUDE_DIR
        NAMES protobuf-c/protobuf-c.h
        HINTS
            /usr/include
            /usr/local/include
            /opt/homebrew/include
            # Skip problematic ProgramFiles paths - let vcpkg or pkg-config handle Windows detection
    )

    find_library(PROTOBUF_C_LIBRARY
        NAMES protobuf-c libprotobuf-c
        HINTS
            /usr/lib
            /usr/local/lib
            /usr/lib/x86_64-linux-gnu
            /opt/homebrew/lib
            # Skip problematic ProgramFiles paths - let vcpkg or pkg-config handle Windows detection
    )

    if(PROTOBUF_C_INCLUDE_DIR AND PROTOBUF_C_LIBRARY)
        set(PROTOBUF_C_FOUND TRUE)
        set(PROTOBUF_C_LIBRARIES ${PROTOBUF_C_LIBRARY})
        set(PROTOBUF_C_INCLUDE_DIRS ${PROTOBUF_C_INCLUDE_DIR})
        set(PROTOBUF_C_DETECTION_METHOD "system")
        
        # 检查是否有预生成文件，如果有则使用它们并包含本地protobuf-c.c
        set(_protobuf_pregen_dir "${PROJECT_SOURCE_DIR}/src/generated/schema/v2")
        if(EXISTS "${_protobuf_pregen_dir}/common.pb-c.c")
            message(STATUS "Found pre-generated protobuf files, using them with local implementation")
            set(PROTOBUF_C_USE_PREGENSETS TRUE)
            set(PROTOBUF_C_SOURCES
                "${_protobuf_pregen_dir}/common.pb-c.c"
                "${_protobuf_pregen_dir}/auth.pb-c.c"
                "${_protobuf_pregen_dir}/room.pb-c.c"
                "${_protobuf_pregen_dir}/federation.pb-c.c"
                "${_protobuf_pregen_dir}/e2ee.pb-c.c"
                "${PROJECT_SOURCE_DIR}/src/external/protobuf-c/protobuf-c.c")
            set(PROTOBUF_C_HEADERS
                "${_protobuf_pregen_dir}/common.pb-c.h"
                "${_protobuf_pregen_dir}/auth.pb-c.h"
                "${_protobuf_pregen_dir}/room.pb-c.h"
                "${_protobuf_pregen_dir}/federation.pb-c.h"
                "${_protobuf_pregen_dir}/e2ee.pb-c.h")
            # 在include路径中添加预生成目录
            list(APPEND PROTOBUF_C_INCLUDE_DIRS 
                ${_protobuf_pregen_dir}
                "${PROJECT_SOURCE_DIR}/src")
        endif()
    endif()
endif()

# 3) vcpkg (Windows runners frequently install dependencies this way)
if(NOT PROTOBUF_C_FOUND AND WIN32)
    set(_vcpkg_roots)
    if(DEFINED ENV{VCPKG_ROOT})
        list(APPEND _vcpkg_roots "$ENV{VCPKG_ROOT}/packages/protobuf-c_x64-windows" "$ENV{VCPKG_ROOT}/packages/protobuf-c_x86-windows")
    endif()
    list(APPEND _vcpkg_roots
        "C:/vcpkg/packages/protobuf-c_x64-windows"
        "C:/vcpkg/packages/protobuf-c_x86-windows"
    )
    foreach(_root ${_vcpkg_roots})
        if(PROTOBUF_C_FOUND)
            break()
        endif()
        if(EXISTS "${_root}/include/protobuf-c.h")
            find_library(_vcpkg_lib
                NAMES protobuf-c.lib
                HINTS "${_root}/lib")
            if(_vcpkg_lib)
                set(PROTOBUF_C_FOUND TRUE)
                set(PROTOBUF_C_LIBRARIES ${_vcpkg_lib})
                set(PROTOBUF_C_INCLUDE_DIRS "${_root}/include")
                set(PROTOBUF_C_DETECTION_METHOD "vcpkg (${_root})")
                
                # 检查是否有预生成文件，如果有则使用它们并包含本地protobuf-c.c
                set(_protobuf_pregen_dir "${PROJECT_SOURCE_DIR}/src/generated/schema/v2")
                if(EXISTS "${_protobuf_pregen_dir}/common.pb-c.c")
                    message(STATUS "Found pre-generated protobuf files, using them with local implementation")
                    set(PROTOBUF_C_USE_PREGENSETS TRUE)
                    set(PROTOBUF_C_SOURCES
                        "${_protobuf_pregen_dir}/common.pb-c.c"
                        "${_protobuf_pregen_dir}/auth.pb-c.c"
                        "${_protobuf_pregen_dir}/room.pb-c.c"
                        "${_protobuf_pregen_dir}/federation.pb-c.c"
                        "${_protobuf_pregen_dir}/e2ee.pb-c.c"
                        "${PROJECT_SOURCE_DIR}/src/external/protobuf-c/protobuf-c.c")
                    set(PROTOBUF_C_HEADERS
                        "${_protobuf_pregen_dir}/common.pb-c.h"
                        "${_protobuf_pregen_dir}/auth.pb-c.h"
                        "${_protobuf_pregen_dir}/room.pb-c.h"
                        "${_protobuf_pregen_dir}/federation.pb-c.h"
                        "${_protobuf_pregen_dir}/e2ee.pb-c.h")
                    # 在include路径中添加预生成目录
                    list(APPEND PROTOBUF_C_INCLUDE_DIRS 
                        ${_protobuf_pregen_dir}
                        "${PROJECT_SOURCE_DIR}/src")
                endif()
            endif()
        endif()
    endforeach()
endif()

# 4) Bundled pre-generated sources (no external library required)
set(_protobuf_pregen_dir "${PROJECT_SOURCE_DIR}/src/generated/schema/v2")
if(NOT PROTOBUF_C_FOUND AND EXISTS "${_protobuf_pregen_dir}/common.pb-c.h")
    set(PROTOBUF_C_FOUND TRUE)
    set(PROTOBUF_C_DETECTION_METHOD "pre-generated headers only")
    set(_protobuf_local_include "${PROJECT_SOURCE_DIR}/src/external/protobuf-c/include")
    set(PROTOBUF_C_INCLUDE_DIRS
        "${_protobuf_local_include}"
        "${PROJECT_SOURCE_DIR}/src/external/protobuf-c"
        "${PROJECT_SOURCE_DIR}/src"
        "${PROJECT_SOURCE_DIR}/src/generated"
        "${_protobuf_pregen_dir}")
    set(PROTOBUF_C_USE_PREGENSETS TRUE)
    set(PROTOBUF_C_SOURCES
        "${PROJECT_SOURCE_DIR}/src/external/protobuf-c/protobuf-c.c")
    set(PROTOBUF_C_HEADERS
        "${_protobuf_local_include}/protobuf-c/protobuf-c.h")
    message(STATUS "Using bundled protobuf-c runtime with pre-generated headers")
endif()

# Always prefer the bundled runtime when requested so that we control protobuf-c features.
if(DRLMS_FORCE_BUNDLED_PROTOBUF_C)
    set(PROTOBUF_C_FOUND TRUE)
    set(HAVE_PROTOBUF_C 1)
    set(PROTOBUF_C_USE_BUNDLED_RUNTIME TRUE)
    set(PROTOBUF_C_LIBRARIES "")
    set(_bundled_include_dirs
        "${PROJECT_SOURCE_DIR}/src/external/protobuf-c/include"
        "${PROJECT_SOURCE_DIR}/src/external/protobuf-c")
    if(PROTOBUF_C_INCLUDE_DIRS)
        list(INSERT PROTOBUF_C_INCLUDE_DIRS 0 ${_bundled_include_dirs})
    else()
        set(PROTOBUF_C_INCLUDE_DIRS ${_bundled_include_dirs})
    endif()
    if(PROTOBUF_C_DETECTION_METHOD)
        set(PROTOBUF_C_DETECTION_METHOD "${PROTOBUF_C_DETECTION_METHOD};bundled-runtime")
    else()
        set(PROTOBUF_C_DETECTION_METHOD "bundled-runtime")
    endif()
    
    # 检查是否有预生成文件，如果有则使用它们
    set(_protobuf_pregen_dir "${PROJECT_SOURCE_DIR}/src/generated/schema/v2")
    if(EXISTS "${_protobuf_pregen_dir}/common.pb-c.c")
        message(STATUS "Found pre-generated protobuf files, using them with bundled runtime")
        set(PROTOBUF_C_USE_PREGENSETS TRUE)
        set(PROTOBUF_C_SOURCES
            "${_protobuf_pregen_dir}/common.pb-c.c"
            "${_protobuf_pregen_dir}/auth.pb-c.c"
            "${_protobuf_pregen_dir}/room.pb-c.c"
            "${_protobuf_pregen_dir}/federation.pb-c.c"
            "${_protobuf_pregen_dir}/e2ee.pb-c.c"
            "${PROJECT_SOURCE_DIR}/src/external/protobuf-c/protobuf-c.c")
        set(PROTOBUF_C_HEADERS
            "${_protobuf_pregen_dir}/common.pb-c.h"
            "${_protobuf_pregen_dir}/auth.pb-c.h"
            "${_protobuf_pregen_dir}/room.pb-c.h"
            "${_protobuf_pregen_dir}/federation.pb-c.h"
            "${_protobuf_pregen_dir}/e2ee.pb-c.h")
        # 在include路径中添加预生成目录
        list(APPEND PROTOBUF_C_INCLUDE_DIRS 
            ${_protobuf_pregen_dir}
            "${PROJECT_SOURCE_DIR}/src")
    else()
        set(PROTOBUF_C_SOURCES "${PROJECT_SOURCE_DIR}/src/external/protobuf-c/protobuf-c.c")
        set(PROTOBUF_C_HEADERS "${_bundled_include_dirs}/protobuf-c/protobuf-c.h")
    endif()
    
    message(STATUS "protobuf-c runtime: forcing bundled implementation")
endif()

if(PROTOBUF_C_FOUND)
    set(HAVE_PROTOBUF_C 1)
    message(STATUS "protobuf-c detected via: ${PROTOBUF_C_DETECTION_METHOD}")
else()
    set(HAVE_PROTOBUF_C 0)
    message(WARNING "protobuf-c library not found; generated protocol sources will be skipped")
endif()
