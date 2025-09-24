### libipc Deep Dive

#### SharedLogBuffer
- 环形缓冲：`NUM_SLOTS = BUFFER_SIZE / MAX_MSG_SIZE`，每槽包含 `MsgHdr + payload`。
- 分片头 `MsgHdr{len,seq,flags}`，`flags&LAST` 标记消息尾片。

Why：固定槽位便于跨进程共享与 lock 简化；分片能覆盖大消息而不需要一次性大块共享内存。

#### Synchronization
- `sem_empty/sem_full` 控制生产/消费；`pthread_rwlock` 保护读写索引与缓冲区。
- `shm_init()` 以 `PTHREAD_PROCESS_SHARED` 初始化跨进程读写锁与信号量。

Why：
- 使用两个信号量构建经典生产者—消费者背压模型；
- 读写分离锁避免大粒度互斥，提升并发读效率；
- 共享内存 + 最小化内核调用，降低上下文切换成本。

#### APIs
- `shm_write(data,len)`: 循环分片，逐片 `sem_wait(empty)` → `wrlock` → 写 → `rdunlock` → `sem_post(full)`。
- `shm_read(out,cap)`: 循环 `sem_wait(full)` → `rdlock` → 读 → `wrunlock` → `sem_post(empty)`，直至 LAST。
- `shm_cleanup()`: 销毁锁与信号量，分离共享内存。

边界条件：
- 写入前必须 `shm_init`；输出缓冲不足时，`shm_read` 仍会累计 total 长度并返回。
- 生产者可连续写多条消息；消费者按 LAST 聚合恢复消息边界。

#### Usage via Tools
- `ipc_sender`：从文本或文件分片写入共享内存。
- `log_consumer`：阻塞读取并打印/落盘，用于教学与验证。

Why：通过工具链呈现“最小可用”示例，降低理解曲线，也便于在 CI 中进行冒烟验证。


