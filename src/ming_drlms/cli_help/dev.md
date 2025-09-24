# Developer commands (dev)

Run developer/CI helpers under the dev group:

```
ming-drlms dev test ipc
ming-drlms dev test integration --host 127.0.0.1 --port 8080
ming-drlms dev test all

ming-drlms dev coverage run
ming-drlms dev coverage show -

ming-drlms dev pkg build
ming-drlms dev pkg install --sudo
ming-drlms dev pkg uninstall --sudo

ming-drlms dev artifacts run --out artifacts
```

Platform notes:
- These commands target Linux/WSL environments; tools like make, pkill must be available.
