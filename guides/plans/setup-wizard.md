# Plano — Setup assistido (`./brain setup`)

Executor: agente + dono. Fase 0 (mockup manual) roda ANTES de qualquer código:
valida roteiro e perguntas, e deixa a máquina do dono configurada de verdade.

## Problema

Hoje o nascimento de uma instância é disperso e exige saber onde cada coisa mora:

| Precisa de | Onde está hoje | Como se descobre |
|---|---|---|
| Semear vault + config + dono | `./brain init --owner-id …` | README / tentativa e erro |
| PROFILE + PLANNING | entrevista `/init` do agente | AGENTS.md |
| Rotina, foco, portas, runner | edição manual de `config/brain.toml` | comentários do `.example` |
| Chaves (Google OAuth, GitHub, pasta de backup) | edição manual de `config/.env` + `scripts/google_auth.py` (token impresso no terminal, colar à mão) | `guides/google-oauth.md`, `guides/backup.md` |
| Fontes observáveis | `./brain watch add` (existe, validado) | `guides/user-guide.md` |
| Noturno | `./brain schedule install` | doctor avisa DEPOIS |
| TUI (venv) | `./brain tui --setup` | erro exit 3 avisa DEPOIS |
| Memória | `[memory] engine` + `./brain memory setup` | `guides/memory.md` |
| Diagnóstico | `./brain doctor` | — |

Nada guia a ordem; erros de configuração aparecem tarde (doctor, porta que falha
na hora de usar). O dono novo (ou o dono numa máquina nova) precisa ler 4 guias.
Referência pedida: o onboarding do hermes-agent — perguntas em sequência,
validação na hora, grava incremental, re-executável, mesma régua em várias
superfícies (CLI primeiro, UI depois).

## Princípios

1. **Um motor de passos, três frentes.** O passo (perguntas, validação, apply)
   mora em `brainlib/setup.py`, declarativo; CLI, TUI e painel são casca.
2. **Estrutura, não vida.** O wizard configura instância e portas; o CONTEÚDO
   (PROFILE, goals, pessoas) continua da entrevista `/init` do agente — o wizard
   termina oferecendo-a. Nenhuma pergunta de "quais seus goals" no CLI.
3. **Idempotente e re-executável.** `./brain setup` de novo mostra o estado de
   cada passo (feito / pendente / desligado) e pula o pronto. Status derivado de
   config + doctor — sem arquivo de estado novo.
4. **Porta opcional é OFF por padrão.** Toda porta externa (backup, feedback,
   publish, oppdrive, focus.google) entra desligada; ligar é passo explícito com
   gate explicado em 2 linhas.
5. **Segredo entra mascarado, valida na hora, nunca volta.** `getpass`, grava
   `config/.env` (0600, preservando chaves existentes), ping real para validar
   (GitHub API, token Google, pasta do Drive), nada de ecoar valor em log/tela.
6. **stdlib-only no CLI**, como o resto. Ping HTTP via `urllib`.
7. **Doctor é a régua.** O último passo do wizard é um doctor filtrado; o score
   de setup do painel deriva dos mesmos checks.

## O mapa de passos (espinha dorsal — igual nas três frentes)

| # | Passo | Pergunta/opção essencial | Grava onde | Validação |
|---|---|---|---|---|
| 0 | Instância | vault novo · demo detectado → arquivar/regenerar? · migrar de outra máquina? | `vault/`, `config/` | zonas + doctor |
| 1 | Identidade | id (slug) + nome do dono | `brain.toml [owner]` + `person.added` | dono no ledger |
| 2 | Rotina | fuso · dias · início/fim · almoço · férias | `brain.toml [work]` | parse + `focus plan` |
| 3 | Foco | `ics` (zero config) **ou** `google` → OAuth inline | `.env` GOOGLE_* + `[focus] mode` | plano proposto; `apply` grava 1 bloco marcado |
| 4 | Noturno | horário · o que roda (agente precisa de runner) | launchd/crontab | `schedule status` + 1ª execução |
| 5 | TUI | instalar venv agora? | `.venv-tui` | `tui` abre |
| 6 | Porta: backup | OAuth do passo 3 reaproveitado · ID da pasta | `.env` GOOGLE_BACKUP_FOLDER_ID + `[backup]` | pasta visível via API; `backup --local` |
| 7 | Porta: feedback | token GitHub (fine-grained, issues no repo) | `.env` GITHUB_TOKEN | GET no repo = 200 |
| 8 | Portas: outbox/publish | destinatários allow · destinos | `[outbound]` `[publish]` | formato |
| 9 | Porta: oppdrive | pasta-raiz · ferramentas MCP | `[oppdrive]` | pasta existe; ferramentas nomeadas |
| 10 | Fontes | menu por kind (gcal/gmail/slack/drive/jira/github) · lembrete: leitura é MCP do AGENTE — conector liga no agente, não aqui | `watch.toml` (via `watch add`) | `watch list` + 1º pull no `/update` |
| 11 | Memória | modo: `none` · `embed` · `full` (ver § abaixo) | `[memory]` + `memory setup` | por modo (ver § abaixo) |
| 12 | Runner/agente | auto/claude/cursor/agy/… · modelo · allow de leitura | `[runner]` | rodada ⚡ ou noturno seco |
| 13 | Fechamento | render + painel · doctor · oferecer `/init` | — | doctor filtrado |

### Passo 11 — Memória em três modos

A memória é o único passo com **modos de armazenagem diferentes**, não só
liga/desliga. Os modos seguem o plano interno da memória (Hindsight com LLM,
Fases 0–7, com as emendas R1–R9 da revisão): o wizard não inventa os modos,
ele configura os que existem.

| Modo | O que é | Bancos | LLM | Sai da máquina? | Chaves | Existe hoje? |
|---|---|---|---|---|---|---|
| `none` | sem Hindsight; `/ask` usa índice → artefato → RAW | — | — | não | nenhuma | ✓ |
| `embed` | só embeddings/chunks: os dois bancos de hoje, retain em modo chunks, sem consolidação nem observações (`NO_LLM_CONFIG`); embeddings locais (LM Studio) | `brain-mem` + `brain-raw` | nenhum | **não** | nenhuma | ✓ |
| `full` | banco único com **extração de fatos** do RAW (contexto de identidades do ledger), observações consolidadas e mental models por GOAL/PROJ/pessoa | `brain-mem` (único) | por operação (extração/consolidação num modelo barato, mental models num maior) | **sim — texto do vault vai à API do LLM** | 1 chave de API no `.env` | depende do plano da memória (Fases 3–5) |

Perguntas e validação por modo:

- **`none`**: nada a perguntar. Válida: tudo funciona (doctor sem memória).
- **`embed`**: URL do servidor (+ onde rodam os embeddings). Grava
  `[memory] engine/url/banks` → `memory setup` cria os dois bancos em modo
  chunks → `memory status` + um `memory sync` seco. Zero chave, zero egress —
  pode rodar até no noturno sem gate.
- **`full`**: tudo do `embed` **mais** os pré-requisitos da seção 4.3 do plano
  da memória (decisões 2 e 3 do dono, registradas):
  1. **Chave do dono + nada público (é porta de saída de dados).** O wizard
     pede o "ok" literal (texto do RAW vai à API de LLM configurada pelo dono,
     para extração, consolidação e mental models) e a **chave no `.env`**
     (mascarada, 0600, provider livre — nunca no repo/compose). A invariante é
     *nenhum dado do dono público* (porta 5); a AGENTS.md **registra** o
     comportamento (`cloud_llm = true`), sem gate de política corporativa.
  2. **Medidor mensal, sem teto (decisão 3).** `brain memory cost` mostra
     tokens + US$ por operação/modelo; o doctor exibe o gasto do mês como
     informação — nunca alerta, nunca bloqueio.
  - Validação antes de gastar: `POST /banks/<banco>/health/llm` por operação +
     `dry-run-extract` numa amostra; o CLI recusa `extract` sem `cloud_llm` e o
     modo `full` sem chave no `.env`. Rollback documentado: `setup --mode
     embed` + `rebuild` volta ao modo `embed` (§4.5 do plano — primeira classe
     nos dois sentidos).
- **Feature-detect, não promessa:** o wizard só lista `full` se o `[memory]`
  da instância suportar as chaves novas (`extract`, `cloud_llm` — Fase 4 do
  plano). Enquanto o plano não aterrissa, o passo mostra `full` como
  "indisponível — depende do plano da memória" e segue com `embed`.

## Fases

### Fase 0 — Mockup manual (ESTE documento, agora)

O dono executa o roteiro acima **à mão**, nesta máquina, comandos exatos na
seção seguinte. Objetivos: (a) máquina real configurada; (b) cada passo provado
— comando certo, pergunta certa, ordem certa; (c) ajustes anotados viram a spec
da Fase 1. Nada é codado antes do dono aprovar o roteiro vivido.

### Fase 1 — CLI (`./brain setup`)

- `brainlib/setup.py`: motor declarativo (passo = id, título, perguntas,
  `status()` derivado de config/doctor, `apply()`); `setup.py` absorve a lógica
  do `scripts/google_auth.py` (loopback :8917 vira função; script fica como
  fallback headless) e ganha um gravador de `.env` mascarado e validado.
- `./brain setup` (interativo), `--only foco,backup` (re-visitar passos),
  `--yes` (não-interativo, default sensato — para teste/script).
- Passo memória com os três modos da § acima: `embed` grava direto; `full`
  feature-detecta as chaves novas do `[memory]`, exige o gate de política com
  "ok" explícito (evento no ledger) e a chave validada antes de gravar.
- Cobertura de superfícies: setup é comando do DONO → precisa constar no painel
  (aba/checklist) e na TUI, ou entrar nos conjuntos de justificação dos testes
  `DashboardAssetTests` / `CoverageTest` — decidir na hora do PR.
- Testes: harness `_inst` em `tests/test_setup.py` (BRAIN_NOW, .env 0600,
  idempotência, `--only`, nunca ecoar segredo).

### Fase 2 — TUI

Face Setup no cockpit (mesmo motor, telas Textual): lista de passos com estado,
entra no passo pendente, sai com apply. Aproveita o padrão formulário das faces
existentes. `./brain tui` detecta vault sem config → oferece setup direto.

### Fase 3 — Painel

- Sem `serve`: aba/checklist ESTÁTICO derivado do doctor (render gera; cada
  item mostra o comando CLI correspondente). Painel é offline — sem formulário.
- Com `serve` no ar: o mesmo checklist vira formulário de verdade (ponte já
  existe no padrão da aba Sugestões). Prioridade menor; só se o dono usar.

### Fase 4 — Docs e distribuição

README quickstart de 5 minutos (`git clone` → `./brain setup` → `/init`),
`guides/setup.md` unifica google-oauth/backup/manual no vocabulário do wizard,
`./brain demo --dir` como pista de teste do wizard (instância demo descartável).
`init` atual fica como modo script/headless.

## Fase 0 — o mockup, passo a passo (executar nesta máquina)

Estado atual daqui: vault DEMO (padaria fictícia), `brain.toml` demo, `.env`
existe. O demo é regenerável (`./brain demo --dir`), então arquivá-lo é barato.

**Decisão prévia do dono (bloqueia o resto):** esta máquina vira a instância
REAL (arquiva o demo) — recomendado, foi o pedido — ou o demo fica e a instância
real mora em outro clone/vault (`BRAIN_VAULT`)? Assumido abaixo: instância real.

1. **Arquivar o demo e nascer de novo**
   `mv vault vault-demo-$(date +%F)` · `./brain init --owner-id <slug> --owner-name "<nome>"`
   → confere: criou `config/brain.toml|watch.toml|.env` (0600), dono no ledger,
   zonas semeadas. `./brain doctor` sem erro de zona/config.
2. **Rotina** — editar `config/brain.toml`: `[owner] timezone`, `[work]`
   days/start/end/lunch, `[[vacations]]` se houver. Valida: `./brain focus plan`
   roda sem erro de fuso.
3. **Foco** — escolher `ics` (nada a fazer) ou `google`: colar
   `GOOGLE_CLIENT_ID/SECRET` no `.env` → `python3 scripts/google_auth.py`
   (navegador → volta sozinho) → colar `GOOGLE_REFRESH_TOKEN` impresso →
   `focus.mode = "google"`. Valida: `./brain focus plan` → `approve` → `apply`
   → evento "Foco" no calendário (com marca do cérebro).
4. **Noturno** — `./brain schedule install --time <HH:MM>` → `./brain schedule
   status`. Nota: o passo "agente" do noturno exige `[runner]` (passo 12); sem
   ele, o noturno roda com o que houver.
5. **TUI** — `./brain tui --setup` → `./brain tui` abre e fecha limpo.
6. **Backup (porta 4)** — criar pasta "Brain Backup" no Drive, copiar o ID →
   `.env GOOGLE_BACKUP_FOLDER_ID=` → `brain.toml [backup] enabled = true`.
   Valida: `./brain backup --local /tmp` → `./brain backup` (upload de verdade).
7. **Feedback (porta 7)** — token fine-grained (issues: RW só em
   `BVLCQ/second-brain-framework`) → `.env GITHUB_TOKEN=`. Valida sem publicar
   nada (o dono roda; token não aparece no chat):
   `curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $(grep ^GITHUB_TOKEN config/.env | cut -d= -f2)" https://api.github.com/user` → 200.
8. **Outbox/publish** — se fizer sentido já: `[outbound].allow` (ids do ledger),
   `[publish].destinations`. Sem validação externa; só formato.
9. **Oppdrive** — só se quiser a porta: pasta-raiz no Drive + `[oppdrive]`.
10. **Fontes** — `./brain watch add <key> --kind <kind> [--set campo=valor]
    --window <janela>` por fonte; os CONECTORES ligam no agente (Hermes:
    manage_connections; claude: config dele). Valida: `./brain watch list` e,
    no primeiro `/update`, `doctor` mostrando `✓ fonte <key>`.
11. **Memória** — três caminhos (ver §"Passo 11"):
    - `none`: nada a fazer; o cérebro funciona sem.
    - `embed` (o modo de hoje): subir o Hindsight (`services/compose.yaml`),
      `[memory] engine = "hindsight"` → `./brain memory setup` (cria os dois
      bancos em modo chunks) → `./brain memory status`. Zero chave, nada sai
      da máquina.
    - `full` (com chave de API — extração, observações, mental models):
      **aterrissado no código** (brainlib/memory.py, modos embed/full; mental
      models = Fase 8 do plano). O passo pergunta: (1) o "ok" literal do dono;
      (2) a chave no `.env` (mascarada, 0600); (3) provider/modelo por
      operação. Valida com `health/llm` + `dry-run-extract` antes de confiar;
      o medidor mensal entra no doctor como informação (sem teto).
12. **Runner** — `[runner] agent = "claude"|"agy"|…` (+ `model`/`effort` se
    quiser). Valida: uma ação ⚡ na TUI ou `./brain nightly --skip-agent` seco.
13. **Fechamento** — `./brain render --open` (painel) · `./brain doctor`
    (esperado: verde, no máximo ⚠ normais do dono) · próxima conversa:
    `/init` com o agente para PROFILE + PLANNING.

Cada passo executado = uma nota aqui (funcionou / pergunta ruim / faltou X);
as notas viram a spec final da Fase 1.

## Riscos e armadilhas

- **OAuth sem navegador** (SSH/máquina remota): manter o fluxo manual do
  `google_auth.py` como fallback impresso (URL + colar código).
- **Token GitHub com escopo errado**: ping live no passo, não só "existe".
- **Cobertura de superfícies**: subcomando novo SEM painel/TUI falha CI —
  decidir justificação ou incluir.
- **Concorrência com `/init`**: wizard configura estrutura ANTES da entrevista;
  se o dono rodar `/init` primeiro, o wizard não deve re-perguntar o que existe.
- **Nightly sem runner**: agendar sem `[runner]` gera noturno pela metade — o
  passo 4 adverte e aponta o passo 12.
- **Serve**: mudança de allowlist exige restart do processo (poço conhecido).
- **Memória `full` é egress**: texto do vault (reuniões, Slack, documentos) vai
  à API do LLM — gate de política inegociável, exceção na AGENTS.md, teto de
  gasto no doctor. O wizard nunca grava `full` sem o "ok" literal.
- **Container Hindsight ≠ versão pinada** (emenda R5 do plano da memória): a
  validação do modo `full` confere a versão real em execução (ideal: pin por
  digest) e a flag do `dry-run-extract` antes de prometer as operações.
- **Demo vs real**: NUNCA auto-arquivar vault; passo 0 sempre confirma.

## Critérios de aceite

- **Fase 0:** máquina real (doctor limpo), roteiro 100% executado sem comando
  errado, notas de ajuste escritas, dono aprova a spec.
- **Fase 1:** máquina nova do zero → `./brain setup` interativo termina com o
  mesmo estado do mockup; `--only` e `--yes` funcionam; segredo nunca em
  tela/log; memória `embed` configurável e `full` corretamente bloqueado (ou
  oferecido com gate) conforme o código suporte; testes verdes (inclusive
  cobertura de superfícies).
- **Fase 2:** todo passo do motor navegável na TUI, mesmo apply, zero lógica
  duplicada (só casca).
- **Fase 3:** checklist no painel bate com o doctor da CLI; formulário só com
  serve no ar.
- **Fase 4:** quickstart de 5 min verdadeiro; guias antigos apontam pro wizard
  sem perder o detalhe de referência.

## Decisões do dono (revisar ao ler — não re-litigar depois)

1. Wizard = estrutura/config; entrevista `/init` continua dona do conteúdo. ✓?
2. Ordem de superfícies: CLI → TUI → painel (estático primeiro, formulário só
   com serve). ✓?
3. `google_auth.py` absorvido como função no motor (script permanece de
   fallback). ✓?
4. Fase 0 nesta máquina = instância REAL (demo arquivado), não vault paralelo. ✓?
5. Nome do comando: `./brain setup`. ✓?
6. Memória em três modos no wizard — `none` · `embed` (chunks, RAW + MEM, zero
   chave, nada sai) · `full` (chave de API, extração + mental models) — com
   `full` tratado como porta de saída de dados: "ok" explícito, exceção na
   AGENTS.md, teto de gasto, e feature-detect até o plano da memória aterrissar. ✓
   → **Ruled pelas decisões 2–3 do plano da memória** (ab9fdfd): gate = chave do
   dono + nada público (registro na AGENTS.md, sem política corporativa) e
   medidor mensal SEM teto. Fase 1 (CLI) aterrissada no commit bc11a9e.
