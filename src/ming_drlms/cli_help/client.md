# Client help

Client operations for server file interactions and log.

## Examples

List files:

```bash
ming-drlms client list -H 127.0.0.1 -p 8080 -u alice -P password
```

Upload a file:

```bash
ming-drlms client upload README.md -H 127.0.0.1 -p 8080 -u alice -P password
```

Download a file:

```bash
ming-drlms client download README.md -o /tmp/README.md -H 127.0.0.1 -p 8080 -u alice -P password
```

Send a LOG message:

```bash
ming-drlms client log "hello" -H 127.0.0.1 -p 8080 -u alice -P password
```
