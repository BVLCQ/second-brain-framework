---
name: connect
description: "Puxa UMA fonte agora via MCP de leitura, snapshota na inbox e processa. Use quando o dono quiser o estado atual antes de uma reunião/decisão."
---

# /connect — uma fonte, agora

1. Identifique a fonte (key do `watch.toml` ou ad-hoc: `jira-PROJ`, `gmail-from:marina-demo`).
2. Leia pelo MCP de leitura correspondente. Fonte do watch: a janela vem de `./brain watch since <key> --json`
   (não calcule datas). Slack: `commands/slack/SKILL.md` (inclui as threads). Sem ferramenta = diga que não dá e pare.
3. `./brain snapshot --key <key> --prefix <kind>`; janela sem nada novo → `--empty`. Sem novidade = uma linha e pare.
4. `/dump` só nesse item. Recibo curto. `./brain render` se nasceu ação/decisão.

Não escreva em Jira/GitHub/Slack/Gmail/Drive. Não "aproveite" para puxar o resto do watch — isso é `/update`.
