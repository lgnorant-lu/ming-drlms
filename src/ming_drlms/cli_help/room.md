# Room help

Manage room metadata under the space group.

- info: query owner, policy, subs, last_event_id
- set-policy: owner only; set retain/delegate/teardown
- transfer: owner only; transfer ownership to another user

## Examples

Info:

```bash
ming-drlms space room info --room demo -H 127.0.0.1 -p 8080 -u alice -P password
```

Set policy:

```bash
ming-drlms space room set-policy --room demo --policy delegate -H 127.0.0.1 -p 8080 -u alice -P password
```

Transfer ownership:

```bash
ming-drlms space room transfer --room demo --new-owner bob -H 127.0.0.1 -p 8080 -u alice -P password
```
