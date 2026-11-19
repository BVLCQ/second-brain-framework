# Memória para IA — Hindsight

O vault é a verdade. Hindsight é um índice que outra IA (e o `/ask`) usam
para achar mais rápido. Se o servidor cair, nada se perde.

## Dois setups (escolha livre, reversível)

| | `embed` | `full` |
|---|---|---|
| Banco | **1** (`bank`, default `brain`), chunks | **1** (`bank`, default `brain`) com extração de fatos |
| LLM em operação | nenhum | extração + consolidação (modelo barato); mental models (Fase 8, ainda não aterrissado) |
| Sai da máquina? | **não** | sim — texto do vault à API de LLM **com a chave do dono** (`config/.env`) |
| Chaves no `.env` | nenhuma | 1 por conta de nuvem (LLM sempre; embeddings e reranker quando de nuvem — a OpenAI nos dois papéis usa a mesma) |
| Custo de API | US$ 0 | medido por `brain memory cost` (medidor mensal, sem teto — decisão do dono) |
| RAW sem `/dump` | entra como está | **hold**: fica retido até o artefato existir (`raw_awaiting_dump = "hold"`) |

Config (`config/brain.toml` `[memory]`) — o modo é derivado: `engine = "none"` → `none`;
`engine = "hindsight"` + `extract = false` → `embed`; `extract = true` (exige `cloud_llm = true`)
→ `full`. O atalho `brain memory setup --mode none|embed|full` grava as chaves do modo e
cria o banco na sequência. O CLI **recusa** `extract` sem `cloud_llm`, e o modo `full`
sem chave `HINDSIGHT_API_*_API_KEY` no `.env`.

### O que muda no `full`

- **Embeddings e reranker de provedor de nuvem** (só-nuvem): o boot não depende do LM Studio.
- Todo documento viaja com um bloco **CONTEXTO** (caminho, data do mundo, pessoas com id e
  grafias, projetos) derivado do ledger — a extração usa só esses nomes/IDs, nunca inventa.
- **Data do mundo** em todo RAW (ordem: artefato do `/dump` → carimbo no nome → cabeçalho
  `capturado:`/`criada:` → mês da pasta `RAW/<ano>/<mês>/`).
- Entidades anexadas por casamento de alias no texto (metadado `entities`).
- `connectors/` e `github/` do RAW **nunca** vão ao banco (`exclude_types`) — nos dois modos.
- Deleção sombra: documento que sai do corpus (tipo excluído, arquivo removido) sai do banco.
- Observações e consolidação ligadas: a fila do `memory status` volta a ter vida.

### O banco único do `embed` (decisão 8)

Desde a decisão 8 do dono (2026-11-05), os dois bancos antigos viraram **um**: `bank`
(default `brain`). O corpus (§3.2 do plano, Fase 3): **RAW** como está (texto e binários
até `max_file_mb`) + **docs curtos `ledger/DEC` e `ledger/WIN`** (narrativa curada para
perguntas de contexto) — tudo em `chunks` com **tags do ledger** (`pessoa:` `proj:`
`goal:` `sem-artefato:1`), **data do mundo** e **entidades por alias** (top-level,
grafo do servidor). FICA FORA do vetor: PROCESSED (o FTS5 do índice cobre busca por
palavra), páginas de ação/pessoa (o SQLite responde estado) e PLANNING/PROFILE.
RAW **sem** `/dump`: espera `degraded_after_days` (7) e entra **degradado** (tag
`sem-artefato:1`, sem entidades); quando o `/dump` processa, a identidade muda, o sha
muda e o documento reenvia com identidade plena. `document_id` = caminho
no vault (ou `ledger/TASK-####`): toda lembrança aponta para algo que você pode abrir.

## Subir o servidor (OrbStack)

```bash
# embed (sem LLM): só o bge-m3 do LM Studio precisa estar disponível
docker compose -f services/compose.yaml up -d

# full (LLM do dono): as chaves moram no config/.env — o compose lê pelo --env-file
docker compose --env-file config/.env \
  -f services/compose.yaml -f services/compose.full.yaml up -d
```

A imagem é pinada **por digest** (emenda R5: tag pode ser reempurrada). O container alcança o
LM Studio do Mac por `host.docker.internal:1234`.

**Ordem de boot na 1.2.0:** o servidor valida o endpoint de embeddings na inicialização —
**suba o LM Studio (com o modelo carregado) antes do `up -d`**, senão o container morre na hora
(o 0.10.x não fazia essa checagem). O modelo de LLM pode continuar descarregado no modo embed.
No wizard e no `brain setup --only memoria` essa ordem é automática: o passo de memória instala
(se faltar), sobe o servidor :1234 e baixa/carrega o `bge-m3` antes do compose — a regra acima
só pesa para quem sobe o container na mão.

**Máquina com outro Hindsight no :8888** (decisão 10): não suba dois containers com o mesmo
nome/porta — **adopte** o servidor existente (`[memory].url` aponta pra ele; o banco do cérebro
nasce lá) ou sobreponha as portas: `HINDSIGHT_API_PORT=8891 HINDSIGHT_UI_PORT=9991 docker compose … up -d`.

### Atualizar o Hindsight de versão

Migrações de schema (Alembic) rodam no boot e são **forward-only** — apontou código antigo pra um
banco já migrado, só restaurando backup. Por isso:

1. `hindsight-admin export-bank <banco>` por banco (seguro até sem export no `embed` — bancos são
   derivados do vault e `brain memory rebuild` reconstrói; no `full` o export evita re-pagar extração);
2. troque o digest no `services/compose.yaml` (resolva o digest da tag: `docker buildx imagetools
   inspect ghcr.io/vectorize-io/hindsight:<tag>-slim`);
3. `up -d` — o boot migra sozinho;
4. **re-audit R5**: a 1.x valida config com erro alto (chave morta para de ser silêncio) e o
   `metadata` de retain só aceita **strings** (o brain serializa `entities` como JSON) — confira
   o smoke do release no CHANGELOG antes de subir em produção.

O `brain doctor` avisa quando o servidor está em versão antiga (comparação com `releases/latest`,
cache ≤1×/dia — informação, nunca bloqueio).

### Alternativa sem Docker: daemon local

```bash
uv tool install hindsight-embed          # daemon + PostgreSQL embutido (pg0)
export HINDSIGHT_API_EMBEDDINGS_PROVIDER=openai
export HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL=http://localhost:1234/v1
export HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL=text-embedding-bge-m3
export HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY=lm-studio   # placeholder; o LM Studio ignora
export HINDSIGHT_API_RERANKER_PROVIDER=rrf
export HINDSIGHT_API_SKIP_LLM_VERIFICATION=true            # modo embed
hindsight-embed configure && hindsight-embed daemon status
curl localhost:8888/health
```

Se o servidor exigir token: `HINDSIGHT_API_TOKEN` no `config/.env`.

## Embeddings: o que carregar na memória

Sem LLM no caminho, o único modelo que importa é o de embeddings. O padrão do Hindsight
(`bge-small-en-v1.5`) é só de inglês — fraco em pt-BR e es. Benchmark (24 perguntas parafraseadas,
14 pt + 10 es, CPU de 4 núcleos, sem outra carga):

| Modelo | Top-1 | MRR | RAM do modelo | Latência/trecho |
|---|---|---|---|---|
| `bge-small-en` (padrão) | 7/24 | 0,42 | ~450 MB | 30 ms |
| `multilingual-e5-small` (`onnx`, no Hindsight) | 19/24 | 0,85 | ~1,75 GB | 55 ms |
| `bge-m3` local (`local`, CPU do container) | 20/24 | 0,91 | ~4,4 GB | 400 ms |
| `bge-m3` no LM Studio (GGUF) | 20/24 | 0,90 | ~635 MB | ~76 ms |

Recomendado: **`bge-m3` servido pelo LM Studio** (melhor qualidade com o menor RAM; 1024 dims).
Sem o LM Studio, `multilingual-e5-small` via `HINDSIGHT_API_EMBEDDINGS_PROVIDER=onnx` perde pouco,
mas tem 384 dims (exige recriar os bancos) e limite de 512 tokens (o chunk padrão de 3000 caracteres
passa disso — reduza o tamanho de chunk na configuração do servidor Hindsight). Não carregue um LLM no LM Studio só para o Hindsight.

## Ligar nesta instância

```bash
brain memory setup --mode embed     # ou full (exige chave no .env) — grava [memory] e cria o banco
brain memory sync                   # incremental; --limit 50 --dry-run disponível
brain memory status                 # modo, pendências, fila, RAW retidos (full)
brain memory recall "quem decidiu o ponto novo?"
brain memory cost                   # medidor mensal (embed: US$ 0; full: tokens + US$ por operação)
```

Modo `full` antes do primeiro `sync` grande: valide sem gastar —

```bash
curl -s -X POST localhost:8888/v1/default/banks/brain/health/llm   # por operação
curl -s -X POST localhost:8888/v1/default/banks/brain/memories/dry-run-extract \
  -H 'Content-Type: application/json' -d '{"content":"ata de exemplo","context":"CONTEXTO"}'
```

O retain do Hindsight é assíncrono: o `sync` guarda o `operation_id` de cada documento em
`config/.memory-state.json` (`_ops`) e, no sync seguinte, consulta o servidor — documento cujo retain
falhou sai do estado e é reenviado (até 3 vezes; depois `doctor` avisa). `brain memory status` /
`brain doctor --online` também avisam de retains falhos e de operações em `processing` há mais de 2h,
e mostram a **fila** de cada banco (`fila: vazia — LLM livre` = não pese a máquina agora).
`--json` traz os números em `queue`.

O noturno chama `sync` sozinho. Após um `/dump` pesado, rode `brain memory sync` no mesmo dia.
`rebuild` apaga os bancos do modo atual (e os dos outros modos, se existirem) e reconstrói —
use quando trocar de modo, mudar o mission ou suspeitar de lixo.

## Trocar de modo (primeira classe nos dois sentidos)

- **`none` → `embed`/`full`**: `brain memory setup --mode …` + `sync`.
- **`embed` → `full`**: chaves no `.env` → subir o compose com o override →
  `brain memory setup --mode full` → `brain memory rebuild` (banco único com extração).
  Nenhum dado do vault se perde — tudo deriva do vault.
- **`full` → `embed`**: `brain memory setup --mode embed` → `brain memory rebuild`.
  O hook de recall continua no banco único (o padrão do `BRAIN_RECALL_BANKS` é `brain`).

## Memória dos agentes: traga a sua (o cérebro não gerencia)

O cérebro **não cria, não aponta e não verifica bancos de memória de agentes** (decisão
de 2026-11-18). Cada agente tem memória própria e configuração própria:

- **Hermes** tem provedor de memória de primeira classe: `hermes config set memory.provider
  hindsight` (+ `~/.hermes/hindsight/config.json` apontando para o SEU servidor e banco).
  O plugin pede consentimento interativo (`hermes plugins install hindsight`).
- **Claude Code / Cursor / Codex** usam o instalador oficial
  (`npx -y @vectorize-io/hindsight-coding-agents install <agente>`) apontado para o
  servidor que VOCÊ escolher — nada disso passa pelo cérebro.

Se você já tem um servidor Hindsight (como o do próprio cérebro), aponte os agentes para
ele por conta e risco dos bancos: use um banco por agente, e lembre que `brain memory
rebuild` só toca o banco que o `[memory]` nomeia.

O que o cérebro registra nesses agentes é só o **canal de leitura** (MCP somente-leitura
e, no Claude Code, o hook de recall): `brain harness connect <agente>` — ver a seção
*Os dois canais do cérebro nos agentes* abaixo.

## Os dois canais do cérebro nos agentes

`brain harness connect <agente>` registra **canais de LEITURA do cérebro** nos agentes de
código — nada de memória, nada de banco:

1. **Hook de recall (`UserPromptSubmit`, só Claude Code)** — controlado por
   `[memory].recall_hook` (`true` | `false`). `brain harness connect claude-code`
   grava `recall_hook = true` e sincroniza `.claude/settings.local.json`. Depois de
   conectar, **abra uma sessão nova; o Claude pode pedir
   revisão do hook em `/hooks`**. Para registro manual em `.claude/settings.local.json`:

   ```json
   {
     "hooks": {
       "UserPromptSubmit": [
         {
           "hooks": [
             {
               "type": "command",
               "command": "BRAIN_HOME=/Users/marina-demo/Apps/second-brain-framework BRAIN_RECALL_ROUTE=embed BRAIN_HINDSIGHT_URL=http://localhost:8888 BRAIN_RECALL_BANKS=brain python3 /Users/marina-demo/Apps/second-brain-framework/services/hooks/recall_context.py",
               "timeout": 5
             }
           ]
         }
       ]
     }
   }
   ```

2. **Servidor MCP somente-leitura (`brain mcp`)** — expõe a busca e leitura do vault
   (o próprio banco `brain`, quando a memória está ligada):
   - **Claude Code** (`~/.claude.json`, via CLI):
     `claude mcp add --scope user brain --env BRAIN_HOME=/Users/marina-demo/Apps/second-brain-framework -- /Users/marina-demo/Apps/second-brain-framework/brain mcp`
   - **Hermes** (`~/.hermes/config.yaml`, via CLI `hermes mcp add brain --command /Users/marina-demo/Apps/second-brain-framework/brain --env BRAIN_HOME=/Users/marina-demo/Apps/second-brain-framework --args mcp`):

     ```yaml
     mcp_servers:
       brain:
         command: /Users/marina-demo/Apps/second-brain-framework/brain
         args:
           - mcp
         env:
           BRAIN_HOME: /Users/marina-demo/Apps/second-brain-framework
         enabled: true
     ```

   - **Cursor** (`~/.cursor/mcp.json`, merge atômico preservando outros servidores):

     ```json
     {
       "mcpServers": {
         "brain": {
           "command": "/Users/marina-demo/Apps/second-brain-framework/brain",
           "args": ["mcp"],
           "env": {
             "BRAIN_HOME": "/Users/marina-demo/Apps/second-brain-framework"
           }
         }
       }
     }
     ```

   - **Codex** (`~/.codex/config.toml`, bloco demarcado validado com `tomllib`):

     ```toml
     # >>> brain: servidor MCP somente-leitura (gerenciado por `brain harness`) >>>
     [mcp_servers.brain]
     command = "/Users/marina-demo/Apps/second-brain-framework/brain"
     args = ["mcp"]
     env = { BRAIN_HOME = "/Users/marina-demo/Apps/second-brain-framework" }
     # <<< brain <<<
     ```

Flags e remoção:

- `--no-recall`: não registra o hook de recall no Claude Code (`recall_hook = false`).
- `--no-mcp`: não registra o servidor MCP somente-leitura no agente.
- `brain harness disconnect <agente>`: remove o servidor MCP e, no Claude Code, grava
  `recall_hook = false` e sincroniza `.claude/settings.local.json`. Memória do agente não
  é mexida — nunca foi do cérebro.

## Provedores — LLM · embeddings · reranker (plano memory-providers.md)

Três slots independentes, escolhidos no wizard e re-editáveis a qualquer momento
(configuração é seção viva, não "setup uma vez"):

| Slot | Default | Nuvem recomendada | Onde muda |
|---|---|---|---|
| **LLM** (só `full`) | — | Anthropic (Haiku extração/consolidação · Sonnet mental models — cenário B) · Fireworks · Z.ai · custom | wizard · `brain memory providers set llm …` · TUI Configurações · painel |
| **Embeddings** | embed: local — LM Studio bge-m3 (zero egress) · **full: Fireworks `qwen3-embedding-8b` @1536 (só-nuvem)** | Fireworks `qwen3-embedding-8b` @1536 · OpenAI · Cohere · custom | idem |
| **Reranker** | off — fusão RRF (veredito 2026-11-07: local reprovado no gate de 400 ms) | Fireworks `qwen3-reranker-8b` (top-50) · Cohere · ZeroEntropy · OpenRouter · custom | idem |

Regras do desenho:

- **O modo define o cardápio (decisão 2026-11-17).** `embed`: embeddings local (default) ou de nuvem.
  **`full` é só-nuvem** — o wizard não oferece `local`, o CLI recusa (`providers set embeddings --provider
  local`) e o doctor avisa instâncias legadas. O passo Memória monta os três pares (LLM · embeddings ·
  reranker, cada um com provedor e chave; reranker: off/RRF default · Fireworks · Cohere) no painel
  (Configurações › Memória), na TUI (Configurações › Provedores, tecla `m`) e no CLI headless
  (`brain memory setup --mode full --provider … --approval ok`). Fireworks embeddings+reranker usam a
  mesma conta; OpenAI de LLM+embeddings idem. Ligou o full? O fluxo verifica o LLM no servidor
  (`health/llm`) e conta se falhou.
- **A escolha mora no `[memory]`** (`llm_provider`, `embeddings_provider`, `reranker_provider`…);
  **a chave mora no `config/.env`** (0600) e nunca volta em output, view ou painel.
- **Egress é dito na tela**: qualquer provedor de nuvem manda texto do vault para fora
  (LLM para extrair, embeddings para vetorizar, reranker para ranquear) — o wizard avisa
  em cada escolha e o doctor narra (`cloud_embeddings`/`cloud_reranker`/`cloud_llm`).
- **Compose**: o `env_file: ../config/.env` injeta as chaves `HINDSIGHT_API_*` no container;
  os cinco campos do stack local são fallback de fábrica. Trocou provedor? Recrie com
  `--env-file config/.env`. **Trocou embeddings?** Vetores antigos ficam incompatíveis —
  `brain memory rebuild` re-deriva tudo do vault.
- **Doctor**: provedor de nuvem sem chave = erro; operações falhas do servidor
  (`failed_operations`, ex.: `No models loaded`) = aviso com a causa nomeada e o
  comando que corrige (`lms load` ou `brain memory providers set llm …`).
- `jina-mlx` existe no servidor mas **fica fora do menu** — benchmark 2026-11-07 reprovou
  (§4.2 do plano da memória).

### LLM por assinatura — sem chave de API (botão Autenticar)

O slot LLM aceita provedores por **assinatura**: `claude-code` (Pro/Max), `xai-oauth`
(SuperGrok), `chatgpt`, `cursor`, `github-copilot`, `nous`. Nenhum deles pede chave na
tela — o campo some e no lugar entra um bloco **Autenticar** (wizard e Configurações ›
Memória), com o chip de estado: *autenticado* ✓ / *autenticar* ⚠.

| Provedor | Como autentica | O que o Brain dirige |
|---|---|---|
| `claude-code` | `claude setup-token` na máquina → token de longo prazo no `config/.env` (`HINDSIGHT_API_LLM_API_KEY`, o caminho *server-held token* do Hindsight — sobrevive a recreate) | Sim, ponta a ponta (`brain memory auth claude-code`): exige o CLI `claude` logado na máquina |
| `xai-oauth` | device-code DENTRO do container: URL + código que você aprova em qualquer navegador; store no volume `hindsight-auth` | Sim (`brain memory auth xai-oauth`): sobe o servidor com o volume e narra a URL no job |
| `chatgpt` · `cursor` · `github-copilot` · `nous` | login no servidor de memória (navegador/CLI do próprio provedor) | Não nesta instalação Docker — o hint do provedor carrega o caminho exato |

**Renovação (o que é automático e o que não é):** o *access token* o Hindsight renova
sozinho (proativo antes de expirar, reativo no 401 — cada provedor gira o próprio store).
O que eventualmente morre é o **login/token raiz** — e aí nenhuma renovação silenciosa é
possível nem desejável (é um ato do dono). O Brain vigia por três frentes: o chip de
estado na tela, o **doctor** (assinatura sem credencial = erro nomeando o comando) e o
**noturno**, que abre uma tarefa `mine` com o comando exato quando a credencial fica
pendente — a memória nunca morre em silêncio. Reautenticar é clicar o mesmo botão
(vira "Reautenticar") ou rodar o `brain memory auth <provedor>` de novo.

Nota ToS (documentada do Hindsight): provedores por assinatura são para **uso pessoal,
máquina local** — exatamente o caso do Brain. Para uso compartilhado/servidor, use
provedor de chave (`anthropic`, `gemini`…). O Google **não tem** faixa de assinatura no
Hindsight: Gemini (`gemini-3.8-flash` default) é pela chave do AI Studio.

## Migração de instâncias antigas (0.10.x · dois bancos · sem harnesses)

1. **Atualize o servidor** — `guides/memory.md` § *Atualizar o Hindsight de versão*
   (export dos bancos → digest 1.2.0 no compose → `up -d` → re-audit). No `embed` o
   export é opcional (bancos são derivados do vault); no `full` ele evita re-pagar extração.
2. **Consolide os bancos** — o `[memory]` dos dois bancos (`brain-raw`/`brain-mem`) virou
   um: `bank = "brain"`. Rode `brain memory rebuild` — ele **apaga os bancos legados do
   servidor** e reenvia o vault no banco único (embed: custo US$ 0, re-embed local).
3. **Escolha o setup** — `brain setup --only memoria`: `embed` (chunks, US$ 0, sem chave)
   ou `full` (extração com a sua chave; o wizard pede o "ok" literal do gate de saída).
   Trocar depois é o mesmo comando — nos dois sentidos.
4. **Agentes de código (opcional)** — canal de leitura: `brain harness connect <agente>`
   (MCP somente-leitura; no Claude Code também o hook de recall). Memória dos agentes fica
   com os próprios agentes — veja *"Memória dos agentes: traga a sua"*.

Usuários do `f7ecb0e` para cá: nada quebra sem esses passos — mas o doctor mostra
⚠ bancos legados no servidor até o `rebuild`, e ⚠ servidor antigo até o bump.

## Mental models · `full` (Fase 8)

Páginas vivas por tema ("onde estamos com X?"), regeneradas pelo Hindsight a partir dos
fatos — o complemento com LLM do dossiê determinístico da Fase 5. **Exige o modo full +
`mental_models = true`** (o refresh usa a sua chave; valide o custo com `brain memory cost`):

```bash
brain memory models sync              # cria mm-goal-# · mm-proj-# · mm-pessoa-<id> (ativos + top pessoas)
brain memory models refresh [id…]     # pede o refresh (sem ids = todos)
brain memory models list · show mm-proj-1
```

Cada model nasce com o **estado do ledger colado** na pergunta-fonte (status/progresso),
tags da entidade (`goal:`/`proj:`/`pessoa:` — só lê o que é dela) e refresh **delta** com
intervalo mínimo de 24 h. Projetos que fecham saem sozinhos no próximo `sync`. Model de
pessoa é pista **[memória]** — o `/ask` confirma no artefato antes de afirmar (R9.4).

## Eval — conjunto-ouro (Fase 0)

```bash
cp template/eval/memory-gold.example.jsonl vault/eval/memory-gold.jsonl   # cure ~60 perguntas
brain memory eval                                                       # roda contra roteador + banco
brain memory eval --route off --save vault/eval/runs/baseline.json      # só o vetor, baseline salvo
```

Métricas por tipo (recall@k, MRR, citação, itens injetados, abstenção nas `nada`, tokens
aproximados) — determinísticas, sem LLM no julgamento. R4: direcional até ~25 por tipo.

## O que NÃO vai

- inbox (ainda não processada) · `config/.env`
- `connectors/` e `github/` do RAW (espelho estruturado já no ledger; diff de código é ruído)
- arquivos maiores que `max_file_mb` (aparecem no doctor como "grandes")
- No `full`: RAW sem artefato (hold até o `/dump`; `memory status` mostra quantos esperam)

## Sem Hindsight

`engine = "none"` (padrão). `/ask` usa `./brain search` → artefato → RAW.
O MCP somente-leitura (`./brain mcp`) também funciona sem memória.

## Hook de recall (Claude Code)

O hook `services/hooks/recall_context.py` injeta o contexto da **camada certa** por
mensagem (Fase 4 do plano — roteador §3.3, determinístico, zero LLM):

| Pergunta | O que injeta |
|---|---|
| estado/ID/título de projeto ("atrasado", `TASK-…`, "projeto de pagamentos") | ≤3 linhas exatas do índice SQLite (`⟶ ledger/<ID>`) — o vetor nem é consultado |
| literal ("o que foi dito", "exatamente", aspas) | 1–2 trechos de origem (≤400 caracteres) com `⟶ <document_id>, <data>` |
| nome/alias de pessoa | linhas do ledger **e** até 2 itens de contexto (consulta expandida com os aliases) |
| demais | até 3 itens de contexto |

Teto de **5 itens** por mensagem; **abstenção** quando nada passa do corte
(`BRAIN_RECALL_MIN_SCORE`, padrão **0.62** — sem reranker, ver abaixo). A perna
vetorial tem prazo próprio (`BRAIN_RECALL_SEMANTIC_MS`, 700 ms): Hindsight lento ou
fora degrada para o que o ledger tiver. Variáveis:

- `BRAIN_RECALL_ROUTE` — `off` | `ledger` | `embed` (padrão **embed**: roteador completo).
  `ledger` é a Fase 2 (só a perna do índice); `off` desliga (idem `BRAIN_RECALL_OFF=1`).
- `BRAIN_RECALL_MIN_SCORE` (0.62) · `BRAIN_RECALL_MAX` (5) · `BRAIN_RECALL_BANKS` (`brain`)
  · `BRAIN_HINDSIGHT_URL` (http://127.0.0.1:8888) · `BRAIN_RECALL_SEMANTIC_MS` (700).
- O roteador acha o índice pelo `BRAIN_HOME` ou subindo do diretório corrente até achar
  `vault/FRESH/_index/brain.sqlite` — rode da raiz da instância ou exporte `BRAIN_HOME`;
  sem achar, a perna ledger silencia (a vetorial segue).

O mesmo classificador está na CLI: `brain route "<pergunta>"` (o `/ask` usa antes de
buscar). **Reranker:** o `jina-mlx` local ficou **fora do menu** — benchmark 2026-11-07
reprovou (não bateu o p95 < 400 ms). Fusão RRF do servidor + corte 0.62; rerankers de
nuvem são opção (`brain memory providers set reranker …`).