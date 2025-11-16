#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
source_env_for_python_tests

RUNNER_OS="${RUNNER_OS:-$(uname -s)}"

printf 'Python version: %s
' "$(python --version 2>&1)"
printf 'Python executable: %s
' "$(command -v python)"
printf 'Working directory: %s
' "$(pwd)"
env | grep -E "(QT_|PROTOCOL_BUFFERS|DRLMS|LD_|DYLD_|PATH)" | sort || true

if [[ "$RUNNER_OS" == "Windows" ]]; then
  export PATH="${ROOT_DIR}/build/_deps/signal-install/bin;${ROOT_DIR}/build/RelWithDebInfo;${ROOT_DIR}/build;${ROOT_DIR}/vcpkg_installed/x64-windows/bin;${PATH}"
fi

python -c "import google.protobuf; print('Protobuf version:', google.protobuf.__version__)"
python -c "from google.protobuf import descriptor as _descriptor; print('Protobuf implementation file:', _descriptor.__file__)"
python -c "import google.protobuf.pyext; print('C extension available')" 2>/dev/null || echo "C extension NOT available"

python -m pytest tests/python/test_cli_client_unit.py -v
python -c "import subprocess, sys; subprocess.run([sys.executable, '-m', 'pytest', 'tests/python/test_cli_demo_unit.py', '-v'], check=True, timeout=60)"
python -m pytest -m "not integration" tests/python --ignore=tests/python/test_cli_client_unit.py --ignore=tests/python/test_cli_demo_unit.py --tb=short -x
