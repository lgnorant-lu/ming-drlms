# Space help

Subscribe, publish and fetch history in shared rooms.

## Examples

Join:

```bash
ming-drlms space join -r demo -H 127.0.0.1 -p 8080 -R -j
```

Send text / file:

```bash
ming-drlms space send -r demo -t "hello"
ming-drlms space send -r demo -f /tmp/file.txt
```

History:

```bash
ming-drlms space history -r demo -n 10 -s 0
```
