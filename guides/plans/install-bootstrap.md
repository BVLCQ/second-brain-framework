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
  receita manual e sai com erro** (linhas 37–46). No Mac de fábrica (sem brew,
  sem CLT, só `/usr/bin/python3` 3.9), o duplo clique no `Abrir o
  Brain.command` termina em parede de texto — o oposto de "uma ação".
- O README lista como "requisitos que o instalador ainda não resolve
  sozinho": **git**, **Python 3.11+** e **Claude Code**. Os dois primeiros são
  bootstrap faltando; o terceiro está desatualizado — o produto é
  agnóstico desde a 2.27.0 (4 agentes + card Outros harnesses).
- As três portas (`curl | sh` · `.command` · `./brain setup`) são uma espinha
  só; logo o bootstrap morre **uma vez**, no `install.sh`, e todas herdam.

## 2. Princípios

1. **Uma espinha.** O bootstrap é um estágio novo DO `install.sh`. O wizard
   não instala dependências de sistema (ele precisa de Python rodando —
   galinha e ovo); o `.command` e o `curl | sh` são lanços da mesma espinha.
2. **Verificar → instalar só o que falta → reexecutar a si mesmo.** Cada
   etapa anuncia o que vai fazer ANTES de fazer. Idempotente: a segunda
   rodada é no-op.
3. **Escopo fechado: git · mise · Python.** O instalador entrega o Brain
   executável + app + wizard aberto. Memory stack (LM Studio, Hindsight)
   continua no wizard e no `setup.md` — são escolhas, não pré-requisitos.
4. **Portas do SO são do dono.** Dialog da Apple (CLT) e senha do brew nunca
   são simuladas nem contornadas: o script espera com timeout e, ao falhar,
   imprime a receita manual equivalente (que é o `setup.md` §0–§1).
5. **doctor é a régua.** Ganha as checagens de git · python (versão e origem:
   mise vs sistema) · mise, para a porta IA-assistida fechar o loop.

## 3. Fases

### F1 — Bootstrap macOS (o caminho do clique único)

Ordem dentro do `install.sh`, antes dos guards atuais:

1. **git**: sem CLT (`xcode-select -p` falha) → `xcode-select --install`
   (dialog da Apple) e espera com timeout; sem GUI (ssh) → cai no git do brew
   (decisão D2).
2. **Homebrew**: ausente → instalador oficial (decisão D1 define sozinho-com-aviso
   vs ensinar-e-exigir).
3. **mise**: `brew install mise` (Linux: installer oficial por curl).
4. **Python**: `mise trust` + `mise install` na raiz — o pin **3.12 vem do
   `mise.toml`**, nunca hardcoded no script.
5. **Re-exec**: o script reexecuta a si mesmo; os guards que já existem
   validam o resultado (mesma máquina, agora pronta).

- **Aceite:** conta macOS limpa (sem brew/CLT, python 3.9) → duplo clique no
  `.command` termina com o wizard aberto no navegador e `./brain doctor`
  verde (máx. ⚠ normais), cada passo impresso; segunda rodada no-op; `curl |
  sh` idem.
- **Rollback:** `git revert` do commit. Desinstalação manual documentada no
  fim do script (`brew uninstall mise` etc.; CLT permanece — inofensivo).

### F2 — Linux/WSL2

Mesmo estágio com detecção de gerenciador (apt/dnf): git e mise pelo pacote,
Python pelo mise. Espelha a Fase 2 do plano de plataforma.
**Aceite:** container Ubuntu limpo → `curl | sh` termina no wizard.

### F3 — doctor, README, setup.md

- `doctor`: checa git, versão do python e origem (mise vs sistema), mise.
- README: some a lista de "requisitos não resolvidos" (fica só o que é
  decisão: agente de IA, se quiser); derruba Claude Code como requisito.
- `setup.md` §0–§1 passa a ser O fallback manual que o script imprime ao
  falhar (uma receita, dois usos).

### F4 — Aceite de ponta a ponta

O teste de instalação limpa já pendente (clone scratch + wizard inteiro,
guardando superfícies globais: symlink `brain`, launchd, ponteiro do
Brain.app, registros MCP) vira o procedimento de aceite datado deste plano.

## 4. Riscos e armadilhas

- **Dialog da Apple e senha sudo** são assíncronas: esperar com timeout e
  falhar honesto, nunca fingir sucesso.
- **Instalar Homebrew em máquina de estranho é invasivo** — announce antes,
  com caminho de saída (D1).
- **Suite não prova instalação real**: os testes cobrem os guards e as
  mensagens (padrão `skipUnless(shutil.which(...))` para binários); o aceite
  real é o F4, manual e datado.
- **Re-exec infinito**: o re-exec é UMA vez, com flag de guarda (`_BRAIN_BOOTSTRAPPED`).

## 5. Decisões do dono (não re-litigar)

1. **Homebrew ausente:** (a) instalar sozinho com aviso e Enter [recomendo —
   é o que completa o "clique uma vez"] ou (b) exigir e ensinar (menos
   invasivo, quebra a promessa). ✓?
2. **git no macOS:** (a) CLT pela dialog da Apple [recomendo — canônico,
   cobre `git` e build tools] ou (b) git do brew (silencioso, duplica o que a
   Apple fornece). ✓?
3. **Escopo:** instalador entrega git+mise+Python 3.12 e PARA; memory stack
   fica no wizard — confirmar. ✓?
4. **README:** derrubar Claude Code da lista de requisitos (agnóstico desde
   2.27.0)? ✓?
