# setup — instalar/configurar uma instância do cérebro

**Gatilho:** o dono pede para instalar, configurar, "setar o brain", ligar a memória,
colocar a TUI para funcionar, ou trocar de máquina. Também vale quando o `doctor`
acusa `comando`/`tui`/`memória` pendentes.

## O que existe

- **`./brain setup`** — wizard interativo e idempotente (tabela de passos, re-executável,
  `--only <ids>` re-visita). Passos: instancia, identidade, rotina, comando (`brain` no
  PATH), foco, noturno, TUI, **memória (none/embed/full)**, portas, fontes, runner, fechamento.
- **`./brain setup --yes [--only ids] [--mode none|embed|full]`** — não-interativo com
  defaults: é o caminho do AGENTE. Nunca grave segredo nem aceite o gate do full por conta
  própria — segredo vai no `config/.env` (diga ao dono para colar lá), e o modo `full`
  exige o "ok" literal do dono no terminal dele.
- **`./brain doctor`** — a régua: valide a instalação com ele depois de qualquer mudança
  (comando no PATH, TUI, chave do full, gasto do mês). Um agente resolve issues em loop:
  muda → `doctor` → até virar ✓.
- **`install.sh`** (raiz do repo) — bootstrap do clone ao wizard (`curl … | sh -`).
- **`setup.md`** (raiz) — receita executável completa de máquina nova para agentes
  (mise/uv, LM Studio, Hindsight). Use-a quando faltar dependência de sistema; feche
  com `./brain setup`.

## Regras

1. O wizard é do DONO: ele roda `./brain setup` no terminal dele quando há perguntas.
   O agente usa `--yes`/`--only` para passos mecânicos e valida com `doctor`.
2. Segredo nunca passa pelo chat: `config/.env` (0600). O wizard e o `.env.example`
   documentam as chaves (GOOGLE_*, GITHUB_TOKEN, HINDSIGHT_API_*).
3. Memória: `embed` = zero LLM, zero chave, nada sai da máquina. `full` = porta de
   saída de dados (chave do dono, `cloud_llm = true`) — o wizard exige o "ok" literal
   e o CLI recusa `extract` sem `cloud_llm`. Guia: `guides/memory.md`.
4. Pré-requisitos externos (OrbStack, LM Studio) o wizard apenas detecta e orienta —
   instalar app é com o dono (`setup.md` seção 3–4).
5. Noturno (`BRAIN_NIGHTLY=1`) nunca roda setup — decisão do dono, presente.

## Fechamento padrão

Rode `./brain doctor`, mostre o resultado e aponte o próximo passo humano: a entrevista
`/init` (PROFILE + PLANNING) — o wizard configura a estrutura, a vida entra depois.
