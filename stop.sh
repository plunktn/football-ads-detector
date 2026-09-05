#!/usr/bin/env bash
# Detiene backend + frontend arrancados con start.sh (o por puerto).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-43124}"
FRONTEND_PORT="${FRONTEND_PORT:-43123}"
ALT_FRONTEND_PORT="${ALT_FRONTEND_PORT:-43125}"
LOG_DIR="${ROOT}/.run"

kill_port() {
  local port="$1"
  local pids
  pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "→ Matando puerto $port (PID: $pids)"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 0.5
    pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      # shellcheck disable=SC2086
      kill -9 $pids 2>/dev/null || true || echo "  (no pude matar $pids — hazlo a mano)"
    fi
  fi
}

if [[ -f "$LOG_DIR/backend.pid" ]]; then
  kill "$(cat "$LOG_DIR/backend.pid")" 2>/dev/null || true
  rm -f "$LOG_DIR/backend.pid"
fi
if [[ -f "$LOG_DIR/frontend.pid" ]]; then
  kill "$(cat "$LOG_DIR/frontend.pid")" 2>/dev/null || true
  rm -f "$LOG_DIR/frontend.pid"
fi

kill_port "$BACKEND_PORT"
kill_port "$FRONTEND_PORT"
kill_port "$ALT_FRONTEND_PORT"
echo "✓ Detenido."
