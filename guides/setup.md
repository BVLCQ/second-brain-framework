# setup.md — o wizard `brain setup`

O setup assistido configura a **estrutura** da instância (config, memória, TUI,
portas). A **vida** (PROFILE, goals, pessoas) continua da entrevista `/init` com o
seu agente — o wizard termina oferecendo-a.

## Três caminhos de instalar

| Caminho | Como | Para quem |
|---|---|---|
| `install.sh` | `curl -fsSL …/install.sh \| sh -` (ou `sh install.sh` no clone) | máquina nova, 30 segundos até o wizard |
| `./brain setup` | wizard interativo, no terminal | o dono, sempre re-executável |
| IA assistida | `./brain setup --yes --only …` + `./brain doctor` em loop (receita completa: `setup.md` na raiz) | agente conduzindo; o doctor é a régua |

Os três terminam no mesmo lugar: `./brain doctor` verde (no máximo ⚠ normais).

## Os passos (idempotentes — status derivado, nada de arquivo novo)

| # | id | O que faz | Validação |
|---|---|---|---|
| 0 | instancia | semeia vault + config (demo detectado → arquiva e nasce de novo, com confirmação) | zonas + doctor |
| 1 | identidade | dono no ledger (`person.added`) | `brain.person` no state |
| 2 | rotina | fuso + expediente + almoço (`[work]`) | parse |
| 3 | comando | **`brain` no PATH** (symlink `~/.local/bin/brain` → repo) | `which brain` resolve |
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
- **`embed`** — dois bancos de chunks, **zero LLM, zero chave, nada sai da máquina**.
  O wizard sobe o Hindsight pelo compose (OrbStack), avisa se o LM Studio/bge-m3 não
  está no ar, cria os bancos e roda um sync de validação (`--limit 3`).
- **`full`** — banco único com extração de fatos: **porta de saída de dados**. Exige o
  **"ok" literal** ("texto do vault vai à API de LLM com a sua chave"), a chave no
  `.env` (mascarada, 0600), o compose com `--env-file config/.env`, e o `health/llm`
  verde antes de confiar. Medidor mensal: `brain memory cost` (sem teto — decisão do
  dono). Voltar ao embed é primeira classe: `brain memory setup --mode embed` + rebuild.

Detalhes por modo: `guides/memory.md`. Plano: `guides/plans/memory-setups.md`.

## Régua e conserto

`./brain doctor` valida a instalação inteira: comando no PATH, TUI, chave do modo full,
gasto do mês (informação, não alarme), além dos checks de sempre. Agente resolvendo
issues: muda → `doctor` → repita até ✓.
