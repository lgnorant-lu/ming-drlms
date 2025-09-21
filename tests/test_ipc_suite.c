#include "shared_buffer.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/wait.h>
#include <sys/ipc.h>
#include <sys/shm.h>
#include <assert.h>

// This test program combines several test cases for libipc.
// It tests:
// 1. Message Integrity: A simple message is written and read correctly.
// 2. Fragmentation & Reassembly: A large message is fragmented and reassembled.

void run_ipc_tests() {
    pid_t pid = fork();

    if (pid < 0) {
        perror("fork failed");
        exit(1);
    }

    if (pid == 0) {
        // --- Child Process (Reader) ---
        if (shm_init() != 0) {
            perror("Reader: shm_init failed");
            exit(1);
        }

        unsigned char read_buffer[4096];
        ssize_t bytes_read;

        // Test 1: Read the simple message
        printf("Reader: Waiting to read simple message...\n");
        bytes_read = shm_read(read_buffer, sizeof(read_buffer));
        if (bytes_read < 0) {
            perror("Reader: shm_read (simple) failed");
            exit(1);
        }
        read_buffer[bytes_read] = '\0';
        printf("Reader: Read simple message: '%s' (%zd bytes)\n", read_buffer,
               bytes_read);
        assert(strcmp((char *)read_buffer, "hello-ipc-test") == 0);
        assert(bytes_read == strlen("hello-ipc-test"));
        printf("Reader: Simple message integrity OK.\n\n");

        // Test 2: Read the large fragmented message
        printf("Reader: Waiting to read large message...\n");
        bytes_read = shm_read(read_buffer, sizeof(read_buffer));
        if (bytes_read < 0) {
            perror("Reader: shm_read (large) failed");
            exit(1);
        }
        printf("Reader: Read large message (%zd bytes)\n", bytes_read);
        assert(bytes_read == 2000);
        for (int i = 0; i < 2000; ++i) {
            assert(read_buffer[i] == 'A');
        }
        printf("Reader: Large message fragmentation and reassembly OK.\n");

        shm_cleanup();
        exit(0);

    } else {
        // --- Parent Process (Writer) ---
        if (shm_init() != 0) {
            perror("Writer: shm_init failed");
            exit(1);
        }

        // Give the reader a moment to start and block
        sleep(1);

        // Test 1: Write a simple message
        const char *simple_msg = "hello-ipc-test";
        printf("Writer: Writing simple message: '%s'\n", simple_msg);
        if (shm_write((const unsigned char *)simple_msg, strlen(simple_msg)) !=
            0) {
            perror("Writer: shm_write (simple) failed");
            exit(1);
        }

        // Give the reader time to process the simple message
        sleep(1);

        // Test 2: Write a large message to test fragmentation
        unsigned char large_msg[2000];
        memset(large_msg, 'A', sizeof(large_msg));
        printf("Writer: Writing large message (%zu bytes)\n",
               sizeof(large_msg));
        if (shm_write(large_msg, sizeof(large_msg)) != 0) {
            perror("Writer: shm_write (large) failed");
            exit(1);
        }

        // Wait for the child process to finish
        int status;
        waitpid(pid, &status, 0);

        if (WIFEXITED(status) && WEXITSTATUS(status) == 0) {
            printf("\n==== All libipc tests passed! ====\n");
        } else {
            printf("\n==== One or more libipc tests FAILED! ====\n");
            exit(1);
        }

        // Clean up the shared memory segment
        shm_cleanup();

        // The creator is responsible for removing the shm segment
        key_t key = (key_t)0x54455354; // "TEST"
        int shm_id = shmget(key, 0, 0);
        if (shm_id >= 0) {
            shmctl(shm_id, IPC_RMID, NULL);
            printf("Writer: Shared memory segment removed.\n");
        }
    }
}

int main() {
    // Set a specific key for testing to avoid interfering with a running server
    setenv("DRLMS_SHM_KEY", "0x54455354", 1); // "TEST"
    run_ipc_tests();
    return 0;
}
