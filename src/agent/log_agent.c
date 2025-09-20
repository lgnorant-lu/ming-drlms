// 长连接命令客户端：
// 用法：
//   log_agent <host> <port> login <user> <pass> list
//   log_agent <host> <port> login <user> <pass> upload <file>
//   log_agent <host> <port> login <user> <pass> download <file> [outpath]

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <openssl/sha.h>

static int connect_server(const char *host, int port) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0)
        return -1;
    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((uint16_t)port);
    if (inet_pton(AF_INET, host, &addr.sin_addr) != 1) {
        close(fd);
        return -1;
    }
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        close(fd);
        return -1;
    }
    return fd;
}

static int send_all(int fd, const void *buf, size_t len) {
    const char *p = (const char *)buf;
    size_t off = 0;
    while (off < len) {
        ssize_t n = send(fd, p + off, len - off, 0);
        if (n <= 0)
            return -1;
        off += (size_t)n;
    }
    return 0;
}

static int recv_line(int fd, char *out, size_t out_sz) {
    size_t n = 0;
    while (n + 1 < out_sz) {
        char c;
        ssize_t r = recv(fd, &c, 1, 0);
        if (r <= 0)
            return -1;
        if (c == '\n') {
            out[n] = '\0';
            return 0;
        }
        out[n++] = c;
    }
    out[n] = '\0';
    return 0;
}

static void to_hex(const unsigned char *in, size_t len, char *out_hex,
                   size_t out_sz) {
    static const char *hexd = "0123456789abcdef";
    size_t j = 0;
    for (size_t i = 0; i < len && j + 2 < out_sz; ++i) {
        out_hex[j++] = hexd[in[i] >> 4];
        out_hex[j++] = hexd[in[i] & 0xF];
    }
    if (j < out_sz)
        out_hex[j] = '\0';
}

static int action_login(int fd, const char *user, const char *pass) {
    char line[512];
    snprintf(line, sizeof line, "LOGIN|%s|%s\n", user, pass);
    if (send_all(fd, line, strlen(line)) != 0)
        return -1;
    char resp[512];
    if (recv_line(fd, resp, sizeof resp) != 0)
        return -1;
    printf("%s\n", resp);
    return (strncmp(resp, "OK|", 3) == 0 || strcmp(resp, "OK") == 0) ? 0 : -1;
}

static int action_list(int fd) {
    if (send_all(fd, "LIST\n", 5) != 0)
        return -1;
    char line[1024];
    for (;;) {
        if (recv_line(fd, line, sizeof line) != 0)
            return -1;
        if (strcmp(line, "BEGIN") == 0) {
            puts("BEGIN");
            continue;
        }
        if (strcmp(line, "END") == 0) {
            puts("END");
            break;
        }
        puts(line);
    }
    return 0;
}

static int file_sha256(const char *path,
                       unsigned char out[SHA256_DIGEST_LENGTH],
                       long long *out_size) {
    FILE *f = fopen(path, "rb");
    if (!f)
        return -1;
    SHA256_CTX ctx;
    SHA256_Init(&ctx);
    const size_t BUF = 8192;
    unsigned char *buf = (unsigned char *)malloc(BUF);
    long long total = 0;
    for (;;) {
        size_t n = fread(buf, 1, BUF, f);
        if (n == 0)
            break;
        SHA256_Update(&ctx, buf, n);
        total += (long long)n;
    }
    SHA256_Final(out, &ctx);
    free(buf);
    fclose(f);
    if (out_size)
        *out_size = total;
    return 0;
}

static int action_upload(int fd, const char *filepath) {
    // 计算sha与大小
    unsigned char dg[SHA256_DIGEST_LENGTH];
    long long fsz = 0;
    if (file_sha256(filepath, dg, &fsz) != 0) {
        perror("open");
        return -1;
    }
    char shahex[SHA256_DIGEST_LENGTH * 2 + 1];
    to_hex(dg, sizeof dg, shahex, sizeof shahex);
    // 文件名取basename（简单截取最后/后部分）
    const char *base = strrchr(filepath, '/');
    base = base ? base + 1 : filepath;
    char cmd[1024];
    snprintf(cmd, sizeof cmd, "UPLOAD|%s|%lld|%s\n", base, fsz, shahex);
    if (send_all(fd, cmd, strlen(cmd)) != 0)
        return -1;
    char line[512];
    if (recv_line(fd, line, sizeof line) != 0)
        return -1;
    if (strcmp(line, "READY") != 0) {
        fprintf(stderr, "server: %s\n", line);
        return -1;
    }
    // 发送二进制
    FILE *f = fopen(filepath, "rb");
    if (!f) {
        perror("open");
        return -1;
    }
    const size_t BUF = 8192;
    unsigned char *buf = (unsigned char *)malloc(BUF);
    for (;;) {
        size_t n = fread(buf, 1, BUF, f);
        if (n == 0)
            break;
        if (send_all(fd, buf, n) != 0) {
            fclose(f);
            free(buf);
            return -1;
        }
    }
    free(buf);
    fclose(f);
    // 接收校验结果
    if (recv_line(fd, line, sizeof line) != 0)
        return -1;
    printf("%s\n", line);
    return (strncmp(line, "OK|", 3) == 0) ? 0 : -1;
}

static int action_download(int fd, const char *filename, const char *outpath) {
    char cmd[1024];
    snprintf(cmd, sizeof cmd, "DOWNLOAD|%s\n", filename);
    if (send_all(fd, cmd, strlen(cmd)) != 0)
        return -1;
    char line[512];
    if (recv_line(fd, line, sizeof line) != 0)
        return -1;
    // SIZE|n|sha
    long long size = 0;
    char sha[128];
    if (sscanf(line, "SIZE|%lld|%127s", &size, sha) != 2) {
        fprintf(stderr, "bad header: %s\n", line);
        return -1;
    }
    if (recv_line(fd, line, sizeof line) != 0)
        return -1; // READY
    FILE *f = fopen(outpath, "wb");
    if (!f) {
        perror("open out");
        return -1;
    }
    const size_t BUF = 8192;
    unsigned char *buf = (unsigned char *)malloc(BUF);
    long long remain = size;
    SHA256_CTX ctx;
    SHA256_Init(&ctx);
    while (remain > 0) {
        size_t chunk = (remain > (long long)BUF) ? BUF : (size_t)remain;
        ssize_t r = recv(fd, buf, chunk, 0);
        if (r <= 0) {
            fclose(f);
            free(buf);
            return -1;
        }
        fwrite(buf, 1, (size_t)r, f);
        SHA256_Update(&ctx, buf, (size_t)r);
        remain -= (long long)r;
    }
    unsigned char dg[SHA256_DIGEST_LENGTH];
    SHA256_Final(dg, &ctx);
    char got[SHA256_DIGEST_LENGTH * 2 + 1];
    to_hex(dg, sizeof dg, got, sizeof got);
    free(buf);
    fclose(f);
    if (strcasecmp(got, sha) != 0) {
        fprintf(stderr, "checksum mismatch\n");
        return -1;
    }
    printf("OK|%s\n", got);
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 7) {
        fprintf(stderr,
                "usage: %s <host> <port> login <user> <pass> "
                "<list|upload|download> [file] [out]\n",
                argv[0]);
        return 1;
    }
    const char *host = argv[1];
    int port = atoi(argv[2]);
    if (strcmp(argv[3], "login") != 0) {
        fprintf(stderr, "first command must be 'login'\n");
        return 1;
    }
    const char *user = argv[4];
    const char *pass = argv[5];
    const char *action = argv[6];

    int fd = connect_server(host, port);
    if (fd < 0) {
        perror("connect");
        return 1;
    }
    fprintf(stdout, "connected to %s:%d\n", host, port);
    fflush(stdout);

    if (action_login(fd, user, pass) != 0) {
        close(fd);
        return 1;
    }

    int rc = 0;
    if (strcmp(action, "list") == 0) {
        rc = action_list(fd);
    } else if (strcmp(action, "upload") == 0) {
        if (argc < 8) {
            fprintf(stderr, "upload needs <file>\n");
            rc = 1;
        } else
            rc = action_upload(fd, argv[7]);
    } else if (strcmp(action, "download") == 0) {
        if (argc < 8) {
            fprintf(stderr, "download needs <file> [out]\n");
            rc = 1;
        } else {
            const char *out = (argc >= 9) ? argv[8] : argv[7];
            rc = action_download(fd, argv[7], out);
        }
    } else if (strcmp(action, "quit") == 0) {
        send_all(fd, "QUIT\n", 5);
        char resp[256];
        if (recv_line(fd, resp, sizeof resp) == 0)
            printf("%s\n", resp);
    } else {
        fprintf(stderr, "unknown action: %s\n", action);
        rc = 1;
    }

    close(fd);
    return rc == 0 ? 0 : 1;
}
