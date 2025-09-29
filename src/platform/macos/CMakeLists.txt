add_library(platform_macos STATIC
    thread.c
    ipc.c)

target_link_libraries(platform_macos
    PUBLIC
        platform_headers
        Threads::Threads)

target_compile_definitions(platform_macos PRIVATE _DARWIN_C_SOURCE)
