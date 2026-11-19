# Plano — Bootstrap do instalador: uma ação, a máquina inteira pronta

> Consolidation note: herda de `guides/plans/platform-support.md` (Fase 2,
> mensagens WSL no instalador) e não reabre decisões dele. A onda
> `onboarding-unification.md` já entregou as portas (F7: `.command`); este
> plano fecha o buraco que resta **dentro** do `install.sh`.

Executor: agente de código da instância. Regime: suite verde
(`python3 -m unittest discover -s tests`), **um commit local por passo**, nada
do dono no repo, `./brain upstream scan` antes de propor o push.

## 1. O problema — o instalador verifica e desiste

- `install.sh` hoje confere git/Python/mise e, se falta algo, **imprime a
  receita manual e sai com erro**. No Mac de fábrica (sem brew, sem CLT, só
  `/usr/bin/python3` 3.9), o duplo clique no `Abrir o Brain.command` termina
  em parede de texto — o oposto de "uma ação".
- O README listava como "requisitos que o instalador ainda não resolve
  sozinho": **git**, **Python 3.11+** e **Claude Code**. Os dois primeiros
  eram bootstrap faltando; o terceiro estava desatualizado — o produto é
  agnóstico desde a 2.27.0 (4 agentes + card Outros harnesses).
- As três portas (`curl | sh` · `.command` · `./brain setup`) são uma espinha
  só; logo o bootstrap morre **uma vez**, no `install.sh`, e todas herdam.

## 2. Princípios

1. **Uma espinha.** O bootstrap é um estágio novo DO `install.sh`. O wizard
   não instala dependências de sistema (ele precisa de Python rodando —
   galinha e ovo); o `.command` e o `curl | sh` são lanços da mesma espinha.
2. **Silencioso nas perguntas NOSSAS; idempotente.** O script não pergunta
   nada: verifica e instala só o que falta (ruling D1). Segunda rodada é
   no-op. As portas que não são nossas — senha sudo da sessão e a janela da
   Apple do CLT (pré-requisito transitivo do Homebrew) — não podem ser
   silenciadas: espera honesta com timeout e, ao falhar, a receita manual
   (`setup.md` §0–§1).
3. **Escopo fechado: git · mise · Python 3.12 · Docker/OrbStack** (ruling
   D3). O instalador entrega o Brain executável + app + wizard aberto, mais o
   runtime de contêiner que a memória consome: **OrbStack** no macOS,
   **Docker Engine** no Linux/WSL2. Hindsight e LM Studio são **config de
   memória** — moram no wizard (`setup --only memoria`), não no instalador:
   são escolhas, não pré-requisitos.
4. **doctor é a régua.** Ganha as checagens de git · python (versão e
   origem: mise vs sistema) · mise · docker — warn contextual, nunca error
   (a saída do doctor gates o modal da TUI).
5. **Falha parcial é honesta.** Contêiner ausente não impede o Brain (memória
   é opcional): avisa e segue. Sem Python, para com a receita manual.

## 3. Fases

### F1 — Bootstrap macOS (o caminho do clique único)

Ordem dentro do `install.sh`, antes dos guards atuais:

1. **CLT (Command Line Tools)**: pré-requisito do Homebrew — a janela da
   Apple aparece uma vez; o script espera com timeout (~10 min). Não há como
   silenciar a Apple.
2. **Homebrew**: ausente → instalador oficial com `NONINTERACTIVE=1`
   (silencioso; a senha sudo da sessão permanece) + `brew shellenv` no PATH
   da sessão.
3. **git**: `brew install git` (ruling D2 — binário do brew, sempre
   atualizável com `brew upgrade`; o `/usr/bin/git` do CLT fica de reserva).
4. **mise**: `brew install mise`.
5. **Python**: `mise trust` + `mise install` na raiz — o pin **3.12 vem do
   `mise.toml`**, nunca hardcoded. O guard de re-exec do próprio `./brain`
   faz o resto.
6. **OrbStack**: `brew install --cask orbstack` + primeiro lançamento
   (`open -a OrbStack`), que completa o comando `docker` na CLI. Falha aqui =
   aviso, não erro (ruling D3: memória é config).

- **Aceite:** conta macOS limpa (sem brew/CLT, python 3.9) → duplo clique no
  `.command` termina com o wizard aberto no navegador e `./brain doctor`
  verde (máx. ⚠ normais), cada passo impresso; segunda rodada no-op; `curl |
  sh` idem.
- **Rollback:** `git revert` do commit. Desinstalação manual documentada no
  fim do script (`brew uninstall git mise`, `brew uninstall --cask orbstack`,
  `brew uninstall` do próprio Homebrew; CLT permanece — inofensivo).

### F2 — Linux/WSL2

Mesmo estágio: git pelo gerenciador (ou já presente), **mise pelo instalador
oficial de curl** (sem brew), Python pelo `mise install`, **Docker Engine**
pelo instalador oficial `get.docker.com` (cobre apt/dnf) + `usermod -aG
docker` com aviso honesto de re-login. Espelha a Fase 2 do plano de
plataforma.
**Aceite:** container Ubuntu limpo → `curl | sh` termina no wizard.

### F3 — doctor, README, setup.md

- `doctor`: checa git · versão do python · mise · docker (warn contextual:
  modo de memória `nenhuma` + docker ausente = informativo; `embed`/`full` +
  ausente = warn com o comando). O docker-probe de memória já existe — o que
  falta é a checagem de máquina.
- README: some a lista de "requisitos não resolvidos" (o instalador resolve);
  **Claude Code fora** — o Brain é agnóstico (ruling D4), o passo "Seu
  agente" do wizard conecta o canal de leitura de quem existir.
- `setup.md` §0–§1 passa a ser O fallback manual que o script imprime ao
  falhar (uma receita, dois usos) — com nota de que o `install.sh` faz isto
  sozinho.

### F4 — Aceite de ponta a ponta

O teste de instalação limpa já pendente (clone scratch + wizard inteiro,
guardando superfícies globais: symlink `brain`, launchd, ponteiro do
Brain.app, registros MCP) vira o procedimento de aceite datado deste plano.

## 4. Riscos e armadilhas

- **A janela do CLT e a senha sudo são assíncronas e da Apple/do sistema** —
  esperar com timeout e falhar honesto, nunca fingir sucesso. O "silêncio"
  do ruling D1 é sobre as NOSSAS perguntas.
- **OrbStack completa a CLI `docker` no primeiro lançamento** — se o usuário
  nunca abrir, o doctor avisa; o wizard de memória aponta o caminho.
- **Grupo docker no Linux pede re-login** — avisar, não fingir pronto.
- **Suite não prova instalação real**: os testes cobrem os guards do doctor e
  as mensagens (padrão `skipUnless(shutil.which(...))` para binários); o
  aceite real é o F4, manual e datado.
- **Homebrew novo não edita o perfil do shell do usuário** — o script exporta
  o `shellenv` na própria sessão e o doctor avisa se o mise não estiver no
  PATH do usuário depois.

## 5. Decisões do dono (perguntas originais — respostas registradas abaixo)

Registradas em 2026-11-20:

1. **Homebrew ausente → instalar silenciosamente** (instalador oficial,
   `NONINTERACTIVE=1`), sem prompt nosso. ✓
2. **git no macOS → brew git** (binário do Homebrew, sempre atualizável). O
   CLT segue como pré-requisito transitório do próprio Homebrew — a janela da
   Apple pode aparecer uma vez; nada de pergunta nossa. ✓
3. **Escopo → git + mise + Python 3.12 + Docker/OrbStack** (OrbStack no
   macOS, Docker Engine no Linux/WSL2). Hindsight e LM Studio são **config de
   memória** (wizard), não instalação. ✓
4. **README → Claude Code fora dos requisitos.** O Brain é agnóstico. ✓
