---
name: timeline
description: "Gera FRESH/timeline.md SOB DEMANDA (não é view noturna): timeline Mermaid do passado (entregas, decisões, mudanças de goal) + gantt dos próximos 30-45d. Use quando o dono pedir a linha do tempo, o histórico visual, ou antes de recap/reviews."
---

# /timeline — a linha do tempo (sob demanda)

Gera `FRESH/timeline.md` com dois blocos **Mermaid**. Sob demanda pelo mesmo
motivo do /map: custo LLM + sensibilidade de sintaxe — não roda no noturno.

1. **Passado** (`timeline`, por semana/mês conforme densidade):
   - entregas (do `_logs/deliveries.md`) — o esqueleto principal
   - decisões `D-####` relevantes (índices) — só as que mudaram direção
   - mudanças de goal (`vault/PLANNING/log.md`)
   - estreias de itens vivos (opcional; só as relevantes ao escopo pedido)
2. **Futuro** (`gantt`, 30-45d): entregáveis com deadline, agrupados por projeto
   (`dateFormat YYYY-MM-DD`; barra por entregável; hoje como `milestone`)

## Regras

- Datas ISO em tudo; escopo default = últimos 90 dias → próximos 45.
  O dono pode pedir janela ("/timeline 2026" — só o ano, ou "desde agosto").
- **Timeline honesta**: período sem evento fica de fora — nada de enchimento.
- Mesmas regras Mermaid do /map (IDs ASCII, labels entre aspas, ≤30 itens).
- Header `generated-at:` + `fontes:`; ao final, 1 linha no chat com o caminho.
