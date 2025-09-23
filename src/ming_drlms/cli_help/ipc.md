# IPC help

Send and tail messages via shared memory tools.

## Examples

Send one message from stdin:

```bash
echo "hello" | ming-drlms ipc send
```

Send a file:

```bash
ming-drlms ipc send --file /tmp/file.txt
```

Tail N messages:

```bash
ming-drlms ipc tail -n 3
```
