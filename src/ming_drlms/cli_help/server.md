# Server help

Start, stop and inspect the DRLMS server.

## Examples

Start (non-strict, local data dir):

```bash
ming-drlms server-up -p 8080 -d server_files --no-strict
```

Status:

```bash
ming-drlms server-status -p 8080
```

Stop:

```bash
ming-drlms server-down
```
