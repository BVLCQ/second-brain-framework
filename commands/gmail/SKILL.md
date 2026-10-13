---
name: gmail
description: "Puxa emails via MCP de leitura: snapshot na inbox → /dump → digest. /gmail [janela|filtro]. Nunca compõe/envia email."
---

# /gmail — ler a caixa

1. MCP Gmail de leitura (`search_threads` / `get_thread`). Janela padrão: hoje. Filtro do dono ("da Ana", "assunto X") vira query.
2. `./brain snapshot --key gmail-<janela-ou-filtro> --prefix gmail`.
3. `/dump`. Digest: o que é novo, o que cobra o dono, o que parece fechar ação (isso vira **proposta**, não fecho).
4. Nunca rascunhe/envie email. Mensagem para alguém = `/outbox` (Slack) ou o dono escreve o email.

Não use o conector Python da v1 — ele não existe mais.
