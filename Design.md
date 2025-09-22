## DRLMS Design Notes

### User Management (users.txt) via CLI

- Storage file: `$DRLMS_DATA_DIR/users.txt` (default `server_files/users.txt`).
- New entries format: `user::<argon2id_encoded_string>`.
- Legacy entries (read-only): `user:salt:sha256hex(password+salt)`.
- Hashing: Argon2id using argon2-cffi with defaults matching server:
  - `t_cost=2`, `m_cost=65536`, `parallelism=1`, `hash_len=32`, `salt_len=16`.
  - Overridable via env: `DRLMS_ARGON2_T_COST`, `DRLMS_ARGON2_M_COST`, `DRLMS_ARGON2_PARALLELISM`.
- Concurrency safety: write to `.users.txt.<pid>.tmp` in same dir, `fsync`, then atomic `os.replace`; set file mode to `0600` when possible.
- CLI commands: `user add|passwd|del|list`.
  - `add`: create argon2id user (interactive password double-entry).
  - `passwd`: update existing user only (error if missing).
  - `del`: delete user, `--force` ignores missing.
  - `list`: table by default, `--json` for automation.

### Error Handling

- Input validation: username matches `^[A-Za-z0-9_.\-]{1,32}$`.
- Exit codes: 0 success; 1 I/O or existence conflict; 2 argument/validation errors.

### Compatibility

- Server supports legacy format and transparently upgrades on successful login; CLI never writes legacy.
- CLI allows editing while server is running thanks to atomic write discipline.


