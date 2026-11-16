# Plano — Estado da arte da memória (ledger + Hindsight)

Executor: agente de código da instância. Regime dos outros planos: testes verdes
(`python3 -m pytest tests/`, e a TUI com o venv `.venv-tui` quando tocar nela), **um
commit local por passo**, nada do dono no repo, `./brain upstream scan` antes de propor
o push. Cenário de custo adotado: **B** (Haiku 5.5 na extração e na consolidação, Sonnet
5.5 nos mental models).

Este documento explica **o que muda, por que muda e como se mede** que mudou para
melhor. As fases são independentes até onde dá: a Fase 1 (ledger) e a Fase 2 (Hindsight
sem LLM) não dependem da chave da Anthropic nem da decisão de política. As Fases 3 a 6
dependem das duas.

---

## 0. Resumo

Hoje o cérebro tem **um livro-razão** (`events.jsonl`) e **dois bancos vetoriais** no
Hindsight (`brain-raw`, `brain-mem`). Os dois só guardam trechos com embedding: nenhum
modelo de linguagem lê nada, e o motor de memória vira, na prática, um pgvector com BM25.

O plano:

1. **Mantém o JSONL como verdade** e acrescenta uma **projeção SQLite** derivada (índices,
   FTS5, consultas estruturadas). Perguntas de estado ("o que está atrasado com X?") param
   de ir para o banco vetorial.
2. **Funde os dois bancos num só**, alimentado pela **fonte** (RAW de reuniões, Slack,
   documentos e notas), com **extração de fatos por LLM**. As identidades e os IDs
   resolvidos pelo `/dump` entram como contexto. Os trechos originais ficam guardados junto
   dos fatos para a citação literal.
3. **Tira o PROCESSED e as páginas de ação da memória vetorial.** O PROCESSED continua no
   vault (leitura, citação, `/share`, FTS5). As conclusões passam a morar em **mental
   models** (um por GOAL, PROJ e pessoa principal), regenerados a partir dos fatos e do
   ledger.
4. **Roteia cada pergunta pela camada certa**: ledger para estado, banco de fatos para
   contexto, trecho original para a letra exata. O hook injeta menos itens, e todos
   pertinentes.
5. **Mede tudo antes e depois** com um conjunto fixo de perguntas reais (Fase 0).

Custo esperado do cenário B: **~US$ 20 por mês, ~US$ 245 por ano** (seção 5), medido
de verdade pela tabela `llm-requests` do Hindsight na primeira semana.

| | Hoje | Depois |
|---|---|---|
| Verdade das entidades | `events.jsonl` | `events.jsonl` (sem mudança) |
| Consulta estruturada | refold em Python a cada chamada; busca linear | SQLite derivado, indexado, FTS5 |
| Bancos Hindsight | 2 (`brain-raw` + `brain-mem`), só chunks | 1 (`brain-mem`), fatos + chunks + mental models |
| LLM no Hindsight | nenhum (qwen3-4b configurado, nunca chamado) | Haiku 5.5 (retain, consolidação), Sonnet 5.5 (mental models) |
| Entidades no grafo | nenhuma | pessoas e projetos do ledger, com aliases |
| Datas no RAW | ausentes (`date: None`) | data do mundo, vinda do ledger ou do nome do arquivo |
| PROCESSED | embutido como chunks | fora da memória vetorial; FTS5 + contexto da extração |
| Páginas `ledger/TASK-*` | embutidas (ficam velhas entre syncs) | fora; o estado vem do SQLite |
| Hook | 2 bancos, corte semântico 0,55, até 8 itens | roteador: ledger e/ou fatos, até 5 itens |
| Saída de dados da máquina | nenhuma | texto do vault vai à API da Anthropic (**gate**, seção 4) |

---

## 1. Diagnóstico (instância de referência, 16 dias de uso)

### 1.1 Livro-razão

| Métrica | Valor |
|---|---|
| Eventos | 1.167 (~73 por dia) |
| Tamanho | 470 KB, ~425 B por evento → ~11 MB e ~27 mil eventos por ano |
| `read_events` + `state.build` | 3 ms + 2 ms |
| `validate_all` | 12 ms |
| `brain status` | 80 ms (quase tudo é a partida do Python) |
| Telemetria (`connector.pulled` 286, `connector.failed` 33, `run.completed` 11) | 28% dos eventos |

O que isso significa:

- **O formato não custa tokens.** O LLM nunca lê o `events.jsonl`: tudo passa pelo
  `./brain`. Os tokens vão para a saída do CLI, as views do FRESH, o hook e o recall.
- **O custo de CPU é O(n) por processo.** Cada chamada do CLI, cada ferramenta do MCP
  (`mcp_server.py` relê o ledger a cada chamada) e cada escrita (`Brain.record` relê e
  revalida tudo dentro do lock) reconstrói o estado do zero. Hoje são 5 ms. Com 5 anos
  (~150 mil eventos) seriam centenas de ms por chamada. A TUI e o MCP sentem primeiro.
- **A busca escala pior que o ledger.** `search.py` monta o modelo inteiro e **relê do disco
  cada artefato `.md` a cada busca**, com contagem de substring em Python.
- **Perguntas estruturadas caem no banco vetorial.** Teste: "quais ações estão atrasadas
  com a pessoa X?" no `brain-mem` devolveu notas de onboarding e três ações, nenhuma
  escolhida por estar atrasada. Atraso é uma conta. Similaridade semântica não faz conta.

### 1.2 Hindsight

- Versão **0.10.3** em Docker (`services/compose.yaml`), embeddings `bge-m3` pelo LM
  Studio (Metal), reranker `rrf`.
- `brain-mem`: 376 documentos → 432 nós. `brain-raw`: 214 documentos → 1.354 nós. Todos do
  tipo `world` (chunks). `pending_consolidation` 432 e 1.354: a consolidação está desligada
  de propósito (`NO_LLM_CONFIG` em `brainlib/memory.py`).
- **O RAW vai sem data** (`"date": None` em `memory.documents()`). Os ~19 mil links
  "temporais" do `brain-raw` refletem a hora da ingestão, não a data dos fatos. A
  recuperação temporal fica inútil.
- **Sem extração, não há entidades.** O recuperador de grafo trabalha praticamente vazio, e
  dois apelidos da mesma pessoa continuam sendo strings diferentes. O ledger já tem os
  aliases; a memória não usa.
- **Os bancos são redundantes.** O PROCESSED resume o RAW, o hook consulta os dois e mistura
  pelo score semântico. Resultado: duplicatas no limite de 8 itens e níveis de abstração
  misturados.
- **O reranker neural já foi testado** (comentário em `services/compose.yaml`):
  `bge-reranker-v2-m3` na CPU do container subiu o top-1 de 91,7% para 95,8%, mas levou
  1,6 s com 30 candidatos. Isso estoura o timeout de 2 s do hook. Ele só vale servido no
  host, com aceleração (Fase 2.4).

### 1.3 Hook de recall (`services/hooks/recall_context.py`)

- Consulta `brain-mem` e `brain-raw` em paralelo, corte semântico 0,55, até 8 itens, trecho
  do RAW cortado em 400 caracteres.
- Na prática injeta trechos de transcrição sem relação com a pergunta ("pera aí, essa tela
  é muito grande"). Cada item irrelevante custa tokens em **toda** mensagem e disputa
  atenção com o contexto que importa.

### 1.4 Volume de texto extraível

| Pasta do RAW | Texto | Entra na extração? |
|---|---|---|
| `meetings/` | 1,63 MB | sim: é onde mora o valor |
| `documents/` | 0,79 MB + 4 binários | sim |
| `notes/` | 0,19 MB | sim |
| `slack/` | 0,10 MB | sim |
| `connectors/` | 0,58 MB (Jira, agenda) | **não**: espelho de sistema estruturado, já virou ledger |
| `github/` | 0,28 MB | **não**: diff de código, ruído para a memória |
| `videos/`, `images/` | binários | só a transcrição, quando existir como texto |

Total extraível: ~3,0 MB em 16 dias → **~1.900 chunks de 3.000 caracteres por mês**. É um
teto: o período inclui o onboarding e os primeiros pulls, que trazem backlog.

---

## 2. Princípios do desenho

1. **O vault continua sendo a verdade.** Tudo o que este plano cria (SQLite, banco de
   fatos, mental models) é derivado e reconstruível. Apagar qualquer um deles não perde
   nada: `brain index rebuild` e `brain memory rebuild` refazem.
2. **Cada tipo de pergunta tem a sua camada.**
   - *Estado* (prazo, status, quem deve, atraso, progresso) → ledger via SQLite. Determinístico.
   - *Contexto* ("o que sabemos sobre X", "por que decidimos Y") → banco de fatos e mental models.
   - *Letra* ("o que exatamente foi dito") → trecho original guardado junto do fato.
   Misturar camadas é a principal causa de ruído hoje.
3. **Extrair da fonte, ancorado no que já foi resolvido.** O `/dump` é seletivo por
   desenho, e a memória existe para perguntas que ninguém previu. Extrair do resumo herda
   o que ele deixou de fora. Mas o RAW sozinho não sabe que "Mari" é `marina-demo`, nem
   que a conversa é do `PROJ-3`. Por isso a extração lê o RAW **com** o mapa de identidades
   e IDs do artefato correspondente.
4. **O modelo certo por operação, com esforço explícito.** Extração e consolidação são
   tarefas estruturadas e de alto volume: Haiku 5.5. Síntese de páginas inteiras (mental
   models) é pouco volume e mais julgamento: Sonnet 5.5. O Opus não entra.
5. **Menos é mais na injeção.** Cinco itens certos valem mais que oito parecidos. O hook
   aprende a não injetar nada quando nada passa do corte.
6. **Medir antes de mudar.** Nenhuma fase é dada como pronta sem bater o baseline da Fase 0
   nas perguntas do seu tipo.

---

## 3. Arquitetura alvo

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
   │ events (todas as linhas) │     │ fatos extraídos (Haiku 5.5 high) │
   │ actions, decisions, …    │     │   ← RAW meetings/slack/docs/notes│
   │ people + aliases         │────▶│   ← contexto: entidades e IDs    │
   │ edges (ação↔pessoa↔proj) │ ent.│ chunks de origem (letra exata)   │
   │ fts (títulos, PROCESSED, │     │ observações (Haiku 5.5 high)     │
   │      RAW texto)          │     │ mental models (Sonnet 5.5 high)  │
   └───────────┬──────────────┘     │   1 por GOAL/PROJ/pessoa         │
               │                    │ decisões e entregas do ledger    │
               │                    └───────────────┬──────────────────┘
               │                                    │
               ▼                                    ▼
   brain query · brain search · MCP · TUI     recall (embedding local, sem LLM)
               └──────────────┬─────────────────────┘
                              ▼
                 hook roteador (até 5 itens) · /ask
```

### 3.1 Camadas

| Camada | Onde | Conteúdo | Quem escreve | Responde |
|---|---|---|---|---|
| Ledger | `PROCESSED/_ledger/events.jsonl` | eventos | só `./brain` | tudo, é a verdade |
| Projeção | `FRESH/_index/brain.sqlite` | estado atual + índices + FTS5 | `brain index` | estado, busca por palavra |
| Fatos | Hindsight `brain-mem` | fatos atômicos com entidades, datas e tags de ID | retain (Haiku) | contexto, "o que sabemos" |
| Evidência | Hindsight `brain-mem` (chunks dos documentos) | texto original | retain | a letra exata |
| Observações | Hindsight `brain-mem` | fatos estáveis consolidados | consolidação (Haiku) | padrões, preferências |
| Mental models | Hindsight `brain-mem` | uma página viva por GOAL, PROJ e pessoa | refresh (Sonnet) | "onde estamos com X", conclusões |
| Vault legível | `PROCESSED/`, `PLANNING/`, `PROFILE/` | artefatos e verdade curada | `/dump`, dono | leitura humana, citação, `/share` |

### 3.2 O que vai e o que não vai para o banco de fatos

| Origem | Vai? | Como |
|---|---|---|
| `RAW/*/meetings/`, `slack/`, `documents/`, `notes/` | sim | extração de fatos + chunks |
| PDFs/DOCX de `documents/` | sim | `files/retain` (o Hindsight converte), mesma extração |
| `RAW/*/connectors/`, `github/` | não | estado já no ledger; código é ruído |
| `RAW/*/videos/`, `images/` | só se houver transcrição em texto | a transcrição é tratada como reunião |
| `PROCESSED/*.md` | não | serve de **contexto** da extração do RAW correspondente |
| Ledger: decisões e entregas | sim, como documentos curtos | o "por quê" é narrativo e responde perguntas de contexto |
| Ledger: ações, pessoas, propostas | não | estado volátil → SQLite; pessoas viram **entidades** |
| `PLANNING/`, `PROFILE/` | não como documento | lidos direto (são pequenos e sempre verdade) e usados como semente dos mental models |
| inbox | não | ainda não processada |

### 3.3 Roteamento de perguntas

| Sinal na pergunta | Rota | Exemplo |
|---|---|---|
| ID (`TASK-…`, `DEC-…`, `PROJ-3`, `GOAL-1`, `OPP-…`) | ledger: ficha da entidade | "como está a TASK-0146?" |
| estado ou tempo (atrasad, prazo, vence, pendente, aberta, quem deve, esta semana) | ledger: `brain query` | "o que está atrasado com a Marina?" |
| nome ou alias de pessoa | ledger (pendências da pessoa) **e** mental model da pessoa | "o que tenho com a Marina?" |
| "exatamente", "palavras", "o que foi dito", citação entre aspas | chunks de origem | "o que exatamente foi dito sobre o SLA?" |
| demais | fatos + observações + mental model mais próximo | "por que mudamos o processo de pagamento?" |

---

## 4. Decisões do dono (gates — nada das Fases 3 a 6 roda sem elas)

1. **Política de dados.** A AGENTS.md diz que o vault não sai da máquina, salvo pelas
   portas. Extrair com um modelo de nuvem manda texto do RAW (reuniões, Slack, documentos)
   para a API da Anthropic. Isso exige:
   - decisão explícita do dono ("ok");
   - confirmação de que a política da empresa permite esse tipo de conteúdo nessa API
     (retenção de dados, ZDR se aplicável);
   - uma linha nova na seção **Segurança** da AGENTS.md: "Exceção: a camada de memória
     (Hindsight) envia texto do vault à API de LLM configurada em `[memory].llm`, só para
     extração, consolidação e mental models, quando `[memory].cloud_llm = true`."
   Sem essa decisão, executar só as Fases 0 a 2 (nada sai da máquina).
2. **Chave.** `ANTHROPIC_API_KEY` mora em `config/.env` (permissão 600), nunca no
   `compose.yaml`. O compose lê com `env_file`. O agente só confere que a variável existe.
3. **Mudanças na constituição** (diff proposto na Fase 7, aplicado só com "ok"):
   seção Memória para IA (um banco, extração por LLM, mental models), nova pasta derivada
   `FRESH/_index/`, nova zona curada `vault/eval/` (conjunto de perguntas), exceção de
   Segurança acima.
4. **Teto de gasto.** Proposta: alerta no `brain doctor` acima de US$ 40 por mês (o dobro do
   esperado) e configurar um limite de gasto mensal no console da Anthropic.

---

## 5. Modelos e custo (cenário B)

### 5.1 Configuração por operação

O Hindsight 0.10.3 aceita um LLM por operação (`HINDSIGHT_API_<OP>_LLM_*`). O provider
`anthropic` **ignora `reasoning_effort`**, então o esforço vai em `*_LLM_EXTRA_BODY`
(`output_config.effort`). O provider não envia `temperature` (que a API recusa desde
21/10/2026) nem configura `thinking` (fica o padrão adaptativo do modelo).

| Operação | Modelo | Esforço | Variáveis |
|---|---|---|---|
| Retain (extração) | `claude-haiku-5-5` | high | `HINDSIGHT_API_RETAIN_LLM_PROVIDER=anthropic`, `…_RETAIN_LLM_MODEL`, `…_RETAIN_LLM_EXTRA_BODY={"output_config":{"effort":"high"}}` |
| Consolidação / observações | `claude-haiku-5-5` | high | `HINDSIGHT_API_CONSOLIDATION_LLM_*` (mesmo formato) |
| Mental models (refresh) | `claude-sonnet-5-5` | high | `HINDSIGHT_API_MENTAL_MODEL_REFRESH_LLM_*` |
| Reflect avulso | `claude-sonnet-5-5` | high | `HINDSIGHT_API_REFLECT_LLM_*` (quase não usado) |
| Padrão (fallback) | `claude-haiku-5-5` | medium | `HINDSIGHT_API_LLM_*` |
| Embeddings | `bge-m3` local (LM Studio) | — | sem mudança, custo zero |
| Recall | sem LLM | — | consultas continuam grátis |

**Por que Haiku na extração.** Atomizar fatos de um texto com esquema fixo é o degrau
"resumos, extração" da escada de custo e desempenho dos modelos 5.5: o Haiku em high
entrega o mesmo que o Sonnet em medium por uma fração do preço. Transcrição é mais suja
que um artefato limpo (erros de reconhecimento de fala, falante trocado), por isso high e
não medium. A Fase 0 confirma.

**Por que Sonnet nos mental models.** Uma atualização lê ~30 mil tokens de fatos e escreve
uma página inteira. É síntese com julgamento e pouco volume (~150 por mês). Sonnet em
high é o ponto da fronteira para isso. Low e medium do Sonnet são dominados pelo Haiku high
e não fazem sentido.

### 5.2 Premissas

- ~1.900 chunks por mês; por chunk, ~4.000 tokens de entrada (~2.500 de instruções, ~700 de
  contexto de identidades e IDs, ~860 de texto) e ~1.600 de saída (fatos + raciocínio em high).
- ~8 fatos por chunk, consolidados em lotes de 20: ~760 chamadas por mês, ~6.000 tokens de
  entrada e ~2.000 de saída cada.
- ~15 mental models, ~150 atualizações por mês (no máximo 1 por dia por modelo, e só quando
  algo relacionado mudou), ~30.000 tokens de entrada e ~3.000 de saída cada.
- 2 rebuilds completos por ano, diluídos nos meses.
- Preços: Haiku 5.5 US$ 0,10 / US$ 0,50 por milhão de tokens (até 100 mil tokens de prompt);
  Sonnet 5.5 US$ 2 / US$ 10.

### 5.3 Custo esperado (US$)

| Componente | Por mês | Por ano |
|---|---|---|
| Retain (Haiku high) | 2,28 | 27,36 |
| Consolidação (Haiku high) | 1,22 | 14,64 |
| Mental models (Sonnet high) | 13,50 | 162,00 |
| Rebuilds diluídos (Haiku) | 3,50 | 42,00 |
| **Total cenário B** | **~20,50** | **~246** |
| Rebuilds pelo Batch API (−50%) | −1,75 | −21 |
| Mental models em modo `delta` (estimativa: −30% na saída) | −1,35 | −16 |

Para comparação: cenário A (Haiku em tudo) ~US$ 7,70 por mês; Sonnet high em tudo ~US$ 153
por mês. **Os mental models são dois terços do custo do cenário B.** Se a Fase 0 mostrar
que o Haiku sintetiza tão bem quanto o Sonnet, trocar ali derruba o custo para o
cenário A. Atualizar os mental models por semana em vez de por dia corta essa parcela pela
metade.

### 5.4 Alavancas de custo já disponíveis no Hindsight

- **Prompt caching.** O provider marca o prompt de sistema com `cache_control`. Se as
  instruções passarem do tamanho mínimo cacheável do modelo, a parte fixa de cada retain
  sai com desconto. Verificar `cache_read_input_tokens` em `/llm-requests`.
- **Batch API** (`retain_batch_enabled`). Metade do preço, com o desconto de cache somado.
  A resposta pode levar horas, então só para rebuild e para o noturno, nunca para o sync
  depois de um `/dump` durante o dia.
- **Mental model `mode: "delta"`.** Edita só as seções que mudaram em vez de reescrever a
  página.
- **`mental_model_min_refresh_interval_seconds = 86400`.** Teto de uma atualização por dia
  por modelo.

### 5.5 Medição real

`GET /v1/default/banks/brain-mem/llm-requests/stats` dá tokens por operação. Na primeira
semana do cenário B, `brain memory cost` (Fase 7) projeta o mês a partir do medido e
substitui as premissas acima.

---

## 6. Fases

Cada fase traz: objetivo, por quê, arquivos, passos, testes, critério de pronto e
rollback.

---

### Fase 0 — Medição (baseline)

**Objetivo.** Ter um número para cada tipo de pergunta antes de mexer em qualquer coisa,
e escolher modelo e fonte com dados em vez de opinião.

**Por quê.** Sem isso, nenhuma das fases seguintes pode ser dada como melhoria. O
benchmark de embeddings que já existe (`guides/memory.md`) mostrou o valor disso: trocou o
modelo padrão por um 3 vezes melhor.

**Arquivos.** `brainlib/memory_eval.py` (novo), `brainlib/cli.py` (subcomando),
`vault/eval/memory-gold.jsonl` (nova zona curada, conteúdo do dono, fora do git),
`template/eval/memory-gold.example.jsonl` (exemplo genérico, no git).

**Passos.**

1. **Conjunto de perguntas** (~60, em PT e ES), uma por linha:
   ```json
   {"id":"q01","q":"o que está atrasado com a Marina?","type":"estado","lang":"pt",
    "expect_ids":["TASK-0031","TASK-0040"],"expect_docs":[]}
   {"id":"q17","q":"qual foi o argumento contra terceirizar a triagem?","type":"detalhe","lang":"pt",
    "expect_ids":[],"expect_docs":["RAW/2026/10/meetings/....md"]}
   ```
   Tipos e proporção-alvo:

   | Tipo | Qtd | O que testa |
   |---|---|---|
   | `estado` | 12 | prazo, status, quem deve (deve ir ao ledger) |
   | `contexto` | 12 | "o que sabemos sobre X" |
   | `decisao` | 8 | "por que decidimos Y", quem decidiu |
   | `detalhe` | 12 | coisa dita de passagem que o `/dump` **não** registrou (o motivo de extrair do RAW) |
   | `literal` | 8 | a frase exata |
   | `conclusao` | 8 | "por que achamos que X importa?" (testa os mental models) |

   O agente **propõe** as perguntas a partir do vault; o dono revisa e aprova. As
   respostas esperadas são conferidas à mão.
2. **`brain memory eval`**:
   ```
   brain memory eval [--gold vault/eval/memory-gold.jsonl] [--bank <banco>] [--route on|off]
                     [--k 5] [--json] [--save vault/eval/runs/<data>-<rótulo>.json]
   ```
   - Para cada pergunta, roda a rota completa (ou só o recall, com `--route off`).
   - Métricas por tipo: **recall@5** (algum `expect_*` nos 5 primeiros), **MRR**,
     **citação correta** (o `document_id` ou o ID devolvido existe e está entre os
     esperados), **itens injetados** (quantos o hook mandaria) e **precisão da injeção**
     (fração dos injetados que está entre os esperados).
   - Tokens injetados por pergunta (contagem aproximada: caracteres ÷ 3,5).
   - Sem LLM no julgamento: as métricas são de recuperação, determinísticas e baratas de
     repetir.
3. **Baseline** com o estado atual (`brain-raw` + `brain-mem`, rota off), salvo como
   `runs/<data>-baseline.json`.
4. **Bancos de teste para escolher fonte e modelo** (rodam depois da Fase 3, com a chave).
   Amostra de duas semanas do RAW, bancos temporários `brain-eval-*`:

   | Variante | Fonte | Retain |
   |---|---|---|
   | a | só PROCESSED | Haiku high |
   | b | só RAW | Haiku high |
   | c | RAW + contexto do PROCESSED | Haiku high |
   | c+p | c + PROCESSED em chunks no mesmo banco | Haiku high |
   | c-m | c | Haiku medium |
   | c-s | c | Sonnet high |

   E para os mental models: os mesmos 15 temas com Haiku high e com Sonnet high, avaliados
   nas perguntas `conclusao` mais uma leitura humana das páginas (o dono dá nota de 1 a 5
   em fidelidade e utilidade).
   `POST /memories/dry-run-extract` mostra os fatos de um chunk sem gravar: útil para
   ajustar as instruções antes de gastar num banco inteiro.

**Testes.** `tests/test_memory_eval.py`: parser do arquivo, cálculo de recall@k e MRR com
um cliente Hindsight falso, rota on e off.

**Pronto quando.** Baseline salvo e conferido. A tabela de variantes vira uma decisão
registrada no fim desta seção ("Decisão da Fase 0: …").

**Hipóteses a confirmar** (critério de sucesso das fases seguintes):

| Tipo | Baseline esperado | Meta |
|---|---|---|
| `estado` | baixo (vai ao vetor) | ≥ 95% (vai ao ledger) |
| `detalhe` | médio | +20 pontos com a variante c |
| `literal` | alto | sem piora |
| `conclusao` | baixo | +30 pontos com mental models |
| itens injetados por mensagem | ~8 | ≤ 5, com precisão ≥ 60% |

**Rollback.** Nada a desfazer: só lê.

---

### Fase 1 — Ledger: projeção SQLite e consultas estruturadas

**Objetivo.** Consultas de estado rápidas e exatas, busca indexada e uma ferramenta
estruturada para o agente, sem tocar no `events.jsonl`.

**Por quê JSONL continua sendo a verdade.**
- Append-only por construção (`O_APPEND` + fsync, lote atômico em `core._flush`).
- Legível, `grep`-ável, `diff`-ável, backup trivial, zero dependências.
- Encaixa naturalmente em event sourcing: o estado é uma dobra dos eventos.
- Um SQLite como fonte também poderia ser append-only (triggers `BEFORE UPDATE/DELETE →
  RAISE`), mas custaria a legibilidade e uma migração arriscada para ganhar uma
  performance que ainda não falta.

**Por quê SQLite como projeção.** O que falta hoje não é armazenamento, é **índice**:
consultar sem refazer a dobra, buscar sem ler cada arquivo, juntar ação com pessoa e
projeto numa consulta. O SQLite é stdlib (`sqlite3`, versão local 3.53 com FTS5), é um
arquivo só e é reconstruível. É derivado, como o FRESH, por isso mora no FRESH.

**Arquivos.** `brainlib/index.py` (novo), `brainlib/core.py` (gancho pós-escrita),
`brainlib/search.py` (passa a usar FTS5), `brainlib/mcp_server.py`, `brainlib/cli.py`
(`index`, `query`), `brainlib/render.py` (garante índice fresco), `brainlib/doctor.py`,
`tests/test_index.py`.

**Passos.**

1.1 **Esquema** (`FRESH/_index/brain.sqlite`, `PRAGMA journal_mode=WAL`):

```sql
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
  -- schema_version, last_seq, ledger_size, ledger_sha_tail, built_at

CREATE TABLE events(
  seq INTEGER PRIMARY KEY, ts TEXT, type TEXT, id TEXT, date TEXT,
  actor TEXT, by TEXT, prov TEXT, source TEXT, data TEXT,  -- data = JSON
  class TEXT                                               -- fato | dono | sistema | telemetria
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
                                    -- GOAL-#, PROJ-#, PROJ-#.#, do goals.md

CREATE TABLE edges(src TEXT, rel TEXT, dst TEXT, PRIMARY KEY(src, rel, dst));
  -- rel: owner, person, project, deliverable, blocked_by, unblocks, decided_by,
  --      supersedes, artifact_person, artifact_project, opp_process, opp_area
CREATE INDEX edges_dst ON edges(dst, rel);

CREATE VIRTUAL TABLE fts USING fts5(
  kind, ref, title, body, date UNINDEXED, path UNINDEXED,
  tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TABLE fts_docs(path TEXT PRIMARY KEY, sha TEXT);  -- o que já está no fts
```

1.2 **Atualização.**
- `index.update(brain)`:
  - **eventos**: insere os de `seq > last_seq` (incremental). Se o arquivo encolheu ou o
    trecho final não bate com `ledger_sha_tail`, refaz tudo (alguém editou à mão; o
    `validate` acusa);
  - **tabelas de entidade**: rematerializa a partir do `State` já dobrado, numa transação
    (`DELETE` + `INSERT`). A dobra custa ms; materializar incrementalmente por evento seria
    complexidade sem ganho. Reavaliar só se `state.build` passar de 200 ms;
  - **FTS**: entidades sempre; artefatos do PROCESSED e texto do RAW (só os tipos da
    seção 3.2) por `sha` em `fts_docs`, ou seja, só os novos ou mudados.
  - `is_overdue` e `is_blocked` dependem de "hoje": são calculados na materialização e
    **conferidos na leitura** (`brain query` recalcula contra `date('now')`), para o índice
    de ontem não mentir hoje.
- **Gancho.** `Brain.record()` chama `index.update` depois do `_flush`, **fora do lock do
  ledger e sem nunca falhar a escrita**: erro no índice grava `meta.stale = 1` e um aviso;
  o leitor que achar `stale` ou `last_seq` atrasado cai na dobra em memória (comportamento
  de hoje). `render` e `nightly` também chamam.
- `brain index rebuild` apaga e refaz. `brain index status` mostra `last_seq`, tamanho e
  atraso.
- O noturno pode atualizar o índice: é derivado, não é evento do dono.

1.3 **Leitores.**
- `search.py`: consulta `fts` com `bm25(fts, 3.0, 1.0)` (título pesa 3×, como hoje),
  mantém a regra AND e depois OR e a marca `match: "parcial"`. Sem índice, cai no código
  atual.
- `mcp_server.py`: as ferramentas de leitura (`overview`, `actions`, `decisions`, `person`,
  `project`, `timeline`, `opportunities`) leem do SQLite com conexão somente-leitura
  (`file:…?mode=ro`, `PRAGMA query_only=1`). Ferramenta nova `query` (ver 1.4).
- TUI: as faces leem do índice quando fresco (opcional neste plano; registrar como
  melhoria se a latência da TUI incomodar).

1.4 **`brain query`**: consulta estruturada, saída compacta (economiza tokens do agente).
```
brain query actions [--open] [--overdue] [--due-within 7] [--person <id|alias>]
                    [--project PROJ-3] [--list mine|waiting|watching] [--blocked]
                    [--fields id,title,due,owner] [--format lines|json] [--limit 50]
brain query decisions [--project …] [--person …] [--since AAAA-MM-DD] [--active]
brain query person <id|alias>        # ficha + pendências nos dois sentidos + última interação
brain query entity <ID>              # qualquer TASK/DEC/WIN/PROJ/GOAL/OPP/PROC
brain query sql "SELECT …"           # somente leitura, para análise ad hoc do agente
```
- Formato `lines` padrão: uma linha por item, sem cabeçalho decorativo, por exemplo
  `TASK-0031 · Revisar contrato · prazo 2026-10-20 (9d atrasada) · marina-demo · PROJ-3`.
- `--person` resolve o alias pela tabela `aliases` (mesmo dobramento do `util.fold`).
- `sql` abre em `mode=ro`, recusa mais de uma instrução e limita a 500 linhas.
- As skills `/ask`, `/person`, `/project`, `/brief` passam a preferir `brain query` para
  estado (ajuste de uma linha em cada `SKILL.md`).

1.5 **Telemetria.** *Revisão do que foi dito na análise:* `connector.pulled` e
`connector.failed` **ficam no ledger**. O `State` usa o hash do último pull para o
"hash idêntico = silêncio" do snapshot, e o `doctor` usa as falhas seguidas. Tirar do
ledger mudaria a constituição para ganhar ~5 ms. No índice ganham `class = 'telemetria'`,
e as views e ferramentas de leitura filtram por classe.

1.6 **Integridade (opcional, baixa prioridade).** Campo `h` em cada evento novo:
`sha256(h_anterior + json_canônico_sem_h)`. O primeiro evento encadeado ancora no
`sha256` do arquivo até ali (evento `ledger.chained`). `brain validate` confere a cadeia e
acusa edição manual que hoje passaria despercebida. Só com "ok" do dono (muda o formato do
evento).

**Testes** (`tests/test_index.py`).
- Rebuild do zero = incremental após N escritas (mesmo conteúdo, tabela por tabela).
- Escrita com índice quebrado (arquivo sem permissão) não falha e marca `stale`.
- `is_overdue` recalculado na leitura em outro dia (data congelada).
- FTS: acento e caixa (`ação` acha `acao`), AND e depois OR, peso do título.
- `query sql` recusa `INSERT`, `ATTACH`, múltiplas instruções.
- MCP: mesmas respostas com e sem índice (paridade).

**Pronto quando.** Perguntas `estado` da Fase 0 ≥ 95% pela rota do ledger; `brain search`
com 10× o volume sintético atual em < 50 ms; MCP com paridade.

**Rollback.** Apagar `FRESH/_index/`. Todos os leitores caem no caminho atual.

---

### Fase 2 — Hindsight sem LLM (ganhos que não dependem da chave)

**Objetivo.** Melhorar o que já existe sem mandar nada para fora da máquina.

**Arquivos.** `brainlib/memory.py`, `services/compose.yaml`, `guides/memory.md`,
`tests/test_brain.py` (ou `tests/test_memory.py`, novo).

**Passos.**

2.1 **Data do mundo em todo documento do RAW.** Ordem de preferência:
1. a `date` do `artifact.added` cujo `raw` aponta para o arquivo (já existe no ledger);
2. carimbo no nome do arquivo (`…-2026-10-19T182906.md` → `2026-10-19T18:29:06`);
3. o `capturado:` do cabeçalho do snapshot;
4. o primeiro dia de `RAW/<ano>/<mês>/`.

Vai em `timestamp` do retain. Isso conserta os links temporais e permite filtro por
período ("o que se falou em setembro").

2.2 **Fora do banco o que é ruído.** `connectors/` e `github/` deixam de ser enviados (a
lista fica em `[memory].exclude_types`, padrão `["connectors", "github"]`). Na próxima
sincronização, os documentos que saíram são apagados do banco
(`DELETE /documents/{id}`), com registro no estado.

2.3 **BM25 em português.** A 0.10.3 tem idioma do BM25 configurável por banco (migração
`configurable_bm25_language`). Configurar `portuguese` no `setup`. Hoje o BM25 roda com
o stemmer padrão.

2.4 **Reranker, com gate de latência.** O teste anterior (seção 1.2) mostrou o ganho de
qualidade e reprovou a latência na CPU do container. Duas saídas, nesta ordem:
- `jina-mlx`: provider de reranker presente na 0.10.3, rodando no host com MLX (Apple
  Silicon). Não testado aqui. Repetir o benchmark do compose; aprovar só se p95 < 400 ms
  com 30 candidatos.
- Reranker de nuvem (`cohere`, `zeroentropy`): só depois do gate de política da seção 4,
  porque manda a pergunta e os candidatos para fora.
Se nenhum passar, fica `rrf`, e o roteador da Fase 6 compensa com corte mais alto.

2.5 **`retain_chunk_size` para transcrição.** Testar 2.000 contra 3.000 caracteres nas
perguntas `literal` e `detalhe` da Fase 0. Trechos menores dão citação mais precisa;
maiores dão mais contexto por fato.

**Testes.** Data inferida nos quatro casos; exclusão por tipo; documento excluído é
apagado do banco no sync (cliente falso).

**Pronto quando.** `literal` e `detalhe` iguais ou melhores que o baseline; links temporais
com datas do mundo (`/stats` mais uma consulta por período que funcione).

**Rollback.** Reverter o commit e `brain memory rebuild`.

---

### Fase 3 — Compatibilidade com a Anthropic (antes de gastar num rebuild)

**Objetivo.** Provar que cada operação funciona com o modelo escolhido, numa amostra,
antes de reconstruir o banco.

**Achados no código do provider `anthropic` da 0.10.3** (lido no container):

| Ponto | Situação | Efeito |
|---|---|---|
| `temperature` | não é enviado | ok |
| `thinking` | não é enviado; vale o padrão adaptativo | ok |
| esforço | `reasoning_effort` é ignorado | usar `*_LLM_EXTRA_BODY` |
| saída estruturada | `strict_schema` é falso por padrão: o esquema vai no prompt, sem forçar ferramenta | ok para Haiku e Sonnet |
| prompt de sistema | marcado com `cache_control` | desconto se passar do mínimo cacheável |
| Batch API | suportado (`supports_batch_api`) | rebuild com −50% |
| **reflect / mental models** | o agente de reflect força `tool_choice` (`LLMToolChoice.named("done")`, `reflect/agent.py:965`) | **o Sonnet 5.5 recusa `tool_choice` forçado com erro 400** |

**O último ponto é bloqueante para o cenário B.** Caminhos, nesta ordem:
1. Verificar se uma versão mais nova do Hindsight já trata a recusa (mapeando `named` e
   `required` para `auto` com instrução no prompt). Se sim, subir a imagem no compose.
2. Se não, abrir issue ou PR no Hindsight com essa tradução no `anthropic_llm.py`. É
   pequena e serve a qualquer usuário de modelo 5.5.
3. Enquanto isso, mental models com **Haiku 5.5 e `thinking` desligado** (aceito em
   esforço até high): `…_MENTAL_MODEL_REFRESH_LLM_EXTRA_BODY={"thinking":{"type":"disabled"},"output_config":{"effort":"high"}}`.
   Isso é o cenário A nos mental models (custo cai ~US$ 13 por mês) até o Sonnet ficar
   viável. Confirmar no teste que o Haiku aceita o `tool_choice` forçado nessas condições.

**Arquivos.** `services/compose.yaml`, `config/.env` (só a chave, pelo dono),
`config/brain.toml.example` (`[memory]` novo, ver Fase 4), `guides/memory.md`.

**Passos.**
1. `compose.yaml`: `env_file: ../config/.env` só para o serviço `hindsight`; variáveis da
   seção 5.1; `HINDSIGHT_API_SKIP_LLM_VERIFICATION` sai; `HINDSIGHT_API_LLM_OUTPUT_LANGUAGE`
   sai também (ver Fase 4.3: o idioma acompanha o documento).
2. `GET /banks/brain-mem/health/llm` em cada operação.
3. `POST /memories/dry-run-extract` com 5 chunks reais (reunião, Slack, documento, nota,
   PDF): conferir os fatos (nomes, datas, números, idioma) e o uso de tokens.
4. Banco `brain-compat` com 20 documentos: retain, consolidação e um mental model com
   `dry-run-refresh`. Registrar no log os erros e as respostas.
5. `GET /llm-requests/stats`: tokens reais por chamada. Ajustar a seção 5.2.

**Pronto quando.** As três operações passam no banco de teste com o modelo definitivo (ou
com o substituto do item 3), e o custo por chunk medido fica a até 2× da premissa.

**Rollback.** Voltar o compose anterior. Os bancos atuais não foram tocados.

---

### Fase 4 — Banco único com extração da fonte

**Objetivo.** Trocar os dois bancos de chunks por um banco de fatos extraídos do RAW,
com entidades do ledger, datas do mundo e trechos originais para citação.

**Por quê.**
- **Fonte em vez de resumo:** o que o `/dump` não registrou continua recuperável.
- **Identidade resolvida:** os fatos nascem com a pessoa certa, e o grafo de entidades
  passa a funcionar.
- **Um banco:** acaba a disputa entre resumo e fonte pelo mesmo espaço no recall.

**Arquivos.** `brainlib/memory.py` (reescrita de `documents()`, `setup()`, `sync()`),
`brainlib/config.py` (padrões de `[memory]`), `config/brain.toml.example`,
`services/hooks/recall_context.py` (banco único), `services/idle_unload.py` (lista de
bancos), `tests/test_memory.py`.

**Passos.**

4.1 **Configuração** (`config/brain.toml`):
```toml
[memory]
engine = "hindsight"
url = "http://localhost:8888"
bank = "brain-mem"                 # banco único; raw_bank sai
max_file_mb = 25
extract = true                      # false = comportamento antigo (chunks)
cloud_llm = true                    # gate da seção 4; false recusa extract
exclude_types = ["connectors", "github"]
entity_types = { pessoa = "PERSON", projeto = "PROJECT", area = "ORG" }
mental_models = true
mm_min_interval_h = 24
monthly_budget_usd = 40             # aviso no doctor
```
`raw_bank` e `mem_bank` continuam aceitos na leitura por uma versão (o `doctor` avisa).

4.2 **Banco** (`setup`):
- `retain_extraction_mode = "custom"` com `retain_custom_instructions` (4.3);
- `enable_observations = true`, `enable_auto_consolidation = true`;
- `entity_labels`: pessoas e projetos do ledger;
- `observations_mission`, `reflect_mission`: em pt-BR, como as atuais;
- BM25 `portuguese` (Fase 2.3);
- `retain_batch_enabled`: ligado só no `rebuild` e no noturno (o `sync` diurno manda
  síncrono).

4.3 **Instruções de extração** (`retain_custom_instructions`, versão inicial, ajustada com
`dry-run-extract`):
- Fatos duráveis: decisões e quem decidiu, compromissos com dono e prazo, entregas e
  números, objeções e argumentos (quem defendeu o quê), mudanças de plano, preferências e
  papéis observados.
- Ignorar logística de reunião, cumprimentos, ruído de transcrição ("pera aí", "tá me
  ouvindo?").
- **Usar os IDs e nomes do bloco de contexto** para pessoas e projetos; nunca inventar nome
  que não está no texto nem no contexto; na dúvida, manter o nome como aparece.
- Preservar datas, números e citações exatamente; escrever cada fato **no idioma do
  documento** (pt-BR, es, en), sem traduzir.
- Quando a fonte é transcrição, atribuir a fala a quem falou, se o falante estiver
  identificado.

4.4 **Contexto por documento** (campo `context` do item de retain, ~700 tokens no máximo):
```
Documento: RAW/2026/10/meetings/<arquivo>.md · reunião · 2026-10-22
Artefato: PROCESSED/2026/10/<artefato>.md — "<título>"
Pessoas (id · nome · aliases): marina-demo · Marina Demo · Mari, Marina D.
Projetos: PROJ-3 — <título>
IDs ligados: TASK-0031, DEC-0012
```
Sai do ledger: `artifact.added` com `raw` = este arquivo dá o artefato, as pessoas e os
projetos; as ações e decisões com `source` no artefato dão os IDs. RAW sem artefato
(ainda não processado pelo `/dump`) **não é enviado**: espera o `/dump`. Assim, nenhum
fato nasce sem identidade resolvida.

4.5 **Entidades explícitas** (campo `entities` do item, `resolve_entities = true`): uma por
pessoa e projeto do contexto, com o nome canônico e o tipo de `entity_types`. Os aliases
viram `bank aliases` (`/aliases`), sincronizados a partir do ledger no `setup` e a cada
`person.added` ou `person.updated`.

4.6 **Tags** de cada documento: `tipo:<reuniao|slack|documento|nota>`, `pessoa:<id>`,
`proj:<PROJ-#>`, `goal:<GOAL-#>` (pelo projeto), `area:<slug>`, `artefato:<caminho>`. As
tags permitem recall filtrado ("só PROJ-3") e mental models com escopo.

4.7 **Documentos do ledger**: decisões e entregas viram documentos curtos
(`ledger/DEC-####`, `ledger/WIN-####`), como hoje, com tags e entidades. Ações e fichas de
pessoa **deixam** de ser enviadas. `_entity_docs()` encolhe para esses dois tipos.

4.8 **`document_id` e citação**: continua sendo o caminho no vault. Os chunks de origem de
cada documento ficam em `/documents/{id}/chunks`, ligados aos fatos. O recall devolve o
fato e, com `include.chunks`, o trecho original para a citação.

4.9 **Rebuild**:
1. `brain memory rebuild --dry-run`: lista o que vai, o que sai e a estimativa de custo
   (chunks × custo medido na Fase 3).
2. Com "ok" do dono: cria `brain-mem-v2` (não apaga nada), envia pelo Batch API, espera a
   consolidação terminar (`brain memory status` mostra a fila).
3. Roda a Fase 0 contra `brain-mem-v2`.
4. Se bater as metas, troca `[memory].bank` para `brain-mem-v2` e, depois de uma semana
   sem regressão, apaga `brain-raw` e o `brain-mem` antigo (com "ok"; `DELETE` de banco é
   irreversível).

4.10 **Sync incremental**: um documento muda só quando muda o RAW (imutável, então
raramente) ou o contexto (pessoa nova, alias novo, artefato reprocessado). O `sha` do item
passa a ser `sha(texto + contexto)`. Mudança de contexto reenvia o documento
(`/documents/{id}/reprocess` quando o texto é o mesmo).

**Testes.** `documents()` com vault de exemplo: exclusões, contexto montado, entidades,
tags, RAW sem artefato fica de fora, documento do ledger só para DEC e WIN; mudança de
alias muda o `sha`; `cloud_llm = false` com `extract = true` é recusado com mensagem
explícita.

**Pronto quando.** Metas da Fase 0 para `contexto`, `decisao`, `detalhe` e `literal`
batidas no `brain-mem-v2`; nenhum fato com pessoa fora do ledger em amostra de 50.

**Rollback.** `[memory].bank` volta para o banco antigo (que não foi apagado até a semana
de observação terminar).

---

### Fase 5 — Mental models

**Objetivo.** Uma página viva por tema importante, que responde "onde estamos com X" e
"por que achamos que Y importa" sem depender de um texto congelado do dia do `/dump`.

**Por quê.** As conclusões do agente (relevância para um goal, riscos, leitura de uma
pessoa) hoje ficam espalhadas nos artefatos do PROCESSED e envelhecem. Um mental model é
regenerado a partir dos fatos atuais e do estado do ledger, com histórico de versões no
próprio Hindsight (`/mental-models/{id}/history`).

**Arquivos.** `brainlib/memory_models.py` (novo), `brainlib/cli.py`
(`brain memory models`), `brainlib/runner.py` (noturno), `brainlib/render_md.py` (view
opcional), `tests/test_memory_models.py`.

**Passos.**

5.1 **Catálogo**, gerado do PLANNING e do ledger (não à mão):

| Tipo | Quais | `id` | Tags de escopo |
|---|---|---|---|
| Goal | todo GOAL com `status: ativo` | `mm-goal-1` | `goal:GOAL-1` |
| Projeto | todo PROJ ativo | `mm-proj-3` | `proj:PROJ-3` |
| Pessoa | as ~6 pessoas com mais vínculos nos últimos 60 dias (`edges` do SQLite) | `mm-pessoa-<id>` | `pessoa:<id>` |

Na instância de referência isso dá ~15.

5.2 **Consulta de origem** (`source_query`), por tipo, em pt-BR:
- Projeto: "Estado atual, decisões recentes e o porquê, riscos, dependências, quem está
  envolvido e o que ficou em aberto no projeto {título} ({id})." Mais um anexo
  determinístico com o estado do ledger (entregáveis, ações abertas, atrasos), vindo do
  `brain query`, colado no início da página como seção "Estado (do ledger)". O LLM não
  recalcula esse estado.
- Goal: idem, agregando os projetos.
- Pessoa: "Papel, como trabalha, preferências, compromissos nos dois sentidos, temas
  recorrentes e histórico recente com {nome}."

5.3 **Gatilho**: `mode: "delta"`, `budget: "mid"`, `refresh_after_consolidation: false`.
O brain decide quando atualizar: no noturno, para cada modelo cujas tags receberam fato
novo desde a última atualização, respeitando `mm_min_interval_h`. O Hindsight não
atualiza a cada consolidação (isso multiplicaria o custo).

5.4 **CLI**:
```
brain memory models sync      # cria/atualiza o catálogo (sem LLM: só metadados)
brain memory models refresh [--id …] [--dry-run]
brain memory models list      # id, tema, atualizado em, versão, tokens da última atualização
brain memory models show <id>
```
O catálogo muda quando o PLANNING muda: projeto fechado → modelo arquivado (não apagado).

5.5 **Onde aparecem**: no recall (o Hindsight já os prioriza), no `/project` e no
`/person` (seção "Leitura atual", com a data da versão e a marca `[memória]`), e
opcionalmente em `FRESH/notes/mm-<id>.md` pelo `render`, como narrativa exibida "como
está" (o FRESH não guarda informação única: a página é derivada e se refaz).

5.6 **Proveniência.** Toda afirmação de mental model é tratada como `[memória]`: pista, não
fato. O `/ask` continua obrigado a confirmar no artefato ou no RAW antes de afirmar.

**Testes.** Catálogo a partir de PLANNING e ledger de exemplo; arquivamento de projeto
fechado; regra do intervalo mínimo; só atualiza com fato novo nas tags.

**Pronto quando.** Perguntas `conclusao` da Fase 0 com +30 pontos; nota média do dono
≥ 4 em fidelidade nas páginas de amostra; custo dos mental models no mês dentro de ±30%
dos US$ 13,50.

**Rollback.** `[memory].mental_models = false`. As páginas ficam no Hindsight sem uso.

---

### Fase 6 — Roteador e hook

**Objetivo.** Cada mensagem recebe só o contexto da camada certa, em até 5 itens, e
nenhum quando nada é pertinente.

**Arquivos.** `services/hooks/recall_context.py`, `brainlib/route.py` (novo, a mesma
lógica para o `/ask` e o eval), `commands/ask/SKILL.md`, `tests/test_route.py`.

**Restrições do hook.** Roda no `python3` do sistema (3.9), só stdlib, timeout total de
2 s, nunca bloqueia a mensagem. Lê o SQLite direto, em `mode=ro`, sem subprocess do
`./brain` (economiza ~80 ms de partida).

**Passos.**

6.1 **Classificação sem LLM** (regras da seção 3.3):
- regex de IDs (`TASK-\d+`, `DEC-\d+`, `WIN-\d+`, `OPP-\d+`, `PROC-\d+`, `PROJ-\d+(\.\d+)?`,
  `GOAL-\d+`) e dos prefixos antigos aceitos;
- pessoas: casar palavras dobradas da mensagem com `aliases.alias_fold`;
- vocabulário de estado e tempo (lista em `route.py`, pt e es);
- vocabulário literal ("exatamente", "palavras", "textualmente", aspas).

6.2 **Saída por rota** (cada linha cita a fonte):
- ledger: até 3 linhas no formato `lines` do `brain query`, com a marca `⟶ ledger/<ID>`;
- mental model: 1 item, as primeiras ~400 caracteres da página mais o `id` e a data da
  versão;
- fatos: até 3, com `⟶ <document_id>, <data>`;
- literal: 1 a 2 trechos de chunk, até 400 caracteres.
Teto: 5 itens no total.

6.3 **Corte.** Sem reranker, corte semântico sobe para 0,62 nos fatos (calibrar na Fase 0
pela precisão da injeção). Com reranker aprovado na Fase 2.4, corte pelo score do
reranker.

6.4 **Texto de abertura** igual ao de hoje ("são pistas, não verdade…"), mais curto.

6.5 **`/ask`**: a skill passa a chamar `brain route "<pergunta>" --json` (mesma lógica, sem
o limite de 2 s) e segue o caminho índice → artefato → RAW, citando a fonte.

**Testes.** Tabela de mensagens → rota esperada (pt e es); orçamento de 5 itens; nada
injetado quando nada passa do corte; hook com SQLite ausente (cai só no Hindsight) e com
Hindsight fora (cai só no ledger).

**Pronto quando.** Precisão da injeção ≥ 60% e ≤ 5 itens por mensagem na Fase 0; p95 do
hook < 1 s.

**Rollback.** `BRAIN_RECALL_ROUTE=off` volta ao comportamento atual (adaptado ao banco
único).

---

### Fase 7 — Operação, documentação e constituição

**Arquivos.** `brainlib/memory.py` (`status`, `cost`), `brainlib/doctor.py`,
`services/idle_unload.py`, `guides/memory.md`, `AGENTS.md`, `guides/user-guide.md`,
`template/` (exemplos).

**Passos.**
1. **`brain memory cost [--days 7]`**: lê `/llm-requests/stats`, agrupa por operação e
   modelo, aplica os preços da tabela em `[memory.prices]` (para não chumbar preço no
   código) e projeta o mês. O `doctor` avisa acima de `monthly_budget_usd`.
2. **`brain memory status`**: banco único, fila (retain, consolidação, mental models),
   documentos do RAW aguardando `/dump` (sem artefato, portanto sem contexto), mental
   models desatualizados.
3. **`idle_unload.py`**: o LLM local deixa de ser usado pelo Hindsight; o tempo de
   ociosidade do LLM no LM Studio pode cair para o mínimo. O embedding continua.
4. **Noturno** (`runner.py`): `memory sync` (Batch) → `memory models refresh` →
   `index update`. O noturno pode tudo isso: nenhum desses passos é evento do dono nem
   porta para o mundo (a saída para a API foi aprovada uma vez, no gate da seção 4, como
   a porta 6).
5. **`guides/memory.md`** reescrito: um banco, extração com contexto, mental models,
   custos, como medir, como voltar ao modo só embeddings (`extract = false` +
   `rebuild`).
6. **AGENTS.md** (diff proposto, aplicado com "ok"):
   - seção "Memória para IA (Hindsight)": um banco (`brain-mem`), fatos extraídos do RAW
     com identidades do ledger, mental models, recall continua pista;
   - tabela de zonas: `FRESH/_index/` (derivado, `brain index`), `vault/eval/` (curado,
     o agente propõe perguntas, o dono aprova);
   - Segurança: a exceção da seção 4.1;
   - "Responder perguntas (`/ask`)": rota por tipo, `brain query` para estado.
7. **`./brain upstream scan`** e proposta de commit ao dono (porta 5), generalizando
   exemplos.

---

## 7. O que muda, arquivo por arquivo

| Arquivo | Mudança | Fase |
|---|---|---|
| `brainlib/index.py` | novo: projeção SQLite, FTS5, atualização incremental | 1 |
| `brainlib/core.py` | gancho pós-`_flush` chama `index.update` (best-effort) | 1 |
| `brainlib/search.py` | FTS5 com `bm25`; caminho antigo como fallback | 1 |
| `brainlib/mcp_server.py` | leitura pelo índice; ferramenta `query` | 1 |
| `brainlib/cli.py` | `index`, `query`, `route`, `memory eval/cost/models` | 0, 1, 5, 6, 7 |
| `brainlib/render.py`, `runner.py` | índice e mental models no render e no noturno | 1, 5, 7 |
| `brainlib/doctor.py` | índice atrasado, custo acima do teto, mental models velhos | 1, 7 |
| `brainlib/memory.py` | banco único, extração, contexto, entidades, tags, datas, exclusões, batch | 2, 4, 7 |
| `brainlib/memory_eval.py` | novo: avaliação | 0 |
| `brainlib/memory_models.py` | novo: catálogo e atualização de mental models | 5 |
| `brainlib/route.py` | novo: classificação e montagem do contexto | 6 |
| `brainlib/config.py`, `config/brain.toml.example` | `[memory]` novo, `[memory.prices]` | 4, 7 |
| `services/compose.yaml` | `env_file`, LLM por operação, BM25, reranker (se aprovado) | 2, 3 |
| `services/hooks/recall_context.py` | roteador, banco único, SQLite direto | 6 |
| `services/idle_unload.py` | banco único; LLM local sem uso pelo Hindsight | 4, 7 |
| `commands/ask`, `person`, `project`, `brief` (`SKILL.md`) | `brain query` para estado; mental model como "leitura atual" | 1, 5, 6 |
| `guides/memory.md`, `AGENTS.md`, `guides/user-guide.md` | documentação e constituição | 7 |
| `template/eval/memory-gold.example.jsonl` | exemplo genérico | 0 |
| `tests/test_index.py`, `test_memory.py`, `test_memory_eval.py`, `test_memory_models.py`, `test_route.py` | novos | todas |

### O que **não** muda

- `events.jsonl`: formato, regras de escrita, IDs, gates, noturno (exceto o campo `h`
  opcional da Fase 1.6).
- O pipeline do `/dump` e o PROCESSED: continuam iguais e continuam sendo a fonte da
  leitura humana, da citação, do `/share` e do FRESH.
- "Não consta" continua sendo resposta válida; a memória continua sendo pista.
- Embeddings locais (`bge-m3`), recall sem LLM, MCP somente-leitura.
- As portas para o mundo exterior: nenhuma nova.

---

## 8. Ganhos esperados

| Ganho | Como aparece | Como se mede |
|---|---|---|
| Respostas de estado exatas | "o que está atrasado com X" vem do ledger, não do vetor | `estado` ≥ 95% (Fase 0) |
| Detalhes que o `/dump` não guardou | fatos extraídos da fonte | `detalhe` +20 pontos |
| Conclusões atualizadas | mental models por GOAL, PROJ e pessoa | `conclusao` +30 pontos; nota do dono |
| Menos tokens por mensagem | hook com até 5 itens pertinentes | itens e tokens injetados por mensagem |
| Menos ruído | sem duplicatas resumo × fonte; sem transcrição solta | precisão da injeção ≥ 60% |
| Identidade consistente | entidades e aliases do ledger no banco | amostra de 50 fatos sem pessoa fora do ledger |
| Busca que escala | FTS5 indexado | `brain search` < 50 ms com 10× o volume |
| CLI, MCP e TUI que escalam | leitura do índice em vez de refold | latência das ferramentas do MCP |
| Recuperação temporal real | datas do mundo no RAW | consulta por período |
| Custo previsível | medição por operação, teto no doctor | `brain memory cost` |

---

## 9. Riscos e mitigação

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Sonnet 5.5 recusa o `tool_choice` forçado do reflect | confirmada no código | Fase 3: versão nova, patch upstream ou Haiku sem thinking |
| Política da empresa não permite mandar o vault à API | média | Fases 0 a 2 entregam valor sem nuvem; `cloud_llm = false` |
| Extração inventa ou troca nomes | média em transcrição | contexto com IDs, entidades explícitas, instrução "não inventar", amostra de 50 na Fase 4 |
| Custo acima do previsto (volume, instruções longas) | média | medição na Fase 3, teto no doctor, Batch no rebuild, intervalo e `delta` nos mental models |
| RAW sem artefato fica fora da memória | certa, por desenho | `memory status` mostra quantos esperam `/dump`; o `/dump` é diário |
| Índice SQLite velho mente sobre atraso | baixa | atraso recalculado na leitura; `stale` cai na dobra |
| Hindsight fora do ar | média | hook cai só no ledger; `/ask` usa índice → artefato → RAW |
| Rebuild apaga a memória boa | baixa | banco `v2` paralelo, troca por configuração, apagar só após uma semana e com "ok" |
| Mental model vira "verdade" na cabeça do agente | média | marca `[memória]`, obrigação de confirmar no vault, estado do ledger colado deterministicamente |

---

## 10. Ordem dos commits

1. `eval: conjunto de perguntas e brain memory eval (baseline)` — Fase 0, passos 1–3
2. `index: projeção SQLite do ledger (eventos, entidades, edges)` — 1.1, 1.2
3. `index: FTS5 e search pelo índice` — 1.2 (FTS), 1.3 (search)
4. `mcp: leitura pelo índice e ferramenta query` — 1.3
5. `query: brain query (actions, decisions, person, entity, sql)` — 1.4 + ajustes de skills
6. `memoria: datas do mundo no RAW e exclusão por tipo` — 2.1, 2.2
7. `memoria: BM25 em português e tamanho de chunk` — 2.3, 2.5 (2.4 só se aprovado)
8. `memoria: LLM por operação no compose (Anthropic), gate cloud_llm` — Fase 3
9. `memoria: banco único com extração da fonte, contexto e entidades do ledger` — Fase 4
10. `memoria: mental models por goal, projeto e pessoa` — Fase 5
11. `hook: roteador ledger/fatos/literal, até 5 itens` — Fase 6
12. `memoria: custo, status, noturno e documentação` — Fase 7 (o diff da AGENTS.md vai
    separado, para aprovação)

Os commits 1 a 7 não dependem da chave nem do gate de política. Do 8 em diante, só depois
da seção 4 resolvida.

---

## Decisão da Fase 0

*(preencher depois de rodar as variantes: fonte escolhida, modelo do retain, modelo dos
mental models, corte do hook)*
