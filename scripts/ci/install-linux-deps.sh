#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

sudo apt-get update
sudo apt-get install -y build-essential cmake libssl-dev libargon2-dev netcat-openbsd lcov clang-format cppcheck protobuf-c-compiler libprotobuf-c-dev

