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
./brain share portfolio [--area <slug|nome>] --format html     # /share portfolio: roadmap priorizado
./brain share opportunity OPP-#### --format md                  # one-pager de uma oportunidade
```

`portfolio` exporta o ranking por pontuação de prioridade, a matriz impacto × facilidade, o que está em andamento e o funil por status — sem IDs internos no texto (só na seção de fontes). `--area` recorta uma área.

O arquivo é pontual — não é atualizado. Mostre o caminho e peça que o dono revise antes de encaminhar. Para publicar no espaço do time (Slack/Drive), use `/publish` (outro gate).
