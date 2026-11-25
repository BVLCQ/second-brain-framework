#!/bin/zsh
# Watchdog — a lógica mora em `brain services ensure` (uma fonte). Este script só
# pausa, roda o CLI e guarda o log. LaunchAgent no login e a cada 5 min.
# Pausar: touch ~/.brain-watchdog-off — apagar o arquivo retoma.
set -u
HERE="${0:A:h}"
BRAIN_DIR="${BRAIN_DIR:-${HERE:h}}"
LOG="${WATCHDOG_LOG:-$BRAIN_DIR/vault/logs/watchdog.log}"
mkdir -p "${LOG:h}"
if [[ -f "$LOG" ]]; then
  size=$(stat -f%z "$LOG" 2>/dev/null || stat -c%s "$LOG" 2>/dev/null || echo 0)
  [[ "$size" -gt 1048576 ]] && mv -f "$LOG" "$LOG.1"
fi
[[ -e "$HOME/.brain-watchdog-off" ]] && exit 0
if [[ ! -x "$BRAIN_DIR/brain" ]]; then
  print -r -- "$(date '+%F %T') services: $BRAIN_DIR/brain ausente — pulando" >> "$LOG"
  exit 0
fi
BRAIN_HOME="$BRAIN_DIR" "$BRAIN_DIR/brain" services ensure --reason watchdog >>"$LOG" 2>&1
