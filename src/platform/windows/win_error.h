#pragma once

#if defined(_WIN32)
#include <winsock2.h>
#include <windows.h>
#endif

int platform_win32_to_errno(unsigned long error_code);
void platform_win32_set_errno(unsigned long error_code);
