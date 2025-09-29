# SPDX-License-Identifier: MIT
# Simple find module for libargon2

find_path(ARGON2_INCLUDE_DIR
          NAMES argon2.h
          DOC "Directory where argon2.h resides")

find_library(ARGON2_LIBRARY
             NAMES argon2
             DOC "libargon2 library")

include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(Argon2
    REQUIRED_VARS ARGON2_LIBRARY ARGON2_INCLUDE_DIR)

if(Argon2_FOUND)
    set(ARGON2_LIBRARIES ${ARGON2_LIBRARY})
    set(ARGON2_INCLUDE_DIRS ${ARGON2_INCLUDE_DIR})
endif()

mark_as_advanced(ARGON2_LIBRARY ARGON2_INCLUDE_DIR)
