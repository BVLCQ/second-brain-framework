#!/usr/bin/env bash
# Second Brain — nightly: conectores + /update via agente headless.
# Agende (instância): launchd ou cron às ~05:00. O /brief da manhã detecta
# se não rodou e faz catch-up — nada apodrece em silêncio.
set -uo pipefail
cd "$(dirname "$0")/.."

# 1. Conectores (pull-only) — cada um é isolado: erro não derruba os demais
for c in jira github slack gmail gdrive; do
  if python3 "scripts/connectors/${c}.py"; then :; else
    echo "AVISO: conector ${c} falhou — seguindo" >&2
  fi
done

# 2. /update via agente headless — AJUSTE PARA SEU AGENTE (um só):
AGENT_CMD="${AGENT_CMD:-codex exec}"           # alternativa: claude -p
if command -v codex >/dev/null 2>&1; then
  $AGENT_CMD "/update"
elif command -v claude >/dev/null 2>&1; then
  claude -p "/update"
else
  echo "AVISO: nenhum agente headless encontrado — inbox acumula para o /dump manual" >&2
fi
