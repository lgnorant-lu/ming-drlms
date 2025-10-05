add_library(platform_linux STATIC thread.c ipc.c net.c file.c)

target_link_libraries(platform_linux
    PUBLIC
        Threads::Threads
        platform_headers)

if(UNIX AND NOT APPLE)
    target_link_libraries(platform_linux PUBLIC rt)
endif()

add_library(platform::linux ALIAS platform_linux)
