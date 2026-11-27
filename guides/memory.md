# Memória para IA — Hindsight

O vault é a verdade. Hindsight é um índice que outra IA (e o `/ask`) usam
para achar mais rápido. Se o servidor cair, nada se perde.

## Dois setups (escolha livre, reversível)

| | `embed` | `full` |
|---|---|---|
| Banco | **1** (`bank`, default `brain`), chunks | **1** (`bank`, default `brain`) com extração de fatos |
| LLM em operação | nenhum | extração + consolidação (modelo barato); mental models (Fase 8 — opcional, `mental_models = true`) |
| Sai da máquina? | **não** | sim — texto do vault à API de LLM **com a chave do dono** (`config/.env`); com embeddings `local`, só o LLM é de nuvem — os vetores ficam na máquina |
| Chaves no `.env` | nenhuma | 1 por conta de nuvem (LLM sempre; embeddings e reranker quando de nuvem — a OpenAI nos dois papéis usa a mesma; embeddings `local` não pedem chave) |
| Custo de API | US$ 0 | medido por `brain memory cost` (medidor mensal, sem teto — decisão do dono) |
| RAW sem `/dump` | entra como está | **hold**: fica retido até o artefato existir (`raw_awaiting_dump = "hold"`) |

Config (`config/brain.toml` `[memory]`) — o modo é derivado: `engine = "none"` → `none`;
`engine = "hindsight"` + `extract = false` → `embed`; `extract = true` (exige `cloud_llm = true`)
→ `full`. O atalho `brain memory setup --mode none|embed|full` grava as chaves do modo e
cria o banco na sequência. O CLI **recusa** `extract` sem `cloud_llm`, e o modo `full`
sem chave `HINDSIGHT_API_*_API_KEY` no `.env`.

### O que muda no `full`

- **Embeddings de provedor de nuvem** (o default do `full`) e reranker de nuvem: o boot não depende do LM Studio.
  Com embeddings `local` (escolha, não padrão) o boot volta a depender dele — veja "Embeddings locais no `full`" nos provedores.
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

**Ordem de boot (1.2.0 em diante):** o servidor valida o endpoint de embeddings na inicialização —
**suba o LM Studio (com o modelo carregado) antes do `up -d`**, senão o container morre na hora
(o 0.10.x não fazia essa checagem). O modelo de LLM pode continuar descarregado no modo embed.
No wizard e no `brain setup --only memoria` essa ordem é automática: o passo de memória instala
(se faltar), sobe o servidor :1234 e baixa/carrega o `bge-m3` antes do compose — a regra acima
só pesa para quem sobe o container na mão.

**Máquina com outro Hindsight no :8888** (decisão 10): não suba dois containers com o mesmo
nome/porta — **adopte** o servidor existente (`[memory].url` aponta pra ele; o banco do cérebro
nasce lá) ou sobreponha as portas: `HINDSIGHT_API_PORT=8891 HINDSIGHT_UI_PORT=9991 docker compose … up -d`.

### Atualizar o Hindsight de versão

**Automático no `brain update` (2.62+).** O servidor de memória acompanha o código: o `update` dispara
`brain services ensure` em segundo plano (e o watchdog/abertura repetem enquanto faltar), que

1. reescreve o slot LLM do `config/.env` no formato da versão (`providers.migrate_env`): modelo que o
   dono digitou continua fixo, o resto passa a seguir o mais novo da linha, e o esforço vai pelo caminho
   que o lane aplica — chave não muda;
2. se a imagem pinada é outra: **baixa primeiro** (falha aqui não toca em nada), para o servidor, **copia o banco**
   para o volume `<volume>-pre-upgrade` (como root; falhou a cópia, religa o de antes e para) e só então recria —
   as migrações do servidor só andam para frente, então a cópia é o que torna a volta possível. O volume vale para
   **todos os bancos do servidor** (`brain` e os de outros agentes, como `Agent`/`hermes`): a cópia cobre todos. Ela
   fica guardada até a próxima atualização (`docker volume rm <volume>-pre-upgrade` libera o espaço);
3. confere `health` e, no `full`, o LLM (`POST /banks/{id}/health/llm`, que o compose liga com
   `HINDSIGHT_API_ENABLE_BANK_LLM_HEALTH=true`);
4. se a imagem nova não subir, **restaura o banco da cópia e recria com a imagem anterior** (`BRAIN_HINDSIGHT_IMAGE`,
   só nessa volta); status e `vault/logs/services.log` dizem o que falhou. Se até a restauração falhar, o servidor
   fica parado e a mensagem aponta o volume com a cópia intacta (não rode `memory rebuild`). Um lock evita duas
   atualizações ao mesmo tempo.

Ensaiado de verdade (Docker real, contêiner de ensaio sobre a cópia de um servidor com três bancos): subida
1.2.0 → 1.3.0 com cópia de segurança, e falha forçada no 1.3.0 com restauração — nos dois casos documentos e
memórias de todos os bancos iguais aos do original, e o 1.2.0 volta a subir sobre o banco restaurado.

À mão (servidor adotado, fora do compose do Brain), a receita de sempre — migrações de schema (Alembic)
rodam no boot e são **forward-only**: apontou código antigo pra um banco já migrado, só restaurando backup.

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
| **LLM** (só `full`) | — | Anthropic ✓ (Haiku 5.5 em TUDO, esforço high — régua do dono) · claude-code/xai-oauth (assinatura com login guiado) · Fireworks (DeepSeek v4.1) · Z.ai (glm-5.3-flash) · OpenAI (gpt-6-luna) · Gemini (3.1-flash-lite) · MiniMax (M3.1-Flash) · custom | wizard · `brain memory providers set llm …` · TUI Configurações · painel |
| **Embeddings** | embed: local — LM Studio bge-m3 (zero egress) · **full: Fireworks `qwen3-embedding-8b` @1536 (nuvem; `local` é escolha, não padrão)** | Fireworks `qwen3-embedding-8b` @1536 · OpenAI · Cohere · custom — ou `local` (bge-m3, nos dois modos) | idem |
| **Reranker** | off — fusão RRF (veredito 2026-11-07: local reprovado no gate de 400 ms) | Fireworks `qwen3-reranker-8b` (top-50) · Cohere · ZeroEntropy · OpenRouter · custom | idem |
| **Decisão** (só `full`) | **off — cada um paga só os tokens do próprio LLM (pular é normal)** | Hindsight `hs-decide-1-flash` — US$ 0,02/1M de entrada, chave `hsk_` por uso (`--recall on --candidates N` opcional) · ou `local` (`/v1/systemone`, zero egress) | idem |

Regras do desenho:

- **O LLM é de nuvem no `full`; os embeddings escolhem.** `embed`: embeddings local (default) ou de
  nuvem. `full`: o default recomendado é o de nuvem, mas `local` (bge-m3 no LM Studio) entra no cardápio
  de todas as superfícies. Uma instância que já usa `local` no `embed` sobe para o `full` com `local`
  pré-selecionado; um payload headless que não nomeia embeddings no `full` cai no de nuvem. LLM local
  segue proibido. O passo Memória monta os três pares (LLM · embeddings ·
  reranker, cada um com provedor e chave; reranker: off/RRF default · Fireworks · Cohere) no painel
  (Configurações › Memória — modo e provedores numa tela só: uma pilha com uma linha por slot, que abre no lugar com
  os campos de `memory providers set` — provedor, chave ou assinatura, qual modelo faz cada operação do LLM, base URL,
  dimensões e teto de candidatos; antes do Aplicar a tela lista o que o Brain liga sozinho — OrbStack, LM Studio,
  modelo, decisor), na TUI (Configurações › Provedores, tecla `m`) e no CLI headless
  (`brain memory setup --mode full --provider … --approval ok`). Fireworks embeddings+reranker usam a
  mesma conta; OpenAI de LLM+embeddings idem. Flag ausente mantém o slot como está — só o que você nomeou é
  regravado (slot ainda sem escolha válida cai no padrão do modo). Ligou o full? O fluxo verifica o LLM no
  servidor (`health/llm`) e conta se falhou.
- **A escolha mora no `[memory]`** (`llm_provider`, `embeddings_provider`, `reranker_provider`…);
  **a chave mora no `config/.env`** (0600) e nunca volta em output, view ou painel.
- **Egress é dito na tela**: qualquer provedor de nuvem manda texto do vault para fora
  (LLM para extrair, embeddings para vetorizar, reranker para ranquear, decisor em nuvem para julgar) — o wizard avisa
  em cada escolha e o doctor narra (`cloud_embeddings`/`cloud_reranker`/`cloud_decision`/`cloud_llm`).
  `full` + embeddings `local` grava `cloud_llm = true` e `cloud_embeddings = false`: wizard, painel, TUI e doctor
  dizem "embeddings local; o LLM continua na nuvem" — o texto do vault segue indo ao LLM. A promessa "nada sai da
  máquina" é só do `embed`.
- **Compose**: o `env_file: ../config/.env` injeta as chaves `HINDSIGHT_API_*` no container;
  os cinco campos do stack local são fallback de fábrica. Trocou provedor? Recrie com
  `--env-file config/.env`. **Trocou embeddings?** Vetores antigos ficam incompatíveis —
  `brain memory rebuild` re-deriva tudo do vault. Isso vale para `local` ↔ nuvem nos dois sentidos — e para trocar
  o modelo ou a dimensão (`--dimensions`) no mesmo provedor —, e **no `full`
  o rebuild reenvia o vault inteiro ao LLM e paga a extração de novo** (`brain memory cost` mede): a saída da
  troca avisa isso antes de gravar. A troca regrava o slot inteiro: dimensão e teto de candidatos que ela não diz
  voltam ao padrão do provedor novo (ou do servidor) — o do provedor anterior não fica no `.env`.
- **Embeddings locais no `full`**: o Hindsight checa o LM Studio no boot e o contêiner morre sem ele. Todo caminho
  que sobe ou recria o servidor no `full` + `local` (wizard, `brain setup --only memoria`, job do painel, login do
  provedor de assinatura) roda antes do `up -d` o mesmo pré-voo do `embed`: LM Studio instalado, servidor em
  `:1234` e `text-embedding-bge-m3` carregado. Faltou? O fluxo **para antes de subir**, narra o que faltou e manda
  rodar `brain setup --only memoria` — o job do painel termina em erro, não em sucesso. O watchdog
  (`services/watchdog.sh`) também não recria em loop um contêiner `full` + `local` enquanto o `:1234` não responde;
  ele registra a causa no log. A saída de `brain memory providers set embeddings --provider local` narra o estado
  do LM Studio e o próximo passo (recriar com o override do `full`, depois `brain memory rebuild`).
- **Doctor**: `full` + embeddings `local`: LM Studio respondendo = ok; instalado com o servidor desligado, ou
  ausente = aviso com o comando que resolve (`brain setup --only memoria`). Provedor de nuvem sem chave = erro;
  operações falhas do servidor
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
| `chatgpt` · `nous` · `github-copilot` | login manual no servidor de memória (`docker exec -it hindsight …`, exibido no wizard via `auth_command`). No Copilot o modelo padrão (`gpt-5.6-terra`) é fraco para memória | Não nesta instalação Docker — aparecem no fim do menu com o sufixo *"login manual no servidor"* e o doctor avisa *"login no servidor não verificado"* quando não há evidência de login |
| `cursor` | `cursor-agent` logado no servidor de memória | Indisponível nesta instalação Docker — omitido do menu padrão do wizard/painel (ainda aceito pela CLI, com aviso no `brain doctor`) |

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
Hindsight: Gemini é pela chave do AI Studio (o Brain recomenda a `gemini-3.1-flash-lite`).

### Modelos: campo livre, vazio = o mais novo da linha recomendada

**Vazio segue o mais novo.** Nos provedores dos quatro laboratórios (Anthropic/Claude Code, OpenAI/ChatGPT,
xAI, Gemini) o Brain lê a lista viva de modelos — API do fornecedor com a chave do `config/.env`, ou o
catálogo público do OpenRouter quando não há chave (assinatura) — no máximo 1×/dia (`brain memory providers
catalog [--refresh]`, botão *Atualizar lista* no painel, entrada *Memória: modelos do LLM* na TUI). O
recomendado abaixo é a **semente**: campo vazio vale o mais novo da mesma linha (`claude-haiku-5-5` →
`claude-haiku-5-6` quando sair). A checagem diária (modo `full`) move as operações que seguem o padrão,
recria o servidor, confere o LLM e, se falhar, volta ao modelo de antes; o painel mostra o que mudou.
Modelo **digitado** fica fixo (`[memory] llm_pinned`) e nunca é movido. Snapshot datado, preview e variante
(`:batch`) não entram na escolha.

**Esforço por modelo.** Cada operação (e o Padrão) tem um seletor de esforço com os níveis que **aquele
modelo** aceita — tabela do fornecedor; versão nova herda a da linha; na API da Anthropic, a capacidade
lida do `/v1/models` vence a regra. Exemplos: Claude Haiku/Sonnet/Opus 5.5 `low…max`; Opus 4.6 `low…high,
max`; Haiku 4.5 sem esforço; GPT-6 `none…xhigh` no OpenAI (o `max` só existe na Responses API, que o
servidor não usa nesse lane) e `none…max` no ChatGPT; Grok 4.7 `low…xhigh`; Gemini 4 Neon/Hydrogen
`low…xhigh`, Carbon `low…high`. Nível fora da lista é recusado antes de gravar. O caminho até o servidor
(Hindsight 1.3.0) depende do lane: `*_REASONING_EFFORT` no Claude Code, OpenAI, ChatGPT e xAI;
`*_EXTRA_BODY` com `output_config.effort` na API Anthropic e `thinking_config.thinking_level` no Gemini —
o Brain só mexe na sua chave dentro do extra body; o resto do JSON do dono fica. CLI: `--effort high`,
`--efforts retain=low,reflect=xhigh`.

Todo provedor de LLM mostra o campo **Modelo** (assinatura inclusive). Vazio aplica o
recomendado — o placeholder diz exatamente qual. As recomendações são **curadas pelo Brain**
na frente da tabela do servidor pinado (estudo 2026-11-19, leaderboard oficial da Hindsight
+ preço de catálogo):

- **Anthropic e Claude Code**: `claude-haiku-5-5` em TODAS as operações, esforço `high`
  (régua do dono — superou o antigo cenário B com Sonnet: haiku-5.5+decide é a melhor
  qualidade acessível, 88.5 all-ops, 14/14 idiomas no retain, e $0.10/$0.50 até 100k;
  se o `config/.env` já tiver `HINDSIGHT_API_LLM_REASONING_EFFORT=max`, o Brain preserva o
  arquivo e o `brain doctor` apenas avisa que está diferente do padrão `high`).
- **OpenAI/ChatGPT**: `gpt-6-luna` (#2 geral, $11/1k; retain 95.8 @ $0.43/1k).
- **Z.ai**: `glm-5.3-flash` (#1 VALOR — $9.33/1k all-ops; #1 consolid. e reflect).
- **Gemini**: `gemini-3.1-flash-lite` ($0.25/$1.50) — **não** a 3.8-flash: 3-6× o preço e
  MAIS FRACA no retain (84.0 vs 88.3).
- **Fireworks**: DeepSeek `v4p1-flash` (#5 geral; #2 consolidação).
- **MiniMax** (novo no menu): `MiniMax-M3.1-Flash` — **campeão de extração** (retain 96.4,
  qualidade 98.8, $0.81/1k; $0.15/$0.60 o 1M).
- **SuperGrok**: `grok-4.7` — exatamente o preço do 4.6 ($2/$6): ficar no 4.5 não economiza nada.

O default é gravado EXPLÍCITO no `config/.env` (o que aplicou é o que o `stack` mostra).
Modelo digitado vence: vale para todas as operações. `custom` continua exigindo modelo.

### Decisão (opcional) — o juiz rápido que corta ~40% das chamadas do LLM

Quarto slot, **só no modo full**, **desligado de fábrica**: pular é o caminho normal — sem
ele, cada operação funciona como sempre e cada pessoa paga só os tokens do próprio LLM.
Opções (painel, TUI, CLI e wizard): **Desligado**, **Local** (o Brain instala e liga o decisor) e três de
nuvem — **Hindsight** (`hs-decide-1-flash`, chave `hsk_`), **OpenAI** (Decisions API, `gpt-6-luna`; reusa a
chave do LLM quando o LLM também é OpenAI) e **Typesafe** (`jev-latest`, System One). Cada um guarda a
**sua** chave (`HINDSIGHT_API_DECISION_CLOUD_API_KEY`, `BRAIN_DECISION_OPENAI_API_KEY`,
`BRAIN_DECISION_TYPESAFE_API_KEY`); a que o servidor lê (`HINDSIGHT_API_DECISION_MODEL_API_KEY`) é sempre a do
ativo — trocar de provedor nunca manda a chave de um para o outro. Fireworks não serve decisão: o servidor só
fala System One (Hindsight, Typesafe, Cloudflare) e a Decisions API da OpenAI.
Quem liga usa o **hs-decide-1-flash** (Hindsight Inference): o modelo de 0,8B treinado
para os julgamentos que o servidor faz (isso repete? muda? ajuda? é suficiente?) — o LLM
só é chamado quando algo precisa ser escrito. Na leaderboard oficial isso **cortou ~40%
das chamadas do LLM SUBINDO a qualidade** (haiku-5.5: US$ 35→21 por 1k casos, 85.5→88.1).

- **Custo**: US$ 0,02 por 1M de tokens de ENTRADA, por uso, sem assinatura — medido em
  ~US$ 0,64 por 1k casos (≈ 25 julgamentos por caso). A chave `hsk_` sai de
  `inference.hindsight.vectorize.io` e cola no wizard (ou `brain memory providers set
  decision --provider hindsight --key …`). Dono cobre a sua e as da equipe; quem não quer
  cola nada e fica no padrão.
- **Egress**: no provedor `hindsight`, trechos pequenos de memória vão à nuvem de inferência do
  Hindsight para julgamento (`cloud_decision = true`) — mesmo gate narrado dos outros provedores
  de nuvem. No provedor `local`, nada sai da máquina (`cloud_decision = false`).
- **Segurança de queda e decisor no recall (`--recall on|off`, padrão `off`)**:
  - Com `--recall off` (padrão, `HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER=none`), o decisor
    só atua em consolidação/reflect/páginas: se falhar ali, essas operações voltam ao caminho
    só-LLM (perde-se a economia, nunca a operação) e o recall segue pelo caminho normal (RRF/reranker).
  - Com `--recall on` (`HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER=<provedor>`, disponível apenas
    no modo `full` com um decisor de nuvem), o decisor também julga os candidatos do recall.
    Ligar exige um teto explícito de candidatos (`--candidates N`, sem default silencioso), e o
    slot Reranker fica oculto/inerte (o valor existente no `config/.env` é preservado, não apagado).
    **Importante**: com o decisor ligado no recall **não há fallback para RRF** nesta versão do
    servidor (1.3.0) — cada candidato gera uma requisição própria ao decisor e, se o decisor cair,
    **o recall falha fechado**. O `brain doctor` emite aviso sempre que o recall com decisor está ativo.
- **Decisor local (`--provider local`)**:
  - Exceção declarada no modo `full`: roda o `hs-decide-1-flash` sem egress
    (`cloud_decision = false`, `HINDSIGHT_API_DECISION_MODEL_MAX_CONCURRENT=1`). O Brain preenche
    a URL e a chave local; ao trocar de `local`, `HINDSIGHT_API_DECISION_MODEL_BASE_URL` sai do
    `config/.env` e a chave `hsk_` da nuvem não é apagada. O slot LLM continua proibido para
    modelos locais e o modo `embed` continua sem decisor. `--recall on` com `local` segue recusado
    (sem medição de latência).
  - **`hs-decide` não é servido por LM Studio nem Ollama**: o protocolo é `/v1/systemone`.
    Escolher `local` (wizard, painel ou `brain memory providers set decision --provider local`)
    instala o servidor num venv próprio (`.decider/`, fora do git): MLX no Apple Silicon, vLLM no
    Linux com GPU NVIDIA. Sem um dos dois, a escolha é recusada e nada é instalado. O Brain preenche
    modelo, URL (`http://host.docker.internal:8000`) e uma chave local em `BRAIN_DECISION_LOCAL_API_KEY`,
    separada da chave `hsk_`. Um teste de fumaça em `/v1/systemone` precisa passar antes de o slot
    ficar ligado; se falhar, o slot volta a `off`. Trocar para outro provedor para e remove o serviço
    (os pesos ficam) e não apaga a chave da nuvem. O noturno não instala — só confere e religa
    (`brain services ensure`).
- **Servidor**: o pin 1.3.0 suporta os cinco (`off` = `none`, o valor de fábrica); o doctor aponta
  chave/URL ausente quando o slot está ligado.

## Migração de instâncias antigas (0.10.x · dois bancos · sem harnesses)

1. **Atualize o servidor** — `guides/memory.md` § *Atualizar o Hindsight de versão*
   (export dos bancos → digest novo no compose → `up -d` → re-audit; no 2.62+ o `brain update` faz isso). No `embed` o
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