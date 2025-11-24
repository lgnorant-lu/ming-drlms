#!/usr/bin/env bash
# Final Acceptance Test for TUI Robustness (Phase 13, Batch C)
# 验收测试：TUI 健壮性集成 - AC-1, AC-2, AC-3

set -euo pipefail

echo "========================================="
echo "TUI Robustness Final Acceptance Test"
echo "Testing: Connection State, Auto-Reconnect, UX"
echo "========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Find server binary
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SERVER_CANDIDATES=(
  "${PROJECT_ROOT}/build/log_collector_server"
  "${PROJECT_ROOT}/log_collector_server"
)

SERVER_BIN=""
for candidate in "${SERVER_CANDIDATES[@]}"; do
  if [[ -x "$candidate" ]]; then
    SERVER_BIN="$candidate"
    break
  fi
done

if [[ -z "$SERVER_BIN" ]]; then
  echo -e "${RED}[FAIL]${NC} Server binary not found. Please build first:"
  echo "  cmake --build build"
  exit 1
fi

echo -e "${GREEN}[OK]${NC} Found server: $SERVER_BIN"
echo ""

# Cleanup function
cleanup() {
  echo ""
  echo "[Cleanup] Stopping server..."
  pkill -f log_collector_server || true
  sleep 1
}
trap cleanup EXIT

# Step 1: Start server
echo "========================================="
echo "[Step 1] Starting server..."
echo "========================================="

export DRLMS_DATA_DIR="${PROJECT_ROOT}"
export DRLMS_PORT=15035

pkill -f log_collector_server || true
sleep 1

"$SERVER_BIN" > /tmp/acceptance_server.log 2>&1 &
SERVER_PID=$!
sleep 2

if ! ps -p $SERVER_PID > /dev/null; then
  echo -e "${RED}[FAIL]${NC} Server failed to start"
  cat /tmp/acceptance_server.log
  exit 1
fi

echo -e "${GREEN}[OK]${NC} Server started with PID: $SERVER_PID"
echo ""

# Step 2: Prompt user to start TUI
echo "========================================="
echo "[Step 2] Manual TUI Verification"
echo "========================================="
echo ""
echo "Please open a PowerShell window and run:"
echo -e "  ${YELLOW}ming-drlms tui${NC}"
echo ""
echo "Then perform the following checks:"
echo ""
echo "✓ [AC-1] Connection State Binding:"
echo "  1. Observe status bar shows: '○ Connecting...'"
echo "  2. After ~1-2 seconds: '● Connected (XXms)'"
echo "  3. Color changes: yellow → green"
echo ""
echo "✓ [AC-2] Auto-Reconnect Test:"
echo "  4. Press [Enter] here to kill server..."
read -p "" </dev/tty

# Kill server
echo "[Killing server...]"
kill $SERVER_PID
sleep 2

echo ""
echo "  5. Observe TUI status: '◐ Reconnecting... (attempt N)'"
echo "  6. Color changes: green → orange/yellow"
echo "  7. Error message (max 1 per 5 seconds): friendly format"
echo "  8. TUI does NOT crash"
echo ""
echo "  Press [Enter] to restart server..."
read -p "" </dev/tty

# Restart server
echo "[Restarting server...]"
"$SERVER_BIN" > /tmp/acceptance_server_2.log 2>&1 &
SERVER_PID=$!
sleep 2

if ! ps -p $SERVER_PID > /dev/null; then
  echo -e "${RED}[FAIL]${NC} Server failed to restart"
  exit 1
fi

echo -e "${GREEN}[OK]${NC} Server restarted with PID: $SERVER_PID"
echo ""
echo "  9. Observe TUI auto-recovers: '● Connected (XXms)'"
echo "  10. Can send/receive messages normally"
echo ""

# Step 3: Check error classification
echo "========================================="
echo "[Step 3] Error Classification Test"
echo "========================================="
echo ""
echo "In TUI, try sending a message. You should see:"
echo "  - Messages appear in chat area"
echo "  - Auto-scroll to bottom"
echo "  - Timestamp format: [HH:MM]"
echo ""
echo "Press [Enter] to continue..."
read -p "" </dev/tty

# Step 4: Check persistence
echo "========================================="
echo "[Step 4] Message Persistence Check"
echo "========================================="
echo ""
echo "1. Send a test message: 'test persistence'"
echo "2. Exit TUI (Ctrl+C or Ctrl+D)"
echo "3. Restart TUI: ming-drlms tui"
echo "4. Verify: Old messages NOT repeated (阅后即焚模式)"
echo "   - If you see history: last_seen_event_id is working"
echo "   - If no history: since_id=0 default behavior"
echo ""
echo "Press [Enter] when done..."
read -p "" </dev/tty

# Step 5: Final checklist
echo "========================================="
echo "[Step 5] Final Acceptance Checklist"
echo "========================================="
echo ""
echo "Please confirm the following:"
echo ""
read -p "☐ Status indicator shows 4 states correctly? (y/n): " status_ok
read -p "☐ Auto-reconnect works without crash? (y/n): " reconnect_ok
read -p "☐ Error messages friendly & throttled? (y/n): " error_ok
read -p "☐ Messages auto-scroll to bottom? (y/n): " scroll_ok
read -p "☐ Reconnect attempt counter visible? (y/n): " counter_ok
read -p "☐ RTT displayed on connection? (y/n): " rtt_ok

echo ""
echo "========================================="
echo "Test Results Summary"
echo "========================================="

PASS_COUNT=0
TOTAL=6

[[ "$status_ok" == "y" ]] && ((PASS_COUNT++)) && echo -e "${GREEN}✓${NC} AC-1: Status binding" || echo -e "${RED}✗${NC} AC-1: Status binding"
[[ "$reconnect_ok" == "y" ]] && ((PASS_COUNT++)) && echo -e "${GREEN}✓${NC} AC-2: Auto-reconnect" || echo -e "${RED}✗${NC} AC-2: Auto-reconnect"
[[ "$scroll_ok" == "y" ]] && ((PASS_COUNT++)) && echo -e "${GREEN}✓${NC} AC-3: Message scroll" || echo -e "${RED}✗${NC} AC-3: Message scroll"
[[ "$error_ok" == "y" ]] && ((PASS_COUNT++)) && echo -e "${GREEN}✓${NC} TD-2: Error classification" || echo -e "${RED}✗${NC} TD-2: Error classification"
[[ "$counter_ok" == "y" ]] && ((PASS_COUNT++)) && echo -e "${GREEN}✓${NC} TD-3: Reconnect counter" || echo -e "${RED}✗${NC} TD-3: Reconnect counter"
[[ "$rtt_ok" == "y" ]] && ((PASS_COUNT++)) && echo -e "${GREEN}✓${NC} TD-4: RTT display" || echo -e "${RED}✗${NC} TD-4: RTT display"

echo ""
echo "Score: $PASS_COUNT/$TOTAL"

if [[ $PASS_COUNT -eq $TOTAL ]]; then
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${GREEN}✓ ALL ACCEPTANCE CRITERIA PASSED ✓${NC}"
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""
  echo "Phase 13, Batch C: TUI Robustness Integration - COMPLETE"
  echo "You may now proceed to production deployment."
  exit 0
else
  echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${RED}✗ SOME TESTS FAILED (${PASS_COUNT}/${TOTAL}) ✗${NC}"
  echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""
  echo "Please review failed items and re-test."
  exit 1
fi
