#include "win_error.h"

#include <errno.h>

#if defined(_WIN32)
#include <winsock2.h>

#ifndef ESOCKTNOSUPPORT
#define ESOCKTNOSUPPORT WSAESOCKTNOSUPPORT
#endif

#ifndef EPFNOSUPPORT
#define EPFNOSUPPORT WSAEPFNOSUPPORT
#endif

#ifndef EHOSTDOWN
#define EHOSTDOWN WSAEHOSTDOWN
#endif

#ifndef EPROCLIM
#define EPROCLIM WSAEPROCLIM
#endif

int platform_win32_to_errno(unsigned long error_code) {
    switch (error_code) {
    case ERROR_SUCCESS:
        return 0;
    case ERROR_FILE_NOT_FOUND:
    case ERROR_PATH_NOT_FOUND:
    case ERROR_INVALID_DRIVE:
        return ENOENT;
    case ERROR_ACCESS_DENIED:
    case ERROR_SHARING_VIOLATION:
    case ERROR_LOCK_VIOLATION:
        return EACCES;
    case ERROR_ALREADY_EXISTS:
    case ERROR_FILE_EXISTS:
        return EEXIST;
    case ERROR_NOT_ENOUGH_MEMORY:
    case ERROR_OUTOFMEMORY:
    case ERROR_NO_SYSTEM_RESOURCES:
        return ENOMEM;
    case ERROR_INVALID_HANDLE:
        return EBADF;
    case ERROR_INVALID_PARAMETER:
    case ERROR_BAD_ARGUMENTS:
        return EINVAL;
    case ERROR_BROKEN_PIPE:
        return EPIPE;
    case ERROR_SEM_TIMEOUT:
    case WAIT_TIMEOUT:
        return ETIMEDOUT;
    case ERROR_BUSY:
    case ERROR_BUSY_DRIVE:
        return EBUSY;
    case ERROR_OPERATION_ABORTED:
        return ECANCELED;
    case ERROR_ARITHMETIC_OVERFLOW:
        return ERANGE;
    case ERROR_INSUFFICIENT_BUFFER:
        return ENOBUFS;
    default:
        if (error_code >= WSAEINTR && error_code <= WSAEWOULDBLOCK) {
            // Winsock error range mirrors errno values starting at 10004
            switch (error_code) {
            case WSAEINTR:
                return EINTR;
            case WSAEBADF:
                return EBADF;
            case WSAEACCES:
                return EACCES;
            case WSAEFAULT:
                return EFAULT;
            case WSAEINVAL:
                return EINVAL;
            case WSAEMFILE:
                return EMFILE;
            case WSAEWOULDBLOCK:
                return EWOULDBLOCK;
            case WSAEINPROGRESS:
                return EINPROGRESS;
            case WSAEALREADY:
                return EALREADY;
            case WSAENOTSOCK:
                return ENOTSOCK;
            case WSAEDESTADDRREQ:
                return EDESTADDRREQ;
            case WSAEMSGSIZE:
                return EMSGSIZE;
            case WSAEPROTOTYPE:
                return EPROTOTYPE;
            case WSAENOPROTOOPT:
                return ENOPROTOOPT;
            case WSAEPROTONOSUPPORT:
                return EPROTONOSUPPORT;
            case WSAESOCKTNOSUPPORT:
                return ESOCKTNOSUPPORT;
            case WSAEOPNOTSUPP:
                return EOPNOTSUPP;
            case WSAEPFNOSUPPORT:
                return EPFNOSUPPORT;
            case WSAEAFNOSUPPORT:
                return EAFNOSUPPORT;
            case WSAEADDRINUSE:
                return EADDRINUSE;
            case WSAEADDRNOTAVAIL:
                return EADDRNOTAVAIL;
            case WSAENETDOWN:
                return ENETDOWN;
            case WSAENETUNREACH:
                return ENETUNREACH;
            case WSAENETRESET:
                return ENETRESET;
            case WSAECONNABORTED:
                return ECONNABORTED;
            case WSAECONNRESET:
                return ECONNRESET;
            case WSAENOBUFS:
                return ENOBUFS;
            case WSAEISCONN:
                return EISCONN;
            case WSAENOTCONN:
                return ENOTCONN;
            case WSAETIMEDOUT:
                return ETIMEDOUT;
            case WSAECONNREFUSED:
                return ECONNREFUSED;
            case WSAEHOSTDOWN:
                return EHOSTDOWN;
            case WSAEHOSTUNREACH:
                return EHOSTUNREACH;
            case WSAEPROCLIM:
                return EPROCLIM;
            default:
                return EINVAL;
            }
        }
        return EINVAL;
    }
}

void platform_win32_set_errno(unsigned long error_code) {
    errno = platform_win32_to_errno(error_code);
}

#endif /* _WIN32 */
