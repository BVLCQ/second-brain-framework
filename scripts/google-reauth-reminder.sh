#!/usr/bin/env bash
# Lembrete semanal: refresh token Google (app em Testing expira em ~7 dias).
# Não imprime segredo. Escreve nota na inbox (entra pelo /dump normal) no
# máximo 1× por semana. Graduado de instância real (dia 1 de uso — obrigado!).
set -uo pipefail
cd "$(dirname "$0")/.."

INBOX="vault/RAW/inbox"
STATE="config/.state.json"
TODAY="$(date +%F)"
WEEK_KEY="$(date +%G-W%V)"
NOTE="$INBOX/reminder-google-oauth-${TODAY}.md"

# já lembramos nesta semana?
if [[ -f "$STATE" ]] && grep -q "\"google_reauth_week\": \"${WEEK_KEY}\"" "$STATE" 2>/dev/null; then
  exit 0
fi
if ls "$INBOX"/reminder-google-oauth-*.md >/dev/null 2>&1; then
  exit 0
fi

reason="GOOGLE_* ausente ou placeholder — Gmail/Drive ainda não autenticam"
if python3 - <<'PY' >/dev/null 2>&1
import os, sys
sys.path.insert(0, "scripts/connectors")
import common
common.load_env()
cid = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
sec = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
ref = os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip()
if not cid or "xxxx" in cid or not sec or "xxxx" in sec or not ref or "xxxx" in ref:
    sys.exit(2)
try:
    common.google_access_token()
except SystemExit:
    sys.exit(3)
sys.exit(0)
PY
then
  exit 0   # token válido — silêncio
else
  code=$?
  if [[ $code -eq 3 ]]; then
    reason="refresh token inválido/expirado (invalid_grant) — rode google_auth.py de novo"
  fi
fi

mkdir -p "$INBOX"
cat > "$NOTE" <<EOF
# Lembrete · OAuth Google (Gmail + Drive)

tipo: nota solta
data: ${TODAY}

Reautorizar Gmail/Drive. ${reason}.

Passos (sem colar token no chat):
1. Projeto GCP com Gmail API + Drive API habilitadas.
2. App em Production (Testing = refresh token de 7 dias = este lembrete toda semana).
3. \`python3 scripts/connectors/google_auth.py\` e cole o refresh só no config/.env.

Guia: guides/google-oauth.md
EOF

python3 - <<PY
import json
from pathlib import Path
p = Path("config/.state.json")
state = {}
if p.exists():
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        state = {}
state["google_reauth_week"] = "${WEEK_KEY}"
p.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY

echo "google-reauth-reminder: nota em $NOTE"
