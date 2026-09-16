---
name: todo
description: "Cria uma ação A-#### a partir do que o dono digitou: '/todo preciso ler X até quarta' → ação no ledger com deadline resolvido, pessoas e projeto linkados. Use quando o dono disser 'preciso', 'tenho que', 'lembra de', ou pedir criação direta de tarefa."
---

# /todo — a ação que nasce pronta

O dono sabe o que precisa fazer ANTES de qualquer reunião documentar isso.
O `/todo` é a porta: texto livre → ação estruturada no ledger, sem arquivo
intermediário na inbox (o registro é o próprio ledger, append-only; origem
honesta: declarado pelo dono).

## Entrevista rápida (SÓ o que faltar — e em UMA rodada)

Depois do parse, cheque os 3 campos de encaixe no planejamento: **deadline**,
**projeto**, **pessoas**. Para cada um AUSENTE, pergunte — tudo em UMA
mensagem, formato de lote com sugestões (o dono responde "1a 2pula 3Ana"):

```
A-0153 · ler material de retenção — antes de eu registrar:
1. Para quando?  (a) qua 18/09  (b) sex 20/09  (c) sem prazo  (d) outra
2. Projeto?      (a) P1 Padronização de métricas  (b) P3 Onboarding  (c) nenhuma  (d) outra
3. Alguém além de você?  (a) nenhum  (b) outra
```

- **Máximo 3 perguntas, uma rodada só.** Respondidas (ou "pula"/silêncio):
  cria com o que tiver — nunca re-pergunte, nunca bloqueie.
- **Sugestões espertas, não genéricas**: prazos = amanhã/fim da semana (ou o
  que o texto insinuar); projetos = os ativos do PLANNING (até 3, com nome
  curto); pessoas = aliases recentes do people-index.
- **Por que perguntar**: deadline coloca no cronograma (`/brief` 72h, gantt
  do `/timeline`); projeto liga a árvore (`month.md`, radar de goals) e
  alimenta o recap; pessoa liga threads e prep de reunião.
- Texto já traz os 3 → **zero perguntas, cria direto** (TODO rápido segue
  rápido — a entrevista é exceção, não ritual).

## Sequência

1. **Parse do texto livre** — extraia:
   - **o quê** (infinitivo limpo: "ler material de retenção")
   - **deadline**: relativa vira data REAL calculada na hora ("até quarta" →
     a próxima quarta em ISO). Nada de "quarta" solto no ledger.
   - **pessoas** ("conversar com a Ana sobre X") → resolve aliases; se a pessoa
     existe no people-index, linka; senão, cria ficha mínima com o nome dito.
   - **projeto/goal** ("do projeto Y") → `proj: P#` se Y casa no projects-index;
     não casa → entra na entrevista (opções reais), nunca chute.
   - **dependências** ("depois que o Bruno responder") → `blocked-by:`/`waiting`.
2. **Entrevista do que faltar** (protocolo acima), se faltar algo.
3. **Idempotência**: ação ABERTA muito parecida já existe? Avise ("já existe
   A-0141 parecida — criar mesmo assim?") — sem bloquear.
4. **Escreva no ledger** (`_logs/actions.md`, append):
   `A-#### · aberta · <data real> · <o quê> · dono: VOCÊ · deadline <ISO> ·
   proj: P# · origem: /todo (declarado pelo dono)`
5. **Alimente os índices** (a garantia que o dump daria de graça — escrita
   direta também indexa): 1 linha em `people-index.md` por pessoa linkada e
   em `projects-index.md` por projeto linkado (`<data> · A-#### · <o quê, 1
   linha>`) — o estado atual da ação vem do ledger (o índice aponta o ID).
6. **Ficha se houver detalhe**: texto longo/contexto (ou "detalhe:") → cria
   `_actions/A-####.md` com o que veio. `/todo A-0146 + <texto>` APENDA
   detalhe à ficha existente (cria se não existir) — nunca reescreve.
7. **Confirme em 1-2 linhas**: "A-0152 · ler material de retenção · até qua
   18/09 · P1 · com a Ana". O dono confere o encaixe em 2 segundos.

A nova ação aparece sozinha no `/brief` (ATRASADAS/72h), `open-actions.md`,
`/week` e no cronograma (`/timeline` gantt) — as views leem o ledger.
Fechar é com o **`/done`** (o par deste comando), incluindo a cascata de
desbloqueio.

## Regras

- Deadline ausente = ação sem data (aparece como "sem prazo", não invente).
- Proveniência destas ações é o próprio dono — a origem no ledger já registra;
  não precisa de tag de extração.
- Nunca crie goal/projeto por aqui (gate!): TODO liga a projeto EXISTENTE.
- Se o pedido for vago ("cuida do onboarding"), devolva 1 pergunta de escopo
  antes de criar — ação mal definida vira ruído no radar.
