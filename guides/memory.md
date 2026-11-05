# Memória para IA — Hindsight

O vault é a verdade. Hindsight é um índice que outra IA (e o `/ask`) usam
para achar mais rápido. Se o servidor cair, nada se perde.

## Dois setups (escolha livre, reversível)

| | `embed` | `full` |
|---|---|---|
| Bancos | 2 (`brain-mem` + `brain-raw`), chunks | **1** (`bank`, default `brain-mem`) com extração de fatos |
| LLM em operação | nenhum | extração + consolidação (modelo barato); mental models (Fase 8, ainda não aterrissado) |
| Sai da máquina? | **não** | sim — texto do vault à API de LLM **com a chave do dono** (`config/.env`) |
| Chaves no `.env` | nenhuma | 1 (provider de LLM) |
| Custo de API | US$ 0 | medido por `brain memory cost` (medidor mensal, sem teto — decisão do dono) |
| RAW sem `/dump` | entra como está | **hold**: fica retido até o artefato existir (`raw_awaiting_dump = "hold"`) |

Config (`config/brain.toml` `[memory]`) — o modo é derivado: `engine = "none"` → `none`;
`engine = "hindsight"` + `extract = false` → `embed`; `extract = true` (exige `cloud_llm = true`)
→ `full`. O atalho `brain memory setup --mode none|embed|full` grava as chaves do modo e
cria os bancos na sequência. O CLI **recusa** `extract` sem `cloud_llm`, e o modo `full`
sem chave `HINDSIGHT_API_*_API_KEY` no `.env`.

### O que muda no `full`

- Todo documento viaja com um bloco **CONTEXTO** (caminho, data do mundo, pessoas com id e
  grafias, projetos) derivado do ledger — a extração usa só esses nomes/IDs, nunca inventa.
- **Data do mundo** em todo RAW (ordem: artefato do `/dump` → carimbo no nome → cabeçalho
  `capturado:`/`criada:` → mês da pasta `RAW/<ano>/<mês>/`).
- Entidades anexadas por casamento de alias no texto (metadado `entities`).
- `connectors/` e `github/` do RAW **nunca** vão ao banco (`exclude_types`) — nos dois modos.
- Deleção sombra: documento que sai do corpus (tipo excluído, arquivo removido) sai do banco.
- Observações e consolidação ligadas: a fila do `memory status` volta a ter vida.

### Os dois bancos do `embed`

`brain-raw` = arquivos do RAW como estão (texto e binários até `max_file_mb`), `chunks` sem
interpretação — responde "o que foi dito". `brain-mem` = artefatos do PROCESSED + uma página
por ação/decisão/entrega/pessoa + PLANNING/PROFILE, também em `chunks`: quem escreveu é melhor
que o extrator (o agente com proveniência, o CLI renderizando o ledger). `document_id` = caminho
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
passa disso — reduza `retain_chunk_size`). Não carregue um LLM no LM Studio só para o Hindsight.

## Ligar nesta instância

```bash
brain memory setup --mode embed     # ou full (exige chave no .env) — grava [memory] e cria os bancos
brain memory sync                   # incremental; --limit 50 --dry-run disponível
brain memory status                 # modo, pendências, fila, RAW retidos (full)
brain memory recall "quem decidiu o ponto novo?"
brain memory cost                   # medidor mensal (embed: US$ 0; full: tokens + US$ por operação)
```

Modo `full` antes do primeiro `sync` grande: valide sem gastar —

```bash
curl -s -X POST localhost:8888/v1/default/banks/brain-mem/health/llm   # por operação
curl -s -X POST localhost:8888/v1/default/banks/brain-mem/memories/dry-run-extract \
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
  O hook de recall volta aos dois bancos (o padrão já é `brain-mem,brain-raw`).

## O que NÃO vai

- inbox (ainda não processada) · `config/.env`
- `connectors/` e `github/` do RAW (espelho estruturado já no ledger; diff de código é ruído)
- arquivos maiores que `max_file_mb` (aparecem no doctor como "grandes")
- No `full`: RAW sem artefato (hold até o `/dump`; `memory status` mostra quantos esperam)

## Sem Hindsight

`engine = "none"` (padrão). `/ask` usa `./brain search` → artefato → RAW.
O MCP somente-leitura (`./brain mcp`) também funciona sem memória.

## Hook de recall (Claude Code)

O hook `services/hooks/recall_context.py` anexa contexto à mensagem. Variáveis:

- `BRAIN_RECALL_ROUTE=ledger` — **rota ledger-only (Fase 2 do plano)**: pergunta de estado
  (ID, prazo, atraso, quem deve, título de projeto) injeta até 3 linhas exatas do índice
  SQLite (`⟶ ledger/<ID>`); todo o resto **silencia**. Zero LLM, zero vetor.
- `BRAIN_RECALL_OFF=1` — desliga tudo.
- A rota ledger acha o índice pelo `BRAIN_HOME` ou subindo do diretório corrente até achar
  `vault/FRESH/_index/brain.sqlite` — rode o hook da raiz da instância (o hook instalado
  pelo repo já roda de lá) ou exporte `BRAIN_HOME`; sem achar, silencia.
- Demais variáveis (`BRAIN_RECALL_MIN_SCORE`, `BRAIN_RECALL_MAX`, bancos) valem para o
  caminho vetorial clássico, que segue o padrão sem a rota ligada.
