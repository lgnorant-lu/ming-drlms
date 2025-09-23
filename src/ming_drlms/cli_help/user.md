# User management help

This topic explains how to manage `$DRLMS_DATA_DIR/users.txt` safely.

- Formats:
  - Legacy (read-only): `user:salt:shahex`
  - Argon2id (recommended): `user::$argon2id$...`
- Concurrency: atomic writes (tmp + fsync + replace), safe while server runs.
- Security: avoid plain passwords in shell history. Prefer stdin.

## Examples

Add user (stdin):

```bash
echo "p@ssw0rd" | ming-drlms user add alice -d server_files -x
```

Change password (stdin):

```bash
echo "newpass" | ming-drlms user passwd alice -d server_files -x
```

List users:

```bash
ming-drlms user list -d server_files --json
```

Delete user:

```bash
ming-drlms user del alice -d server_files
```
