---
name: update
description: "O motor completo: puxa as fontes do watch.toml via MCP, grava snapshots, processa a inbox (/dump) e regenera as views. É o que o cron noturno pede ao agente; use também quando o dono quiser atualização geral."
---

# /update — puxar, processar, mostrar

No noturno (`BRAIN_NIGHTLY=1`) isto é o único comando largo permitido. Sem aprovações, sem envio, sem publicação, sem `focus apply` no Google.

1. Leia `config/watch.toml`. Fonte não listada = não puxa.
2. Para cada `[[source]]`, use **só** ferramentas MCP de leitura. A janela de leitura (slack, gmail, jira) vem de
`./brain watch since <key> --json` — `since`, `epoch` e `jql` (use no lugar de `-1d`). Não calcule datas; `window = "auto"`
é "desde o último pull". Slack: siga `commands/slack/SKILL.md` (**inclui as threads**). Grave o resultado:

```
./brain snapshot --key <key> --prefix <kind> --ext md
```

(stdin = o conteúdo; ou `--file`). Janela sem nada novo (a leitura funcionou) → `./brain snapshot --key <key> --empty`.
MCP vazio por erro/negação → `--fail "MCP não devolveu nada"` (isso sim é falha).
Fonte com `folder = …`: siga o protocolo de pasta de `commands/drive/SKILL.md` — um `--item` por arquivo e por subpasta (hash próprio), `--rev` + `--check` antes de ler. Pasta sem item novo é silêncio, não falha.
2+ falhas seguidas da mesma key → **escalar ao dono** (`brain doctor`).
3. `/dump` no que chegou.
4. `./brain render`.
5. Se memória estiver ligada: `./brain memory sync` (falha isolada — não derruba o resto).
6. Recibo: fontes puxadas / sem novidade / falhas · itens processados · avisos do doctor.

Proibido: ferramentas MCP de escrita, `outbox approve/sent`, `publish`, `focus approve/apply` (google), mudanças de PLANNING.
