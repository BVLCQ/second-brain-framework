# Plano — Suporte de plataformas: macOS + Linux nativos, Windows via WSL2

Executor: agente de código da instância. Regime: suite verde (`python3 -m unittest
discover -s tests`, ~7–8 min, rodar em background com log), **um commit local por
passo verde**, nada do dono no repo, `./brain upstream scan` antes de propor o push.
Commits deste plano: `git add` explícito dos arquivos listados em cada passo — sessão
irmã pode ter WIP na árvore; nunca `git add -A`.

## Problema

O Brain nasceu no macOS e o código de borda confirma. O núcleo (~27 mil linhas em
`brainlib`+`commands`) é stdlib e neutro de plataforma; a consciência de SO mora em 7
arquivos de borda (~1,4 mil linhas), e o CI já roda a suíte inteira verde em
`ubuntu-latest` — Linux é suportado **de fato**, mas não **de primeira classe** (docs,
doctor e instalação não contam a história). Windows não tem história nenhuma.

A porta nativa do Windows (adaptador `schtasks`, atalho `.lnk`, `install.ps1`, UTF-8
no console) foi avaliada e **descartada** (5–10 dias de trabalho + um terceiro SO
sempre verde no CI) porque Docker Desktop no Windows já *é* WSL2: o usuário Windows
que instala Docker já instalou uma VM Linux. Linux direto no WSL2 dá a ele o mesmo
ambiente **sem** a borda de container na frente dos pontos que mais importam — o
agente do host chamando `./brain` (caminho de escrita da constituição), navegador,
editor, cron. A imagem Docker tem um nicho legítimo (appliance sempre ligado) e vira
plano separado, não shim de compatibilidade.

## Princípios

1. **Plataforma-honrado, não plataforma-invisível.** Toda capacidade tem três estados
   possíveis: funciona · degrada com dica acionável · ausente e reportado pelo doctor.
   O modelo já existe no código (`pdftotext` → Swift/PDFKit → `pypdf`;
   `swift_tool()` devolve `None` fora do mac; `fcntl = None` guard em `core.py`).
2. **WSL2 é Linux.** Zero código nativo Windows. A única consciência de Windows no
   código é detectar WSL *dentro* do Linux (para `wslview` e dicas do doctor).
3. **Uma costura por capacidade.** Código que sabe de SO só nos módulos de borda:
   `opener.py`, `launcher.py`, `runner.py`, `swift.py`, `pdf.py`, `video.py`,
   `util.py` (abas/osascript), `setup.py` (probe do LM Studio) e `doctor.py`
   (reporte). Núcleo nunca cita `sys.platform`. Enforçado por teste, não por
   disciplina.
4. **Sem novas dependências.** stdlib; `wslview` vem do pacote `wslu` do usuário —
   detectado e recomendado, nunca exigido em código.
5. **Falha amigável no Windows nativo.** Um guard no entry avisa "use WSL2" com o
   link do guia — em vez do traceback de `fcntl` (`index.py:14` importa sem guarda).
6. **Swift é acelerador do macOS, nunca corretude.** Nada depende dele para estar
   certo; sempre há cadeia de fallback genérica (modelo de `pdf.py`).

## Mapa — o que existe × o que falta

| Área | macOS | Linux | WSL2 | Falta |
|---|---|---|---|---|
| Núcleo (ledger, dump, render, portas, MCP) | ✓ | ✓ (CI verde) | ✓ (é Linux) | — |
| TUI (Textual) | ✓ `.venv-tui` | ✓ | ✓ Windows Terminal | dica `python3-venv` no Ubuntu |
| Agendamento noturno | launchd | cron (já codado) | cron c/ systemd | dica `/etc/wsl.conf` |
| Abrir URL/arquivo | `open`+osascript | `xdg-open` | — | **branch `wslview`** (Fase 1) |
| Ícone do painel | `.app` | `.desktop` | WSLg → Start Menu? | **smoke** (Fase 0) |
| Probe LM Studio | `localhost:1234` | idem | quebra (host Windows) | **ler URL configurada** (Fase 1) |
| Docker/Hindsight | ✓ compose | ✓ | ✓ Docker Desktop | — |
| LM Studio (app do host) | localhost funciona | — | roteamento WSL2→host | **guia + doctor** (Fase 2) |
| Transcrição/quadros on-device | Swift ✓ | ✗ whisper.cpp (dica) | ✗ | fora de escopo (D2) |
| OAuth Google | browser+localhost | idem | callback Windows→WSL2 funciona de fábrica | smoke (Fase 0) |
| Instalador | `install.sh` ✓ | `install.sh` ✓ | idem + dicas | mensagens WSL (Fase 2) |

## Fases

### Fase 0 — CI de duas plataformas + smoke WSL2 (sem código de produto)

1. `ci.yml`: matrix ganha `os: [ubuntu-latest, macos-latest]` (× python 3.11–3.14).
   O runner macos protege os ramos darwin (launcher/plist, skips de swiftc/osacompile
   já existem nos testes). Repo público = custo zero, jobs paralelos.
2. Checklist de smoke numa WSL2 limpa (Ubuntu 24.04, Windows 11) — ver **Risco 1**
   sobre hardware. Itens e resultado esperado:
   - `sh install.sh` → init + `app install` ✓
   - `./brain open --setup` → **espera-se falha** sem `wslview` (registra; valida a
     Fase 1)
   - `brain app install` → `.desktop` em `~/.local/share/applications`; **pergunta
     central: o ícone aparece no Start Menu do Windows (WSLg)?** registrar
   - wizard com OAuth do Google → callback `localhost:PORT` (Windows→WSL2 é
     encaminhado por padrão) ✓ esperado
   - `./brain tui --setup` → pode faltar `python3-venv` (valida dica da Fase 2)
   - `./brain schedule install` → cron com systemd habilitado ✓ esperado
   - LM Studio no lado Windows + modo embed → **espera-se probe falhar** (valida a
     Fase 1); testar também rede espelhada (`networkingMode=mirrored` no
     `.wslconfig`) e "serve on local network" + IP do host
   - `./brain repos pull`, snapshot MCP, `render --open` pós-`wslview`

   **Critérios:** CI verde nas duas runs; checklist preenchido com resultados reais
   (incluindo os "falhou como previsto").
   **Rollback:** reverter o commit do `ci.yml`.
   **Commit:** `git add .github/workflows/ci.yml` + o checklist preenchido anexado a
   este plano (subseção "Resultado do smoke").

### Fase 1 — Costuras de código (Linux puro + WSL)

Cada item = um commit com testes.

1. **`opener.py` + `util.open_url`: branch WSL.** Detecção: `/proc/version` contém
   `microsoft` OU `$WSL_DISTRO_NAME` definido (função `util.on_wsl()`). URL e arquivo
   sem app mapeado → `wslview` quando presente, `xdg-open` senão. App mapeado em
   `[tui.open]` segue sendo comando Linux; sem comando correspondente no WSL, cai no
   `wslview` + nota. Testes: `argv_for(..., platform=...)` já é paramétrico —
   acrescentar casos WSL; detecção com env/`/proc` fake.
2. **`setup.py lmstudio_up()`: probe na URL configurada.** Hoje hardcode
   `http://localhost:1234` (`setup.py:206`); passa a ler a `base_url` do slot de
   embeddings (fallback localhost:1234 quando vazio) — virar util reutilizável, o
   doctor usa a mesma.
3. **`doctor.checks()`: linhas de capacidade por SO.** poppler (`pdftotext`/
   `pdftoppm`), `wslview` (só em WSL, dica `apt install wslu`), LM Studio (URL
   configurada), agendador (launchd · cron · WSL sem systemd → dica `/etc/wsl.conf`),
   aviso se `inst.root` estiver sob `/mnt/` (performance 9p). Cada linha ✓/⚠ com
   dica acionável — nunca erro que bloqueie.
4. **Guard win32 no entry.** Antes de qualquer import que possa tocar `fcntl`
   (`index.py:14` sem guarda): `BrainError` clara — "Windows nativo não é suportado;
   use WSL2 (guides/wsl2.md)" — código de saída fixo. Teste: função pura + caminho do
   cli com mock.
5. **Teste de costura (novo `tests/test_platform_seams.py`).** Lista abençoada de
   arquivos que podem citar `sys.platform`, `fcntl`, `start_new_session`,
   `launchctl`, `osascript`, `xdg-open`, `wslview`, `crontab`; qualquer outro arquivo
   do `brainlib` que citar → falha (modelo: `CoverageTest` com conjunto justificado).

   **Critérios:** suite verde em ubuntu e macos CI; `grep` de `start_new_session`/
   `fcntl` só nos abençoados; doctor no Mac do dono inalterado exceto linhas novas.
   **Rollback:** itens são commits independentes — reverter individualmente.

### Fase 2 — Instalação e documentação de primeira classe

1. **`install.sh`: mensagens WSL.** Detectar WSL (`uname -r` contém `microsoft`):
   dicas `python3-venv` + cron/systemd + apontar `guides/wsl2.md`. Continua POSIX sh.
2. **`guides/wsl2.md` (novo, PT-BR):** instalação passo a passo no WSL2; **vault em
   ext4, nunca `/mnt/c`** (9p lento); Windows Terminal; LM Studio no host Windows —
   rede espelhada (Win11) OU "serve on local network" + `base_url` do embed apontando
   pro host; Start Menu via WSLg (conforme resultado do smoke; fallback se D4);
   mapeamento `[tui.open]` por comando (ex.: `cursor`); teardown: `brain app
   uninstall` + `wsl --unregister <distro>`.
3. **Tiers nas docs:** README, `setup.md`, `guides/user-guide.md`,
   `guides/commands.md` — tabela: macOS tudo · Linux/WSL2 tudo exceto
   transcrição/quadros on-device (dica whisper.cpp).
4. **Ritual de release:** bump `brainlib/__init__.py` `__version__` + seção no
   `CHANGELOG.md` (é o que o `brain update` imprime).

   **Critérios:** guia seguido ponta a ponta numa WSL2 limpa chega ao painel aberto no
   navegador Windows com noturno agendado; `./brain upstream scan` limpo.
   **Rollback:** docs e `install.sh` revertem por commit.

### Fase 3 — Fora do escopo (planos separados, exigem decisão do dono)

- **Transcrição whisper.cpp** (paridade Linux/WSL2 do `video.py`).
- **Imagem Docker "appliance sempre ligado"** (NAS/VPS: nightly + serve + MCP +
  Hindsight empacotados; agendador interno sleep-loop). Justificada como produto
  próprio, não como shim de Windows.

## Riscos e armadilhas

1. **Não há máquina Windows no parque do dono** (só Macs). Fases 0 e 2 dependem de
   hardware externo — colaborador, comunidade do repo público (issue "testers
   wanted" pós-push) ou máquina emprestada. Sem isso, WSL2 fica "documentado com
   melhor-esforço" e o smoke fica pendente com a limitação dita em voz alta.
2. **WSLg → Start Menu: alta confiança, não verificado daqui.** É exatamente para
   isso que existe a Fase 0. Se falhar: fallback `.lnk` emitido de dentro do WSL
   chamando `powershell.exe` (interop) — continua sem codebase Windows (decisão D4).
3. **Rede WSL é assimétrica.** Windows→WSL2 (callback OAuth `localhost`) funciona de
   fábrica; WSL2→Windows (LM Studio) exige rede espelhada ou IP do host + LM Studio
   ouvindo além de 127.0.0.1. O guia cobre os dois caminhos; o doctor dá a dica.
   Detecção de host no NAT muda a cada boot — nunca gravar IP fixo em config; guia
   prefere modo espelhado.
4. **`python3-venv` ausente no Ubuntu mínimo** mata `tui --setup` no `ensurepip` —
   dica no `install.sh` (Fase 2) e no doctor (Fase 1.3).
5. **`/mnt/c` proibido para o vault** — performance 9p; doctor avisa (Fase 1.3).
6. **`notify-send` sob WSLg não tem daemon** — já é guardado por `command -v`;
   silêncio aceitável, `app.log` é o fallback. Nada a fazer.
7. **UTF-8:** `launcher.sh` já exporta `PYTHONIOENCODING=utf-8` e `LANG`;
   interativo é Windows Terminal (guia). Sem trabalho de código.
8. **Cron no WSL antigo sem systemd** (`/etc/wsl.conf`) — guia + doctor.
9. **Sessão irmã na árvore:** commits sempre com `git add` explícito; conferir
   `git status` antes de cada patch; nunca engolir WIP alheio.
10. **Suíte:** armadilhas de sempre (skill `second-brain-dev`): `BRAIN_NOW` vazando
    entre módulos, `PYTHONPATH` do gateway, rodar a suite em background com log.
11. **Scanner upstream:** nada do dono nos exemplos do guia WSL2 — dados fictícios da
    padaria (`marina-demo`), caminhos genéricos.

## Regras permanentes para desenvolvimentos futuros

1. Código novo que toca SO entra **só** nos módulos abençoados — o teste de costura
   (Fase 1.5) barra o resto. Mudou a lista? muda o teste no mesmo commit.
2. Toda capacidade nova plataforma-dependente nasce com os três estados
   (funciona · degrada com dica · doctor reporta) **no mesmo commit**.
3. Windows nativo segue OFF (D1): nenhum recurso ganha código win32; o guard do
   entry aponta pro guia WSL2.
4. CI nas duas runs (ubuntu+macos) é o guardião — nunca deixar a matrix regredir a
   uma só.
5. Swift acelerador, nunca corretude: fallback genérico sempre; novo uso de
   `swift_tool()` nasce com o caminho sem-mac definido.
6. Paridade CLI+TUI+painel continua valendo para qualquer flag nova (regra de casa).

## Decisões do dono (não re-litigar)

1. **Estratégia Windows = WSL2**, sem código nativo e sem Docker como shim; imagem
   appliance = plano separado opcional. ✓?
2. **Tier oficial:** Linux/WSL2 = tudo exceto transcrição/quadros on-device (Swift),
   com dica whisper.cpp na doc. ✓?
3. **CI ganha `macos-latest`** na matrix (protege ramos darwin; custo zero em repo
   público). ✓?
4. **Fallback `.lnk`** só se o smoke da Fase 0 mostrar que o WSLg não registra o
   `.desktop` no Start Menu (YAGNI até prova). ✓?
5. **Guard win32** com mensagem amigável apontando pro guia (em vez de traceback).
   ✓?
