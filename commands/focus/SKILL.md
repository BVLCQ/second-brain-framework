---
name: focus
description: "Planeja blocos de foco nas SUAS ações (EDF), mostra o lote, espera um 'ok' e só então aplica no calendário ou gera .ics. Use quando o dono pedir 'agenda meu foco', 'bloqueia tempo', ou na sexta (/week)."
---

# /focus — tempo protegido

Nada vai para o calendário sem aprovação explícita do lote.

1. Sem snapshot recente de agenda: rode `/calendar` primeiro (ou avise que o plano trata a agenda como livre).
2. `./brain focus plan` (opcional `--days 7`). Mostre os blocos em tabela humana (dia, hora, ação, prazo) + ações que **não cabem** (`at_risk`) + sem esforço estimado.
3. Espere "ok" / "aprovo" / equivalente. Pedido de ajuste: mude prazos/esforços no ledger (`action update`) e gere **outro** plano — não edite o JSON do plano.
4. Com a resposta literal:

```
./brain focus approve FOCUS-#### --quote "<literal>"
./brain focus apply FOCUS-####
```

Modo `ics` (padrão): arquivo em `FRESH/focus/FOCUS-####.ics` — o dono importa. Modo `google`: a porta cria eventos `focusTime` marcados; eventos sem marca **nunca** são tocados.
5. Ações fechadas: `./brain focus sync` remove blocos futuros (autorizado pelo lote). No noturno isto roda sozinho.

Não espalhe blocos no calendário um a um. Não use outro calendário que não o `focus.calendar`. Não aplique plano `proposto`.
