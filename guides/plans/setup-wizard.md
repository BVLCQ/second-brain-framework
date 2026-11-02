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
| 11 | Memória | `none` **ou** `hindsight` (URL) | `[memory]` + `memory setup` (bancos) | `memory status` |
| 12 | Runner/agente | auto/claude/cursor/agy/… · modelo · allow de leitura | `[runner]` | rodada ⚡ ou noturno seco |
| 13 | Fechamento | render + painel · doctor · oferecer `/init` | — | doctor filtrado |

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
11. **Memória** — se o servidor Hindsight estiver de pé: `[memory] engine =
    "hindsight"` → `./brain memory setup` (cria os bancos) → `./brain memory
    status`. Senão fica `none` — tudo funciona sem.
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
- **Demo vs real**: NUNCA auto-arquivar vault; passo 0 sempre confirma.

## Critérios de aceite

- **Fase 0:** máquina real (doctor limpo), roteiro 100% executado sem comando
  errado, notas de ajuste escritas, dono aprova a spec.
- **Fase 1:** máquina nova do zero → `./brain setup` interativo termina com o
  mesmo estado do mockup; `--only` e `--yes` funcionam; segredo nunca em
  tela/log; testes verdes (inclusive cobertura de superfícies).
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
