# setup.md — o wizard `brain setup`

O setup assistido configura a **estrutura** da instância (config, memória, TUI,
portas). A **vida** (PROFILE, goals, pessoas) continua da entrevista `/init` com o
seu agente — o wizard termina oferecendo-a.

> **2.30:** o wizard do navegador agora mora NO PRÓPRIO painel — primeira vez,
> "reconfigurar" e a rota `/onboarding` (atalho para `/#onboarding`) abrem o modo
> wizard da mesma página, e "Abrir meu Brain" volta às faces sem recarregar.
> Esta nota continua valendo para o wizard de TERMINAL abaixo.

> **2.23:** o wizard do navegador (`/onboarding`) e este daqui renderizam o MESMO
> registro de passos (`setup.WEB_STEPS`) — mesmos ids, mesmos títulos. O do navegador
> cobre também identidade/perfil, agente, conectores+fontes, memória completa e
> "A máquina" (noturno · comando · TUI · foco · framework · atalho de um clique —
> ícone no Dock no macOS, atalho na área de trabalho no Linux/WSLg), com cada ação como job
> visível. A entrada sem terminal é o `Abrir o Brain.command` na raiz do repo.

## Três caminhos de instalar

| Caminho | Como | Para quem |
|---|---|---|
| `install.sh` | `curl -fsSL …/install.sh \| sh -` (ou `sh install.sh` no clone) | máquina nova — instala o que faltar (git · Homebrew · mise · Python · contêiner) e abre o wizard |
| `./brain setup` | wizard interativo, no terminal | o dono, sempre re-executável |
| IA assistida | `./brain setup --yes --only …` + `./brain doctor` em loop (receita completa: `setup.md` na raiz) | agente conduzindo; o doctor é a régua |

Os três terminam no mesmo lugar: `./brain doctor` verde (no máximo ⚠ normais).

## Os passos (idempotentes — status derivado, nada de arquivo novo)

| # | id | O que faz | Validação |
|---|---|---|---|
| 0 | instancia | **pergunta seu nome** (o id é gerado dele; padrão = nome da conta do Mac), semeia vault + config (demo detectado → arquiva e nasce de novo, com confirmação) | zonas + doctor |
| 1 | identidade | dono no ledger (`person.added`); só pergunta se o `init` rodou sem nome | `brain.person` no state |
| 2 | rotina | fuso + expediente (`[work]`; o almoço ficou como tunável fino do config, sem pergunta) | parse |
| 3 | comando | **`brain` no PATH** (symlink `~/.local/bin/brain` → repo) | `which brain` resolve |
| 3b | painel | **ícone do painel** (`brain app install`; interativo pergunta, `--yes` cria — como o passo `comando`) | app/entrada existe |
| 4 | foco | `ics` (default, zero config) ou `google` com OAuth inline (loopback; token gravado no `.env`, nunca impresso) | chaves no `.env` |
| 5 | noturno | `schedule install --time` | `schedule status` |
| 6 | tui | cria `.venv-tui` (hashes travados) | venv existe |
| 7 | memoria | **modo none · embed · full** (§ abaixo) | por modo |
| 8 | portas | backup / feedback (token pingado) / outbox / publish — OFF por padrão | ping/formato |
| 9 | fontes | aponta `brain watch add` (conector liga no agente, não aqui) | — |
| 10 | runner | `[runner].agent` | — |
| 11 | fechamento | render + doctor + convite ao `/init` | doctor |

`--only id1,id2` re-visita passos prontos; `--yes` roda defaults sem perguntar.

## O passo memória (three modes)

- **`none`** — sem Hindsight; `/ask` usa índice → artefato → RAW.
- **`embed`** — banco único de chunks (`brain`), **zero LLM, zero chave, nada sai da
  máquina**. O wizard sobe o Hindsight pelo compose (OrbStack), avisa se o LM Studio/bge-m3
  não está no ar, cria o banco e roda um sync de validação (`--limit 3`).
- **`full`** — banco único com extração de fatos: **porta de saída de dados**. Exige o
  **"ok" literal** ("texto do vault vai à API de LLM com a sua chave"), a chave no
  `.env` (mascarada, 0600), o compose com `--env-file config/.env`, e o `health/llm`
  verde antes de confiar. Medidor mensal: `brain memory cost` (sem teto — decisão do
  dono). Voltar ao embed é primeira classe: `brain memory setup --mode embed` + rebuild.
- **Agentes de código** — o cérebro **não gerencia memória de agente** (decisão de
  2026-11-18): registra só o canal de leitura — `brain harness connect <agente>` (MCP
  somente-leitura; no Claude Code também o hook de recall). Memória do agente é
  configurada por ele mesmo (receita: `guides/memory.md`).

Detalhes por modo: `guides/memory.md`.

## Régua e conserto

`./brain doctor` valida a instalação inteira: comando no PATH, TUI, chave do modo full,
gasto do mês (informação, não alarme), além dos checks de sempre. Agente resolvendo
issues: muda → `doctor` → repita até ✓.
