---
name: slack
description: "Puxa mensagens do Slack sob demanda: /slack #canal [@user] [período] — janela padrão 7d. Snapshots caem na inbox e são processados. Para ENVIAR mensagem, use /outbox — este comando só lê."
---

# /slack — ler um canal ou conversa

1. MCP de busca/leitura do Slack (histórico do canal ou DM). Janela padrão: 7 dias.
2. `./brain snapshot --key slack-<canal-ou-user> --prefix slack`.
3. `/dump` (tipo conector → change digest).
4. Recibo: o que mudou, menções ao dono, decisões/ações extraídas.

**Enviar** é outra porta: `/outbox`. "Responde a fulano" → redija em `/outbox`, nunca `chat.postMessage` direto.
