#!/usr/bin/env bash
# Second Brain — nightly: conectores + /update via agente headless.
# Agende (instância): launchd ou cron às ~05:00. O /brief da manhã detecta
# se não rodou e faz catch-up — nada apodrece em silêncio.
#
# O log desta execução mora em vault/logs/nightly.log — DENTRO da zona cega
# do git — porque o output do agente pode citar assunto de email, nomes de
# cards etc. (o vault é do dono; o repo nunca vê).
set -uo pipefail
cd "$(dirname "$0")/.."

mkdir -p vault/logs
exec >> vault/logs/nightly.log 2>&1
echo "──── nightly $(date '+%Y-%m-%d %H:%M') ────"

# 1. Conectores (pull-only) — cada um é isolado: erro não derruba os demais
for c in jira github slack gmail gdrive; do
  if python3 "scripts/connectors/${c}.py"; then :; else
    echo "AVISO: conector ${c} falhou — seguindo" >&2
  fi
done

# 2. Lembrete semanal de reauth Google (auto-gateado; silêncio se token ok)
bash scripts/google-reauth-reminder.sh || true

# 3. Backup semanal do vault (domingo) — a única exceção de escrita, ver guides/backup.md
DOW=$(date +%u)  # 1=seg … 7=dom
if [ "$DOW" = "7" ] && [ -f config/.env ]; then
  python3 scripts/connectors/backup.py || echo "AVISO: backup falhou — verificando na próxima" >&2
fi

# 3. /update via agente headless — AJUSTE PARA SEU AGENTE (um só):
AGENT_CMD="${AGENT_CMD:-codex exec}"           # alternativa: claude -p
if command -v codex >/dev/null 2>&1; then
  $AGENT_CMD "/update"
elif command -v claude >/dev/null 2>&1; then
  claude -p "/update"
else
  echo "AVISO: nenhum agente headless encontrado — inbox acumula para o /dump manual" >&2
fi
