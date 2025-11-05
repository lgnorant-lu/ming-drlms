#include "shared_buffer.h"
#include "platform/compat.h"
#include "platform/platform.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#if defined(_WIN32)
#include <process.h>
#include <windows.h>

static int setenv_compat(const char *name, const char *value, int overwrite) {
    if (!overwrite) {
        const char *existing = getenv(name);
        if (existing && *existing)
            return 0;
    }
    if (!value)
        value = "";
    return _putenv_s(name, value);
}

#define setenv(name, value, overwrite) setenv_compat(name, value, overwrite)
#else
#include <sys/ipc.h>
#include <sys/shm.h>
#include <sys/wait.h>
#include <unistd.h>
#endif

// This test program combines several test cases for libipc.
// It verifies message integrity and fragmentation/reassembly across processes.

static void sleep_ms(unsigned int ms) {
#if defined(_WIN32)
    Sleep(ms);
#else
    usleep(ms * 1000u);
#endif
}

static int reader_main(void) {
    if (shm_init() != 0) {
        perror("Reader: shm_init failed");
        return 1;
    }

    unsigned char read_buffer[4096];
    ssize_t bytes_read;

    printf("Reader: Waiting to read simple message...\n");
    bytes_read = shm_read(read_buffer, sizeof(read_buffer));
    if (bytes_read < 0) {
        perror("Reader: shm_read (simple) failed");
        shm_cleanup();
        return 1;
    }
    if ((size_t)bytes_read >= sizeof(read_buffer))
        bytes_read = (ssize_t)(sizeof(read_buffer) - 1);
    read_buffer[bytes_read] = '\0';
    printf("Reader: Read simple message: '%s' (%zd bytes)\n", read_buffer,
           bytes_read);
    fflush(stdout);
    assert(strcmp((char *)read_buffer, "hello-ipc-test") == 0);
    assert(bytes_read == (ssize_t)strlen("hello-ipc-test"));
    printf("Reader: Simple message integrity OK.\n\n");

    printf("Reader: Waiting to read large message...\n");
    bytes_read = shm_read(read_buffer, sizeof(read_buffer));
    if (bytes_read < 0) {
        perror("Reader: shm_read (large) failed");
        shm_cleanup();
        return 1;
    }
    printf("Reader: Read large message (%zd bytes)\n", bytes_read);
    fflush(stdout);
    if (bytes_read != 2000) {
        fprintf(stderr, "Reader WARNING expected 2000 bytes, got %zd\n",
                bytes_read);
        for (size_t i = 0; i < (size_t)bytes_read && i < 64; ++i) {
            fprintf(stderr, "%02X ", read_buffer[i]);
        }
        fprintf(stderr, "\n");
        fflush(stderr);
    }
    if (bytes_read != 2000) {
        return 1;
    }
    for (size_t i = 0; i < 2000u; ++i) {
        assert(read_buffer[i] == 'A');
    }
    printf("Reader: Large message fragmentation and reassembly OK.\n");

    shm_cleanup();
    return 0;
}

static int writer_main(void) {
    if (shm_init() != 0) {
        perror("Writer: shm_init failed");
        return 1;
    }

    sleep_ms(200);

    const char *simple_msg = "hello-ipc-test";
    printf("Writer: Writing simple message: '%s'\n", simple_msg);
    if (shm_write((const unsigned char *)simple_msg, strlen(simple_msg)) != 0) {
        perror("Writer: shm_write (simple) failed");
        shm_cleanup();
        return 1;
    }

    sleep_ms(200);

    const size_t large_len = 2000;
    unsigned char large_msg[2000];
    memset(large_msg, 'A', large_len);
    printf("Writer: Writing large message (%zu bytes)\n", large_len);
    if (shm_write(large_msg, sizeof(large_msg)) != 0) {
        perror("Writer: shm_write (large) failed");
        shm_cleanup();
        return 1;
    }

    return 0;
}

#if defined(_WIN32)
static int spawn_reader_process(PROCESS_INFORMATION *pi) {
    char module_path[MAX_PATH];
    DWORD len =
        GetModuleFileNameA(NULL, module_path, (DWORD)sizeof(module_path));
    if (len == 0 || len >= sizeof(module_path))
        return -1;

    char cmd[512];
    snprintf(cmd, sizeof(cmd), "\"%s\" --child", module_path);

    STARTUPINFOA si;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(pi, sizeof(*pi));

    if (!CreateProcessA(NULL, cmd, NULL, NULL, FALSE, 0, NULL, NULL, &si, pi))
        return -1;
    return 0;
}

static unsigned int current_pid_component(void) {
    return (unsigned int)GetCurrentProcessId();
}
#else
static unsigned int current_pid_component(void) {
    return (unsigned int)getpid();
}
#endif

static unsigned int generate_shm_key(void) {
    unsigned int pid_component = current_pid_component();
    unsigned int time_component = (unsigned int)time(NULL);
    return 0x54455300u ^ pid_component ^ time_component;
}

static void configure_environment(unsigned int key) {
    char key_buf[32];
    snprintf(key_buf, sizeof key_buf, "0x%08x", key);
    setenv("DRLMS_SHM_KEY", key_buf, 1);

#if !defined(_WIN32)
    key_t sysv_key = (key_t)key;
    int stale_id = shmget(sysv_key, 0, 0600);
    if (stale_id >= 0) {
        shmctl(stale_id, IPC_RMID, NULL);
    }
#else
    (void)key;
#endif
}

int main(int argc, char **argv) {
    int is_child = (argc >= 2 && strcmp(argv[1], "--child") == 0);

    if (!is_child) {
        unsigned int key = generate_shm_key();
        configure_environment(key);
    }

    if (is_child) {
        return reader_main();
    }

#if defined(_WIN32)
    PROCESS_INFORMATION pi;
    if (spawn_reader_process(&pi) != 0) {
        fprintf(stderr, "Writer: failed to spawn reader process\n");
        return 1;
    }

    int writer_rc = writer_main();

    DWORD wait_rc = WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD child_exit = 1;
    if (wait_rc == WAIT_OBJECT_0) {
        if (!GetExitCodeProcess(pi.hProcess, &child_exit))
            child_exit = 1;
    } else {
        fprintf(stderr, "Writer: WaitForSingleObject failed (%lu)\n",
                (unsigned long)wait_rc);
    }

    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);

    shm_cleanup();

    if (writer_rc != 0 || child_exit != 0) {
        printf("\n==== One or more libipc tests FAILED! ====\n");
        return 1;
    }

    printf("\n==== All libipc tests passed! ====\n");
    return 0;
#else
    pid_t pid = fork();
    if (pid < 0) {
        perror("fork failed");
        return 1;
    }

    if (pid == 0) {
        char *child_argv[] = {argv[0], "--child", NULL};
        execvp(child_argv[0], child_argv);
        perror("execvp failed");
        _exit(127);
    }

    int writer_rc = writer_main();

    int status = 0;
    if (waitpid(pid, &status, 0) < 0) {
        perror("waitpid failed");
        shm_cleanup();
        return 1;
    }

    shm_cleanup();

    int child_rc = 1;
    if (WIFEXITED(status))
        child_rc = WEXITSTATUS(status);

    if (writer_rc != 0 || child_rc != 0) {
        printf("\n==== One or more libipc tests FAILED! ====\n");
        return 1;
    }

    printf("\n==== All libipc tests passed! ====\n");
    return 0;
#endif
}
