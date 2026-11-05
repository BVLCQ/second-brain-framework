# Plano — Memória em dois setups: `embed` (sem LLM) e `full` (com LLM)

Executor: agente de código da instância. Regime dos outros planos: testes verdes
(`python3 -m pytest tests/`, e a TUI com o venv `.venv-tui` quando tocar nela), **um
commit local por passo**, nada do dono no repo, `./brain upstream scan` antes de propor
o push.

Este documento **consolida e substitui** o plano anterior de memória (Fases 0–7 com as
emendas R1–R9 da revisão independente). O núcleo auditado não muda: roteamento por
camadas, JSONL como verdade com projeção SQLite derivada, medição antes de mudar,
pré-requisitos explícitos por setup, rollback por fase. A novidade é o
reordenamento em **dois setups completos e independentes**:

1. **`embed`** — sem LLM em qualquer operação (retain, consolidação, mental models).
   Nada sai da máquina, custo de API zero. Não é um "modo quebrado" nem um stub: é o
   estado da arte da estratégia *só-recuperação*, com todas as camadas determinísticas
   do plano (índice SQLite, banco único enriquecido, roteador, dossiê) rodando por
   inteiro.
2. **`full`** — tudo do `embed` **mais** as camadas de LLM: extração de fatos do RAW
   com identidades do ledger, observações consolidadas e mental models por GOAL/PROJ/
   pessoa. Custo medido ~US$ 20/mês (cenário B), com **medidor mensal** de uso — sem
   teto nem bloqueio (decisão 3).

**`embed` é prefixo estrito de `full`**: a escada de commits é uma só; o `full` começa
exatamente onde o `embed` termina. Subir de `embed` para `full` não joga fora nenhum
commit, nenhum dado e nenhuma configuração — só acrescenta as camadas de LLM (com os
pré-requisitos da seção 4.3) e recria o banco em modo de extração. Descer de volta é
igualmente primeira classe (seção 4.5) — não é um-ou-outro. O vocabulário é o mesmo do
passo 11 do setup assistido (`none` · `embed` · `full`).

---

## 0. Resumo para decidir

| | Hoje (dois bancos, chunks) | Setup `embed` | Setup `full` |
|---|---|---|---|
| LLM em qualquer operação | nenhum | nenhum | Haiku 5.5 (retain, consolidação), Sonnet 5.5 (mental models) |
| Sai da máquina? | não | **não** | sim — texto do vault à API **com a chave do dono** (seção 4.3) |
| Custo de API | US$ 0 | **US$ 0** | ~US$ 20,50/mês (~US$ 246/ano) |
| Chaves no `.env` | nenhuma | nenhuma | 1 (provider de LLM) |
| Verdade das entidades | `events.jsonl` | `events.jsonl` (sem mudança) | `events.jsonl` (sem mudança) |
| Consulta estruturada | refold + busca linear | SQLite derivado, FTS5, `brain query` | idem |
| Bancos Hindsight | 2, só chunks, sem data, sem entidades | **1**, chunks enriquecidos: datas do mundo, tags do ledger, entidades por alias, aliases do banco | **1**, fatos + chunks de origem + observações + mental models |
| PROCESSED / páginas de ação | embutidos como chunks (velham entre syncs) | fora do vetor; FTS5 + SQLite | idem |
| Hook de recall | 2 bancos, corte 0,55, até 8 itens, muito ruído | roteador: ledger e/ou trechos, ≤ 5 itens, abstenção | roteador: ledger e/ou fatos e/ou mental model e/ou trecho, ≤ 5 itens |
| "O que está atrasado com X?" | vetor (erra) | ledger, exato | idem |
| "O que foi dito de passagem?" | vetor, sem data | vetor + BM25 pt + reranker local + datas | idem + fatos extraídos |
| "Por que achamos que X importa?" | não responde | dossiê determinístico (estado + evidência) na hora da resposta | mental model vivo, regenerado |
| Pré-requisito além do `embed` | — | nenhum | chave própria do dono no `.env` (seção 4.3) |

**Escolha do dono, nos dois sentidos (decisão 1).** `embed` e `full` são caminhos de
primeira classe: começar por qualquer um, subir para `full` quando quiser e **voltar**
para `embed` quando quiser — não é um-ou-outro. Como `embed` é prefixo estrito, subir
não joga fora nada; descer é configuração + rebuild (seção 4.5). As metas da Fase 0 são
por setup, então qualquer escolha é um sistema completo.

---

## 1. Diagnóstico (herdado do plano anterior, verificado no código e no container)

- **O formato do ledger é barato em tokens e legível, mas O(n) em CPU:** ~1.167
  eventos em 16 dias (~73/dia; ~11 MB/ano); `read_events` + `state.build` em 5 ms;
  porém cada processo refaz a dobra do zero — CLI, MCP e cada escrita. A TUI e o MCP
  sentem primeiro com anos de uso.
- **`search.py` relê cada artefato `.md` do disco a cada busca** (contagem de substring
  em Python) — escala pior que o ledger.
- **Perguntas de estado caem no banco vetorial.** "O que está atrasado com X?" devolve
  notas e ações quaisquer: atraso é uma conta; similaridade semântica não faz conta.
- **Dois bancos redundantes:** `brain-raw` (214 docs → 1.354 nós) espelha o que
  `brain-mem` (376 → 432) resume; o hook consulta os dois e mistura níveis de
  abstração no limite de 8 itens.
- **O RAW vai sem data** (`"date": None`): os links "temporais" refletem a hora da
  ingestão; recuperação por período é inútil.
- **Sem extração não há entidades** no grafo; dois apelidos da mesma pessoa são strings
  diferentes (o ledger já tem os aliases; a memória não usa).
- **Hook injeta ruído** (trechos de transcrição sem relação), corte 0,55, 8 itens.
- **Reranker neural já medido** (comentário no `services/compose.yaml`): `bge-reranker-v2-m3`
  na CPU do container: top-1 de 91,7% → 95,8%, mas 1,6 s @ 30 candidatos — estoura o
  timeout do hook. Só vale servido no host com aceleração (Fase 4.2).
- **Volume extraível:** ~3,0 MB em 16 dias (`meetings` 1,63 MB + `documents` 0,79 +
  `notes` 0,19 + `slack` 0,10) → teto de ~1.900 chunks/mês. `connectors/` e `github/`
  não entram (espelho estruturado já no ledger; diff de código é ruído).
- **Premissa corrigida (2026-11-05):** o container `0.10.1-slim` que rodava em :8888
  **não era do cérebro** — era o serviço pessoal do dono (`~/hindsight-service`, banco
  `hermes`); o compose do cérebro nunca subiu naquela máquina (colisão de
  `container_name`/portas com o serviço pessoal — decisão 10). A disciplina R5 segue
  de pé com alvo novo: **1.2.0 por digest** (decisão 9). Todo "confirmado no código"
  vale para a versão auditada no passo 0 de cada fase.

## 2. Princípios

1. **O vault continua sendo a verdade.** Tudo o que este plano cria (SQLite, banco,
   mental models) é derivado e reconstruível: `brain index rebuild` e
   `brain memory rebuild` refazem.
2. **Cada tipo de pergunta tem a sua camada.** *Estado* (prazo, atraso, quem deve) →
   ledger via SQLite, determinístico. *Contexto* ("o que sabemos sobre X") → banco
   (`embed`: trechos + docs de decisão; `full`: fatos + observações + mental model).
   *Letra* ("o que exatamente foi dito") → trecho original guardado junto do fato/chunk.
3. **Extrair da fonte, ancorado no que já foi resolvido** (*full*): a extração lê o RAW
   **com** o mapa de identidades e IDs do ledger. Em `embed`, a âncora é determinística:
   tags, entidades e aliases vindos do ledger, casados por texto.
4. **`embed` é prefixo estrito de `full`.** Nenhum commit do `embed` é descartado ao
   subir; a troca de setup é configuração + rebuild, não reescrita.
5. **Sem LLM, a síntese acontece na hora da resposta.** O agente da sessão é quem lê as
   evidências recuperadas e conclui. O sistema de memória do `embed` entrega
   **recuperação precisa e dossiê determinístico** — não conclusões pré-digeridas. Não
   fingir o contrário; as metas da Fase 0 são por setup.
6. **Menos é mais na injeção.** ≤ 5 itens pertinentes; zero itens quando nada passa do
   corte (abstenção é métrica, não falha).
7. **Medir antes de mudar.** Nenhuma fase é dada como pronta sem bater o baseline da
   Fase 0 nas perguntas do seu tipo.
8. **Modelo certo por operação** (*full*): extração/consolidação em modelo barato
   (Haiku 5.5 high), síntese de páginas (mental models) em maior (Sonnet 5.5 high).
   Opus não entra. Embeddings sempre locais (`bge-m3` via LM Studio) — recall não
   passa por LLM em nenhum setup.

## 3. Arquitetura alvo (uma arquitetura, dois setups)

```
                         vault/ (verdade)
   ┌────────────────────────────────────────────────────────────────┐
   │ PROCESSED/_ledger/events.jsonl   PLANNING/  PROFILE/           │
   │ RAW/<ano>/<mês>/<tipo>/          PROCESSED/<ano>/<mês>/*.md    │
   └───────┬───────────────────────────────┬────────────────────────┘
           │ brain index (determinístico)  │ brain memory sync
           ▼                               ▼
   FRESH/_index/brain.sqlite        Hindsight · banco único brain-mem
   ┌──────────────────────────┐     ┌──────────────────────────────────┐
   │ events · actions · …     │     │ embed:  chunks enriquecidos      │
   │ people + aliases         │────▶│   (data do mundo, tags,          │
   │ edges · fts (títulos,    │ ent.│    entidades por alias)          │
   │ PROCESSED, RAW, PLANNING)│     │   + docs ledger/DEC · ledger/WIN │
   └───────────┬──────────────┘     │ full:   + fatos extraídos        │
               │                    │   + observações consolidadas     │
               │                    │   + mental models (1 por tema)   │
               ▼                    └───────────────┬──────────────────┘
   brain query · brain search · MCP · TUI    recall (embedding local, sem LLM)
               └────────────┬─────────────────────┘
                            ▼
              hook roteador (≤ 5 itens) · /ask · dossiê
```

### 3.1 Camadas e qual setup as tem

| Camada | Onde | Quem escreve | Responde | `embed` | `full` |
|---|---|---|---|---|---|
| Ledger | `events.jsonl` | só `./brain` | tudo — a verdade | ✓ | ✓ |
| Projeção | `FRESH/_index/brain.sqlite` | `brain index` | estado, busca por palavra | ✓ | ✓ |
| Evidência (chunks) | Hindsight `brain-mem` | retain | a letra exata | ✓ | ✓ |
| Docs de decisão/entrega | Hindsight `brain-mem` | retain (`_entity_docs`, só DEC/WIN) | "por que decidimos Y" em nível factual | ✓ | ✓ |
| Enriquecimento (tags, datas, entidades, aliases) | Hindsight | sync, do ledger | recall filtrado, período, grafo | ✓ (por alias, determinístico) | ✓ (resolvido na extração) |
| Fatos atômicos | Hindsight | retain com extração | "o que sabemos sobre X" | — | ✓ |
| Observações | Hindsight | consolidação | padrões, preferências | — | ✓ |
| Mental models | Hindsight | refresh | "onde estamos com X" | — (dossiê na hora) | ✓ |
| Dossiê determinístico | montado na leitura | `brain memory dossier` | estado + evidência por entidade | ✓ | ✓ (útil também aqui) |

### 3.2 O que vai e o que não vai para o banco (vale para os dois setups)

| Origem | Vai? | Como |
|---|---|---|
| `RAW/*/meetings/`, `slack/`, `documents/`, `notes/` | sim | chunks enriquecidos (`full`: + extração de fatos) |
| PDFs/DOCX de `documents/` | sim | `files/retain` (o Hindsight converte) |
| `RAW/*/videos/`, `images/` | só a transcrição em texto, quando existir | tratada como reunião |
| `RAW/*/connectors/`, `github/` | **não** | estado já no ledger; código é ruído |
| `PROCESSED/*.md` | **não** | FTS5 do índice cobre busca por palavra; serve de **contexto** da extração no `full` |
| Ledger: decisões (DEC) e entregas (WIN) | sim, como documentos curtos | narrativa curada responde perguntas de contexto |
| Ledger: ações, pessoas, propostas | **não** | estado volátil → SQLite; pessoas viram **entidades** e **tags** |
| `PLANNING/`, `PROFILE/` | **não** como documento | pequenos e sempre verdade: lidos direto e indexados no FTS5 |
| inbox | não | ainda não processada |

### 3.3 Roteamento de perguntas (mesmo classificador nos dois setups)

| Sinal na pergunta | Rota | Exemplo |
|---|---|---|
| ID (`TASK-…`, `DEC-…`, `PROJ-3`, `GOAL-1`, `OPP-…`, + prefixos antigos aceitos) | ledger: ficha da entidade | "como está a TASK-0146?" |
| título de projeto/goal dobrado (tabela `planning`) | ledger: ficha **e** mental model/dossiê | "como está o projeto de pagamentos?" |
| vocabulário de estado/tempo (atrasad, prazo, vence, pendente, quem deve…) | ledger: `brain query` | "o que está atrasado com a Marina?" |
| nome/alias de pessoa | ledger (pendências) **e** model/dossiê da pessoa | "o que tenho com a Marina?" |
| "exatamente", "palavras", "o que foi dito", aspas | chunks de origem | "o que exatamente foi dito sobre o SLA?" |
| demais | `embed`: chunks + docs DEC/WIN · `full`: fatos + observações + mental model | "por que mudamos o processo de pagamento?" |

---

## 4. Os dois setups

### 4.1 Setup `embed` — estado da arte sem LLM

O que o torna completo, e não um paliativo:

- **Estado nunca passa pelo vetor.** Índice SQLite + `brain query` respondem prazo,
  atraso, progresso e pendências com exatidão determinística (Fase 1).
- **Recuperação híbrida de verdade.** Um banco único com BM25 em português + vetores
  `bge-m3` fundidos por RRF, opcionalmente com **reranker neural local** (host, MLX)
  se passar o gate de latência (Fase 4.2). Nenhuma consulta usa LLM.
- **Enriquecimento determinístico vindo do ledger** — o único dono da verdade sobre
  identidades: datas do mundo em todo RAW, tags (`tipo:`, `pessoa:`, `proj:`, `goal:`,
  `area:`), entidades anexadas por casamento de alias, aliases do banco sincronizados.
  O grafo de entidades funciona no subconjunto literal — honesto e grátis.
- **Injeção disciplinada.** Roteador com ≤ 5 itens, corte calibrado, prazo por perna,
  e **abstenção** quando nada é pertinente.
- **Dossiê determinístico** (`brain memory dossier`) no lugar de mental models: ficha
  do ledger + decisões/entregas ligadas + melhores trechos com a tag da entidade,
  montado na hora da leitura — nunca velho, sempre citado, zero LLM.
- **Custo US$ 0 de API, zero egress** — pode rodar em qualquer instância, inclusive
  com política de dados restritiva, e no noturno sem gate.

O que o `embed` **não** faz (por desenho, dito com honestidade): não atomiza fatos (a
resposta cita trechos, e o agente da sessão lê mais tokens para concluir), não
consolida observações entre documentos, não pré-computa sínteses (perguntas
`conclusao` continuam limitadas à recuperação), e o grafo de entidades só enxerga o
que casou por alias literal (parafraseio e erro de transcrição ficam para o `full`).

### 4.2 Setup `full` — camadas de LLM sobre o mesmo substrato

Tudo do `embed`, mais: fatos extraídos do RAW com identidades resolvidas (a extração
recebe o contexto de IDs/aliases do artefato correspondente), observações consolidadas
em lote, mental models regenerados por GOAL/PROJ/pessoa com o estado do ledger colado
deterministicamente, e as pernas de fatos/mental model no roteador. Cenário de custo B:
~US$ 20,50/mês (seção 4.4), dois terços disso nos mental models.

### 4.3 Pré-requisitos do `full` (o `embed` não tem nenhum)

Decisão 2 do dono: o gate não é "egress sim ou não" — é **chave aprovada + nada público**.

1. **Chave do dono, provider livre.** O modo `full` só fala com a API configurada pelo
   dono — Anthropic, OpenAI-compatível, outro — com a chave dele em `config/.env`
   (0600), nunca no repo nem no compose (o compose lê com `env_file`). Enviar texto do
   vault à própria API escolhida pelo dono é permitido por definição. LLM local
   (LM Studio etc.) também é opção do dono, sem gate — nota histórica do compose: o
   extrator local pequeno foi testado e aposentado (mais fraco que os autores, lento);
   se for local, que seja capaz.
2. **Nenhum dado do dono público.** Essa é a invariante. Já vigente pela porta 5:
   `upstream scan` + hook `pre-push` barram qualquer coisa do dono no repo público. O
   plano não acrescenta superfície: bancos no volume do Hindsight, índice no `FRESH/`
   (cego pro git), chave no `.env`, exemplos genéricos no `template/`.
3. **AGENTS.md registra, não pede permissão.** A linha na seção Segurança ("a camada
   de memória envia texto do vault à API de LLM configurada, quando
   `[memory].cloud_llm = true`") documenta o comportamento da instância e entra com o
   "ok" de quem liga o modo. Sem verificação de política corporativa no caminho.
4. **Sem teto de gasto (decisão 3).** Custo é responsabilidade do dono. `brain memory
   cost` é medidor mensal de tokens e US$ (Fase 10); ninguém é bloqueado nem assediado
   por alerta.

### 4.4 Custos

| Componente | `embed` /mês | `full` /mês |
|---|---|---|
| Retain (Haiku 5.5 high) | 0 | 2,28 |
| Consolidação (Haiku 5.5 high) | 0 | 1,22 |
| Mental models (Sonnet 5.5 high) | 0 | 13,50 |
| Rebuilds diluídos (Batch −50%) | 0 | 3,50 |
| **Total** | **US$ 0** | **~US$ 20,50** (~US$ 246/ano) |

`embed`: embeddings `bge-m3` locais (LM Studio, Metal) e reranker local opcional —
custo de API zero; alavancas de custo do `full` (prompt caching, Batch API, mental
model `delta`, `mm_min_interval_h`) seguem no plano anterior e são medidas reais pela
tabela `llm-requests` na primeira semana (`brain memory cost`).

### 4.5 Trocar de setup

Primeira classe nos dois sentidos (decisão 1): não é um-ou-outro — o dono sobe e
desce de setup quando quiser.

- **`embed` → `full`:** resolver os pré-requisitos (4.3) → Fase 6 (compatibilidade,
  sem gastar) → Fase 7 (banco `brain-mem-v2` com extração, paralelo) → Fase 8 (mental
  models) → Fase 9 (pernas do roteador). Nenhum commit do `embed` é revertido.
- **`full` → `embed`:** `[memory] extract = false`, `cloud_llm = false`,
  `mental_models = false` + `brain memory rebuild` (volta a chunks enriquecidos);
  mental models ficam órfãos no Hindsight (inofensivos) ou o banco é recriado; a
  exceção da AGENTS.md sai com "ok" do dono. Mesmo mecanismo do rollback da Fase 7.
- **`none` → qualquer:** o passo 11 do setup assistido cobre.

---

## 5. Fases

Cada fase traz: objetivo, por quê, arquivos, passos, testes, critério de pronto e
rollback. Fases 0–2 são **comuns**; 3–5 completam o **`embed`**; 6–9 completam o
**`full`**; 10 fecha a operação nos dois.

### Fase 0 — Medição (baseline) · comum

**Objetivo.** Número por tipo de pergunta antes de mexer em qualquer coisa; escolha de
fonte/modelo com dados, não opinião. Sem LLM no julgamento: métricas de recuperação,
determinísticas, baratas de repetir.

**Arquivos.** `brainlib/memory_eval.py` (novo), `brainlib/cli.py`,
`vault/eval/memory-gold.jsonl` (zona curada do dono, fora do git),
`template/eval/memory-gold.example.jsonl` (genérico, no git).

**Passos.**

1. **Conjunto de perguntas** (~60, PT e ES), uma por linha:
   ```json
   {"id":"q01","q":"o que está atrasado com a Marina?","type":"estado","lang":"pt",
    "expect_ids":["TASK-0031","TASK-0040"],"expect_docs":[]}
   ```
   | Tipo | Qtd | O que testa |
   |---|---|---|
   | `estado` | 12 | prazo, status, quem deve (deve ir ao ledger) |
   | `contexto` | 12 | "o que sabemos sobre X" |
   | `decisao` | 8 | "por que decidimos Y", quem decidiu |
   | `detalhe` | 12 | dito de passagem que o `/dump` **não** registrou |
   | `literal` | 8 | a frase exata |
   | `conclusao` | 8 | "por que achamos que X importa?" |
   | `nada` | 6 | pergunta cuja resposta correta é **não consta** (fusão que não houve, PROC-99) — `expect_*` vazios |

   Perguntas `conclusao` ganham **duas variantes de expectativa**: no `embed`,
   `expect_docs` = os documentos de evidência (a síntese é na hora da resposta); no
   `full`, a página do mental model. O eval aceita as duas leituras do gold.
   O agente **propõe** as perguntas; o dono revisa e aprova.
2. **`brain memory eval`** com `--gold`, `--bank`, `--route on|off`, `--k`, `--json`,
   `--save vault/eval/runs/<data>-<rótulo>.json`. Métricas por tipo: **recall@5**,
   **MRR**, **citação correta**, **itens injetados**, **precisão da injeção**,
   **taxa de abstenção** (fração das `nada` em que o hook injeta zero) e tokens
   aproximados por pergunta (caracteres ÷ 3,5).
3. **Baseline** do estado atual (`brain-raw` + `brain-mem`, rota off), salvo em
   `runs/<data>-baseline.json`.
4. **Bancos de teste** (só quando houver o que testar): amostra de duas semanas do RAW
   em bancos temporários `brain-eval-*` — no `embed`, para calibrar `retain_chunk_size`
   (2.000 × 3.000) e o corte do hook; no `full`, também as variantes de fonte e modelo
   (a/b/c/c+p/c-m/c-s do plano anterior) e Haiku × Sonnet nos mental models com nota
   do dono (1–5, fidelidade e utilidade). `POST /memories/dry-run-extract` mostra os
   fatos de um chunk sem gravar (requer `enable_dry_run_extract`, Fase 6).

**Testes.** `tests/test_memory_eval.py`: parser do gold, recall@k e MRR com cliente
falso, rota on/off, abstenção, variantes de expectativa.

**Pronto quando.** Baseline salvo e conferido; decisões registradas em "Decisão da
Fase 0". **Disciplina R4:** até ~25 perguntas por tipo o eval é direcional, não gate;
comparações com intervalo (binomial), não ponto contra ponto.

**Rollback.** Nada a desfazer: só lê.

---

### Fase 1 — Ledger: projeção SQLite e consultas estruturadas · comum

**Objetivo.** Consultas de estado rápidas e exatas, busca indexada, ferramenta
estruturada para o agente — sem tocar no `events.jsonl`.

**Por quê.** O JSONL continua sendo a verdade (append-only, legível, grep-ável,
event sourcing natural). O que falta não é armazenamento, é **índice**. O SQLite é
stdlib (FTS5 disponível), um arquivo só, derivado — por isso mora no `FRESH`.

**Arquivos.** `brainlib/index.py` (novo), `brainlib/core.py` (gancho pós-escrita),
`brainlib/search.py`, `brainlib/mcp_server.py`, `brainlib/cli.py`,
`brainlib/render.py`, `brainlib/doctor.py`, `tests/test_index.py`.

**Passos.**

1.1 **Esquema** (`FRESH/_index/brain.sqlite`, `PRAGMA journal_mode=WAL`):

```sql
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
  -- schema_version, last_seq, ledger_size, ledger_sha_tail, built_at, stale
CREATE TABLE events(
  seq INTEGER PRIMARY KEY, ts TEXT, type TEXT, id TEXT, date TEXT,
  actor TEXT, by TEXT, prov TEXT, source TEXT, data TEXT,   -- data = JSON
  class TEXT                                               -- fato|dono|sistema|telemetria
);
CREATE INDEX ev_id ON events(id);
CREATE INDEX ev_type_date ON events(type, date);

CREATE TABLE actions(
  id TEXT PRIMARY KEY, title TEXT, owner TEXT, list TEXT, status TEXT,
  due TEXT, due_suggested INTEGER, priority TEXT, parked INTEGER,
  project TEXT, deliverable TEXT, opened TEXT, closed TEXT, last_activity TEXT,
  source TEXT, prov TEXT, is_open INTEGER, is_overdue INTEGER, is_blocked INTEGER
);
CREATE INDEX act_open ON actions(is_open, due);
CREATE INDEX act_owner ON actions(owner, is_open);

CREATE TABLE decisions(id TEXT PRIMARY KEY, title TEXT, date TEXT, project TEXT,
  status TEXT, superseded_by TEXT, context TEXT, rationale TEXT, source TEXT, prov TEXT);
CREATE TABLE deliveries(id TEXT PRIMARY KEY, title TEXT, date TEXT, ref TEXT,
  result TEXT, impact TEXT, source TEXT, prov TEXT);
CREATE TABLE people(id TEXT PRIMARY KEY, name TEXT, role TEXT, relation TEXT, email TEXT);
CREATE TABLE aliases(alias_fold TEXT, person_id TEXT, PRIMARY KEY(alias_fold, person_id));
CREATE TABLE artifacts(id TEXT PRIMARY KEY, kind TEXT, title TEXT, date TEXT, raw TEXT,
  summary TEXT, link TEXT);
CREATE TABLE processes(id TEXT PRIMARY KEY, title TEXT, area TEXT, hours_month REAL, data TEXT);
CREATE TABLE opportunities(id TEXT PRIMARY KEY, title TEXT, area TEXT, status TEXT,
  ice REAL, ice_suggested INTEGER, data TEXT);
CREATE TABLE questions(id TEXT PRIMARY KEY, text TEXT, status TEXT, kind TEXT);
CREATE TABLE proposals(id TEXT PRIMARY KEY, kind TEXT, status TEXT, target TEXT);
CREATE TABLE planning(id TEXT PRIMARY KEY, kind TEXT, parent TEXT, title TEXT,
  status TEXT, due TEXT, done TEXT, weight REAL, progress REAL);

CREATE TABLE edges(src TEXT, rel TEXT, dst TEXT, PRIMARY KEY(src, rel, dst));
  -- owner, person, project, deliverable, blocked_by, unblocks, decided_by,
  -- supersedes, artifact_person, artifact_project, opp_process, opp_area
CREATE INDEX edges_dst ON edges(dst, rel);

CREATE VIRTUAL TABLE fts USING fts5(
  kind, ref, title, body, date UNINDEXED, path UNINDEXED,
  tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TABLE fts_docs(path TEXT PRIMARY KEY, sha TEXT);
```

1.2 **Atualização.**
- `index.update(brain)`: eventos de `seq > last_seq` (incremental); se o arquivo
  encolheu ou o trecho final não bate com `ledger_sha_tail`, refaz tudo (edição
  manual — o `validate` acusa). Tabelas de entidade: rematerializadas do `State`
  dobrado numa transação (`DELETE` + `INSERT`). FTS: entidades sempre; PROCESSED,
  RAW (tipos da seção 3.2) e PLANNING/PROFILE por `sha` em `fts_docs`.
- `is_overdue`/`is_blocked` dependem de "hoje": calculados na materialização e
  **reconferidos na leitura** contra `date('now')`.
- **Contrato multi-processo (R1):** `index.update` inteiro sob lock de arquivo
  dedicado (`fcntl.flock` em `FRESH/_index/.update.lock`); `last_seq` só avança
  (compare-and-set: `UPDATE meta SET value=:n WHERE key='last_seq' AND
  CAST(value AS INTEGER) < :n` — se não avançou, outro processo passou na frente:
  reler e repetir); `PRAGMA busy_timeout=2000` em **toda** conexão, inclusive
  `mode=ro` (hook, MCP). Fallback final: `meta.stale = 1` → leitor cai na dobra.
- **Gancho:** `Brain.record()` chama `index.update` depois do `_flush`, fora do lock
  do ledger, **best-effort** — erro no índice nunca falha a escrita. `render` e
  `nightly` também chamam. `brain index rebuild|status`.
- Telemetria (`connector.pulled`…) **fica no ledger** (hash de silêncio e doctor
  dependem dela); no índice ganha `class='telemetria'` e as views filtram por classe.

1.3 **Leitores.** `search.py` consulta `fts` com `bm25(fts, 3.0, 1.0)` (título 3×),
regra AND→OR e marca `match: "parcial"`; sem índice, cai no código atual. MCP lê do
SQLite em `mode=ro` + `PRAGMA query_only=1` com paridade de respostas.
**Sanitização FTS5 (R2):** helper único `fts_terms(query)`: quebrar em palavras,
envolver **cada** termo em aspas (dobrando aspas internas), sufixar o último com `*`;
`kind:x` é busca literal, nunca filtro de coluna; semântica de ID parcial
(`TASK-014` acha `TASK-0146`) decidida e travada por teste.

1.4 **`brain query`** (saída `lines` compacta, uma linha por item):
```
brain query actions [--open] [--overdue] [--due-within 7] [--person <id|alias>]
                    [--project PROJ-3] [--list mine|waiting|watching] [--blocked]
                    [--fields id,title,due,owner] [--format lines|json] [--limit 50]
brain query decisions [--project …] [--person …] [--since AAAA-MM-DD] [--active]
brain query person <id|alias>
brain query entity <ID>              # TASK/DEC/WIN/PROJ/GOAL/OPP/PROC
brain query sql "SELECT …"           # ro, uma instrução, ≤ 500 linhas
```
`--person` resolve alias pela tabela `aliases`. Skills `/ask`, `/person`, `/project`,
`/brief` passam a preferir `brain query` para estado.

**Testes.** Rebuild do zero = incremental após N escritas; concorrência real
intercalada de dois processos → zero `stale`, `last_seq` = máximo (R1); `is_overdue`
recalculado em outro dia; FTS acento/caixa/AND→OR/peso/`fts_terms` (R2); `query sql`
recusa `INSERT`/`ATTACH`/múltiplas instruções; paridade MCP com e sem índice.

**Pronto quando.** `estado` ≥ 95% pela rota do ledger; `brain search` < 50 ms com 10×
o volume sintético; MCP com paridade.

**Rollback.** Apagar `FRESH/_index/` — todos os leitores caem no caminho atual.

---

### Fase 2 — Hook: perna ledger antecipada · comum (commit 5.5)

**Objetivo.** O incômodo mais medido do sistema (hook injetando transcrição solta) é
corrigido **antes** de qualquer rebuild e de qualquer dólar de API.

**Passos.** `BRAIN_RECALL_ROUTE=ledger`: classifica ID (regex + prefixos antigos),
alias de pessoa (contra `aliases.alias_fold`), vocabulário de estado/tempo (pt/es) e
títulos dobrados de PROJ/GOAL (tabela `planning` — R6) e injeta até **3 linhas** do
ledger no formato `lines`, com marca `⟶ ledger/<ID>`. **Tudo o que não é estado
injeta nada** — o silêncio é a melhoria. A classificação mora em `brainlib/route.py`
(a mesma lógica do `/ask` e do eval) e é testada em produção por semanas antes de
ficar responsável pelo orçamento de 5 itens.

**Arquivos.** `brainlib/route.py` (novo), `services/hooks/recall_context.py`,
`tests/test_route.py`.

**Testes.** Tabela mensagem → rota (pt/es); nada injetado fora de estado; SQLite
ausente → hook silencia sem erro.

**Rollback.** `BRAIN_RECALL_ROUTE=off` (comportamento atual).

---

### Fase 3 — Banco único enriquecido, sem LLM · `embed`

**Objetivo.** O banco único já é real (decisão 8: `[memory] bank = "brain"` vale
para os dois modos); esta fase o torna **enriquecido** deterministicamente: só a fonte (RAW dos tipos da seção 3.2) + docs `ledger/DEC-*` e
`ledger/WIN-*`, com data do mundo, tags do ledger, entidades por alias e aliases do
banco. Sem LLM em qualquer passo.

**Por quê um banco só.** O diagnóstico: os dois são redundantes (o PROCESSED resume o
RAW) e misturam níveis de abstração no recall. O PROCESSED sai do vetor porque o FTS5
da Fase 1 cobre busca por palavra no texto curado; as páginas de ação/pessoa saem
porque o SQLite responde estado. Regra do banco: quem escreveu melhor que o extrator
(agente, CLI) não é re-extraído — entra como está; no `embed`, **tudo** entra como está.

**Arquivos.** `brainlib/memory.py` (reescrita de `documents()`, `setup()`, `sync()`),
`brainlib/config.py`, `config/brain.toml.example`, `services/hooks/recall_context.py`
(banco único), `services/idle_unload.py`, `tests/test_memory.py`.

**Passos.**

3.0 **Passo 0 — versão por digest (R5 generalizada).** Recriar o container na versão
fixada **por digest** (tag pode ser reempurrada); confirmar `docker ps` = pin;
smoke de compatibilidade contra o container real de cada recurso usado: `tags` no
recall, entidades explícitas no item de retain **em modo chunks** (metadado — sem
resolver no servidor), `/aliases`, `bm25_language`, `retain_chunk_size`,
`/documents/{id}/reprocess`, deleção de documento. Registrar a versão auditada em
`meta` do banco e em `guides/memory.md`. **Alvo: 1.2.0-slim por digest (decisão 9)** —
o 1.x valida config com erro alto (chave morta para de ser silêncio), então o
re-audit das chaves do `NO_LLM_CONFIG`/`FULL_CONFIG` é obrigatório, não cortesia.

3.1 **Configuração**:
```toml
[memory]
engine = "hindsight"
url = "http://localhost:8888"
bank = "brain"                     # banco único nos DOIS modos (decisão 8); raw_bank/mem_bank legados: lidos 1 versão, doctor avisa
max_file_mb = 25
exclude_types = ["connectors", "github"]
entity_types = { pessoa = "PERSON", projeto = "PROJECT", area = "ORG" }
raw_awaiting_dump = "degraded"     # embed: envia com contexto degradado (3.6)
recall_cutoff = 0.62               # corte sem reranker (hook) — calibrar na Fase 0
# camadas de LLM — setup full (Fases 6–9); embed = false
extract = false
cloud_llm = false                  # true = o dono ativou o envio à própria API (seção 4.3)
mental_models = false
```

3.2 **Data do mundo em todo documento** (ordem: `date` do `artifact.added` cujo `raw`
aponta o arquivo → carimbo no nome (`…-2026-10-19T182906.md`) → `capturado:` do
cabeçalho → primeiro dia de `RAW/<ano>/<mês>/`). Vai em `timestamp` do retain — conserta
os links temporais e habilita "o que se falou em setembro".

3.3 **Exclusões e sombra.** `exclude_types` fora do envio; o `sync` ganha **deleção
sombra**: documento que saiu de `documents()` (tipo excluído, página de ação
descontinuada, arquivo removido) é apagado do banco (`DELETE /documents/{id}`) com
registro no estado. Sem isso, o banco v2 herda lixo.

3.4 **Conteúdo.** `documents()` passa a emitir: RAW dos tipos da seção 3.2 (texto e
binários via `files/retain`), docs `ledger/DEC-####` e `ledger/WIN-####` (com tags e
data). Saem: PROCESSED, PLANNING/PROFILE, páginas de ação e de pessoa (FTS5/SQLite
cobrem). `_entity_docs()` encolhe para DEC/WIN.

3.5 **Tags** de cada documento: `tipo:<reuniao|slack|documento|nota>`, `pessoa:<id>`,
`proj:<PROJ-#>`, `goal:<GOAL-#>`, `area:<slug>`, `artefato:<caminho>`. Derivadas do
ledger (arestas artefato↔pessoa/projeto). Recall filtrado ("só PROJ-3") e dossiê
(Fase 5) usam as tags.

3.6 **Entidades e aliases determinísticos.** Pessoas/projetos do contexto do artefato
viram `entities` explícitas no item de retain — **anexadas por casamento de alias no
texto, sem resolução no servidor**. *Auditado na 1.2.0 (2026-11-05):* a entidade do
item é top-level com campo **`text`** (o `name` antigo devolve 422), aceita em modo
chunks e alimenta o grafo de entidades do servidor; aliases do ledger vão ao banco no
`setup` por `POST /aliases {alias, canonical}` (409 = já registrado). RAW degradado
(sem `/dump`) entra **sem entidades** (R7-embed).
RAW **sem artefato** (ainda sem `/dump`): regra decidida agora (R7-embed) — após
`degraded_after_days` (sugestão 7), entra com contexto degradado (tags `tipo:` e
`sem-artefato:1`, data do nome do arquivo, **sem entidades**). Quando o `/dump`
processar, o contexto muda, o `sha` muda e o documento reenvia com identidade plena.
Reprocessar é grátis no `embed` (embedding local) — por isso a política é "envia já,
enriquece depois" (no `full` é o contrário: esperar, para não pagar extração sem
âncora — Fase 7).

3.7 **Banco** (`setup`): `retain_extraction_mode = "chunks"` (sem LLM),
`enable_auto_consolidation = false`, `enable_observations = false` (nada na fila de
consolidação — `pending_consolidation` sempre 0). *Auditado na 1.2.0 (2026-11-05):*
**não existe chave `bm25_language`** (PATCH devolve "Unknown configuration fields") —
o analisador de texto fica no default do servidor; `retain_chunk_size` decide a Fase 0.

3.8 **Sync incremental.** `sha` do item = `sha(texto + contexto)`; mudança de contexto
(alias novo, artefato reprocessado) reenvia (`/documents/{id}/reprocess` quando o texto
é o mesmo). Rechurn é custo local (embedding), não API.

3.9 **Rebuild.** `brain memory rebuild --dry-run` (lista o que entra/sai, estimativa de
tempo — custo US$ 0); com "ok": cria `brain-mem-v2-embed` (não apaga nada), envia,
roda a Fase 0 contra o v2; se bater as metas do `embed`, troca `[memory].bank` e,
após uma semana sem regressão, apaga `brain-raw` e o `brain-mem` antigo (com "ok";
`DELETE` de banco é irreversível).

**Testes.** Data inferida nos quatro casos; exclusão por tipo + deleção sombra
(cliente falso); contexto degradado após N dias e reenvio com identidade após
`/dump`; entidades anexadas só por alias presente no texto; `sha` muda com o contexto;
banco criado com chunks/BM25 pt/sem consolidação.

**Pronto quando.** `literal` e `detalhe` ≥ baseline no v2 (metas direcionais: `detalhe`
+10 pts com chunk/BM25/datas/reranker); links temporais com datas do mundo; recall por
período funciona; zero `pending_consolidation`.

**Rollback.** `[memory].bank` volta ao banco antigo (guardado pela semana de
observação); `BRAIN_RECALL_BANKS` volta a dois bancos.

---

### Fase 4 — Roteador completo do hook (`embed`) + reranker local · `embed`

**Objetivo.** Cada mensagem recebe só o contexto da camada certa, ≤ 5 itens, nenhum
quando nada é pertinente — sem LLM na classificação nem na consulta.

**Arquivos.** `services/hooks/recall_context.py`, `brainlib/route.py`,
`commands/ask/SKILL.md`, `tests/test_route.py`.

**Restrições do hook.** `python3` do sistema (3.9), só stdlib, timeout total 2 s,
nunca bloqueia a mensagem. Lê o SQLite direto em `mode=ro` (sem subprocess do
`./brain`).

**Passos.**

4.1 **Classificação sem LLM** (regras da seção 3.3): regex de IDs (com prefixos
antigos), aliases de pessoa, títulos de PROJ/GOAL (R6), vocabulário de estado e de
literal (pt/es), e **expansão determinística de consulta**: a pergunta é reescrita
como múltiplas consultas (original + aliases da pessoa detectada + formas dobradas)
fundidas com deduplicação.

4.2 **Reranker local, com gate de latência.** Benchmark do compose refeito com
`jina-mlx` servido no host (Metal; verificar na 0.10.3 se o provider roda no container
ou aponta para endpoint do host — parte do smoke 3.0). Aprovar **só se p95 < 400 ms
com 30 candidatos**. Reranker de nuvem (`cohere`, `zeroentropy`) é **exclusivo do
`full`** (manda pergunta e candidatos para fora — mesma regra da seção 4.3: chave do
dono). Se nenhum passar: `rrf` e corte semântico 0,62.

4.3 **Saída por rota** (cada linha cita a fonte): ledger → até 3 linhas `lines`
`⟶ ledger/<ID>`; literal → 1–2 trechos de chunk (≤ 400 caracteres) `⟶ <document_id>,
<data>`; contexto → até 3 chunks/docs `⟶ <document_id>, <data>` (com reranker, ordena
por ele). Teto: **5 itens**. Texto de abertura "são pistas, não verdade…" mais curto.

4.4 **Prazo por perna (R9.1).** Orçamento interno: perna ledger primeiro (ms), perna
vetorial com teto próprio (700 ms sem reranker; 1.400 ms com reranker aprovado),
margem de 200 ms. Hindsight **lento** (não só fora) → hook degrada e entrega o que
tiver. `BRAIN_RECALL_ROUTE`: `off` | `ledger` | `embed` (default desta fase).

4.5 **`/ask`** passa a chamar `brain route "<pergunta>" --json` (mesma lógica, sem o
limite de 2 s) e segue índice → artefato → RAW, citando fonte e proveniência.

**Testes.** Tabela mensagem → rota (pt/es); orçamento de 5 itens; abstenção nas
`nada`; Hindsight lento degrada; SQLite ausente → só Hindsight; Hindsight fora → só
ledger.

**Pronto quando.** Precisão da injeção ≥ 60%, ≤ 5 itens/mensagem, abstenção ≥ 80%
nas `nada` (Fase 0); p95 do hook < 1 s.

**Rollback.** `BRAIN_RECALL_ROUTE=off`.

---

### Fase 5 — Dossiê determinístico · `embed` (fecha o setup)

**Objetivo.** Substituto honesto dos mental models quando não há LLM: montar, na hora
da leitura, a página "onde estamos com X" a partir de fontes citáveis — sem síntese
pré-computada, nunca velha.

**Passos.** `brain memory dossier <ID|alias>` monta e imprime (markdown compacto ou
`--json`):
1. **Ficha** da entidade pelo SQLite (`brain query entity/person`) — estado de hoje;
2. **Decisões e entregas ligadas** (edges do SQLite; texto integral do DEC/WIN);
3. **Melhores trechos** do banco com as tags da entidade (`pessoa:<id>`/`proj:…`/
   `goal:…`), cada um com `⟶ document_id, data`.
Sem LLM: é montagem, não julgamento — todo parágrafo tem fonte. Skills `/project` e
`/person` ganham a seção "Leitura atual" chamando o dossiê; o `/ask` usa quando a
rota detecta entidade. Não vira arquivo do FRESH (montado na leitura, como o `render`
deriva views — nada único é guardado).

**Arquivos.** `brainlib/memory.py` (`dossier`), `brainlib/cli.py`,
`commands/person/SKILL.md`, `commands/project/SKILL.md`, `tests/test_memory.py`.

**Testes.** Dossiê de pessoa e de projeto em vault de exemplo: ficha + DEC/WIN + N
trechos, todos com fonte; entidade sem memória → só a ficha (sem inventar); alias
resolvido.

**Pronto quando.** `contexto` e `decisao` da Fase 0 nas metas do `embed`
(direcional: `contexto` +5, `decisao` +10); `/project` e `/person` usando.
**Setup `embed` completo aqui** (commit 11 fecha docs — Fase 10).

**Rollback.** Comando novo, nada a reverter.

---

### Fase 6 — Compatibilidade com o provider (antes de gastar num rebuild) · `full`

**Objetivo.** Provar cada operação com o modelo escolhido, numa amostra, antes de
reconstruir o banco. Achados do provider `anthropic` na 0.10.3 (histórico; re-auditar
na 1.2.0 — passo 0):

| Ponto | Situação | Efeito |
|---|---|---|
| `temperature` / `thinking` | não enviados | ok |
| esforço | `reasoning_effort` ignorado | usar `*_LLM_EXTRA_BODY` (`output_config.effort`) |
| prompt de sistema | `cache_control` | desconto se passar do mínimo cacheável |
| Batch API | suportado | rebuild com −50% |
| **reflect/mental models** | força `tool_choice` nomeado | **Sonnet 5.5 recusa com 400** — bloqueante do cenário B |

**Resolvido upstream (decisão 9):** a regressão #5738 — `tool_choice` forçado quebra
reflect no Sonnet/Opus desde a 0.10.2 — foi fixada na **1.1.0** (todo tool call passa
a ir por response schema, sem `tool_choice` nativo; na 1.2.0 é o caminho universal).
O caminho (1) é o único: (2) PR upstream e (3) workaround Haiku ficam como histórico,
sem execução. O cenário B (Sonnet nos mental models) volta a ser o alvo da Fase 8.

**Passos.** Compose com `env_file: ../config/.env` só no serviço `hindsight`;
`HINDSIGHT_API_<OP>_LLM_*` por operação (retain/consolidation = Haiku high;
mental-model-refresh/reflect = Sonnet high; default = Haiku medium);
`HINDSIGHT_API_SKIP_LLM_VERIFICATION` sai; **ligar `enable_dry_run_extract`** (feature
flag; sem ela o dry-run falha com erro que parece do endpoint — R5);
`GET /banks/brain-mem/health/llm` por operação; dry-run com 5 chunks reais (reunião,
Slack, documento, nota, PDF); banco `brain-compat` com 20 documentos (retain,
consolidação, um mental model); `GET /llm-requests/stats` → conferir premissas de
custo (±2×).

**Pronto quando.** Três operações verdes com o modelo definitivo (ou substituto 3);
custo por chunk medido ≤ 2× da premissa. **Rollback:** voltar o compose; bancos atuais
intactos.

---

### Fase 7 — Extração da fonte no banco único · `full`

**Objetivo.** Fatos atômicos extraídos do RAW com identidades resolvidas, trechos
originais ligados para citação.

**Passos.**
- Config: `extract = true`, `cloud_llm = true` (o CLI **recusa** `extract` sem
  `cloud_llm` — o dono ativou o envio à própria API, seção 4.3);
  `raw_awaiting_dump = "hold"` — no `full`, RAW sem artefato **não é
  enviado**: nenhum fato nasce sem identidade resolvida (contraste com 3.6: no `full`,
  reextração custa dinheiro; `memory status` mostra quantos esperam `/dump`, e o
  limiar de backlog que abre conversa fica em > 20 arquivos).
- `setup`: `retain_extraction_mode = "custom"` com `retain_custom_instructions`
  (fatos duráveis: decisões e quem decidiu, compromissos com dono e prazo, entregas e
  números, objeções e argumentos, mudanças de plano, preferências; ignorar logística e
  ruído de transcrição; **usar só nomes/IDs do bloco de contexto, nunca inventar**;
  preservar datas/números/citações; fato no idioma do documento; atribuir fala a
  quem falou quando identificado), `enable_observations/enable_auto_consolidation =
  true`, entidades `resolve_entities = true`, Batch só no rebuild e no noturno.
- **Contexto por documento** (~700 tokens): caminho, tipo, data, artefato
  correspondente, pessoas (id · nome · aliases), projetos, IDs ligados — sai do
  ledger. **Rechurn no custo (R8):** estimar do ledger (`person.added`/`updated` e
  reprocessamentos × documentos afetados) e conferir na primeira semana; mitigação já
  desenhada (só nome canônico + aliases principais no prompt; os completos ficam em
  `/aliases`).
- Rebuild: `brain-mem-v2` paralelo pelo Batch API, dry-run com estimativa de custo
  (chunks × custo medido na Fase 6), "ok" do dono, Fase 0 contra o v2, troca de
  `[memory].bank`, semana de observação, apagar antigos com "ok".

**Testes.** `documents()` com vault de exemplo (exclusões, contexto, entidades, tags,
RAW sem artefato retido); `cloud_llm=false` + `extract=true` recusado com mensagem
clara; `sha(texto+contexto)` muda com alias novo.

**Pronto quando.** Metas da Fase 0 do `full` para `contexto`/`decisao`/`detalhe`/
`literal` batidas no v2; amostra de 50 fatos sem pessoa fora do ledger.

**Rollback.** `[memory].bank` volta ao banco antigo (não apagado).

---

### Fase 8 — Mental models · `full`

**Objetivo.** Uma página viva por tema importante que responda "onde estamos com X" e
"por que Y importa", regenerada dos fatos e do ledger.

**Passos.** Catálogo gerado do PLANNING + edges do SQLite (todo GOAL ativo →
`mm-goal-#`; todo PROJ ativo → `mm-proj-#`; ~6 pessoas com mais vínculos em 60 dias →
`mm-pessoa-<id>`); `source_query` por tipo em pt-BR **com o estado do ledger colado
deterministicamente no início** (o LLM não recalcula estado); gatilhos `mode: "delta"`,
`budget: "mid"`, `refresh_after_consolidation: false`, mínimo de 24 h por modelo e só
com fato novo nas tags; CLI `brain memory models sync|refresh|list|show`; superfícies:
recall (o Hindsight prioriza), `/project` e `/person` ("Leitura atual", com data da
versão e marca **[memória]**), opcionalmente `FRESH/notes/mm-<id>.md` pelo render.
**Proveniência inegociável (R9.4):** mental model é pista `[memória]`; o `/ask`
confirma no artefato/RAW antes de afirmar. Models de pessoa são o artefato mais
sensível do sistema (perfil comportamental de terceiros): data da versão sempre
visível.

**Testes.** Catálogo do PLANNING/ledger; arquivamento de projeto fechado; intervalo
mínimo; só atualiza com fato novo nas tags. **Pronto quando:** `conclusao` +30 pts;
nota do dono ≥ 4; custo dos models ±30% dos US$ 13,50. **Rollback:**
`mental_models = false` (páginas ficam sem uso).

---

### Fase 9 — Pernas de fatos e mental model no roteador · `full`

**Objetivo.** Completar o roteador da Fase 4 com as camadas de LLM.

**Passos.** `BRAIN_RECALL_ROUTE=full`: mantém ledger (≤ 3 linhas) e literal (1–2
trechos) e acrescenta **fatos** (≤ 3, `⟶ <document_id>, <data>`) e **mental model**
(1 item, ~400 caracteres + id + data da versão). Teto continua **5 itens**; corte
pelos scores do reranker quando aprovado (nuvem permitida neste setup — chave do
dono, seção 4.3). Vocabulário do classificador idêntico ao do `embed` (mesmo
`route.py`).

**Testes.** Orçamento de 5 itens com as quatro pernas; model não injetado quando
velho além do aceitável; tudo da Fase 4 continua valendo (lento degrada, fora cai).
**Pronto quando:** precisão ≥ 60%, ≤ 5 itens, `conclusao` nas metas. **Rollback:**
`BRAIN_RECALL_ROUTE=embed`.

---

### Fase 10 — Operação, documentação e constituição · por setup

1. **`brain memory cost`** — **medidor mensal** (decisão 3): `GET /llm-requests/stats`,
   agrupa por operação/modelo, aplica `[memory.prices]`, mostra o mês corrente (tokens
   + US$) e projeta o fechamento; `embed` reporta US$ 0 e conta chunks. **Sem teto,
   sem bloqueio** — responsabilidade do dono; o `doctor` mostra o gasto do mês como
   informação, não como aviso.
2. **`brain memory status`**: banco único, fila, documentos aguardando `/dump` (no
   `full`), mental models desatualizados (no `full`).
3. **`idle_unload.py`**: lista de bancos única; no `embed` o LM Studio só carrega o
   `bge-m3` (+ reranker aprovado).
4. **Noturno:** `memory sync` → (`full`: `memory models refresh`) → `index update`.
   Nenhum desses é evento do dono; no `embed`, nada de gate (sem egress).
5. **`guides/memory.md` reescrito por setup** (inclui como voltar de `full` a
   `embed`: `extract=false` + rebuild; e o aviso de versão auditada do Hindsight).
6. **Setup assistido:** atualizar a tabela de modos do passo 11 — `embed` passa a ser
   "banco único enriquecido (datas, tags, entidades), sem LLM" (não mais "os dois
   bancos de hoje"); a pergunta do modo `full` vira registro da escolha (chave do
   dono), não gate de política corporativa.
7. **AGENTS.md** (diff proposto, aplicado com "ok"): seção Memória por setup; zonas
   `FRESH/_index/` (derivado, `brain index`) e `vault/eval/` (curado: agente propõe,
   dono aprova); `/ask` roteado por tipo com `brain query` para estado; **no `full`
   apenas**: a linha de Segurança da seção 4.3 (registro do comportamento).
8. `./brain upstream scan` + proposta de commit ao dono (porta 5), generalizando
   exemplos.

---

## 6. Ordem dos commits (escada unificada — bifurcação no 12)

| # | Commit | Fase | Setup |
|---|---|---|---|
| 1 | `eval: conjunto de perguntas (com tipo nada), brain memory eval, baseline` | 0 | comum |
| 2 | `index: projeção SQLite do ledger (eventos, entidades, edges)` + lock/CAS (R1) | 1 | comum |
| 3 | `index: FTS5, fts_terms e search pelo índice` (R2) | 1 | comum |
| 4 | `mcp: leitura pelo índice e ferramenta query` | 1 | comum |
| 5 | `query: brain query (actions, decisions, person, entity, sql)` + skills | 1 | comum |
| 5.5 | `hook: rota ledger-only (BRAIN_RECALL_ROUTE=ledger), 3 linhas, silêncio nos demais` (R3) | 2 | comum |
| 6 | `memoria: datas do mundo no RAW e exclusão por tipo + deleção sombra` | 3 | comum |
| 7 | `memoria: banco único embed enriquecido (BM25 pt, chunk, tags, entidades, aliases, contexto degradado) — v2-embed` | 3 | `embed` |
| 8 | `hook: roteador embed (ledger + literal/contexto, ≤5 itens, prazo por perna)` (R6, R9.1) | 4 | `embed` |
| 9 | `memoria: reranker local jina-mlx (gate p95) ou corte calibrado` | 4 | `embed` |
| 10 | `memoria: dossiê determinístico (brain memory dossier)` | 5 | `embed` |
| 11 | `memoria: status/doctor/noturno embed + docs (guides/memory.md, setup assistido, AGENTS zonas)` | 10 | **`embed` pronto** |
| 12 | `memoria: LLM por operação no compose, dry-run, chave do dono (cloud_llm)` (+ digest, R5) | 6 | `full` |
| 13 | `memoria: extração da fonte no banco único (contexto, entidades resolvidas, DEC/WIN) — v2` | 7 | `full` |
| 14 | `memoria: mental models por goal, projeto e pessoa` | 8 | `full` |
| 15 | `hook: pernas de fatos e mental model (BRAIN_RECALL_ROUTE=full)` | 9 | `full` |
| 16 | `memoria: medidor mensal de custo, noturno full e documentação (AGENTS: registro de segurança)` | 10 | **`full` pronto** |

Commits 1–11: sem chave, sem egress, US$ 0 — **setup `embed` completo**. Do 12 em
diante: só depois dos pré-requisitos da seção 4.3 (chave do dono).

## 7. O que não muda

- `events.jsonl`: formato, regras de escrita, IDs, gates, noturno — **formato fechado
  por decisão do dono** (campo `h` encadeado: **nunca**).
- O pipeline do `/dump` e o PROCESSED: continuam a fonte da leitura humana, da
  citação, do `/share` e do FRESH.
- "Não consta" continua resposta válida; memória continua pista.
- Embeddings locais (`bge-m3`), recall sem LLM no caminho da consulta, MCP
  somente-leitura.
- Nenhuma porta nova para o mundo exterior — o egress do `full` vai só à API com a
  chave do dono e é registrada na AGENTS.md (seção 4.3); a invariante "nada do dono
  no repo público" continua com a porta 5.

## 8. Ganhos esperados e metas por setup (Fase 0; direcionais até ~25/tipo — R4)

| Métrica | Baseline hoje | Meta `embed` | Meta `full` |
|---|---|---|---|
| `estado` (ledger) | baixo (cai no vetor) | ≥ 95% | ≥ 95% |
| `detalhe` | médio | +10 pts (chunk, BM25 pt, datas, reranker local) | +20 pts (+ fatos da fonte) |
| `literal` | alto | sem piora | sem piora |
| `contexto` | médio-baixo | +5 pts (banco único, tags, dossiê) | +20 pts (fatos + observações) |
| `decisao` | médio | +10 pts (docs DEC + datas + BM25) | +15 pts |
| `conclusao` | baixo | ≈ baseline (síntese na hora da resposta; dossiê entrega a evidência) | +30 pts (mental models) |
| Abstenção (`nada`) | ~0 (hoje injeta sempre) | ≥ 80% | ≥ 80% |
| Itens injetados/mensagem · precisão | ~8 · baixa | ≤ 5 · ≥ 60% | ≤ 5 · ≥ 60% |
| `brain search` com 10× volume | lento (relê tudo) | < 50 ms | < 50 ms |
| Custo de API | US$ 0 | **US$ 0** | ~US$ 20,50/mês (medidor mensal, sem teto) |

Ganhos estruturais comuns: identidade consistente (aliases do ledger no banco e no
classificador), recuperação temporal real (datas do mundo), CLI/MCP/TUI que escalam
(índice em vez de refold), custo visível e medido por setup.

## 9. Riscos e mitigação

| Risco | Setup | Mitigação |
|---|---|---|
| Container ≠ versão analisada (confirmado: 0.10.1 rodando, pin 0.10.3) | ambos | Passo 0 por digest + smoke de cada recurso (3.0, Fase 6); versão auditada registrada |
| Concorrência de índice (CLI×MCP×noturno×TUI) | comum | Lock de arquivo + CAS de `last_seq` + `busy_timeout` (R1); fallback `stale`→dobra |
| FTS5 recebe sintaxe de consulta (`TASK-0146`, `kind:x`) | comum | `fts_terms` único, semântica de prefixo decidida por teste (R2) |
| Entidade por alias literal erra (parafraseio, erro de transcrição) | `embed` | Por desenho: sem identidade inventada; no `full`, a extração resolve |
| Banco único mistura níveis de abstração | ambos | Tags + tipagem + roteador; **critério de saída por escrito (R9.3):** se `detalhe`/`literal` mostrar contaminação, separar chunks de evidência em banco próprio (as tags tornam o split barato) |
| `jina-mlx` não existe como provider/estoura latência | `embed` | Gate p95 < 400 ms; senão `rrf` + corte 0,62 calibrado |
| Sonnet 5.5 recusa `tool_choice` forçado do reflect | `full` | Fase 6: versão nova, PR upstream ou Haiku sem thinking (confirmado no código) |
| Dono não quer egress | qualquer | Fases 0–5 entregam o setup `embed` completo; `cloud_llm=false` recusa `extract` |
| Extração inventa/troca nomes | `full` | Contexto com IDs, entidades explícitas, "não inventar", amostra de 50 na Fase 7 |
| Custo acima do previsto | `full` | Medição na Fase 6, medidor mensal, Batch no rebuild, `delta` + intervalo nos models |
| Rechurn de contexto reenvia em cascata | `embed` grátis · `full` custa | R8: estimar do ledger, conferir na 1ª semana; aliases principais no prompt, completos em `/aliases` |
| RAW sem artefato: `embed` envia sem identidade / `full` acumula backlog | ambos | Regra decidida (3.6 / Fase 7): degradado após 7 dias vs. hold + limiar 20 abre conversa |
| Índice velho mente sobre atraso | comum | Recalculado na leitura; `stale` cai na dobra |
| Hindsight fora/lento | comum | Hook degrada por perna e cai só no ledger; `/ask` usa índice → artefato → RAW |
| Rebuild apaga memória boa | ambos | Banco v2 paralelo, troca por config, apagar só após semana e com "ok" |
| Mental model vira "verdade" | `full` | Marca `[memória]`, obrigação de confirmar no vault, estado do ledger colado deterministicamente |

## Decisão da Fase 0

*(preencher depois de rodar: chunk size, corte do hook, reranker aprovado ou não; no
`full`: fonte escolhida, modelo do retain, modelo dos mental models)*

---

## Decisões do dono (registradas — não re-litigar)

1. **Setup é escolha livre, nos dois sentidos.** `embed` e `full` são caminhos de
   primeira classe; começar por qualquer um, subir para `full` e voltar para `embed`
   quando quiser. Não é um-ou-outro (§4.5).
2. **`full` = chave do dono + nada público.** Dados só vão à API configurada com a
   chave aprovada do dono (provider livre, `.env`, nunca no repo). LLM local: sem
   gate. A invariante é **nenhum dado do dono público** (porta 5). A linha da
   AGENTS.md registra o comportamento; sem gate de política corporativa (§4.3).
3. **Sem teto de gasto.** Custo é responsabilidade do dono. `brain memory cost` vira
   medidor mensal (tokens + US$ por operação/modelo); ninguém é bloqueado por gasto
   (§4.3, Fase 10).
4. **Reranker local `jina-mlx`: testar** — aprovado só se p95 < 400 ms @ 30
   candidatos (Fase 4.2).
5. **RAW sem artefato: como desenhado** — `embed` envia com contexto degradado após
   7 dias; `full` retém até o `/dump`; limiar 20 abre conversa (3.6, Fase 7).
6. **Eval: confirmado** — ~60 perguntas com tipo `nada`, dono revisa e aprova; zona
   curada `vault/eval/`, exemplo genérico no `template/` (Fase 0).
7. **Campo `h` encadeado no ledger: nunca.** O formato do evento é fechado (§7).
8. **Um banco só, chamado `brain`, nos dois modos** (2026-11-05). O `embed` abandona o
   modelo de dois bancos: `[memory] bank = "brain"` vale para `embed` e `full`;
   `mem_bank`/`raw_bank` viram legados (lidos 1 versão, doctor avisa). Migração de
   instâncias com `brain-raw`/`brain-mem`: trocar a config + `brain memory rebuild`
   (bancos são derivados do vault; no `embed`, custo US$ 0 — só re-embed local).
9. **Hindsight 1.2.0 por digest** (2026-11-05). O pin 0.10.3 carregava a regressão
   upstream #5738 (fixada na 1.1.0) e nenhum dos ganhos que este plano usa (mental
   models endurecidos, datas no fuso do conteúdo, schema-por-resposta universal).
   O compose fixa `1.2.0-slim` por digest; re-audit de config obrigatório (1.x falha
   alto em chave morta). Migrações Alembic são forward-only: export/backup antes;
   rollback = restaurar o export ou `rebuild` (bancos derivados).
10. **Colisão de nome/porta é precondição** (2026-11-05). Máquina que já roda outro
    Hindsight no :8888 (ex.: o serviço pessoal do Hermes do dono): **adotar** o
    servidor existente (`[memory].url` aponta pra ele; o banco `brain` nasce lá) ou
    sobrepor as portas por env no compose. Nunca dois containers reclamando
    `container_name: hindsight`/8888 na mesma máquina.
11. **O serviço único também serve os harnesses** (2026-11-05). O mesmo servidor
    hospeda `brain` (derivado do vault) e `hermes` (memória dos agentes: Claude
    Code/Cursor/Codex/Hermes). Banco de agente nunca é tocado pelo `memory rebuild`
    nem vira fato do vault. Design completo: `guides/plans/memory-harness-wizard.md`.
