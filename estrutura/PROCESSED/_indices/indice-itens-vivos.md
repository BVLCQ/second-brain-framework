# Índice de itens vivos (append-only)

> O registro das fontes vigiadas com IDENTIDADE CONTÍNUA — um doc da watchlist,
> um board do Jira, um canal/pessoa do Slack. Uma seção por item; a primeira
> linha é o estado inicial; cada MUDANÇA (hash diferente) apensa:
> `data · snapshot no RAW · o que mudou (1 linha)`. Pull sem mudança = silêncio.
> Fluxos sem identidade por item (ex.: digest diário do Gmail) NÃO entram —
> o artefato diário já é o registro. A view `vault/FRESH/itens-vivos.md` deriva daqui.
>
> **Ciclo de vida:** a VIGÊNCIA mora no `config/watch.yaml` (item removido lá
> deixa de ser puxado — a view o marca "arquivado"); a MEMÓRIA mora aqui e
> nunca é apagada. Seções nunca são removidas deste índice.

<!-- MODELO de seção (apague este comentário ao criar a primeira real):

## gdoc · Dicionário de Dados (id: 1AbC…)
- 2026-09-14 · vault/RAW/2026/09/gdoc-dicionario-…-<ts>.md · estado inicial (v1 completa)
- 2026-09-16 · vault/RAW/2026/09/gdoc-dicionario-…-<ts>.md · §3 "Campos" reescrito; +2 comentários (Bruno)

## jira · board MIG
- 2026-09-14 · vault/RAW/2026/09/jira-board-mig-…-<ts>.md · estado inicial (12 cards)
- 2026-09-15 · vault/RAW/2026/09/jira-board-mig-…-<ts>.md · MIG-118 criado (Ana); MIG-101 → In review

## slack · #retention
- 2026-09-15 · vault/RAW/2026/09/slack-retention-…-<ts>.md · thread plano Q4 (14 msgs)

-->
