---
name: update
description: "O motor completo: roda os conectores (conforme config/watch.yaml), processa a inbox (/dump) e regenera TODAS as views de FRESH. É o que o cron noturno executa; use também sob demanda quando o dono pedir atualização geral."
---

# /update — o motor completo

## Sequência

1. **Conectores** (se `config/.env` + `config/watch.yaml` existirem): executar
   `scripts/connectors/` na ordem — jira, github, slack, gmail, gdrive. Cada um
   escreve snapshots em `vault/RAW/inbox/` (prefixo da fonte). Conector ausente ou
   sem credencial: pular com 1 linha de aviso, não abortar o resto.
2. **`/dump`** — processar toda a inbox (idempotente por construção).
3. **Regenerar TODAS as views de FRESH**: daily-brief, week, month,
   open-actions, projects, stakeholders, live-items, pocket, map, timeline.
   Cada uma com `generated-at:` + `fontes:`. Views são reescritas inteiras —
   nada de patch incremental.

`month.md`: lookahead 30-45 dias por goal → projeto → entregável (deadlines,
progresso, dependências cruzadas visíveis — cadeias de `blocked-by/unblocks`
que atravessam projetos). `pocket.md`: ver spec em `commands/week/SKILL.md`.

`map.md` — o mapa visual (blocos **Mermaid**; renderiza em Obsidian/GitHub):
- **Áreas & projetos** (`graph TD`): frentes do PROFILE → G# → P# (label =
  nome curto; deadline como sufixo quando existe)
- **Stakeholders × projetos** (`graph LR`): pessoa → projeto com label do
  papel (fonte: people-index + projects-index; incluir gestor/leads do PROFILE)
- **Ações & dependências** (`graph LR`): só ações ABERTAS com grafo ativo —
  `unblocks` (seta verde) e `blocked-by` (seta vermelha, ⛔ no nó bloqueado)
Regras Mermaid (grafo quebrado = view inútil): IDs ASCII sem espaços
(`G1`, `P1`, `A0146`, `ST_ana`); labels SEMPRE entre aspas duplas
(`P1["Dicionário de dados v1"]`); ≤30 nós por grafo — acima disso, agregar
por projeto e citar o detalhe no open-actions.

`timeline.md` — a linha do tempo (Mermaid):
- `timeline` (passado, por semana/mês): entregas (deliveries.md), decisões
  D-#### relevantes, mudanças de goal (PLANNING/log.md), estreias de itens vivos
- `gantt` (futuro, 30-45d): entregáveis com deadline, agrupados por projeto
Datas ISO; período sem evento fica de fora (timeline honesta, não enchimento).

`live-items.md` (deriva de `_indices/live-items-index.md` + `config/watch.yaml`):
uma linha por item do registro — última mudança, idade, nº de snapshots; sem
mudança desde o estado inicial = "estável". **Vigência:** item presente na
watch.yaml = vigiado; item do registro que NÃO está mais na watch.yaml =
"arquivado (não vigiado)" — última linha histórica, sem idade corrente. Item
estável há >60d ganha nota: "considerar tirar da watchlist?" (sugestão, não
ação — a curadoria da watchlist é do dono, sem gate).

## Reporte (≤10 linhas)

```
⚙ UPDATE — <data hora>
  conectores: jira 3 novidades · github 2 · slack 1 · (gmail: sem credencial)
  dump: 6 itens processados (0 duplicados) · inbox: 0 restantes
  views regeneradas: 5 · duração: ~2min
```

## Regras

- Rodar 2× = zero duplicatas (idempotência de conectores por hash + dump por
  artefato). Se não for o que aconteceu, reportar o defeito.
- Erro em UMA fonte não derruba as outras — isolar, avisar, seguir.
- Sem `.env`/`watch.yaml`: pular etapa 1 em silêncio (cérebro manual é válido).
- Este comando NÃO mexe em PLANNING (gate) e NUNCA em ferramentas externas
  além de LER via conectores.
