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

    # Ensure import library exists, copy if needed
    if(NOT EXISTS "${lib_file}")
        # Try to find the import library in various locations
        set(possible_lib_locations
            "${bin_dir}/signal-protocol-c.lib"
            "${SIGNAL_LIB_DIR}/../lib/signal-protocol-c.lib"
        )

        foreach(lib_location IN LISTS possible_lib_locations)
            if(EXISTS "${lib_location}")
                execute_process(
                    COMMAND ${CMAKE_COMMAND} -E copy "${lib_location}" "${lib_file}"
                    RESULT_VARIABLE copy_result
                )
                if(copy_result EQUAL 0)
                    message(STATUS "Copied import library from ${lib_location} to ${lib_file}")
                    break()
                endif()
            endif()
        endforeach()
    endif()
else()
    message(WARNING "WARNING: signal-protocol-c.dll not found at ${dll_file}")
endif()

if(EXISTS "${lib_file}")
    message(STATUS "Found signal-protocol-c.lib (import library) at ${lib_file} - OK")
else()
    message(WARNING "WARNING: signal-protocol-c.lib (import library) not found at ${lib_file}")
endif()

