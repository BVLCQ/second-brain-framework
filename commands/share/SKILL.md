---
name: share
description: "Gera um export autocontido (HTML ou Markdown) em vault/reports/share/ para mandar a um colega. Sem jargão interno, sem lista 'observando', sem rascunhos. Use quando o dono pedir 'me dá um status do P1 pra enviar'."
---

# /share — export para colega

```
./brain share project P1 --format html
./brain share goal G1 --format md
./brain share status
./brain share period 2026-09-01:2026-09-30 --format html
```

O arquivo é pontual — não é atualizado. Mostre o caminho e peça que o dono revise antes de encaminhar. Para publicar no espaço do time (Slack/Drive), use `/publish` (outro gate).
