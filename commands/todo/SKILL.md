---
name: todo
description: "Cria uma ação A-#### a partir do que o dono digitou: '/todo preciso ler X até quarta' → ação no ledger com deadline resolvido, pessoas e projeto linkados. Use quando o dono disser 'preciso', 'tenho que', 'lembra de', ou pedir criação direta de tarefa."
---

# /todo — a ação que nasce pronta

O dono sabe o que precisa fazer ANTES de qualquer reunião documentar isso.
O `/todo` é a porta: texto livre → ação estruturada no ledger, sem arquivo
intermediário na inbox (o registro é o próprio ledger, append-only; origem
honesta: declarado pelo dono).

## Sequência

1. **Parse do texto livre** — extraia:
   - **o quê** (infinitivo limpo: "ler material de retenção")
   - **deadline**: relativa vira data REAL calculada na hora ("até quarta" →
     a próxima quarta em ISO). Nada de "quarta" solto no ledger.
   - **pessoas** ("conversar com a Ana sobre X") → resolve aliases; se a pessoa
     existe no people-index, linka; senão, cria ficha mínima com o nome dito.
   - **projeto/goal** ("do projeto Y") → `proj: P#` se Y casa no projects-index;
     não casa → deixe sem e pergunte depois (nunca chute o projeto errado).
   - **dependências** ("depois que o Bruno responder") → `blocked-by:`/`waiting`.
2. **Idempotência**: ação ABERTA muito parecida já existe? Avise ("já existe
   A-0141 parecida — criar mesmo assim?") — sem bloquear.
3. **Escreva no ledger** (`_logs/actions.md`, append):
   `A-#### · aberta · <data real> · <o quê> · dono: VOCÊ · deadline <ISO> ·
   proj: P# · origem: /todo (declarado pelo dono)`
4. **Ficha se houver detalhe**: texto longo/contexto (ou "detalhe:") → cria
   `_actions/A-####.md` com o que veio. `/todo A-0146 + <texto>` APENDA
   detalhe à ficha existente (cria se não existir) — nunca reescreve.
5. **Confirme em 1-2 linhas**: "A-0152 · ler material de retenção · até qua
   18/09 · linkada a P1". O dono confere o parse em 2 segundos.

A nova ação aparece sozinha no `/brief` (ATRASADAS/72h), `open-actions.md` e
`/week` — as views leem o ledger.

## Regras

- Deadline ausente = ação sem data (aparece como "sem prazo", não invente).
- Proveniência destas ações é o próprio dono — a origem no ledger já registra;
  não precisa de tag de extração.
- Nunca crie goal/projeto por aqui (gate!): TODO liga a projeto EXISTENTE.
- Se o pedido for vago ("cuida do onboarding"), devolva 1 pergunta de escopo
  antes de criar — ação mal definida vira ruído no radar.
