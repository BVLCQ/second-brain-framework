---
name: map
description: "Gera FRESH/map.md SOB DEMANDA (não é view noturna): três grafos Mermaid — áreas→goals→projetos, stakeholders×projetos, dependências entre ações abertas. Use quando o dono pedir o mapa, a visão geral, ou antes de reviews de planejamento."
---

# /map — o mapa visual (sob demanda)

Gera `FRESH/map.md` com três blocos **Mermaid** (renderizam em Obsidian/GitHub).
Custo consciente: grafos por LLM são caros e propensos a quebra — por isso não
rodam no noturno; geram quando o dono pede (o header `generated-at:` mostra a idade).

1. **Áreas & projetos** (`graph TD`): frentes do PROFILE → G# → P# (label =
   nome curto; deadline como sufixo quando existe)
2. **Stakeholders × projetos** (`graph LR`): pessoa → projeto com label do
   papel (fonte: people-index + projects-index; incluir gestor/leads do PROFILE)
3. **Ações & dependências** (`graph LR`): só ações ABERTAS com grafo ativo —
   `unblocks` (seta verde) e `blocked-by` (seta vermelha, ⛔ no nó bloqueado)

## Regras Mermaid (grafo quebrado = view inútil)

- IDs ASCII sem espaços: `G1`, `P1`, `A0146`, `ST_ana` (sanitizar nomes!)
- Labels SEMPRE entre aspas duplas: `P1["Dicionário de dados v1"]`
- ≤30 nós por grafo — acima disso, agregar por projeto e citar o detalhe no
  `open-actions.md` (o mapa mostra a floresta, não cada árvore)

Header padrão `generated-at:` + `fontes:`; responde no chat com o caminho +
1 linha do que mudou desde a última geração (se houver uma anterior).
