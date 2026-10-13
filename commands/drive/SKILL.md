---
name: drive
description: "Docs vivos do Drive via MCP de leitura: snapshot datado na inbox → /dump (change digest). /drive <termo> busca, /drive <id> exporta. Nunca cria/edita docs."
---

# /drive — ler um doc

1. MCP Google Drive: busca ou exporta o arquivo (Markdown/texto).
2. `./brain snapshot --key gdoc-<id-ou-slug> --prefix gdoc`.
3. `/dump`. Primeira vez = estado inicial; seguintes = o que mudou.
4. Nunca crie, edite, comente ou compartilhe pelo MCP. Publicar um report no Drive é `/publish` (porta com gate).
