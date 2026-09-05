#!/usr/bin/env bash
# Arranca backend (43124) + frontend (43123) del Football Ads Detector.
#
# Uso:
#   ./start.sh
#   FRONTEND_PORT=43125 ./start.sh   # si 43123 está ocupado
#   ./stop.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-43124}"
FRONTEND_PORT="${FRONTEND_PORT:-43123}"
LOG_DIR="${ROOT}/.run"
mkdir -p "$LOG_DIR"

port_pids() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null || true
}

kill_port() {
  local port="$1"
  local pids
  pids="$(port_pids "$port")"
  if [[ -z "$pids" ]]; then
    return 0
  fi
  echo "→ Liberando puerto $port (PID: $pids)"
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  sleep 1
  pids="$(port_pids "$port")"
  if [[ -n "$pids" ]]; then
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
    sleep 0.5
  fi
  pids="$(port_pids "$port")"
  if [[ -n "$pids" ]]; then
    echo "ERROR: no pude liberar el puerto $port (PID: $pids)."
    echo "  Corre en tu terminal:  kill -9 $pids"
    echo "  O arranca en otro puerto: FRONTEND_PORT=43125 ./start.sh"
    return 1
  fi
}

if [[ ! -x "$ROOT/backend/.venv/bin/python" ]]; then
  echo "ERROR: falta backend/.venv. Crea el venv e instala requirements.txt primero."
  exit 1
fi

if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "→ Instalando dependencias del frontend…"
  (cd "$ROOT/frontend" && npm install)
fi

kill_port "$BACKEND_PORT"
kill_port "$FRONTEND_PORT"

echo "→ Backend  http://127.0.0.1:${BACKEND_PORT}"
(
  cd "$ROOT/backend"
  exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload
) >"$LOG_DIR/backend.log" 2>&1 &
echo $! >"$LOG_DIR/backend.pid"

echo "→ Frontend http://localhost:${FRONTEND_PORT}"
(
  cd "$ROOT/frontend"
  # package.json fija -p 43123; override con next si el puerto cambia
  if [[ "$FRONTEND_PORT" == "43123" ]]; then
    exec npm run dev
  else
    exec env WATCHPACK_POLLING=true WATCHPACK_POLLING_INTERVAL=1000 \
      npx next dev -H 0.0.0.0 -p "$FRONTEND_PORT"
  fi
) >"$LOG_DIR/frontend.log" 2>&1 &
echo $! >"$LOG_DIR/frontend.pid"

for _ in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

if ! curl -sf "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1; then
  echo "✗ API no respondió. Ver $LOG_DIR/backend.log"
  exit 1
fi

# Espera frontend Ready (hasta ~20s)
frontend_ok=0
for _ in $(seq 1 40); do
  if curl -sf --max-time 1 "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1; then
    frontend_ok=1
    break
  fi
  # Si el log ya marcó EADDRINUSE, aborta pronto
  if grep -q "EADDRINUSE" "$LOG_DIR/frontend.log" 2>/dev/null; then
    break
  fi
  sleep 0.5
done

echo
echo "✓ API OK  $(curl -s "http://127.0.0.1:${BACKEND_PORT}/health")"
if [[ "$frontend_ok" -eq 1 ]]; then
  echo "✓ UI OK"
else
  echo "✗ UI no respondió en :${FRONTEND_PORT}. Ver $LOG_DIR/frontend.log"
  if grep -q "EADDRINUSE" "$LOG_DIR/frontend.log" 2>/dev/null; then
    echo "  Puerto ocupado. Prueba: kill -9 \$(lsof -tiTCP:${FRONTEND_PORT} -sTCP:LISTEN)"
    echo "  O: FRONTEND_PORT=43125 ./start.sh"
  fi
  exit 1
fi

echo
echo "Listo."
echo "  UI:  http://localhost:${FRONTEND_PORT}"
echo "  API: http://127.0.0.1:${BACKEND_PORT}"
echo "  Logs: $LOG_DIR/{backend,frontend}.log"
echo "  Parar: ./stop.sh"
