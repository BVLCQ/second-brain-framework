---
name: publish
description: "Publica um report já gerado no espaço do time (Slack canvas / Drive). Destino precisa estar em [publish].destinations. Cada publicação tem aprovação própria."
---

# /publish — porta do espaço do time

1. O arquivo já existe em `vault/reports/` (`/share` ou `/recap`).
2. Destino em `[publish].destinations`. Se não estiver: mostre a linha e pare.
3. `./brain publish request reports/share/<arquivo> --to "slack:#canal"`.
4. Mostre o conteúdo que vai sair. Espere "ok" / "publica".
5. `./brain publish approve PUB-#### --quote "<literal>"`.
6. Publique **esse** arquivo (hash travado) pelo MCP de escrita do destino.
7. `./brain publish done PUB-#### --link <url>`. Arquivo mudou depois da aprovação = não publique; refaça o pedido.

No noturno esta porta está trancada.
