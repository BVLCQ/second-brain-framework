#!/bin/zsh
# Watchdog dos serviços locais do Segundo Cérebro — rodado pelo LaunchAgent no login e a cada 5 min.
# Religa o que estiver fora: servidor do LM Studio, VM do OrbStack, container do Hindsight.
# O inverso (descarregar modelos ociosos) é o idle_unload.py, num LaunchAgent próprio a cada minuto.
# Pausar (ex.: desligar o OrbStack de propósito): touch ~/.brain-watchdog-off — apagar o arquivo retoma.
set -u

HERE="${0:A:h}"
BRAIN_DIR="${BRAIN_DIR:-${HERE:h}}"
LOG="${WATCHDOG_LOG:-$BRAIN_DIR/vault/logs/watchdog.log}"
CONFIG_TOML="$BRAIN_DIR/config/brain.toml"
ENV_FILE="$BRAIN_DIR/config/.env"
LMS="${LMS:-$HOME/.lmstudio/bin/lms}"
ORBCTL="${ORBCTL:-/opt/homebrew/bin/orbctl}"
DOCKER="${DOCKER:-/Applications/OrbStack.app/Contents/MacOS/xbin/docker}"
CURL="${CURL:-/usr/bin/curl}"
WATCHDOG_LMS_TRIES="${WATCHDOG_LMS_TRIES:-6}"
WATCHDOG_LMS_SLEEP="${WATCHDOG_LMS_SLEEP:-5}"
WATCHDOG_HEALTH_TRIES="${WATCHDOG_HEALTH_TRIES:-18}"
WATCHDOG_SLEEP="${WATCHDOG_SLEEP:-10}"

mkdir -p "${LOG:h}"
# rotação simples: passa de 1 MB, guarda só a cópia anterior
[[ -f "$LOG" && $(stat -f%z "$LOG") -gt 1048576 ]] && mv -f "$LOG" "$LOG.1"
log() { print -r -- "$(date '+%F %T') $*" >> "$LOG"; }

[[ -e "$HOME/.brain-watchdog-off" ]] && exit 0

# 1. LM Studio (servidor OpenAI-compatible na 1234; os modelos carregam sob demanda — JIT)
if ! $CURL -sf -m 5 http://127.0.0.1:1234/v1/models >/dev/null; then
  if [[ -x "$LMS" ]]; then
    log "lmstudio: fora do ar — subindo"
    "$LMS" daemon up >>"$LOG" 2>&1
    "$LMS" server start >>"$LOG" 2>&1
    lms_up=0
    for (( i=1; i<=WATCHDOG_LMS_TRIES; i++ )); do
      if $CURL -sf -m 5 http://127.0.0.1:1234/v1/models >/dev/null; then
        lms_up=1
        break
      fi
      sleep "$WATCHDOG_LMS_SLEEP"
    done
    if (( lms_up )); then
      log "lmstudio: servidor no ar em :1234"
    else
      log "lmstudio: timeout aguardando :1234 responder (30s)"
    fi
  else
    log "lmstudio: fora do ar e $LMS ausente — pulando"
  fi
fi

# 2. OrbStack (a VM; o container sobe junto pelo restart: unless-stopped)
if [[ "$($ORBCTL status 2>/dev/null)" != "Running" ]]; then
  log "orbstack: VM parada — subindo"
  $ORBCTL start >>"$LOG" 2>&1
fi

# Deriva o modo de memória de [memory] em config/brain.toml (espelha brainlib/memory.py:mode)
mem_mode="embed"
mem_emb="local"                   # padrão de fábrica de [memory].embeddings_provider (brainlib/config.py)
if [[ -f "$CONFIG_TOML" ]]; then
  in_memory=0
  has_memory_section=0
  mem_engine=""
  mem_extract=""
  while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
    raw_line="${raw_line%$'\r'}"
    line="${raw_line%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue
    if [[ "$line" == \[*\] ]]; then
      if [[ "$line" == "[memory]" ]]; then
        in_memory=1
        has_memory_section=1
      else
        in_memory=0
      fi
      continue
    fi
    if (( in_memory )) && [[ "$line" == *=* ]]; then
      key="${line%%=*}"
      val="${line#*=}"
      key="${key#"${key%%[![:space:]]*}"}"
      key="${key%"${key##*[![:space:]]}"}"
      val="${val#"${val%%[![:space:]]*}"}"
      val="${val%"${val##*[![:space:]]}"}"
      if [[ "$val" == \"*\" || "$val" == \'*\' ]]; then
        val="${val:1:-1}"
      fi
      if [[ "$key" == "engine" ]]; then
        mem_engine="$val"
      elif [[ "$key" == "extract" ]]; then
        mem_extract="$val"
      elif [[ "$key" == "embeddings_provider" ]]; then
        mem_emb="$val"
      fi
    fi
  done < "$CONFIG_TOML"
  if (( has_memory_section )); then
    if [[ "$mem_engine" != "hindsight" ]]; then
      mem_mode="none"
    elif [[ "${mem_extract:l}" == "true" ]]; then
      mem_mode="full"
    else
      mem_mode="embed"
    fi
  fi
fi
if [[ "$mem_mode" == "none" ]]; then
  log "hindsight: modo none — pulando"
  exit 0
fi

# 3. Hindsight — dá até 3 min para o container ficar saudável antes de agir
for (( i=1; i<=WATCHDOG_HEALTH_TRIES; i++ )); do
  $CURL -s -m 5 http://127.0.0.1:8888/health | grep -q connected && exit 0
  sleep "$WATCHDOG_SLEEP"
done
# full com embeddings locais: o Hindsight checa o LM Studio no boot — com :1234 fora do ar o contêiner morre de
# novo, então recriá-lo a cada 5 min só enche o log. O passo 1 já tentou subir o servidor; o que falta é do dono.
if [[ "$mem_mode" == "full" && "$mem_emb" == "local" ]] \
    && ! $CURL -sf -m 5 http://127.0.0.1:1234/v1/models >/dev/null; then
  log "hindsight: sem health e o LM Studio (embeddings local no full) não responde em :1234 — não recrio o contêiner (morreria no boot); rode: brain setup --only memoria"
  exit 0
fi
state_raw="$($DOCKER inspect -f '{{.State.Status}}|{{.State.Restarting}}' hindsight 2>/dev/null || true)"
c_status="${state_raw%%|*}"
c_restarting="${state_raw#*|}"
[[ -z "$c_status" ]] && c_status="ausente"
[[ -z "$c_restarting" || "$c_restarting" == "$state_raw" ]] && c_restarting="false"
compose_args=(compose)
if [[ "$mem_mode" == "full" ]]; then
  if [[ -f "$ENV_FILE" ]]; then
    compose_args+=(--env-file "$ENV_FILE")
  else
    log "hindsight: aviso — modo full sem $ENV_FILE; rodando compose.full.yaml sem --env-file"
  fi
fi
compose_args+=(-f "$HERE/compose.yaml")
if [[ "$mem_mode" == "full" ]]; then
  compose_args+=(-f "$HERE/compose.full.yaml")
fi
compose_args+=(up -d)
compose_out="$($DOCKER "${compose_args[@]}" 2>&1)"
[[ -n "$compose_out" ]] && print -r -- "$compose_out" >> "$LOG"
if [[ "$compose_out" == *(Created|Started|Recreated)* ]]; then
  log "hindsight: sem health (estado: $c_status) — container subido/recriado via docker compose up -d, modo: $mem_mode"
elif [[ "$compose_out" == *Running* ]]; then
  log "hindsight: sem health (estado: $c_status, restarting=$c_restarting) — compose up -d não alterou (Container hindsight Running)"
else
  log "hindsight: sem health (estado: $c_status, restarting=$c_restarting) — docker compose up -d terminou sem iniciar container"
fi
