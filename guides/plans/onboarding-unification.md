# Plano — Onboarding unificado: um cérebro, uma configuração

> **Estado: ENTREGUE (2.23.0 + 2.30.0).** F1–F7 aterrissaram na 2.23.0 (identidade
> visual, registro único `setup.WEB_STEPS`, "Seu agente", conectores, memória
> completa, jobs visíveis, `Abrir o Brain.command`); **F8 aterrissou na 2.30.0**
> (o wizard é um modo do painel: `/onboarding` vira atalho para `/#onboarding`,
> transição sem recarregar; a página própria segue no repo como rollback).
> Ressalva 2.25.0: o cérebro não gerencia memória de agentes — o que o F3
> conecta é só o canal de leitura (`brain harness connect`).

Executor: agente de código da instância. Regime: suite verde
(`python3 -m unittest discover -s tests`, TUI com o venv `.venv-tui` quando tocar nela),
**um commit local por passo**, assets do painel reconstruídos (`scripts/build_assets.py`)
em toda mudança de `assets/src/`, nada do dono no repo, `./brain upstream scan` antes de
propor o push.

Este plano **consolida** o `guides/plans/onboarding-in-settings.md` (2.17.0 entregou os
passos 3–5 dele: abas da face Configurações, Memória unificada, Visão geral e remoção do
atalho) e **herda** os dois passos pendentes — identidade visual (passo 1) e
`/onboarding` como modo de primeira vez do painel (passo 6) — com a direção visual
**decidida pelo dono em 2026-11-18** (seção 3.1 abaixo, que resolve a decisão 1 daquele
plano). Fecha também o rombo do `/init` (gatilho morto para quem onboardou no navegador)
e a entrada sem terminal.

---

## 1. O problema — quatro meios-onboardings

A mesma configuração está espalhada por quatro superfícies com vocabulários e alcances
diferentes. Nenhuma cobre o caminho inteiro:

| Preocupação | `install.sh` | Wizard navegador (`/onboarding`) | Wizard terminal (`brain setup`) | `/init` (skill) |
|---|---|---|---|---|
| clone, Python, vault, ícone | ✓ | — | `instancia` · `painel` | — |
| identidade + perfil | — | `Você` + `Sobre você` | `identidade` (só nome) | bloco 1 |
| rotina | — | `Sua rotina` | `rotina` | — |
| conectar apps | — | `Conectores` (só Claude) | `fontes` (só aponta) | bloco 4 |
| permissões do agente | — | `Permissões` (só `.claude/`) | — | — |
| memória | — | `Memória` (roteia o wizard) | `memoria` | — |
| chaves | — | `Integrações` (só GITHUB) | `portas` | — |
| goals/projetos | — | `Goals e projetos` (IA propõe) | — | bloco 2 |
| pessoas | — | — | — | bloco 3 |
| noturno, `brain` no PATH, foco, TUI, hook | — | **nada** | os cinco passos | — |

Consequências concretas:

1. **Quem instala pelo** `curl`**/ícone termina com o doctor amarelo** (sem noturno, sem

   comando, sem regra de fetch/hook) — o "app" parece inacabado.
2. **Quem termina o wizard do navegador nunca recebe a entrevista do** `/init`: o gatilho

   dele ("PROFILE e PLANNING vazios") fica falso, e os blocos 3 (pessoas) e 4 (fontes)
    ficam sem dono.
3. **Conectores e permissões são Claude-shaped** (`claude mcp list`,

   `.claude/settings.local.json`) numa framework agnóstica (Hermes, Cursor, Codex,
    agy, gemini). Sem Claude Code, o passo vira beco sem saída com dica em prosa.
4. **Dois vocabulários** para o mesmo estado (`lite`×`embed` — resolvido na 2.17.0 a

   favor de `embed`; `Integrações`×`portas`) e **duas listas de passos** que divergem
    (navegador sem os passos de máquina; terminal sem os passos de vida).
5. **UI desconectada**: parte das ações do wizard grava e some (spinner mudo), sem

   trabalho visível em segundo plano; erro da ponte na primeira abertura vira
    mensagem apontando para `vault/logs/serve.log`.
6. **Sem terminal, não há porta de entrada**: `install.sh` precisa de `sh`; quem só

   clona (ou baixa o ZIP) e abre o Finder não tem primeiro passo.

## 2. Princípios

1. **Um registro de passos, dois renderers.** `setup.py STEPS` é a fonte única

   (id, título, status, run, superfícies); o wizard do navegador e o de terminal
    renderizam a mesma lista, com as mesmas palavras.
2. **Nada de UI desconectada.** Todo clique dispara um job visível (padrão `_Job` da

   ponte): linha a linha do que está acontecendo, terminando em ✓ ou num erro
    acionável na própria tela.
3. **Agente-agnóstico de ponta a ponta.** Primeiro escolhe-se o harness; conectores,

   permissões e memória de agentes derivam dele (mapa por agente, não caso Claude).
4. **Estado real, não checklist.** `feito` continua derivado do estado (ledger, config,

   doctor); progresso de interface (`logs/onboarding.json`) nunca é a verdade.
5. **"Depois" é entidade.** Passo pulado com intenção vira TASK no ledger (ou ASK para

   o agente), nunca frase de ajuda.
6. **O wizard é um modo do painel.** Mesma identidade visual, mesma shell; na primeira

   vez sem faces/⌘K; depois, a configuração continua nas abas de Configurações (já
    existem) e o modo de primeira vez fica a um clique da Visão geral (já existe).

## 3. Decisões do dono (2026-11-18, conversa do mockup — não re-litigar)

1. **Identidade visual: os tokens do PAINEL vencem.** O onboarding adota o sistema de

   design do painel (`dashboard.css`: claro/escuro, `--accent`, painéis neutros) — não o
    contrário. Resolve a decisão 1 de `onboarding-in-settings.md` em **(b)**, revertendo a
    direção recomendada lá (nunca executada).
2. **Harness antes dos conectores.** Tela "Seu agente": detecta (claude-code, hermes,

   cursor-cli, codex), seleciona o principal e conecta (`[runner].agent` + MCP
    somente-leitura + hook de canais + permissões) como job em segundo plano. A tela
    "Permissões" separada deixa de existir.
3. **Conectores ganham "+" fonte.** Editor de fontes espelhando o `watch.toml`

   (tipo · key · janela · parâmetro), via `brain watch add/remove` validados.
4. **Memória completa no wizard.** Os 3 modos (nenhuma · embed · full) **e** os 3 slots

   (LLM · Embeddings · Reranker) com defaults marcados (`recommended` do
    `providers.py`), chave por slot quando o provedor pede, aviso de egresso para
    nuvem — a mesma view da aba Memória do painel, não uma versão reduzida.
5. **Todo toggle/clique = trabalho em background visível** (jobs), inclusive

   instalações e conexões.
6. **A tela é alcançável no app**, não só no CLI (Configurações › Visão general já

   aponta; o wizard em si é que ainda é outra página/visual).
7. **Entrada sem CLI**: duplo clique resolve (`.command` na raiz do repo; detalhe na

   Fase 7).

Nome do modo leve: `embed` **em todo lugar** (já decidido na 2.17.0; a API ainda aceita
`lite` como alias).

## 4. Mapa das telas (fluxo aprovado no mockup)

```
Boas-vindas
Você e sua rotina        (Você + Sua rotina fundidos)
Sobre você
Seu agente               [novo]  harness: detecta, escolhe, conecta (job)
Conectores e fontes      [mudou] chips por app + editor de fontes watch (+ adicionar)
Memória                  [mudou] 3 modos + 3 slots com defaults
Chaves e portas          [mudou] GITHUB + Google OAuth + outbox (união das listas)
A máquina                [novo]  noturno · comando · TUI · foco · framework (defaults)
Goals e projetos         (mantido; proposta da IA com job visível)
A conversa               [novo]  entrevista: v1 = ASK ao agente; v2 = chat no app
Pronto                   [mudou] resumo derivado do doctor + "depois" como entidades
```

## 5. Fases

### F1 — Identidade única (herda passo 1 do plano antigo, direção (b))

`onboarding.html` é reconstruído sobre os tokens do painel: mesmo `:root` de
`dashboard.css` (com a variante `data-theme=dark`), mesmos componentes (painéis,
botões, pills, chips), mesma família de fonte. Os tokens próprios (`--cy`, `--vi`,
`--panel` navy) saem. O botão de tema acompanha o painel.

- **Aceite:** onboarding e painel lado a lado, claro e escuro, sem costura visível;
`scripts/build_assets.py` verde; suite verde.
- **Rollback:** `git revert` do commit (o onboarding anterior volta inteiro).
- **Armadilha:** o build de assets cobre o painel; o `onboarding.html` é asset separado
servido pela ponte — manter o caminho de build dos dois.

### F2 — Registro único de passos

`setup.py STEPS` ganha os campos de superfície e os passos de vida; `onboard.py` passa a
derivar sua lista dele (id + título idênticos nos dois renderers). A tela "A máquina"
entra no wizard: noturno (default 05:00), comando no PATH, TUI (default ligado? — ver
decisão 4), foco (default `.ics`), framework (regra de fetch + hook). Defaults
existentes dos passos; a tela é conferir e continuar.

- **Aceite:** `brain setup` e o wizard listam os mesmos ids/títulos; uma instância
nova configurada 100% pelo navegador chega ao `brain doctor` sem pendências
obrigatórias; suite verde.
- **Rollback:** cada passo continua idempotente e derivado de estado — reverter é
voltar à lista anterior; nada de migração.
- **Armadilhas:** todo prompt novo do wizard precisa de resposta programada no
`_WebUI` (rota painel/navegador morre em pergunta sem default — regra da skill);
mudança de semântica do doctor muda exit code e quebra o modal da TUI (gate
`tests.test_tui` junto).

### F3 — Seu agente (harness)

Nova tela antes dos conectores. Detecção via `harness._DETECT` + presets do runner;
"Conectar" grava `[runner].agent`, registra o MCP somente-leitura (`wire_mcp`),
aplica o hook de canais e sincroniza permissões (`perms.sync`) — cada linha um job.
Sem agente nenhum: caminho "conectar depois" que cria TASK nomeada.

- **Aceite:** instância demo com harness falso → conectar grava config + registra
eventos; a tela "Permissões" não existe mais como passo; `CoverageTest` /
`NOT_IN_PANEL` / `NOT_IN_TUI` atualizados no mesmo commit.
- **Rollback:** o passo é aditivo; desligar é remover a tela (estado gravado é válido
— `[runner].agent` e MCP são configuração legítima pré-existente).
- **Armadilha:** testes de wiring nunca tocam os configs reais do dono
(`~/.hermes`, `~/.cursor`…) — padrão `run=`/`which=` injetável do `harness.py`.

### F4 — Conectores agnósticos + editor de fontes

`CONNECTORS` ganha mapa de ferramentas por agente (hoje: prefixo
`mcp__claude_ai_*` só). O scan segue o agente escolhido em F3 (hermes: `config.yaml`
`mcp_servers`; claude: `claude mcp list`; cursor/codex: arquivos MCP). O editor de
fontes (+ / remover) chama `watch.add/watch.remove` com validação na hora; chips de
app continuam ligando/desligando ferramentas de leitura + fontes simples.

- **Aceite:** demo sem Claude Code completa o passo sem beco sem saída; fonte criada
na tela aparece no `watch.toml` e some ao remover; validação recusa fonte inválida
com mensagem na tela.
- **Rollback:** chips de app voltam ao comportamento atual; o editor de fontes é
aditivo.
- **Armadilha:** "conectar depois" tem que criar a TASK pelo ledger (não só marcar
progresso) — senão é frase de novo.

### F5 — Memória completa no wizard

O passo memória do wizard vira a mesma view da aba Memória do painel: modo no topo
(**apenas livro-razão** · embed · full — rótulo decidido pelo dono: o usuário não
precisa saber de `/ask` nem da fallback; "apenas livro-razão" diz o que o cérebro faz),
slots abaixo (embed → embeddings+reranker; full → +LLM), defaults dos `recommended`
(LLM default: **Anthropic**, decisão 7), chave por slot, aviso de egresso para nuvem,
pré-requisitos com estado ao vivo e passo exato. Modo "apenas livro-razão" com
pré-requisito ausente deixa TASK (`memory_later` já modela a intenção).

- **Aceite:** wizard e aba mostram as mesmas escolhas para a mesma instância
(paridade dos 5 pontos de providers: `PROVIDERS`, saída do `providers set`,
wizard `_providers_step`, roteado do painel, spec `forms.py`); full exige aceite
explícito; chaves nunca voltam para a tela nem para o log.
- **Rollback:** passo memória do wizard volta ao modo atual (roteado pelo `_WebUI`).
- **Armadilha:** pergunta de wizard sem default válido mata a porta roteada
(regra da skill — provedor sem `model`/`models` precisa de caso no `_WebUI`);
linha de recreate do compose deriva do MODO (`-f compose.full.yaml` no full).

### F6 — Jobs em toda parte

`_Job` estendido a todos os passos que fazem trabalho (agente, conectores, fontes,
máquina, OAuth do Google, memória, proposta de planejamento). Regra: nenhum botão
primário sem estado `running → done/error` visível; erro de job = mensagem acionável
na tela, não ponteiro para log. A primeira abertura sem ponte ganha tela de retry
estática (padrão da tela de token que já existe), em vez de erro para `serve.log`.

- **Aceite:** cada ação do wizard tem feedback de job; ponte morta durante o
onboarding mostra retry na tela; corpo de POST com chave continua fora do log.
- **Rollback:** jobs são adições por ação; reverter uma ação não afeta as outras.

### F7 — Entrada sem CLI + `/init` fechado

**Sem CLI:** `Abrir o Brain.command` na raiz do repo (duplo clique no Finder abre o
Terminal sozinho, roda o `install.sh` — mise, Python, ícone, abre o wizard — e fecha a
janela ao fim). README ganha o caminho "sem terminal": clonar (ou baixar o ZIP do
GitHub) → duplo clique. ZIP não tem `.git`: o `.command` faz `git init` + remote +
regra de fetch (senão `update`/`doctor` mentem) — decisão 6 abaixo.

`/init` **fechado:** `finish()` do onboarding grava `onboarding.finished` no ledger e
uma ASK ("terminar a entrevista: pessoas + fontes"). A skill `/init` passa a disparar
também por essa ASK pendente (não só por PROFILE vazio). Tela "A conversa" v1 explica
e deixa a ASK (o agente retoma na próxima sessão; ⚡ da TUI também). v2 (depois):
chat no app com o loop do `draft_planning`, bloco a bloco, sempre proposta→aprovação.

- **Aceite:** pós-onboarding, `brain ask list` mostra a entrevista; `/dump` passo 0 a
aplica; fluxo duplo-clique numa máquina limpa chega ao wizard sem digitação;
ponte morta → retry (F6).
- **Rollback:** a ASK é um evento normal (descartável); o `.command` é um arquivo
solto na raiz (removível sem rastro).
- **Armadilha:** o `.command` roda no diretório do repo — reusar o `install.sh`
inteiro, não duplicar lógica; `.command` em repo público não pode carregar caminho
de máquina.

### F8 — `/onboarding` como modo de primeira vez do painel (herda passo 6 antigo)

O wizard passa a rodar na shell do painel (sidebar, marca, tema), sem faces/⌘K;
"Abrir o painel" troca para as faces sem recarregar. A Visão geral continua sendo a
porta de volta depois de configurado.

- **Aceite:** primeira vez e "reconfigurar" usam o mesmo HTML do painel; transição
sem trocar de página; painel sem ponte mostra as abas em modo leitura (regra
atual mantida).
- **Rollback:** a rota `/onboarding` volta a servir a página própria.

### F9 — Guias, CHANGELOG, versão

`guides/setup.md`, `commands/setup/SKILL.md`, `setup.md` (raiz), README e
`CHANGELOG.md` na mesma onda — vocabulário único, telas novas documentadas.

## 6. Ordem sugerida e dependências

F1 (visual) → F2 (registro) → F3 (harness) → F4 (conectores/fontes) → F5 (memória) →
F6 (jobs, vai entrando junto com F3–F5) → F7 (entrada sem CLI + ASK) → F8 (modo
primeira vez) → F9 (docs). F1 não depende de nada e já resolve a quebra visual; F3–F5
dependem de F2; F8 por último porque consolida o que F1–F7 construíram.

## 7. Riscos e armadilhas (resumo do que a skill já cobra)

- **Cobertura de superfícies:** todo subcomando novo no painel/TUI ⇒ ALLOWED da ponte
  + conjuntos `NOT_IN_PANEL`/`NOT_IN_TUI` no mesmo commit; comentário `#` no meio de
  linha desses literais silencia rótulos.
- **Paridade de provedores são 5 pontos** (ver F5); campo novo = CLI + TUI + ficha +
`model.py` + painel + rebuild de assets.
- **Segredo:** corpo de POST de chave nunca no log (já vale); chaves não voltam para
o navegador; `.env` 0600.
- **Noturno nunca roda setup** — jobs do wizard herdam a trava (`BRAIN_NIGHTLY=1`).
- **Máquina nua:** defaults precisam funcionar sem apps de terceiro (LM Studio,
  OrbStack) — por isso "nenhuma + TASK" é o caminho honesto quando faltam
  pré-requisitos (decisão 3). **Atualização (ruling 2026-11-19):** o trecho LM Studio
  desta regra foi revertido pelo dono — o Brain **instala, sobe e configura** o LM
  Studio sozinho no passo de memória (`setup.lmstudio_ensure`: instalador oficial,
  servidor :1234, `bge-m3` baixado e carregado, tudo narrado no job; WSL não instala —
  lá o LM Studio mora no host Windows). O dono fica ciente, não executa; instalado com
  servidor desligado aparece como "instalado", nunca como "falta — baixar". **Na
  sequência o dono estendeu o ruling ao runtime de contêiner** (`setup.docker_ensure`:
  OrbStack pelo Homebrew no macOS · Docker Engine pelo script oficial no Linux/WSL) —
  a regra da máquina nua agora só vale para o `up -d` manual e para o que o instalador
  do sistema não cobre (ex.: Homebrew ausente).
- **Repo público:** mockups e exemplos usam os dados fictícios da padaria
(`marina-demo`, `#seu-canal`); nenhum caminho de máquina em código/doc commitado.

## 8. Decisões do dono (perguntas originais — respostas registradas abaixo)

1. **Ordem de execução.** F1 primeiro (visual fecha a quebra mais visível) ou F2

   primeiro (registro único evita retrabalho das telas novas)? Recomendo **F1 → F2**:  
    o visual é independente e F2 reorganiza exatamente as telas que F3–F5 vão usar. ✓?
   1. Seguir recomendação
2. **"A conversa" v1.** ASK-only (o agente retoma na próxima sessão) ou já com chat

   in-app no primeiro pacote? Recomendo **ASK-only** — o loop de chat do
    `draft_planning` é reuso real, mas a ASK entrega valor na primeira onda sem nova
    máquina. ✓?
   1. Ask-only
3. **Memória sem pré-requisito.** Default "Nenhuma" + TASK, ou trava no embed

   esperando OrbStack/LM Studio? Recomendo **Nenhuma + TASK** (regra da máquina nua).
    ✓?
   1. O agente vai usar o /ask naturalmente, correto? O usuário não precisa saber disso ou não precisa achar que ele precisa usar /ask durante uma conversa. Nesse caso, use "Apenas livro-razão" no lugar de Nenhuma. Depois Embed e depois FULL
4. **TUI default.** No passo "A máquina", TUI vem ligada por padrão (cria o

   `.venv-tui` de ~40 MB) ou desligada com "ativar" de um clique? Recomendo
    **ligada** — é o cockpit do dono e o custo é único. ✓?
   1. Ligada por padrão
5. **Nome do** `.command`**.** "Abrir o Brain.command" na raiz do repo? Recomendo sim,

   nome PT-BR mesmo (é o único arquivo que o dono clica no Finder). ✓?
   1. Recomendado
6. **ZIP do GitHub sem** `.git`**.** `git init` + remote + regra de fetch automáticos

   (update/doctor honestos) ou aviso pedindo clone? Recomendo **automático** com uma
    linha no fim do `.command` dizendo o que fez. ✓?
   1. Automático
7. **Default do LLM no full.** Anthropic (recommended) como default do slot?

   ✓?
   1. Sim,

## 8. Decisões do dono — RESPONDIDAS em 2026-11-18 (registro)

1. **Ordem de execução:** seguir a recomendação — **F1 → F2**. *(resposta: "Seguir
   recomendação")*
2. **"A conversa" v1:** **ASK-only**. *(resposta: "Ask-only")*
3. **Memória sem pré-requisito:** **"Apenas livro-razão"** (rótulo novo do modo
   `none` — o usuário não precisa saber de `/ask` nem sentir que perdeu algo; o
   agente usa a fallback naturalmente). Progressão na tela: apenas livro-razão →
   Embed → Full. *(resposta do dono, com o motivo)*
4. **TUI default:** **ligada por padrão**.
5. **`.command`:** **"Abrir o Brain.command"** na raiz (nome PT-BR).
6. **ZIP sem `.git`:** **automático** (`git init` + remote + regra de fetch, com uma
   linha no fim do `.command` dizendo o que fez).
7. **LLM default no full:** **Anthropic**.

As respostas acima já foram incorporadas às seções afetidas (F5, F7, §3).
