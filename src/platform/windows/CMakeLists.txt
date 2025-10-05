add_library(platform_windows STATIC
    thread.c
    ipc.c
    net.c
    file.c
    win_error.c)

if(MSVC)
    target_compile_options(platform_windows PRIVATE /W4 /WX-)
else()
    target_compile_options(platform_windows PRIVATE -Wall -Wextra -Wpedantic)
endif()

target_link_libraries(platform_windows
    PUBLIC
        platform_headers
    PRIVATE
        ws2_32)

add_library(platform::windows ALIAS platform_windows)
