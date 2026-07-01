#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_LABEL="com.xuguotao.stock.data-ops-runner"
TASK_GROUP="${TASK_GROUP:-}"
if [[ -n "$TASK_GROUP" ]]; then
  LABEL="com.xuguotao.stock.data-ops-runner.$TASK_GROUP"
else
  LABEL="$BASE_LABEL"
fi
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
PYTHON_BIN="${PYTHON_BIN:-}"
DATA_OPS_LOG_DIR="${DATA_OPS_LOG_DIR:-$ROOT_DIR/logs}"
if [[ -n "$TASK_GROUP" ]]; then
  RUNNER_LOG="$DATA_OPS_LOG_DIR/data_ops_runner_${TASK_GROUP}.log"
else
  RUNNER_LOG="$DATA_OPS_LOG_DIR/data_ops_runner.log"
fi
# launchd will run: python -m src.data_ops.runner
# default relative log path: logs/data_ops_runner.log

usage() {
  echo "Usage: TASK_GROUP={realtime|intraday|maintenance} $0 {install|uninstall|status}"
}

validate_task_group() {
  case "$TASK_GROUP" in
    ""|realtime|intraday|maintenance) ;;
    *)
      echo "invalid TASK_GROUP: $TASK_GROUP" >&2
      exit 2
      ;;
  esac
}

resolve_python_bin() {
  if [[ -z "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(command -v python3 || command -v python || true)"
  elif [[ "$PYTHON_BIN" != /* ]]; then
    PYTHON_BIN="$(command -v "$PYTHON_BIN")"
  fi
  if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
    echo "python executable not found; set PYTHON_BIN=/absolute/path/to/python" >&2
    exit 1
  fi
}

append_env_if_set() {
  local key="$1"
  local value="${!key:-}"
  if [[ -n "$value" ]]; then
    cat >> "$PLIST" <<PLIST
    <key>$key</key>
    <string>$value</string>
PLIST
  fi
}

write_plist() {
  validate_task_group
  resolve_python_bin
  mkdir -p "$(dirname "$PLIST")" "$DATA_OPS_LOG_DIR"
  cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>WorkingDirectory</key>
  <string>$ROOT_DIR</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>-m</string>
    <string>src.data_ops.runner</string>
PLIST
  if [[ -n "$TASK_GROUP" ]]; then
    cat >> "$PLIST" <<PLIST
    <string>--task-group</string>
    <string>$TASK_GROUP</string>
PLIST
  fi
  cat >> "$PLIST" <<PLIST
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>DATA_OPS_LOG_DIR</key>
    <string>$DATA_OPS_LOG_DIR</string>
    <key>DATA_OPS_RUNNER_ID</key>
    <string>${DATA_OPS_RUNNER_ID:-data-ops-${TASK_GROUP:-launchd}}</string>
PLIST
  append_env_if_set DATA_OPS_CLICKHOUSE_HOST
  append_env_if_set DATA_OPS_CLICKHOUSE_USER
  append_env_if_set DATA_OPS_CLICKHOUSE_PASSWORD
  append_env_if_set DATA_OPS_CLICKHOUSE_DATABASE
  cat >> "$PLIST" <<PLIST
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$RUNNER_LOG</string>
  <key>StandardErrorPath</key>
  <string>$RUNNER_LOG</string>
</dict>
</plist>
PLIST
}

case "${1:-}" in
  install)
    write_plist
    launchctl unload "$PLIST" >/dev/null 2>&1 || true
    launchctl load "$PLIST"
    echo "installed $LABEL"
    ;;
  uninstall)
    validate_task_group
    launchctl unload "$PLIST" >/dev/null 2>&1 || true
    rm -f "$PLIST"
    echo "uninstalled $LABEL"
    ;;
  status)
    validate_task_group
    launchctl list | grep "$LABEL" || true
    echo "log: $RUNNER_LOG"
    ;;
  *)
    usage
    exit 2
    ;;
esac
