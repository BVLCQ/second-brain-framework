---
name: update
description: "O motor completo: puxa as fontes do watch.toml via MCP, grava snapshots, processa a inbox (/dump) e regenera as views. É o que o cron noturno pede ao agente; use também quando o dono quiser atualização geral."
---

# /update — puxar, processar, mostrar

No noturno (`BRAIN_NIGHTLY=1`) isto é o único comando largo permitido. Sem aprovações, sem envio, sem publicação, sem `focus apply` no Google.

1. Leia `config/watch.toml`. Fonte não listada = não puxa.
2. Para cada `[[source]]`, use **só** ferramentas MCP de leitura. Grave o resultado:

```
./brain snapshot --key <key> --prefix <kind> --ext md
```

(stdin = o conteúdo; ou `--file`). Vazio → `--fail "MCP não devolveu nada"`.
2+ falhas seguidas da mesma key → **escalar ao dono** (`brain doctor`).
3. `/dump` no que chegou.
4. `./brain render`.
5. Se memória estiver ligada: `./brain memory sync` (falha isolada — não derruba o resto).
6. Recibo: fontes puxadas / sem novidade / falhas · itens processados · avisos do doctor.

Proibido: ferramentas MCP de escrita, `outbox approve/sent`, `publish`, `focus approve/apply` (google), mudanças de PLANNING.
