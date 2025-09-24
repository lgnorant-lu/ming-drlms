### Agent & Tools Deep Dive

#### log_agent
- 采集/上传工具（与服务器文件/日志交互），用于演示/运维场景。

#### ipc_sender / log_consumer
- `ipc_sender` 将文本或文件内容通过共享内存发送，演示 `libipc` 的写入流程与分片机制。
- `log_consumer` 作为消费者读取共享内存消息，便于教学与调试。

#### proc_launcher
- 简化启动流程的实用工具，用于流程化演示或脚本编排。


