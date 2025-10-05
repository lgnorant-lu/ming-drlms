# Windows IPC 设计提案（M-Infra.3 阶段预研）

> 目的：为 `libipc` 模块在 Windows 平台上的共享内存与同步原语提供可行的 Win32 实现路线，降低后续研发不确定性。

## 1. 背景与目标

当前 `libipc` 在 Linux/macOS 上依赖 System V 共享内存 (`shmget`/`shmat`) 与 POSIX 信号量 (`sem_init`/`sem_wait`) 构建环形日志缓冲区。Windows 平台缺乏直接等价的 API，需要重新设计：

- **共享内存**：基于 `CreateFileMappingW` / `MapViewOfFile` 实现命名内存段，跨进程共享。
- **同步原语**：使用 Win32 `CreateSemaphoreW` / `WaitForSingleObject` / `ReleaseSemaphore` 实现跨进程信号量。
- **键值兼容**：维持 `platform_ipc_key_t` 为 32-bit 键，以便延续现有 `DRLMS_SHM_KEY` 环境变量的语义。

## 2. 总体架构

```
+-------------------+                      +---------------------------+
| 进程 A            |                      | 进程 B                    |
| shm_init()        |                      | shm_init()                |
|                   |  映射同名段         |                           |
| CreateFileMapping | <------------------> | OpenFileMapping          |
| MapViewOfFile     |                      | MapViewOfFile             |
| CreateSemaphoreW  |  共享名称与初值     | OpenSemaphoreW            |
+-------------------+                      +---------------------------+
```

- **共享内存命名方案**：
  - 统一使用 `Global\drlms_shm_<KEY>`（KEY 为 8 位十六进制）。
  - `platform_shm_acquire` 负责构造名称并创建/打开 `HANDLE`，返回 `platform_shm_handle_t`。
- **信号量命名方案**：
  - 使用 `Global\drlms_sem_<PID>_<SEQ>` 格式，确保全局唯一。
  - 初始化进程写入 `wchar_t name[]` 字段到共享内存对象，后续进程通过 `OpenSemaphoreW` 附加。

## 3. 关键函数伪代码

### 3.1 共享内存获取 `platform_shm_acquire`

```c
int platform_shm_acquire(uint32_t key, size_t size, HANDLE *out_handle, int *out_created) {
    wchar_t name[64];
    swprintf(name, L"Global\\drlms_shm_%08lx", key);
    HANDLE h = CreateFileMappingW(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE,
                                  (DWORD)(size >> 32), (DWORD)size, name);
    if (!h) return win32_error_to_errno(GetLastError());
    if (out_created) *out_created = (GetLastError() != ERROR_ALREADY_EXISTS);
    *out_handle = h;
    return 0;
}
```

### 3.2 信号量初始化 `platform_semaphore_init`

```c
int platform_semaphore_init(platform_semaphore_t *sem, int shared, unsigned value) {
    memset(sem, 0, sizeof(*sem));
    if (shared) {
        generate_global_name(sem->name, L"Global\\drlms_sem_%08lx_%08lx_%06ld", pid, tid, counter++);
    }
    sem->handle = CreateSemaphoreW(NULL, value, LONG_MAX,
                                   shared ? sem->name : NULL);
    if (!sem->handle) return -1;
    sem->is_named = shared;
    return 0;
}
```

### 3.3 信号量附着 `platform_semaphore_attach`

```c
int platform_semaphore_attach(platform_semaphore_t *sem) {
    if (!sem->is_named) {
        /* 非共享，结构体内 handle 已可用 */
        return sem->handle ? 0 : -1;
    }
    if (!sem->handle) {
        HANDLE h = OpenSemaphoreW(SEMAPHORE_ALL_ACCESS, FALSE, sem->name);
        if (!h) return -1;
        sem->handle = h;
    }
    return 0;
}
```

### 3.4 清理 `shm_cleanup`

- `platform_semaphore_detach`: `CloseHandle`。
- `platform_shm_unmap`: `UnmapViewOfFile`。
- `platform_shm_release`: `CloseHandle`，最后一个句柄关闭即回收资源。

## 4. 错误处理与兼容性

| 场景 | Win32 返回值 | 对应 `errno` | 说明 |
| ---- | ------------- | ------------- | ---- |
| `CreateFileMappingW` 返回 `NULL` | `GetLastError()` | `EACCES` / `ENOMEM` / `EINVAL` | 根据错误码转换，初版可统一映射为 `EACCES` 并在日志中打印 Win32 错误码 |
| `WaitForSingleObject` 返回 `WAIT_ABANDONED` | - | `EOWNERDEAD` | 当前方案认为不期望出现，可记录日志后继续 |
| 信号量命名冲突 | `ERROR_ALREADY_EXISTS` | `EEXIST` | 初始化端可重试生成名称 |

为了保留原逻辑，`platform_ipc_key_t` 继续视作 `uint32_t`，并在 `shared_buffer.c` 中维持现有环境变量解析。不需要修改上层调用。

## 5. 后续行动项

1. **完善错误映射**：实现 `win32_error_to_errno` 帮助函数，提供更准确的 `errno` 值。
2. **信号量释放策略**：研究 `CreateSemaphoreW` 命名空间（`Global` vs `Local`）与权限设置，确保服务模式和 UAC 下正常运行。
3. **读写锁 unlock 策略**：针对 SRWLOCK 设计线程本地存储，区分 Shared/Exclusive，确保 `platform_rwlock_unlock` 正确释放。
4. **资源可视化工具**：编写调试脚本检查 `Handle` 泄露，可借助 `Process Explorer`.

---

该方案已在 `src/platform/windows/` 中提供初始骨架实现，下一步将基于该设计完成剩余函数，并导入到 `libipc` 的 Windows 适配路径中。
