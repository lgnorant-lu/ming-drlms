#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <time.h>
#if !defined(_WIN32)
#include <unistd.h>
#include <sys/stat.h>
#else
#include <windows.h>
#endif
#include "platform/compat.h"
#include "../libipc/shared_buffer.h"

// 文件元信息结构（与 ipc_sender.c 保持一致）
typedef struct {
    uint32_t magic;        // 魔数 0x4D455441 ('META')
    char filename[256];    // 文件名
    uint64_t filesize;     // 文件大小（字节）
    char checksum[65];     // SHA256校验和（十六进制）
    time_t modified_time;  // 修改时间
    uint8_t transfer_mode; // 传输模式（0=二进制）
    uint8_t reserved[3];   // 对齐
    char sender[64];       // 发送者标识
    uint32_t sequence;     // 序列号
    uint8_t padding[100];  // 填充到512字节
} FileMetadata;

static void print_usage(const char *prog) {
    fprintf(stderr, "用法: %s [--output DIR] [--key HEX]\n", prog);
    fprintf(stderr, "  --output, -o  输出目录（默认: ./received/）\n");
    fprintf(stderr, "  --key, -k     共享内存键值（十六进制）\n");
    fprintf(stderr, "\n示例:\n");
    fprintf(stderr, "  %s --output ./downloads/\n", prog);
}

#if defined(_WIN32)
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
#endif

int main(int argc, char **argv) {
    const char *output_dir = "./received/";
    const char *key_hex = NULL;

    // 解析命令行参数
    for (int i = 1; i < argc; ++i) {
        if ((strcmp(argv[i], "--output") == 0 || strcmp(argv[i], "-o") == 0) &&
            i + 1 < argc) {
            output_dir = argv[++i];
        } else if ((strcmp(argv[i], "--key") == 0 ||
                    strcmp(argv[i], "-k") == 0) &&
                   i + 1 < argc) {
            key_hex = argv[++i];
        } else if (strcmp(argv[i], "--help") == 0 ||
                   strcmp(argv[i], "-h") == 0) {
            print_usage(argv[0]);
            return 0;
        }
    }

    if (key_hex && *key_hex) {
        setenv("DRLMS_SHM_KEY", key_hex, 1);
    }

    // 初始化共享内存
    if (shm_init() != 0) {
        fprintf(stderr, "ERR: shm_init 失败\n");
        return 1;
    }

    fprintf(stderr, "文件接收端已启动，等待文件...\n");
    fprintf(stderr, "输出目录: %s\n", output_dir);

    // 创建输出目录
#if defined(_WIN32)
    CreateDirectoryA(output_dir, NULL);
#else
    mkdir(output_dir, 0755);
#endif

    int file_count = 0;

    // 循环接收文件
    while (1) {
        unsigned char buffer[65536];
        ssize_t n;

        // ===== 第一步：接收并解析元信息 =====
        fprintf(stderr, "\n[等待] 正在接收文件元信息...\n");
        n = shm_read(buffer, sizeof(buffer));
        if (n < (ssize_t)sizeof(FileMetadata)) {
            fprintf(stderr,
                    "ERR: 接收到的数据过短 (%zd 字节)，预期至少 %zu 字节\n", n,
                    sizeof(FileMetadata));
            continue;
        }

        FileMetadata meta;
        memcpy(&meta, buffer, sizeof(FileMetadata));

        // 验证魔数
        if (meta.magic != 0x4D455441) {
            fprintf(stderr, "WARN: 魔数不匹配 (0x%08X)，跳过\n", meta.magic);
            continue;
        }

        // 显示元信息
        fprintf(stderr, "\n=== 文件元信息 ===\n");
        fprintf(stderr, "  文件名: %s\n", meta.filename);
        fprintf(stderr, "  大小: %llu 字节 (%.2f KB)\n",
                (unsigned long long)meta.filesize, meta.filesize / 1024.0);
        fprintf(stderr, "  发送者: %s\n", meta.sender);
        fprintf(stderr, "  序列号: %u\n", meta.sequence);
        fprintf(stderr, "  校验和: %s\n", meta.checksum);

        // 显示修改时间
        if (meta.modified_time > 0) {
            char timebuf[64];
#if defined(_WIN32)
            struct tm tm_local;
            localtime_s(&tm_local, &meta.modified_time);
            strftime(timebuf, sizeof(timebuf), "%Y-%m-%d %H:%M:%S", &tm_local);
#else
            strftime(timebuf, sizeof(timebuf), "%Y-%m-%d %H:%M:%S",
                     localtime(&meta.modified_time));
#endif
            fprintf(stderr, "  修改时间: %s\n", timebuf);
        }
        fprintf(stderr, "==================\n\n");

        // 构造输出路径
        char outpath[1024];
        snprintf(outpath, sizeof(outpath), "%s%s", output_dir, meta.filename);

        // 打开输出文件
        FILE *out = fopen(outpath, "wb");
        if (!out) {
            fprintf(stderr, "ERR: 无法创建文件 %s: %s\n", outpath,
                    strerror(errno));
            continue;
        }

        // ===== 第二步：接收文件内容 =====
        fprintf(stderr, "[接收] 正在接收文件内容...\n");
        size_t total_received = 0;

        while (total_received < meta.filesize) {
            n = shm_read(buffer, sizeof(buffer));
            if (n <= 0) {
                fprintf(stderr, "\nERR: 读取文件内容失败 (已接收 %zu 字节)\n",
                        total_received);
                break;
            }

            fwrite(buffer, 1, n, out);
            total_received += n;

            // 显示进度
            if (meta.filesize > 0) {
                fprintf(stderr, "  进度: %zu / %llu 字节 (%.1f%%)\r",
                        total_received, (unsigned long long)meta.filesize,
                        100.0 * total_received / meta.filesize);
            }
        }

        fclose(out);
        fprintf(stderr, "\n");

        // 验证完整性
        if (total_received == meta.filesize) {
            fprintf(stderr, "[SUCCESS] 文件接收完成: %s (%zu 字节)\n", outpath,
                    total_received);
            file_count++;
        } else {
            fprintf(stderr, "[WARN] 文件大小不匹配: 预期 %llu, 实际 %zu\n",
                    (unsigned long long)meta.filesize, total_received);
        }

        // 恢复文件修改时间（可选）
#if !defined(_WIN32)
        if (meta.modified_time > 0) {
            struct stat st;
            if (stat(outpath, &st) == 0) {
                struct timespec times[2];
                times[0].tv_sec = st.st_atime; // 保留访问时间
                times[0].tv_nsec = 0;
                times[1].tv_sec = meta.modified_time; // 设置修改时间
                times[1].tv_nsec = 0;
                utimensat(AT_FDCWD, outpath, times, 0);
            }
        }
#endif
    }

    shm_cleanup();
    fprintf(stderr, "\n总共接收 %d 个文件\n", file_count);
    return 0;
}
