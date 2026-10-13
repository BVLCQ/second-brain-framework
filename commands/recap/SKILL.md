---
name: recap
description: "Gera documento datado e compartilhável em vault/reports/ com o histórico e impacto de um goal, projeto ou período. Use quando o dono pedir recap, impacto, retrospectiva ou 'o que fizemos de X'."
---

# /recap — história e impacto

1. Identifique o alvo: `G#`, `P#` ou período `AAAA-MM-DD:AAAA-MM-DD`.
2. `./brain share goal|project|period <alvo> --format md` (e `--format html` se for para apresentação).
3. Se o dono quiser narrativa além do export (contexto, o que NÃO aconteceu, próximos passos): escreva um Markdown extra em `vault/reports/recap-<data>-<slug>.md` usando só fatos do ledger/artefatos, cada um com fonte. Sem fonte = "não declarado".
4. Ofereça `/publish` se for para o time, ou o caminho do arquivo se for para um colega.

Não reescreva recap antigo — gere outro.
