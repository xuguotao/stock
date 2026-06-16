#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/reports/runtime}"
PID_DIR="${PID_DIR:-$ROOT_DIR/.runtime}"

mkdir -p "$LOG_DIR" "$PID_DIR"

kill_port() {
  local port="$1"
  local pids
  pids="$(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "Stopping process on port $port: $pids"
    kill $pids 2>/dev/null || true
    sleep 1
  fi

  pids="$(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "Force stopping process on port $port: $pids"
    kill -9 $pids 2>/dev/null || true
  fi
}

wait_port() {
  local port="$1"
  local name="$2"
  local retries=30

  for _ in $(seq 1 "$retries"); do
    if lsof -ti tcp:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "$name is listening on http://$HOST:$port"
      return 0
    fi
    sleep 1
  done

  echo "$name did not start on port $port. Check logs in $LOG_DIR." >&2
  return 1
}

echo "Restarting stock web app..."
echo "Root: $ROOT_DIR"

kill_port "$BACKEND_PORT"
kill_port "$FRONTEND_PORT"

echo "Starting backend..."
(
  cd "$ROOT_DIR"
  nohup uvicorn src.web.backend.app:app --reload --host "$HOST" --port "$BACKEND_PORT" \
    > "$LOG_DIR/backend.log" 2>&1 &
  echo $! > "$PID_DIR/backend.pid"
)

echo "Starting frontend..."
(
  cd "$ROOT_DIR/frontend"
  if [[ ! -d node_modules ]]; then
    npm install
  fi
  nohup npm run dev -- --host "$HOST" --port "$FRONTEND_PORT" \
    > "$LOG_DIR/frontend.log" 2>&1 &
  echo $! > "$PID_DIR/frontend.pid"
)

wait_port "$BACKEND_PORT" "Backend"
wait_port "$FRONTEND_PORT" "Frontend"

echo
echo "Ready:"
echo "  Frontend: http://$HOST:$FRONTEND_PORT"
echo "  Backend:  http://$HOST:$BACKEND_PORT"
echo "  Logs:     $LOG_DIR"
