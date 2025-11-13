# CheckWindowsLib.cmake - Windows library validation script
# This script checks for the correct Windows shared library format

if(NOT SIGNAL_LIB_DIR)
    message(FATAL_ERROR "SIGNAL_LIB_DIR not set")
endif()

# Check for DLL in bin directory
get_filename_component(bin_dir "${SIGNAL_LIB_DIR}" DIRECTORY)
set(bin_dir "${bin_dir}/bin")

set(dll_file "${bin_dir}/signal-protocol-c.dll")
set(lib_file "${SIGNAL_LIB_DIR}/signal-protocol-c.lib")

if(EXISTS "${dll_file}")
    message(STATUS "Found signal-protocol-c.dll at ${dll_file} - OK")

    # For MSVC, import library is typically in the same directory as DLL
    set(dll_dir "${bin_dir}")
    set(implib_source "${dll_dir}/signal-protocol-c.lib")

    # Ensure import library exists in lib directory for linking
    if(NOT EXISTS "${lib_file}")
        if(EXISTS "${implib_source}")
            execute_process(
                COMMAND ${CMAKE_COMMAND} -E copy "${implib_source}" "${lib_file}"
                RESULT_VARIABLE copy_result
            )
            if(copy_result EQUAL 0)
                message(STATUS "Copied import library from ${implib_source} to ${lib_file}")
            else()
                message(WARNING "Failed to copy import library from ${implib_source}")
            endif()
        else()
            message(WARNING "Import library not found at ${implib_source}")
        endif()
    endif()
else()
    message(WARNING "WARNING: signal-protocol-c.dll not found at ${dll_file}")
endif()

if(EXISTS "${lib_file}")
    message(STATUS "Found signal-protocol-c.lib (import library) at ${lib_file} - OK")
else()
    message(FATAL_ERROR "ERROR: signal-protocol-c.lib (import library) not found at ${lib_file}")
endif()

