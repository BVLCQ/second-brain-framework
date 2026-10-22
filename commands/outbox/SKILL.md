---
name: outbox
description: "Redige uma mensagem, mostra o texto EXATO, espera 'enviar 1' (ou equivalente), envia pelo Slack MCP como o dono e registra o permalink. Use quando o dono pedir para cobrar, avisar ou responder alguém."
---

# /outbox — o cérebro escreve; o dono manda

1. Destinatário precisa estar em `[outbound].allow` (`config/brain.toml`). Se não estiver: mostre a linha a acrescentar e **pare** — não envie.
2. Redija o texto que o dono vai assinar (curto, sem jargão interno, sem IDs ACT-#### no corpo). Grave:

```
./brain outbox draft --to <id-ou-#canal> --text "…" --ref ACT-#### --why "cobrar dependência"
```

3. Mostre o texto **inteiro** no chat, numerado se houver mais de um rascunho. Peça aprovação explícita do texto (`enviar 1`, "ok, manda").
4. `./brain outbox approve MSG-#### --quote "<literal>"`.
5. Envie pelo MCP do Slack **exatamente** o que `./brain outbox show MSG-####` imprime. Como o dono, não como bot, se a ferramenta permitir.
6. `./brain outbox sent MSG-#### --link <permalink>`. Falhou: `outbox failed MSG-#### --error "…"`.
7. Texto mudou depois da aprovação = `outbox cancel` e rascunho novo. Aprovação não é herdada.

Teto: `[outbound].daily_max`. No noturno esta porta está trancada.
