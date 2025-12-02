set(LIBIPC_SOURCES
    shared_buffer.c
)

add_library(libipc_obj OBJECT ${LIBIPC_SOURCES})

# Shared headers for libipc consumers.
target_include_directories(libipc_obj PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${PROJECT_SOURCE_DIR}/src/platform/include)

target_link_libraries(libipc_obj PUBLIC platform Threads::Threads)

if(UNIX AND NOT APPLE)
    target_link_libraries(libipc_obj PUBLIC rt)
endif()

add_library(ipc_static STATIC $<TARGET_OBJECTS:libipc_obj>)
set_target_properties(ipc_static PROPERTIES OUTPUT_NAME ipc)

add_library(ipc_shared SHARED $<TARGET_OBJECTS:libipc_obj>)
if(WIN32)
    set_target_properties(ipc_shared PROPERTIES OUTPUT_NAME ipc_shared)
else()
    set_target_properties(ipc_shared PROPERTIES OUTPUT_NAME ipc)
endif()

target_link_libraries(ipc_static PUBLIC Threads::Threads platform)

target_link_libraries(ipc_shared PUBLIC Threads::Threads platform)

if(UNIX AND NOT APPLE)
    target_link_libraries(ipc_static PUBLIC rt)
    target_link_libraries(ipc_shared PUBLIC rt)
endif()
