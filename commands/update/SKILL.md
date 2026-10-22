---
name: update
description: "O motor completo: puxa as fontes do watch.toml via MCP, grava snapshots, processa a inbox (/dump) e regenera as views. É o que o cron noturno pede ao agente; use também quando o dono quiser atualização geral."
---

# /update — puxar, processar, mostrar

No noturno (`BRAIN_NIGHTLY=1`) isto é o único comando largo permitido. Sem aprovações, sem envio, sem publicação, sem `focus apply` no Google.

0. **Passo 0 — fila de reserva:** `./brain ask list --answered`. Aplique cada resposta do dono antes de puxar qualquer fonte
   (`person alias`, `action open`, reclassificar…) e registre `./brain ask applied ASK-#### --how "…" --prov observado --source chat`.
   Dúvida nova que precisa do dono (identidade, classificação, permissão) vira `./brain ask add "…" [--option …] --context … --run <id da
   rodada> --prov observado --source …`; o recibo só resume ("3 perguntas abertas: ASK-0004…"). No noturno você pode perguntar, não responder.
1. Leia `config/watch.toml`. Fonte não listada = não puxa.
2. Para cada `[[source]]`, use **só** ferramentas MCP de leitura. A janela de leitura (slack, gmail, jira) vem de
`./brain watch since <key> --json` — `since`, `epoch` e `jql` (use no lugar de `-1d`). Não calcule datas; `window = "auto"`
é "desde o último pull". Slack: siga `commands/slack/SKILL.md` (**inclui as threads**). Grave o resultado:

```
./brain snapshot --key <key> --prefix <kind> --ext md
```

(escreva o conteúdo com a ferramenta Write e passe `--file <caminho>`; pipe e heredoc não passam no allowlist). Janela sem nada novo (a leitura funcionou) → `./brain snapshot --key <key> --empty`.
MCP vazio por erro/negação → `--fail "MCP não devolveu nada"` (isso sim é falha).
Fonte com `folder = …`: siga o protocolo de pasta de `commands/drive/SKILL.md` — um `--item` por arquivo e por subpasta (hash próprio), `--rev` + `--check` antes de ler. Pasta sem item novo é silêncio, não falha.
Fonte `kind = "drive-doc"` (playbook de um processo; campos `doc` = id do Drive e `link` = `PROC-…`/`OPP-…`): pegue o `modifiedTime` do doc pelo MCP do Drive (só metadados) e rode `./brain snapshot --key <key> --item <doc> --rev <modifiedTime> --check` — `inalterado` = pule, sem gastar leitura. Se mudou: exporte o doc (Markdown/texto) e grave `./brain snapshot --key <key> --item <doc> --rev <modifiedTime> --name "<título>" --prefix playbook --ext md`. No `/dump` desse snapshot, registre o artefato com `./brain artifact … --link <PROC-…>`; o processo passa a mostrar "playbook atualizado em …".
2+ falhas seguidas da mesma key → **escalar ao dono**: `./brain ask add "A fonte <key> falhou 2× seguidas: …" --kind outro --context <key> --prov observado --source <key>` (e `brain doctor`).
3. `/dump` no que chegou.
4. `./brain render`.
5. Se memória estiver ligada: `./brain memory sync` (falha isolada — não derruba o resto).
6. Recibo: fontes puxadas / sem novidade / falhas · itens processados · avisos do doctor.

Proibido: ferramentas MCP de escrita, `outbox approve/sent`, `publish`, `focus approve/apply` (google), mudanças de PLANNING.
