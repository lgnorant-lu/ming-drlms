#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

OPENSSL_PREFIX=$(brew --prefix openssl@3)
ARGON2_PREFIX=$(brew --prefix argon2)
cat <<'EOF'
Setting macOS environment variables for Homebrew deps.
EOF

echo "OPENSSL_ROOT_DIR=${OPENSSL_PREFIX}" >> "$GITHUB_ENV"
echo "LDFLAGS=-L${OPENSSL_PREFIX}/lib -L${ARGON2_PREFIX}/lib" >> "$GITHUB_ENV"
echo "CPPFLAGS=-I${OPENSSL_PREFIX}/include -I${ARGON2_PREFIX}/include" >> "$GITHUB_ENV"
echo "PKG_CONFIG_PATH=${OPENSSL_PREFIX}/lib/pkgconfig:${ARGON2_PREFIX}/lib/pkgconfig:${PKG_CONFIG_PATH:-}" >> "$GITHUB_ENV"
