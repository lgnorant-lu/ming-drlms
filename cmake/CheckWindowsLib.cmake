# CheckWindowsLib.cmake - Windows library validation script
# This script checks for the correct Windows static library format

if(NOT SIGNAL_LIB_DIR)
    message(FATAL_ERROR "SIGNAL_LIB_DIR not set")
endif()

set(lib_file "${SIGNAL_LIB_DIR}/signal-protocol-c.lib")
set(lib_static_file "${SIGNAL_LIB_DIR}/signal-protocol-c-static.lib")
set(a_file "${SIGNAL_LIB_DIR}/libsignal-protocol-c.a")

if(EXISTS "${lib_file}")
    # Copy to static variant if needed
    if(NOT EXISTS "${lib_static_file}")
        execute_process(
            COMMAND ${CMAKE_COMMAND} -E copy "${lib_file}" "${lib_static_file}"
            RESULT_VARIABLE copy_result
        )
        if(copy_result EQUAL 0)
            message(STATUS "Created signal-protocol-c-static.lib from signal-protocol-c.lib")
        else()
            message(WARNING "Failed to create signal-protocol-c-static.lib")
        endif()
    endif()
    message(STATUS "Found signal-protocol-c.lib - OK")
elseif(EXISTS "${lib_static_file}")
    message(STATUS "Found signal-protocol-c-static.lib - OK")
elseif(EXISTS "${a_file}")
    message(FATAL_ERROR
        "ERROR: Found libsignal-protocol-c.a but no .lib file. "
        "This indicates MinGW toolchain output which is incompatible with MSVC. "
        "Please ensure the external project uses the same toolchain as the main build."
    )
else()
    message(WARNING "WARNING: No static library found for signal-protocol-c")
endif()

