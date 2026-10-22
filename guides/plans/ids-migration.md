# Plano — Migração de IDs para prefixos declarativos

Executor: Sonnet. Mesmo regime do plano da face Portfólio: testes verdes por passo,
commit local por passo, sem push, nada do dono no repo.

## Decisões do dono (não re-litigar)

| Antigo | Novo | Entidade |
|---|---|---|
| `A-0146` | `ACT-0146` | ação |
| `D-0012` | `DEC-0012` | decisão |
| `E-0003` | `WIN-0003` | entrega/conquista (alimenta `wins.md`) |
| `R-0007` | `PROP-0007` | proposta |
| `M-0002` | `MSG-0002` | mensagem (outbox) |
| `S-0001` | `PUB-0001` | publicação |
| `F-0001` | `FOCUS-0001` | plano de foco |
| `G1` | `GOAL-1` | goal (sem zeros) |
| `P3` | `PROJ-3` | projeto (sem zeros) |
| `P3.2` | `PROJ-3.2` | entregável |

`PROC-####`, `OPP-####` e slugs de área não mudam. A numeração continua (a próxima ação
depois de `A-0146` é `ACT-0147`).

**Migração completa, por decisão explícita do dono**: o ledger é reescrito uma vez
(exceção histórica à regra append-only), e também RAW, PROCESSED, notas, PLANNING,
reports, watch.toml e os nomes de arquivo — tudo que referencia um ID. Backup antes.
Depois da migração, o código só **emite** os nomes novos; os antigos continuam
**aceitos na entrada** (CLI, parser do `goals.md`, TUI, MCP) como sinônimo, traduzidos
na hora — isso não reescreve nada, só evita erro de digitação por hábito.

## Passo 1 — Código: um registro único de prefixos

- Novo `brainlib/ids.py`: tabela `PREFIXES` (entidade → prefixo novo, largura),
  `LEGACY` (antigo → novo), regexes compiladas a partir dela (`ACTION_ID`, `PLAN_NODE`,
  `LINK_RE` etc.) e `normalize(ref) -> str` (antigo → novo; novo passa intacto).
- Substituir todo regex/prefixo literal em `schema.py`, `state.py` (`next_id`,
  `PREFIX_COLL`), `planning.py` (parser de `## GOAL-1 — …`, `### PROJ-3 — …`,
  `- [ ] PROJ-3.1 …`, aceitando também `G1`/`P3`/`P3.1` na leitura), `notes.py`,
  `harvest.py`, `watch.py`, `render*`, `model.py`, `mcp_server.py`, `tui/store.py`,
  `tui/app.py`, `assets/dashboard.html`. `grep` final: nenhum `A-\d`, `"A"`, `G\d`,
  `P\d` literal fora de `ids.py` e dos testes de legado.
- Toda entrada (CLI, `brain add` JSON, TUI, MCP) passa por `ids.normalize`.
- Templates, skills (`commands/*/SKILL.md`), `AGENTS.md`, guias, `template/`,
  `config/*.example`, demo e testes: exemplos com os nomes novos.
- Testes: legado aceito na entrada e gravado no formato novo; parser lê os dois formatos
  do `goals.md` e escreve o novo; `next_id` continua a sequência.

## Passo 2 — `brain migrate ids` (genérico, sobe pro repo: outras instâncias precisam)

`brain migrate ids [--apply] [--include-external]`. Sem `--apply` = dry-run.

1. **Pré-checagens**: recusa com `BRAIN_NIGHTLY=1`; pega o lock do ledger; recusa se já
   migrado (marcador em `vault/PROCESSED/_ledger/MIGRATED-ids`).
2. **Backup**: zip completo de `vault/` + `config/watch.toml` em
   `vault/../brain-pre-ids-migration-<timestamp>.zip` (fora do vault, para o backup não
   ser migrado). Imprime caminho e tamanho. Sem backup íntegro, não segue.
3. **Mapa**: IDs do ledger (todas as coleções) e nós do PLANNING → `{antigo: novo}`.
   Só IDs que **existem** entram no mapa.
4. **Ledger**: reescreve cada evento (`id`, todos os campos de `data` que referenciam
   IDs — `project`, `deliverable`, `blocked_by`, `unblocks`, `link`, `target`, `goal`,
   `plan_file`, `source`, `raw`, listas — e textos livres onde o ID aparece com fronteira
   de palavra). Mantém `seq` e `ts`. Recalcula os hashes que cobrem texto alterado
   (`text_sha` de mensagem, `content_sha` de share, `sha` de focus) e grava um evento
   final `ids.migrated` (novo tipo em `schema.py`, `by system`) com o mapa e o sha do
   backup. Escrita atômica; `brain validate` precisa passar no resultado antes do swap.
5. **Arquivos com ID no nome**: `RAW/**/notes/A-0001-…-note.md` → `ACT-0001-…`, e o que
   mais o `find` achar; atualiza os caminhos no ledger no mesmo passo.
6. **Texto**:
   - Arquivos **escritos pelo cérebro** (notas em RAW, `PROCESSED/**`, `PLANNING/goals.md`,
     `PLANNING/log.md`, `reports/**`, `PROFILE/**`, `config/watch.toml`): substitui todos os
     IDs do mapa, com fronteira de palavra (`\bP3\.2\b` antes de `\bP3\b`).
   - **RAW externo** (reuniões, Slack, conectores, documentos): só os IDs longos
     (`A-0146`…) por padrão. `G#`/`P#` em texto externo costumam ser outra coisa
     (prioridade P1 do Jira, "P2" de pesquisa): o dry-run lista cada ocorrência com
     contexto (±40 caracteres), e só `--include-external` substitui.
   - `logs/` não são migrados (histórico de execução).
7. **Derivados**: `FRESH/` é apagado e regenerado com `brain render`; marca para
   `brain memory rebuild` se o Hindsight estiver ligado.
8. **Relatório**: por zona, arquivos tocados e substituições; diff do `goals.md`; lista de
   ocorrências externas ambíguas. O dry-run escreve o relatório em
   `vault/reports/migration/ids-<timestamp>.md`.

Testes: instância de demo com IDs antigos → dry-run não muda nada → apply → validate ok,
nomes de arquivo trocados, hashes conferem, segunda execução recusa, falso positivo
externo (`P1` numa transcrição) intocado sem `--include-external`.

## Passo 3 — Documentação

`AGENTS.md` (tabela de IDs, exemplos de PLANNING, regra da exceção histórica),
`guides/user-guide.md`, `guides/plans/face-portfolio.md`. Rodar `./brain upstream scan`.

## Passo 4 — Aplicação no vault real (no checkout principal, com o dono)

Não é código; é feito depois do merge, no checkout principal:
1. Desligar o noturno durante a migração.
2. `./brain migrate ids` (dry-run) → mostrar ao dono o relatório, o diff do `goals.md` e
   as ocorrências externas ambíguas.
3. Com o "ok" do dono (o diff do `goals.md` também passa pelo gate):
   `./brain migrate ids --apply [--include-external]`.
4. `./brain validate`, `./brain render`, abrir a TUI, religar o noturno.
