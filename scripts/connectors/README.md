# Conectores — pull-only, read-only

Cada conector LÊ uma fonte externa e escreve um snapshot Markdown em
`vault/RAW/inbox/` (prefixo da fonte no nome). O processamento (`/dump`) faz o resto.
**Nenhum conector escreve em ferramenta externa — não existe chamada de escrita
no código, por design.** Tokens read-only em `config/.env` (chmod 600).

> **Gmail e Drive** também são scripts (OAuth read-only via
> `google_auth.py` — guia [`guides/google-oauth.md`](../guides/google-oauth.md);
> skills `commands/gmail` e `commands/drive`). Mesma disciplina: leitura →
> snapshot → /dump.

## Uso

```bash
cd <instância>
python3 scripts/connectors/jira.py        # escopos do config/watch.yaml
python3 scripts/connectors/github.py      # repos do watch.yaml
python3 scripts/connectors/slack.py       # watchlist (canais + users)
python3 scripts/connectors/slack.py #canal 30d   # sob demanda (/slack)
python3 scripts/connectors/slack.py @user        # sob demanda (/slack)
bash scripts/nightly-update.sh            # todos + /update via agente headless
```

Zero dependências: só stdlib (urllib). Opcional: PyYAML (senão, parse
minimalista embutido lê o watch.yaml).

## Como obter cada token (tudo read-only)

### Jira
id.atlassian.net → Security → **API token** (criar). Escopo natural da conta —
o conector só faz `GET /search`. Preencha `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_TOKEN`.

### GitHub
Settings → Developer settings → **Fine-grained tokens** → selecionar APENAS os
repos do watch.yaml → permissões: Contents **Read-only**, Issues **Read-only**,
Pull requests **Read-only**. `GITHUB_TOKEN`.

### Slack
Criar app (api.slack.com/apps → From scratch) → OAuth & Permissions →
**User token** (xoxp-) com escopos: `channels:history`, `groups:history`,
`im:history` (DMs), `mpim:history`, `channels:read`, `groups:read`,
`im:read`, `users:read`, `users:read.email`. Instalar no workspace.
`SLACK_TOKEN`.

> DMs (`/slack @user`) dependem de `im:history` — sem ele o conector reporta
> erro de escopo (por design: reporta, não insiste).

## Estado

`config/.state.json` guarda o hash do último snapshot por fonte — mudou = novo
snapshot; idêntico = silêncio (change digest acontece no /dump). Nunca commitar.

## Adicionar um conector novo (padrão)

1. `scripts/connectors/<fonte>.py` — stdlib apenas, import `common`.
2. `load_env()` → leia o que precisa → GET read-only → markdown →
   `write_snapshot("<fonte>-", …)` → `changed_since_last` → `save_state`.
3. Regra de ouro: se o método HTTP não for GET, o código está errado.
