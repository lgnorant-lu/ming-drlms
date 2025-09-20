#!/usr/bin/env bash
set -euo pipefail
HOST=${1:-127.0.0.1}
PORT=${2:-8080}
FILE=${3:-README.md}
OUT=${4:-/tmp/README.md}

# Minimal mode for coverage collection: run only positive flows
if [[ "${COVERAGE_MIN:-0}" == "1" ]]; then
  ./log_agent "$HOST" "$PORT" login alice password list >/dev/null 2>&1 || true
  if [[ -f "$FILE" ]]; then
    ./log_agent "$HOST" "$PORT" login alice password upload "$FILE" >/dev/null 2>&1 || true
  fi
  ./log_agent "$HOST" "$PORT" login alice password download "$FILE" "$OUT" >/dev/null 2>&1 || true
  echo "OK (minimal)"
  exit 0
fi

# list
./log_agent "$HOST" "$PORT" login alice password list | sed -n '1,10p'

# upload
if [[ -f "$FILE" ]]; then
  ./log_agent "$HOST" "$PORT" login alice password upload "$FILE" | sed -n '1,5p'
fi

# list again
./log_agent "$HOST" "$PORT" login alice password list | sed -n '1,10p'

# download
./log_agent "$HOST" "$PORT" login alice password download "$FILE" "$OUT" | sed -n '1,5p'

echo "OK"

# Negative cases
echo "-- NEG: NOTFOUND --"
./log_agent "$HOST" "$PORT" login alice password download __no_such_file__ /tmp/nope 2>/dev/null || true
echo "-- NEG: AUTH (missing login) --"
printf "LIST\n" | ./log_agent "$HOST" "$PORT" || true
echo "-- NEG: EXISTS (re-upload same file) --"
if [[ -f "$FILE" ]]; then
  ./log_agent "$HOST" "$PORT" login alice password upload "$FILE" >/dev/null 2>&1 || true
  ./log_agent "$HOST" "$PORT" login alice password upload "$FILE" | sed -n '1,3p' || true
fi

# CHECKSUM mismatch in a single connection
echo "-- NEG: CHECKSUM (mismatch) --"
if command -v nc >/dev/null 2>&1; then
  printf "LOGIN|alice|password\nUPLOAD|fake.bin|16|0000000000000000000000000000000000000000000000000000000000000000\n" | nc "$HOST" "$PORT" > /tmp/up_hdr.txt || true
  head -c 16 /dev/zero | nc "$HOST" "$PORT" || true
  sed -n '1,3p' /tmp/up_hdr.txt || true
else
  bash -lc 'exec 3<>/dev/tcp/'"$HOST"'/'"$PORT"'; \
    echo -e "LOGIN|alice|password\nUPLOAD|fake.bin|16|0000000000000000000000000000000000000000000000000000000000000000" >&3; \
    IFS= read -r l1 <&3; echo "$l1"; IFS= read -r l2 <&3; echo "$l2"; \
    head -c 16 /dev/zero >&3; IFS= read -r l3 <&3; echo "$l3"; exec 3>&- 3<&-' || true
fi

# BUSY requires server configured with DRLMS_MAX_CONN=1
echo "-- NEG: BUSY (need DRLMS_MAX_CONN=1) --"
if command -v timeout >/dev/null 2>&1; then
  timeout 2 bash -lc 'exec 3<>/dev/tcp/'"$HOST"'/'"$PORT"'; echo -e "LOGIN|alice|password" >&3; sleep 2' >/dev/null 2>&1 &
  ./log_agent "$HOST" "$PORT" login alice password list | sed -n '1,3p' || true
else
  echo "(skip BUSY: timeout not available)"
fi
