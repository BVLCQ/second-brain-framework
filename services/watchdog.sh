#!/bin/zsh
# Watchdog dos serviços locais do Segundo Cérebro — rodado pelo LaunchAgent no login e a cada 5 min.
# Religa o que estiver fora: servidor do LM Studio, VM do OrbStack, container do Hindsight.
# O inverso (descarregar modelos ociosos) é o idle_unload.py, num LaunchAgent próprio a cada minuto.
# Pausar (ex.: desligar o OrbStack de propósito): touch ~/.brain-watchdog-off — apagar o arquivo retoma.
set -u

HERE="${0:A:h}"
LOG="$HERE/../vault/logs/watchdog.log"
LMS="$HOME/.lmstudio/bin/lms"
ORBCTL=/opt/homebrew/bin/orbctl
DOCKER=/Applications/OrbStack.app/Contents/MacOS/xbin/docker
CURL=/usr/bin/curl

mkdir -p "${LOG:h}"
# rotação simples: passa de 1 MB, guarda só a cópia anterior
[[ -f "$LOG" && $(stat -f%z "$LOG") -gt 1048576 ]] && mv -f "$LOG" "$LOG.1"
log() { print -r -- "$(date '+%F %T') $*" >> "$LOG"; }

[[ -e "$HOME/.brain-watchdog-off" ]] && exit 0

# 1. LM Studio (servidor OpenAI-compatible na 1234; os modelos carregam sob demanda — JIT)
if ! $CURL -sf -m 5 http://127.0.0.1:1234/v1/models >/dev/null; then
  log "lmstudio: fora do ar — subindo"
  "$LMS" daemon up >>"$LOG" 2>&1
  "$LMS" server start >>"$LOG" 2>&1
fi

# 2. OrbStack (a VM; o container sobe junto pelo restart: unless-stopped)
if [[ "$($ORBCTL status 2>/dev/null)" != "Running" ]]; then
  log "orbstack: VM parada — subindo"
  $ORBCTL start >>"$LOG" 2>&1
fi

# 3. Hindsight — dá até 3 min para o container ficar saudável antes de agir
for _ in {1..18}; do
  $CURL -s -m 5 http://127.0.0.1:8888/health | grep -q connected && exit 0
  sleep 10
done
log "hindsight: sem health — docker compose up -d"
$DOCKER compose -f "$HERE/compose.yaml" up -d >>"$LOG" 2>&1
