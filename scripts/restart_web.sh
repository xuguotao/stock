#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_DIR/.env"
  set +a
fi

HOST="${HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_PROXY_HOST="${BACKEND_PROXY_HOST:-127.0.0.1}"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/reports/runtime}"
PID_DIR="${PID_DIR:-$ROOT_DIR/.runtime}"
BACKEND_SESSION="${BACKEND_SESSION:-stock-web-backend}"
FRONTEND_SESSION="${FRONTEND_SESSION:-stock-web-frontend}"

mkdir -p "$LOG_DIR" "$PID_DIR"

shell_quote() {
  printf "%q" "$1"
}

stop_screen_session() {
  local session="$1"
  if command -v screen >/dev/null 2>&1 && screen -ls | grep -q "[.]$session[[:space:]]"; then
    echo "Stopping screen session $session"
    screen -S "$session" -X quit >/dev/null 2>&1 || true
    sleep 1
  fi
}

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

detect_lan_host() {
  if [[ -n "${PUBLIC_HOST:-}" ]]; then
    echo "$PUBLIC_HOST"
    return 0
  fi

  if command -v ipconfig >/dev/null 2>&1; then
    local service
    for service in en0 en1; do
      local address
      address="$(ipconfig getifaddr "$service" 2>/dev/null || true)"
      if [[ -n "$address" ]]; then
        echo "$address"
        return 0
      fi
    done
  fi

  if command -v hostname >/dev/null 2>&1; then
    local address
    address="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
    if [[ -n "$address" ]]; then
      echo "$address"
      return 0
    fi
  fi

  echo "$HOST"
}

echo "Restarting stock web app..."
echo "Root: $ROOT_DIR"

stop_screen_session "$BACKEND_SESSION"
stop_screen_session "$FRONTEND_SESSION"
kill_port "$BACKEND_PORT"
kill_port "$FRONTEND_PORT"

echo "Starting backend..."
backend_cmd="cd $(shell_quote "$ROOT_DIR") && exec uvicorn src.web.backend.app:app --reload --host $(shell_quote "$HOST") --port $(shell_quote "$BACKEND_PORT") >> $(shell_quote "$LOG_DIR/backend.log") 2>&1"
: > "$LOG_DIR/backend.log"
if command -v screen >/dev/null 2>&1; then
  screen -dmS "$BACKEND_SESSION" bash -lc "$backend_cmd"
  echo "$BACKEND_SESSION" > "$PID_DIR/backend.session"
else
  nohup bash -lc "$backend_cmd" >/dev/null 2>&1 &
  echo $! > "$PID_DIR/backend.pid"
fi

echo "Starting frontend..."
frontend_cmd="cd $(shell_quote "$ROOT_DIR/frontend") && if [[ ! -d node_modules ]]; then npm install; fi && BACKEND_HOST=$(shell_quote "$BACKEND_PROXY_HOST") BACKEND_PORT=$(shell_quote "$BACKEND_PORT") exec npm run dev -- --host $(shell_quote "$HOST") --port $(shell_quote "$FRONTEND_PORT") >> $(shell_quote "$LOG_DIR/frontend.log") 2>&1"
: > "$LOG_DIR/frontend.log"
if command -v screen >/dev/null 2>&1; then
  screen -dmS "$FRONTEND_SESSION" bash -lc "$frontend_cmd"
  echo "$FRONTEND_SESSION" > "$PID_DIR/frontend.session"
else
  nohup bash -lc "$frontend_cmd" >/dev/null 2>&1 &
  echo $! > "$PID_DIR/frontend.pid"
fi

wait_port "$BACKEND_PORT" "Backend"
wait_port "$FRONTEND_PORT" "Frontend"

LAN_HOST="$(detect_lan_host)"

echo
echo "Ready:"
echo "  Frontend: http://$LAN_HOST:$FRONTEND_PORT"
echo "  Backend:  http://$LAN_HOST:$BACKEND_PORT"
echo "  Bind:     $HOST"
echo "  Logs:     $LOG_DIR"
if command -v screen >/dev/null 2>&1; then
  echo "  Sessions: $BACKEND_SESSION, $FRONTEND_SESSION"
fi
