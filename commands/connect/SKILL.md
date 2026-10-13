---
name: connect
description: "Puxa UMA fonte agora via MCP de leitura, snapshota na inbox e processa. Use quando o dono quiser o estado atual antes de uma reunião/decisão."
---

# /connect — uma fonte, agora

1. Identifique a fonte (key do `watch.toml` ou ad-hoc: `jira-PROJ`, `gmail-from:ana`).
2. Leia pelo MCP de leitura correspondente. Sem ferramenta = diga que não dá e pare.
3. `./brain snapshot --key <key> --prefix <kind>`. Sem novidade = uma linha e pare.
4. `/dump` só nesse item. Recibo curto. `./brain render` se nasceu ação/decisão.

Não escreva em Jira/GitHub/Slack/Gmail/Drive. Não "aproveite" para puxar o resto do watch — isso é `/update`.
