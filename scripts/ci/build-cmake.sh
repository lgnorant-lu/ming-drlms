#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

RUNNER_OS="${RUNNER_OS:-$(uname -s)}"
CMAKE_BIN="$(command -v cmake || true)"
if [[ -z "$CMAKE_BIN" ]]; then
  if [[ "$RUNNER_OS" == "Linux" ]]; then
    CMAKE_BIN="/usr/bin/cmake"
  elif [[ "$RUNNER_OS" == "macOS" ]]; then
    HOMEBREW_PREFIX=$(brew --prefix)
    CMAKE_BIN="${HOMEBREW_PREFIX}/bin/cmake"
  fi
fi
if [[ -z "$CMAKE_BIN" ]]; then
  echo "cmake not found" >&2
  exit 1
fi

BUILD_CONFIG=""
CMAKE_ARGS=(-DENABLE_TESTS=ON)
if [[ "$RUNNER_OS" == "Windows" ]]; then
  export PATH="${ROOT_DIR}/build/_deps/signal-install/bin;${ROOT_DIR}/build/RelWithDebInfo;${ROOT_DIR}/build;${ROOT_DIR}/vcpkg_installed/x64-windows/bin;${PATH}"
  [[ -n "${CMAKE_TOOLCHAIN_FILE:-}" ]] && CMAKE_ARGS+=("-DCMAKE_TOOLCHAIN_FILE=${CMAKE_TOOLCHAIN_FILE}")
  [[ -n "${VCPKG_TARGET_TRIPLET:-}" ]] && CMAKE_ARGS+=("-DVCPKG_TARGET_TRIPLET=${VCPKG_TARGET_TRIPLET}")
  BUILD_CONFIG="--config RelWithDebInfo"
fi

echo "Configuring CMake ($RUNNER_OS)..." >&2
"${CMAKE_BIN}" -S . -B build "${CMAKE_ARGS[@]}"
"${CMAKE_BIN}" --build build ${BUILD_CONFIG}
