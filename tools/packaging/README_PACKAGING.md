# Packaging Overview

## Docker（当前阶段不推荐，等待包管理器发布稳定后再启用）
（本仓库暂不在 README 与 CI 中公开 Docker 使用流程，避免误导。）

## Debian (.deb) via fpm
Prereqs:
```
sudo apt-get update && sudo apt-get install -y ruby-dev build-essential rpm
sudo gem install --no-document fpm
```
Build:
```
make all
mkdir -p pkgroot/opt/drlms pkgroot/var/lib/drlms pkgroot/var/log/drlms
install -m755 log_collector_server log_agent proc_launcher log_consumer ipc_sender pkgroot/opt/drlms
cp -f libipc.so pkgroot/opt/drlms
fpm -s dir -t deb -n drlms-server -v 1.0.0 \
  --description "Distributed Real-time Log Monitoring Server" \
  --deb-systemd tools/packaging/systemd/drlms.service \
  --prefix / -C pkgroot \
  opt/drlms var/lib/drlms var/log/drlms
```
Install:
```
sudo dpkg -i drlms-server_1.0.0_amd64.deb
sudo systemctl enable --now drlms
```

## PyPI (CLI)
The GitHub workflow `.github/workflows/release.yml` publishes CLI when triggered with `version`.
Locally:
```
python -m pip install --upgrade pip build twine
python -m build tools/cli
python -m twine upload tools/cli/dist/*
```
