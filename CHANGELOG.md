## 2.29.0 — bootstrap do instalador: uma ação, a máquina inteira pronta

- **O `install.sh` deixou de verificar e desistir.** Máquina nova sem nada
  (sem git, sem Homebrew, só o Python 3.9 do sistema): o script instala o
  que faltar, silencioso e idempotente — git (Homebrew no macOS, gerenciador
  de pacotes no Linux) · mise · Python (o pin do `mise.toml`, nunca
  hardcoded) · runtime de contêiner (**OrbStack** no macOS, **Docker
  Engine** no Linux/WSL2). Segunda rodada é no-op. As portas do SO — senha
  sudo da sessão e a janela da Apple das Command Line Tools — continuam do
  sistema, com espera honesta; ao falhar, o script imprime a receita manual
  (`setup.md` §0–§1).
- **Contêiner é instalação; memória é configuração.** OrbStack/Docker entra
  pelo instalador; Hindsight e LM Studio continuam no passo Memória do
  wizard — são escolhas, não pré-requisitos. Falha no contêiner não bloqueia
  o Brain.
- **`doctor` ganha checagens de máquina** (git · mise · contêiner) — sempre
  aviso, nunca erro: docker ausente com memória ligada vem com o comando que
  resolve; com memória desligada, é só informativo.
- **README agnóstico de verdade:** some a lista de "requisitos que o
  instalador não resolve"; Claude Code deixa de ser requisito — qualquer
  agente (ou nenhum) serve, e o passo "Seu agente" conecta quem existir na
  máquina. O modo de memória "lite" virou "embed" no texto. Plano:
  `guides/plans/install-bootstrap.md`.

## 2.28.0 — o lote das issues #56–#61 (ativação, fila de revisão, assinaturas e rotina da manhã)

- **Importar histórico na primeira sessão (#56):** novo `brain seed folder <pasta>` — varre
  .md/.txt/.docx/.pdf, grava snapshots na inbox com a **data de captura original** (o mtime vira
  o nome e o carimbo do arquivo), lote retomável (`--limit`, padrão 30; rodar de novo continua de
  onde parou) e idempotência por hash (pasta já importada = silêncio). Recusa pasta dentro do
  vault (auto-ingestão) e deixa a extração para o `/dump` normal.
- **Fila de revisão (#61):** `brain review list` agrupa, num só lugar derivado do ledger, tudo o
  que espera o dono — propostas com evidência, rascunhos, publicações, perguntas, plano de foco e
  duplicadas — com uma contagem única (`review` no view-model) para painel e TUI. `brain review
  accept <id>…` aceita propostas **em lote com um confirm**, gravando um evento por item (falha em
  um não derruba os outros); portas (mensagem/publicação/foco) nunca entram em lote.
- **Memória full por assinatura (#59):** o slot LLM passa a aceitar **Assinatura** (Claude
  Pro/Max, ChatGPT, Cursor, GitHub Copilot, SuperGrok, Nous Portal — sem chave nova) ou chave de
  API; **LLM local saiu do menu do slot** (máquina pesada; extrator fraco polui). Doctor
  slot-aware: full com assinatura é válido sem chave no .env; embeddings seguem locais por padrão
  e reranker segue opcional — existe full com zero chave nova. `memory cost` marca assinatura
  como custo incluído no plano.
- **Recall com verdade no tempo (#58):** recall ganha decaimento temporal
  (`recall_half_life_days`, padrão 45; 0 desliga) para fatos de estado/configuração/compromisso —
  perenes (preferência, identidade, decisão) não decaem —, contradição marcada (o mais novo
  "vale", o velho aparece "supercedado", nada é apagado), supersessão explícita (`brain memory
  supersede`) e payload com âncora, data e proveniência: item sem âncora no vault chega como
  `[pista]`, nunca como fato. O hook renderiza `[memória · as of AAAA-MM-DD · prov]`.
- **Doctor que cura (#57):** `brain doctor --fix` (dry-run por padrão; `--apply` executa) com diff
  determinístico e quatro classes seguras — pid órfão da ponte, índice de busca velho, views
  velhas, memória dessincronizada; achados de gate viram sugestão com o comando exato, nunca
  auto-fix. Métricas de frescor (idade de dump/render/sync + backlog da inbox) no view-model para
  o painel anunciar a própria decrepitude.
- **Rotina da manhã (#60):** a sincronização diária passa a correr por padrão às **09:00**
  (horário do dono, configurável; quem já agendou mantém a escolha) e termina deixando o **brief
  do dia pronto** em FRESH/notes — uma linha quando não há novidade; `brain note write` grava
  narrativa derivada sem evento de dono (funciona no noturno).

## 2.27.0 — o lote das issues #32–#55 (engenharia + UI/UX do painel)

- **Índice SQLite rápido e confiável (#32, #34, #36):** escrita normal no ledger não refaz mais o
  índice inteiro — crescimento vira append incremental (o tail no offset antigo confirma que nada
  foi reescrito) e rebuild completo só quando o ledger encolhe ou a última linha mudou de verdade.
  Pesos bm25 corrigidos: título volta a levar 3× (o boost caía na coluna `kind` e o corpo pontuava
  zero). Leitores conferem frescor (`last_seq` × ledger) antes de usar o índice e caem na dobra ao
  vivo quando atrasado; falha da atualização pós-escrita ganha linha em `logs/index-errors.log` em
  vez de silêncio.
- **Instância e ledger resistentes (#33, #37):** `brain init` com `BRAIN_HOME` fora do clone semeia
  o vault a partir da raiz do framework (e avisa com os caminhos procurados quando não acha);
  referência quebrada no ledger agora vira `BrainError` nomeando seq/tipo/id + "rode
  ./brain validate" — e o `validate` segue reportando tudo com saída 4, sem traceback.
- **Ponte e subprocessos com limite (#35, #38):** a GC de jobs da ponte roda ANTES da checagem de
  "já existe em execução" — job de agente preso é expirado (rc 124) em vez de deixar as ações ⚡ em
  409 para sempre; o `proc.wait()` pós-EOF do agente herda o orçamento de timeout. pdftotext/
  pdftoppm (120 s), venv+pip (600 s) e abertura de OAuth (15 s) ganham timeout com `BrainError`
  nomeando a ferramenta.
- **TUI (#39, #40, #41, #42):** "Saúde online" da paleta executa `doctor --online` de verdade
  (itens `sys:*` chamam `run_sys` direto); alerta "não cabe: 0" some quando nada está em risco;
  o índice de duplicatas é cacheado por carga da store e a checagem por tecla ganha debounce de
  120 ms; checklist de higiene aplicado (bloqueadores múltiplos na ficha, `esc` só tira o filtro
  da aba em foco, auto-reload sem TOCTOU, código morto removido).
- **Painel — contraste e layout (#43, #44, #49, #50, #51):** pílula da face atual com tinta do
  tema e 12,5 px (6,05:1 no escuro); tokens de primeiro plano do tema claro escurecidos até
  4,5:1 em todos os pares texto×fundo (verificado por teste que calcula a razão WCAG); resumo do
  projeto com clamp de 2 linhas; telas de 500 px sem overflow lateral (grade do Foco com scroller
  próprio); alvos de toque ≥ 24 px nos botões pequenos e área expandida invisível nos links de
  pessoa.
- **Painel — comportamento (#45, #46, #47, #48, #52, #54):** agenda do Início e semana do Foco
  ordenadas por hora (não por id); datas ISO cruas viram dd/mm/aaaa; Ctrl K / ⌘K implementado com
  rótulo por plataforma; hierarquia de títulos h1→h2 sem mudança visual; portfólio standalone
  mostra travessão onde o recorte não traz a contagem (não mais zeros falsos); goals fora de
  "em dia" ganham mini-chip clicável com o motivo que salta até o projeto responsável.
- **CSS higiene (#53):** seletores e `@media` duplicados consolidados preservando a cascata, cores
  literais tokenizadas, tokens mortos removidos e escala tipográfica fechada em
  10,5/11,5/12,5/14/16/20/26 px.
- **Passo "Seu agente" agnóstico (#55):** os quatro agentes conhecidos aparecem sempre, com a
  detecção como selo ("detectado"/"não detectado") — conectar um não detectado devolve a receita
  manual — e o card "Outros harnesses" entrega os snippets MCP prontos (JSON, TOML e CLI) para
  qualquer ferramenta que fale MCP, marcando o passo como manual.

## 2.26.0 — o lote das issues #26–#31

- **Atalho de um clique + aba reaproveitada:** o passo "A máquina" do wizard ganhou a linha
  "Ícone no Dock" (macOS; `pin_shortcut` idempotente, tile `file-tile` bem-formado — um tile
  antigo sem `tile-type` é detectado e regravado) / "Atalho na área de trabalho" (Linux/WSLg,
  cópia executável do `.desktop`). E abrir o painel não espalha abas: a varredura de reuso
  agora procura a aba do Brain em TODOS os navegadores abertos (o padrão primeiro), não só
  no navegador padrão — nunca lança um navegador fechado.
- **Doctor/boot do Hindsight (#27):** `brain doctor` reconhece o estado transitório do container
  nos primeiros 3 minutos pós-boot (ou em restart-loop aguardando o LM Studio) e avisa em vez de
  errar "banco ausente"; o watchdog só aciona o `lms` se ele existir, espera até 30s pelo `:1234`
  e registra o que o `compose up -d` realmente fez (subiu/recriou vs "Running" sem efeito).
- **Operações falhas do servidor no doctor (#26):** o contador `failed_operations` do Hindsight
  entra no `memory status`/doctor — o level vira `warn` mesmo sem documento rastreado localmente e,
  quando o erro diz `No models loaded`, a causa é nomeada junto do comando que corrige (`lms load`
  no LM Studio ou `brain memory providers set llm …`).
- **Arrastar para a inbox (#28):** arrastar arquivo ou pasta sobre o painel vivo (`./brain serve`)
  mostra as zonas **Mover**/**Copiar** (estilo Telegram) e entrega em `vault/RAW/inbox/` pela ponte
  (`POST /api/inbox`: 50 MB por envio, sufixo `-2` em colisão, `.DS_Store`/`.keep.md` ignorados,
  noturno bloqueado). Sem a ponte, o painel avisa como entregar de outra forma; quando o navegador
  não deixa apagar o original, copia e diz isso na tela.
- **Fontes: ligar/desligar, agrupamento e slack-dm (#29, #30):** o `watch.toml` ganha `enabled`
  (padrão `true`; desligada é pulada no `/update`, no noturno e no `watch since`, e segue listada,
  esmaecida) e o novo `kind = "slack-dm"` com `exclude` — DMs e DMs em grupo do dono (recebidas e
  enviadas), um snapshot por conversa ativa, conteúdo só no vault. A aba Fontes (TUI e painel)
  agrupa por tipo, traz os problemas primeiro, alterna a ordem por último pull e liga/desliga por
  fonte (`x` na TUI, interruptor no painel — `brain watch edit <key> --set enabled=…`).
- **Autocompletar entidades nos formulários (#31):** campos que referenciam entidades (destino da
  mesclagem, bloqueios, pessoas) filtram ao digitar — número ou palavras do título/nome, sem
  acento/caixa — mostrando `ID · título` na TUI e no painel pela mesma especificação
  (`forms.filter_options`); confirmar a sugestão preenche o ID.

## 2.25.0 — o cérebro não gerencia memória de agentes

- **Decisão do dono (18/11, revogando a de 05/11):** memória de agente é concern do próprio
  agente. O cérebro **não cria, não aponta e não verifica banco nenhum** de Claude Code,
  Cursor, Codex ou Hermes — quem já tem memória configurada nunca mais tem o ponteiro
  reescrito por baixo (`~/.hermes/hindsight/config.json` e `memory.provider` ficam intactos).
- **Saiu:** `wire_hermes`, o instalador oficial via `npx`, o `~/.hindsight/coding-agent.json`,
  as chaves `[memory].harness_bank`/`harnesses`, `brain memory harness install|verify|remove`,
  o sub-passo "Harnesses" do wizard, a seção de harnesses da aba Memória (painel e TUI) e os
  checks de banco do doctor. **Migração:** configs antigas com `harness_bank`/`harnesses` são
  ignoradas sem erro; `recall_hook = "auto"` vira `false` (o hook liga explícito com
  `brain harness connect claude-code`); blocos do Codex escritos com o marcador antigo ficam
  órfãos — remova à mão se houver.
- **Ficou (não é memória):** o canal de LEITURA do cérebro nos agentes, agora com CLI própria
  e enxuta — `brain harness connect|disconnect|status <agente>` (MCP somente-leitura; no
  Claude Code também o hook de recall, flags `--no-mcp`/`--no-recall`). A detecção de agentes
  do onboarding ("Seu agente") usa a mesma máquina.
- **Guia novo:** *"Memória dos agentes: traga a sua"* (`guides/memory.md`) — a receita de como
  apontar CADA agente para o servidor que VOCÊ escolher, sem passar pelo cérebro.
- **Onboarding (feedback do teste real):** boas-vindas mostra o ícone do app (não a arte
  navy); a dica de conectores segue o agente escolhido; o almoço sai do wizard (tunável fino
  não se pergunta); token do GitHub com passo a passo (link com `public_repo` pré-marcado e
  `No expiration` sugerido); formulário de fonte se molda ao tipo escolhido.

## 2.24.0 — o lote das issues #21–#25: aprovação sem atrito, retratação e painel vivo

- **Confirmar já aprova (#21).** Nos formulários de gate do painel e da TUI (goal/projeto, promover
  oportunidade, aprovar mensagem, plano de foco, publicação, aceitar/rejeitar proposta) o campo
  "sua aprovação" deixa de existir: apertar "aprovar" é a aprovação, e a interface preenche
  `--approval`/`--quote` com `painel` ou `tui` — o ledger segue registrando a aprovação e a
  superfície de origem. Na CLI nada muda (o texto não vazio continua obrigatório) e o consentimento
  do modo full da memória segue digitado, por ser consentimento de nuvem.
- **O TODO não esvazia com "todas" (#22).** Marcado o filtro "todas (fechadas além de 14d)", a coluna
  Feita agora mostra as ações fechadas sem corte de data; desmarcado, mantém a janela de 14 dias.
  (O corte era recuada só com o filtro desligado — ligá-lo fixava o corte em hoje e esvaziava a
  coluna.)
- **Pessoas moram no Portfólio (#23).** No painel e na TUI, o cadastro de pessoas sai da face
  Execução e passa a morar no Portfólio, junto de Áreas, Processos e Documentos — mesmo
  agrupamento nas duas superfícies, com rota, busca e links preservados.
- **A porta de sugestões aprende a se corrigir (#24).** `brain feedback withdraw` retira um rascunho
  pendente (o dono qualquer; o agente só rascunho próprio, sem issue) — sai da fila, `push` recusa,
  `list --all` mostra o motivo. `brain feedback retract` retrata uma issue publicada:
  `--withdraw` comenta e fecha como "não será feita" (o agente pode sozinho em item que ele mesmo
  publicou, com evidência registrada — decisão do dono, opção B); `--correct` revisa o corpo e
  exige o "ok" do dono. No noturno nada chega ao GitHub: vira pergunta (ASK) e o doctor avisa das
  retratações pendentes. Textos de comentário e correção passam pelos mesmos guardas públicos.
- **O painel roda as ações do agente (#25).** Com `brain serve` no ar e runner configurado, os
  botões e atalhos "(agente)" (atualizar tudo, puxar fonte, processar inbox, brief…) disparam o
  mesmo caminho headless da TUI (`/api/agent` + `/api/agent/job/<id>`), com saída transmitida no
  console lateral, uma ação por vez (409 na segunda) e recusa no noturno. Sem ponte ou sem runner,
  o aviso de hoje continua — agora com o motivo.

## 2.23.0 — onboarding unificado: um cérebro, uma configuração

- **Um registro de passos, duas renderizações.** O wizard do navegador e o de terminal agora falam a
  mesma língua: `setup.WEB_STEPS` é a fonte única (id · título · grupo) e o `/onboarding` renderiza
  dela. "Você" e "Sua rotina" viram uma tela; a tela "Permissões" separada deixa de existir.
- **O wizard cobre a máquina inteira (o buraco do `curl | sh`).** Tela "A máquina": noturno, comando
  `brain` no PATH, TUI (ligada por padrão), foco `.ics` e regra de fetch/hook do framework — cada item
  um trabalho visível rodando em segundo plano, com log linha a linha. Quem termina o onboarding no
  navegador chega ao `doctor` sem pendências obrigatórias.
- **Tela "Seu agente" (antes dos conectores).** Detecta Claude Code, Hermes, Cursor e Codex na máquina;
  "Conectar" grava o `[runner].agent`, registra o MCP somente-leitura do cérebro e libera as permissões
  — como job, com cada passo aparecendo. "Fazer depois" cria uma tarefa com nome no TODO, não uma
  frase de ajuda.
- **Conectores sem Claude Code + fontes na tela.** Sem o Claude, ligar Gmail/Slack/Calendar continua
  valendo (as fontes é que provam) e as allow-rules ficam para quem as usa. Novo editor de fontes:
  botão "+" cria a fonte do `watch.toml` (tipo · key · janela · parâmetro) com validação na hora, e o
  × remove — o universo observável deixou de ser arquivo escondido.
- **Memória completa no wizard.** Os três modos na ordem que o dono escolheu — **apenas livro-razão**
  · **embed** · **full** — e os três motores (LLM · embeddings · reranker) com o registry inteiro de
  provedores, defaults "✓ recomendado", chave por slot, aviso de egresso para nuvem e fail-fast de
  chave antes de qualquer job. O modo full segue exigindo o aceite explícito.
- **O onboarding termina de verdade.** `finish` grava `onboarding.finished` no ledger e deixa a
  entrevista de profundidade como pergunta aberta (pessoas + fontes) — o `/init` passa a disparar por
  ela também, então quem onboardou no navegador não perde a conversa.
- **Entrada sem terminal.** `Abrir o Brain.command` na raiz do repo: duplo clique no Finder roda tudo
  (a janela que abre trabalha sozinha) e uma pasta baixada como ZIP do GitHub vira repositório git com
  origin configurado — o `brain update` funciona desde o primeiro dia.
- **Identidade visual única.** O wizard trocou o tema navy próprio pelos tokens do painel (claro e
  escuro, com o mesmo alternador) — configurar o Brain e usá-lo são o mesmo aplicativo agora.

## 2.22.0 — os canais do cérebro nos agentes e multi-instância de verdade

- **O cérebro alcança os agentes de código (#5, #20).** `brain memory harness install` registra, além do
  instalador oficial do Hindsight, os dois canais de LEITURA do cérebro: o hook de submissão de prompt no
  Claude Code (`.claude/settings.local.json`, via `perms.sync` — roteador, teto de 5 itens, abstenção) e o
  servidor MCP somente-leitura (`brain mcp`) no Claude Code, no Hermes (`hermes mcp add brain --command …
  --env BRAIN_HOME=… --args mcp`), no Cursor (`~/.cursor/mcp.json`) e no Codex (`~/.codex/config.toml`,
  bloco demarcado e validado). Toda sessão, em qualquer diretório, ganha consulta sob demanda — e nada do
  banco dos agentes vira fato do vault (a suíte segue cobrindo a separação). `--no-recall`/`--no-mcp`
  desligam um dos canais; `brain memory harness remove <agente>` (tecla `x` na TUI, botão no painel)
  desfaz o registro do hook/MCP e devolve `recall_hook` para "auto".
- **Hermes honesto (#19).** `wire_hermes` só registra o harness quando `memory.provider` fica de fato em
  `hindsight` (checando a CLI e o `~/.hermes/config.yaml`); a verificação e o doctor passam a conferir os
  canais de cada harness — hook, MCP, provider e, com `--online`, o plugin do Hermes — avisando o comando
  exato que corrige o que faltar. Sem CLI do Hermes no PATH, o resultado diz o que rodar em vez de
  declarar conectado.
- **Cada instância com o seu noturno (#9).** O agendamento no macOS usa rótulo `launchd` próprio por
  instância (`com.segundo-cerebro.nightly.<slug>-<hash8>`) e migra o plist legado apenas quando ele
  apontava para a própria instância; no cron, instalar/remover preserva as linhas das outras. O comando
  `brain` e o app Brain não trocam de instância em silêncio: setup e `brain app install` avisam quando já
  apontam para outra instância existente e só trocam com confirmação em terminal interativo (link
  quebrado se repara direto). O doctor de cada instância relata o estado do SEU noturno — inclusive
  quando o agendamento da máquina roda outra instância.
- **Varredura do upstream:** `/Users/marina-demo/…` passa a ser tratado como nome fictício declarado no
  cheque de caminhos de máquina (mesmo critério já usado para os termos do ledger).

## 2.21.0 — o lote das issues #5–#18: noturno honesto, hook de recall e TUI sem armadilhas

- **Noturno que não mente mais (#6, #7).** O agente headless é sondado no setup (interativo) e no
  `doctor --online` com um prompt mínimo — sem login, o dono vê o motivo e o comando que corrige. Quando
  o agente escolhido morre antes de produzir nada (sessão expirada, `Authentication required`), o noturno
  tenta o próximo da ordem automática (`[runner].fallback = true`, desligável); se ele já tocou no ledger
  ou na inbox, não há fallback — o erro sobe inteiro. O doctor mostra o passo e o motivo das falhas em
  vez de um "com falhas" mudo, e quem usa runner que não é o claude com fontes MCP no watch.toml recebe
  o aviso de que só o preset claude recebe as regras de leitura (limite documentado no guia).
- **O contexto do cérebro chega ao Claude Code (#5).** `perms.sync` registra o hook de recall
  (`services/hooks/recall_context.py`) em `UserPromptSubmit` do `.claude/settings.local.json` quando
  `[memory].recall_hook = "auto"` (default) e o harness `claude-code` está conectado — `true`/`false`
  forçam. O hook silencia no noturno (`BRAIN_NIGHTLY=1`), resolve a instância por `BRAIN_HOME` antes do
  cwd e sai em silêncio quando não acha instância. Hooks do dono e o `settings.json` versionado ficam
  intocados.
- **TUI sem armadilhas (#11, #14, #15, #16, #17).** Pousar em painel que a face não define e usar `?`
  ou `h/l`/`[ ]` não derruba mais o app; a tecla `s` volta a mover ação cujo bloqueador já foi fechado
  (só bloqueadores abertos travam, como o status derivado); `brain render` com falha após uma escrita
  vira aviso em amarelo ("FRESH e o painel ficaram velhos") em vez de linha de sucesso; o subtítulo dos
  painéis alinha à direita de verdade (via estilos, não atributo fantasma); o relógio do log segue o fuso
  da instância e o `BRAIN_NOW` dos testes; e um Select que fica sem opções (nenhum goal ativo, p. ex. no
  promover oportunidade) abre em "— escolha —" com o submit barrado — não explode mais.
- **Onboarding e instalador (#8, #13).** Sem o Claude Code na máquina, o passo Conectores conclui com o
  caminho (menciona o Hermes quando presente) em vez de job de erro; o rascunho de planejamento aceita
  qualquer agente configurado e cita o certo. O `install.sh` roda `mise trust` no clone novo antes de
  qualquer Python e, se o `init` falhar, imprime a correção exata em vez de abortar mudo.
- **RAW e memória (#10, #12, #18).** O nome do tipo é prefixo válido: `snapshot --prefix connectors`
  arquiva em `connectors/` (e o snapshot avisa quando um `--prefix` não classifica); arquivos
  `connectors-*`/`github-*` que caíram em `documents/` ficam fora do banco vetorial. O corpus não é mais
  relido e re-hashado várias vezes na mesma execução (`sync`/`status`/`doctor` pagam uma leitura só,
  por assinatura exata), `NO_LLM_CONFIG` existe uma única vez e `gemini` entra na lista do runner no
  wizard.

## 2.20.1 — hotfix: tecla m com a memória desligada não derruba mais a TUI

- **Correção.** Abrir o formulário "Memória: modo e provedores" com o modo atual `nenhuma` derrubava a
  TUI (IndexError no compose do FormModal): o cardápio de embeddings é dinâmico por modo e a tabela
  não tem chave `none` — o Select ficava sem opções. Agora a fonte cai no cardápio do embed quando o
  modo está fora da tabela (e o painel idem no forms.js), e o FormModal degrada para um campo inerte
  ("—") se alguma fonte dinâmica um dia devolver vazio — o formulário abre, nunca trava.
- Testes de regressão nos dois níveis: fonte nunca vazia (`test_forms`) e abertura real do
  formulário com modo none (`test_tui`).

## 2.20.0 — o fluxo da memória nas três superfícies: LLM · embeddings · reranker, lado a lado

- **Full com reranker no cardápio.** O passo Memória agora monta os três pares — LLM, Embeddings e
  Reranking, cada um com provedor + API key lado a lado (era provedor-provedor-chave-chave). Reranker:
  desligado (RRF, default) · Fireworks Qwen3-Reranker-8B · Cohere rerank-v3.5. Fireworks nos embeddings
  e no reranker usam a mesma conta — o fluxo avisa e reusa a chave; OpenAI de LLM e embeddings idem.
- **TUI tem o mesmo fluxo do painel.** Configurações › Provedores, tecla `m`: formulário com modo
  (nenhuma/embed/full), LLM (+modelo no OpenAI), embeddings pelo modo, reranker, as três chaves e a
  aprovação literal do full. Antes a TUI só tinha a troca por slot e o wizard em terminal suspenso.
- **CLI headless.** `brain memory setup --mode full --provider anthropic --embeddings fireworks
  --reranker fireworks --key … --emb-key … --approval ok` roda o mesmo wizard roteirizado do painel
  (provedores → compose → modo → bancos → health/llm). O noturno não liga o full (gate de egress).
- **Uma fonte para as três pontas.** `setup.validate_memory_setup` + `configure_memory` validam e
  rodam o mesmo fluxo para painel (job), TUI (formulário) e CLI; o wizard interativo segue existindo
  (`brain setup --only memoria`, tecla `w`).

## 2.19.0 — full é só-nuvem; o painel liga a memória sem LM Studio

- **Modos com cardápio próprio (decisão do dono).** `embed` aceita embeddings locais (bge-m3 no LM Studio,
  default) ou de nuvem; **`full` é só-nuvem**: o wizard não oferece `local` para embeddings (default Fireworks
  `qwen3-embedding-8b` @1536), o CLI recusa a troca para `local` no full e o doctor avisa instâncias legadas.
  Motivo: full com embeddings locais morria na checagem de boot do Hindsight em qualquer Mac sem LM Studio —
  o caminho recomendado era o quebrado.
- **Painel.** O passo Memória escolhe o provedor de embeddings por modo (embed: local/Fireworks/OpenAI; full:
  Fireworks/OpenAI), pede a chave de CADA conta (LLM e embeddings — OpenAI nos dois usa a mesma) e o LLM OpenAI
  pede o nome do modelo (não há default por operação; Anthropic segue o cenário B Haiku/Sonnet). Antes: full no
  painel sem LM Studio falhava no boot (Anthropic) ou morria no meio do wizard (OpenAI).
- **Verificação depois de ligar o full.** O wizard chama `health/llm` no banco ao terminar: chave ou provedor
  errado aparece na hora ("⚠ verificação do LLM falhou"), não no primeiro retain.
- **Recreate certo.** Os avisos de recriar o container (saída do `providers set` e a ficha do formulário) agora
  incluem o override do full (`-f services/compose.full.yaml`): recriar com o compose base religava
  `SKIP_LLM_VERIFICATION=true`, e um LLM morto virava falha silenciosa de extração.
- TUI e painel compartilham a ficha de provedores (`forms.py`) — a regra vale igual nas três superfícies.

## 2.18.0 — formulários iguais na TUI e no painel; o ícone reaproveita a aba

- **Uma especificação, duas pontas.** Os formulários da TUI e do painel HTML eram escritos duas vezes, à mão, e
  divergiam: campos, nomes, ordem, obrigatórios, o que aparece por tipo e a linha `brain …` montada. Agora todos
  (61) moram em `brainlib/forms.py` — a TUI desenha os campos a partir dali (`open_form`) e o painel recebe a mesma
  especificação no view model (`M.forms`) e monta o comando com o mesmo motor (`assets/src/forms.js`, que compila
  as mesmas regexes do Python).
- **O que mudou no painel** (passa a ser como a TUI): Fontes mostra só os campos do tipo (`drive-doc` pede o doc,
  `slack` o canal, `jira` monta a JQL pelo escopo e tira o site da URL) em vez do "Outros campos"; datas aceitam
  `sex`, `+3d`, `20/10` com a data resolvida ao lado; obrigatório tem `*` e bloqueia o confirmar com a mesma
  mensagem; entregável aceita só o número (`9` → `PROJ-1.9`); a lista `mine` preenche o dono com `eu`; nota rápida
  com vínculo validado; promover pede título, motivo e a sua aprovação; marcar entregável feito pede a evidência;
  "Superar decisão" usa `decision supersede` (como a TUI); cobrar e responder pergunta montam a mesma linha.
- **Correções de gate.** O painel pré-preenchia "ok" em aprovar proposta, publicação, editar goal/projeto e
  estrutura do plano, e o promover mandava `--approval "ok"` sozinho. Aprovação literal agora nunca vem preenchida,
  nas duas pontas (`tests/test_forms.py::test_gates_never_prefill_approval`).
- **O que a TUI ganhou do painel:** contexto na decisão, evidência na entrega, e-mail na nova pessoa, "destrava" na
  nova ação, "substituída por" ao superar decisão, sugestões (autocompletar) nos campos de pessoa, projeto e vínculo.
- **O ícone do app reaproveita a aba do Brain.** No macOS, `util.open_url` (o app, `brain open` e `render --open`)
  procura no navegador **padrão** — Safari, Chrome, Brave, Edge, Arc, Chromium, Vivaldi ou Opera — uma aba já aberta
  na ponte local (`127.0.0.1:<porta>`) e a traz para a frente em vez de abrir outra janela; se a ponte foi reiniciada
  (token novo), a aba recebe o token e recarrega na mesma rota. Só consulta navegador que já está rodando (nunca o
  abre à toa) e só o padrão (o macOS pede uma permissão de automação por app, na primeira vez). Sem permissão, sem
  aba ou em outro navegador (Firefox), abre como antes. Os testes interceptam `webbrowser.open`: nunca mexem nas abas
  do dono.
- **Painel com o mesmo ícone do Dock.** A barra lateral e o favicon do painel usavam a marca simplificada
  (`brain-mark.svg`, com dois nós por lado) e destoavam do ícone do app; agora usam o `brain.svg`, o mesmo do Dock.
  A marca simplificada segue só nos tamanhos de 16/32 px do `.icns` e no favicon do onboarding.
- **Trava:** `tests/test_forms.py` recusa campo escrito à mão fora do `forms.py`, exige que todo formulário abra
  nas duas pontas (ou diga por que não) e roda ~1.000 combinações de valores pelo Python e pelo node comparando
  comando, validação, dicas, listas e valor inicial. As coberturas da CLI (TUI e painel) passam a ler os comandos
  da especificação. `dates.py` sai de `tui/` (o painel usa a mesma regra); a ponte aceita `decision supersede`.

## 2.17.1 — o clone sempre sabe o que o upstream tem

- **Passo `framework` no `brain setup`.** Confere a regra de fetch do `origin` (`remote.origin.fetch`) e o hook
  pre-push, e conserta o que faltar (`brain setup --only framework`). Sem a regra, o `git fetch` comum só atualiza o
  `FETCH_HEAD`: o `origin/main` local fica velho e o `ahead/behind` do `update`, do `doctor` e da conferência antes
  do push mentem — o que parecia "o upstream não andou" era um espelho parado. Um `git clone` normal já traz a
  regra; ela falta em clones montados à mão.
- `brain init` (que o `install.sh` já roda) aplica o mesmo reparo, e o `brain doctor` avisa quando a regra falta.
  Uma regra que já existe, inclusive a de um clone de um ramo só, nunca é alterada.

## 2.17.0 — a configuração guiada mora na face Configurações

- **Um passo por aba.** A face Configurações passa a ter Visão geral, Perfil, Rotina, Conectores, Memória,
  Integrações e Saúde. Cada aba usa os mesmos endpoints da configuração guiada (`/api/onboard/*`): Perfil mantém a
  prévia antes de gravar o `profile.md`, Conectores verifica as conexões só quando você clica, e Permissões virou
  uma seção de Conectores.
- **Visão geral** é a primeira aba da face: a lista dos passos com `feito` ou `depois`, o progresso, "Rever
  boas-vindas" (abre o `/onboarding` do começo) e o atalho para Goals e projetos em Execução. `feito` vem do estado
  real (`onboard.state()["setup"]`), não da lista de passos vistos: passo pulado segue `depois` e não gera contador.
  O único contador da face continua sendo o da Saúde.
- **Memória:** o modo (nenhuma · embed · full) entra no topo da aba, acima dos provedores e harnesses. O onboarding
  também passa a chamar o modo leve de **Embed**, o mesmo nome da CLI e do `brain.toml` (a API aceita `lite` e
  `embed`).
- **O atalho "Configuração guiada" saiu da barra lateral.** O caminho de volta agora é a Visão geral.
- **Painel aberto como arquivo:** as abas novas avisam que a configuração se edita pelo app Brain (a ponte é quem
  grava).
- A primeira vez continua igual: `brain open` abre a configuração guiada enquanto ela não foi concluída.

## 2.16.1 — ícone que se vê no Dock e no painel

- **Ícone legível em tamanho pequeno.** O "Sinapse" detalhado (199 linhas de 4 px numa tela de 1024) virava uma
  mancha escura no Dock e na barra lateral. O ícone do app (`assets/icon/brain.svg`, e o `brain-512.png` gerado
  dele) agora tem traço grosso, fundo índigo→violeta e cinco nós por hemisfério. Até 32 px entra a marca
  simplificada `brain-mark.svg`: barra lateral do painel, favicon e os tamanhos 16/32 do `.icns`. A arte detalhada
  fica como ilustração da boas-vindas do onboarding (`brain-hero.svg`, rota `/brain-hero.svg`). Para ver o ícone
  novo no Dock, reinstale o app com `brain app install`.
- **Barra lateral do painel:** a marca é SVG embutido pelo `scripts/build_assets.py`, recortado no ladrilho, e o
  painel continua abrindo offline. O desenho visível passa de cerca de 20 para 30 px, e o "demo" ao lado do nome
  saiu.
- **"Configuração guiada" só na face Configurações.** Nas faces Execução e Portfólio o atalho parecia uma
  pendência. É o passo intermediário até a integração proposta abaixo.
- **Uma segunda ponte não deixa a primeira órfã.** `brain serve` numa outra porta sobrescrevia o registro
  da ponte do app e o apagava ao encerrar: a ponte principal continuava viva, ocupando a porta, e o app caía
  no retrato (sem comandos e sem o atalho da configuração guiada). Agora cada ponte só registra se não houver
  outra no ar e só apaga o próprio registro.
- **Proposta** `guides/plans/onboarding-in-settings.md`: a configuração guiada passa a morar na face
  Configurações, com um passo por aba, a Visão geral no lugar do atalho global e uma só identidade visual. Ainda
  não foi implementada.

## 2.16.0 — o app Brain: instalação e configuração guiada no navegador

- **App Brain.** O app (e o painel) passam a se chamar **Brain** — Segundo Cérebro segue como nome do framework.
  Ícone novo, o "Sinapse" (`brainlib/assets/icon/brain.svg`): no macOS o `.icns` é montado na instalação com
  `sips` + `iconutil` (vêm com o sistema); sem eles, cai no PNG de 512 px versionado. `brain app install` instala
  em `/Applications` (a pasta Aplicativos) quando a conta escreve lá, senão `~/Applications`, e remove a cópia
  antiga (`~/Applications`, nome "Segundo Cérebro") que ele mesmo criou.
- **Configuração guiada no navegador** (`/onboarding` na ponte local, `brainlib/onboard.py`): você · sobre você
  (prévia do PROFILE antes de gravar) · rotina · conectores (estado pelo `claude mcp list`, em segundo plano;
  ligar um conector libera só as ferramentas de LEITURA em `[runner].allow` e cria as fontes simples no
  `watch.toml`) · permissões (`.claude/settings.local.json`) · memória (nenhuma, lite, full — a API key vai direto
  para o `config/.env` e o full exige o aceite explícito do envio) · integrações (token do GitHub) · goals e
  projetos (texto e documentos entram na `RAW/inbox/`; o agente propõe a árvore; o dono aprova no navegador e ela
  nasce pelo gate do `brain plan`). Rotas novas com as travas da ponte (host, origin, token); o corpo nunca vai
  para o log; upload com nome saneado, tipo e tamanho limitados, só na inbox.
- **`brain open`**: o que o clique no app faz — a configuração guiada enquanto ela não terminou, depois o painel.
  O `install.sh` agora semeia a instância, cria o app e abre a configuração no navegador (o wizard de terminal
  `brain setup` continua para quem prefere e para IAs).
- **Sem id para inventar.** `brain init --owner-name "…"` gera o id do nome (`Marina Demo` → `marina-demo`);
  `--owner-id` vira opcional. O wizard de terminal pergunta só o nome. `doctor` aponta para `./brain setup`.
- A ponte relê o `brain.toml` a cada pedido (`config.reload`, que preserva `BRAIN_VAULT`/`BRAIN_CONFIG`): o
  onboarding e o painel mudam a config com a ponte no ar.
- A abertura do navegador passa por `util.open_url` (no macOS, `/usr/bin/open`).
- README revisado: portas conforme o `AGENTS.md`, comando de testes que o CI roda, instalação pelo app.

## 2.15.0 — mesmas teclas no TUI e no painel

- **Um verbo, uma tecla.** `d` descarta, remove, cancela, aposenta, desliga ou rejeita em toda tela (antes era `D`
  em Ações, `x` em quase tudo, `u` em Documentos, `r` em Propostas). `e` edita (Pessoas deixa de usar `u`),
  `T` alterna só abertas ↔ todas (Ações deixa de usar `a`), `L` liga documento (o `l` volta a ser só navegação
  de abas), `p` publica na aba Publicar (o `P` fica só para progresso), `r` é só render e `enter` só abre a ficha
  (responder pergunta é `a`). As teclas antigas `D`, `a` (Ações) e `u` (Pessoas) seguem valendo, escondidas, por uma versão.
- **Lacunas de paridade fechadas.** Painel: página **Fontes** (`n e d w`), página **Documentos** (`L d enter`),
  `L`/`v` em Oportunidades, `L`/`o` em Processos, `f` corrige o aviso em Saúde, `R` "quem é…?" em Pessoas,
  `T` em Perguntas/Mensagens/Sugestões, `N` nota em qualquer página, `E` mudar árvore, teclas do agente no Início
  (mostram o comando do chat) e `g`/`:`/ctrl+P como a paleta. TUI: `M` mescla ação duplicada e `` ` `` abre/fecha o log.
  A ponte do painel ganhou `doc link|unlink`, `watch add|edit|remove`, `opportunity evidence` e `person resolve`.
- `doctor.fix_for` passa a ser a única regra de "o que fazer com este aviso" (TUI e painel).

## 2.14.0 — ícone clicável do painel

- **`brain app install`**: cria o app **Segundo Cérebro** — clique duplo faz o
  `brain render --open` (regenera as views, sobe a ponte se preciso e abre o
  painel vivo), sem abrir terminal. macOS: `~/Applications/Segundo Cérebro.app`
  (Launchpad, Spotlight, arrastável para o Dock); Linux: entrada `.desktop`.
- Ícone desenhado em Python puro (PNG + `.icns` montados à mão): sem
  dependência nova e sem binário no repo. Se a abertura falhar, o app mostra um
  aviso e o detalhe fica em `vault/logs/app.log`.
- `--dest` (ex.: `~/Desktop`) e `--name` (várias instâncias). `brain app
  uninstall` só remove o que o próprio comando criou — recusa pasta de outro app.
- O wizard (`brain setup`) ganhou o passo **painel**: o modo interativo
  pergunta (padrão sim) e o `--yes` cria direto, como o passo `comando`.
  Refazer o passo (`--only painel`) é idempotente.
- O app guarda o caminho da instância e do framework: mudou a pasta, reinstale.

## 2.13.1 — o chat do Claude Code não pede mais licença

- **Sessão interativa pré-autorizada.** Antes só o agente headless (noturno e
  ações ⚡) tinha as ferramentas liberadas; o chat do terminal/app perguntava a
  cada `ls`, `cat`, pasta fora do cwd e MCP de leitura. Agora o repo traz
  `.claude/settings.json` (git, genérico): `Bash` inteiro, Read, Edit, Write,
  Glob, Grep, NotebookEdit, WebFetch, WebSearch e Task liberados, modo
  `acceptEdits`, e os limites da Constituição em `deny` — livro-razão, `.env`,
  `git push --force`/`-f` e `--no-verify`.
- **`brain agent permissions`** gera `.claude/settings.local.json` (gitignorado)
  com o que é da instância: MCP de leitura (`[runner].allow`), porta oppdrive,
  extras do `[tui].agent_allow` e `additionalDirectories` (raiz da instância,
  vault e pastas de repos do `watch.toml` — a sessão num worktree enxerga o
  vault). Roda sozinho em `init`, `agent allow`, `update` e no noturno; o
  `doctor` avisa se ficou para trás. `--check` só confere.
- MCP de **escrita** no mundo exterior continua fora: só pelas portas.

## 2.13.0 — `mine` é sempre do dono do Brain

- **Lista `mine` preenche o dono**: na TUI e no painel, escolher a lista `mine` põe o dono em `eu` (sair de `mine`
  limpa só o que era você). No ledger, `mine` sem dono grava o dono do Brain, e `mine` com outra pessoa é
  **recusado** ("é waiting"); ação nova de outra pessoa, sem lista dita, nasce `waiting` (antes herdava `mine`).
  Trocar o dono de uma `mine` pede mudar a lista junto (`--list waiting`).
- **"eu" vale o dono do Brain**: `eu`, `Eu` ou `EU` em `--owner`, `--people` e no JSON do `brain add`.
- **TODO do painel filtra pela lista `mine`**, sem exigir que você seja o dono (a TUI sempre foi assim): some a
  diferença entre as duas telas. Cartão de `mine` com dono antigo diferente mostra quem é; a paleta (`⌘K`) também
  fecha e marca "fazendo" essas ações. A semente da demo deixou de ter uma `mine` do Caio-demo.
- Dado antigo não é reescrito: `mine` com outro dono continua no ledger; editar a ação na TUI/painel já vem com
  `eu` preenchido e o comando mostra a correção.

## 2.12.0 — filtros em cascata (TUI e painel)

- **`/` empilha filtros**: o primeiro `/` filtra a lista; `/` de novo abre um filtro
  novo que refina **o que sobrou** do anterior, quantos você quiser. `esc` tira um
  por vez, o último aplicado primeiro (dentro do campo, `esc` desfaz só aquele
  nível). Enter com o campo vazio não cria nível. Cada lista (painel/aba na TUI,
  página no painel) guarda os seus.
- **Filtro à vista**: na TUI o título do painel mostra `⌕ filtro: a › b`, o rodapé
  diz `N de M · filtrado de T`, a lista vazia nomeia a corrente inteira e a barra
  de dicas ganha `esc tira filtro (n)`. Antes só aparecia no detalhe ampliado.
- **Painel HTML com a mesma tecla**: `/` agora filtra os cartões e linhas da página
  (antes abria a paleta), com a mesma cascata e o mesmo `esc`; uma barra no topo
  mostra as fichas de cada filtro (clicáveis para tirar), a contagem `N de M` e o
  "não consta". A paleta de busca e comandos segue em **⌘K** e ganhou o **`g`**,
  como na TUI. Na TUI, um id exato no 2º nível continua mostrando o que se liga a
  ele (dentro do que sobrou); no painel o filtro é por texto.

## 2.11.0 — molde das issues e validadores de dado sensível

- **Molde por tipo** para tudo que o cérebro publica no GitHub: `sugestao`, `bug` e `framework` (proposta de
  código aceita). Cada campo vira `### Título`, igual ao que os formulários novos de `.github/ISSUE_TEMPLATE/`
  (Sugestão, Bug, Proposta de código) escrevem — issue do cérebro e issue à mão têm a mesma cara.
  `brain feedback template --kind …` imprime o molde; o agente é obrigado a segui-lo (`--body-file`).
- **Validadores públicos** (`brainlib/publicguard.py`) em todo caminho que publica: pessoas e domínios do
  ledger, IDs do vault, **prints/imagens**, links externos e internos, e-mails reais, @menções, telefone,
  CPF/CNPJ, IP e IDs opacos do Drive/Slack. Recusam sem override e sem ecoar o valor (só tipo e linha).
  Exemplos usam sempre a padaria fictícia (`marina-demo`, "Padaria Pão Quente"). Guia: `guides/feedback-issues.md`.
- **`brain feedback revise FB-####`** corrige título/corpo de um FB que ainda não virou issue (evento
  `feedback.revised`; o ledger continua append-only) e liga o FB à proposta que o originou.
- `[feedback].allow_hosts` libera hosts extras em links do texto público.
- **Título padronizado**: `[Sugestão] …`, `[Bug] …`, `[Proposta] …` (proposta de código aceita). O **id local
  (`FB-####`) não sobe mais** — nem no título nem no rodapé da issue: é numeração da instância e geraria
  duplicidade no repo público. Tag escrita à mão é trocada pela oficial; o `push` recusa qualquer id local no texto final.

## 2.10.1 — token do GitHub no setup

- **Setup › Portas** explica como criar o token da porta 7 (fine-grained: Issues
  Read and write no repo do framework; clássico `public_repo` para quem não é
  colaborador), valida o token e confere que o repo está visível e com Issues
  ligadas. O valor continua indo só para `config/.env`, mascarado.
- **`brain doctor`** avisa quando há sugestão (`FB-####`) na fila sem
  `GITHUB_TOKEN`, ou ainda não publicada.

## 2.10.0 — propostas de código viram issue + checagem de docs em lote

- **Proposta `framework`**: `brain proposal add --kind framework` é a proposta
  que muda o código ou a estrutura do próprio cérebro. Ela carrega o texto
  **público** da issue (`--issue-title`/`--issue-body`), que você vê ao decidir.
  **Aceitar = aprovar a issue**: o `proposal accept` registra um `FB-####` e
  publica no repo do framework (porta 7). Rejeitada, nada sobe; sem token ou
  rede o aceite vale e o `FB` fica `pendente`. O texto é barrado se citar IDs
  do vault (`TASK-…`, `OPP-…`) além das regras de dado pessoal de sempre. TUI
  mostra "Issue pública" na proposta.
- **`brain watch docs`**: lista as fontes `drive-doc` com o id e a última
  revisão lida (uma busca de metadados no Drive serve a todas) e, com
  `--revs`, diz quais ler (mudou ou nunca lida), quantas estão inalteradas e
  quais o Drive não devolveu. O `/update` passa a checar os one-pagers em lote
  em vez de uma fonte por vez.
- **Fonte `granola`** no `watch.toml` (reuniões e transcrições pelo MCP do Granola, um item por
  reunião) e o `/dump` as trata como reunião (`RAW/…/meetings/`).

## 2.9.2 — fechadas recentes sempre à vista na TUI

- **Paridade com a coluna "Feita" do painel**: na aba **Minhas** da TUI, as
  ações fechadas nos últimos 14 dias agora ficam sempre no fim da lista —
  antes elas só apareciam depois de apertar `a`, e sumiam de novo ao trocar
  de vista. O que foi feito fica visível sem caçar atalho.
- `a` na aba Minhas alterna **só recentes** ↔ **todas** (fechadas antigas e
  descartadas continuam só em "todas", como no painel). Nas abas
  Aguardando/Observando o padrão segue só abertas.
- Vistas de prazo (`v`) continuam só com abertas — a mesma regra do painel.
  Guia §8 atualizado.

## 2.9.1 — paridade CLI × TUI × painel (auditoria dupla)

- **Painel usa a ponte única**: todo gesto passa pelo `runCommand` — no modo
  retrato o comando copiado leva `--by owner` como no vivo (antes 12 atalhos
  copiavam sem, e um copiava uma linha que não era comando).
- **Fechar/reabrir no painel viram diálogo** com os campos da TUI (como foi +
  resultado, que vira entrega WIN; motivo) — tecla, ficha, arrasto e paleta.
- **Gates de verdade no foco**: aprovar pede a resposta literal, aplicar
  escolhe ics ou google (não mais `--mode google` fixo), planejar roda
  `focus plan --days` e o sync escolhe dry-run ou aplicar.
- **Porta 2 no painel**: aprovar mensagem mostra o texto exato e espera seu
  `enviar N`; cancelar cobre rascunho e aprovada, com motivo.
- **Guardas de estado**: mutação só em ação aberta (como a TUI), responder/
  aceitar/descartar só no que está aberto, publicar/descartar de OPP nos
  estados que fazem sentido; `s` numa ação bloqueada explica e não move
  (agora igual nos três: o status "bloqueada" é derivado do `blocked_by`).
- **Seleção respeitada**: outbox, feedback e cobrança agem sobre o item
  selecionado (antes o primeiro da lista).
- **Teclas da TUI no painel**: `v`/`O`/`a` no TODO (vista · ordem · todas),
  `G`/`P`/`S` em Projetos, `u`/`a` em Pessoas, `s`/`i` na Matriz, `c`/`x`/`p`
  na ficha de oportunidade, `a`-nova-opp no processo, `A`/`x` de publicação,
  `s`/`v`/`i` na Configurações › Memória e `o`-testar-online na Saúde
  (`doctor --online` entrou na allowlist do serve).
- **Saúde só na Configurações** em toda parte: o link antigo `#health`
  redireciona, a paleta lista as três faces + as páginas cfg, e o
  portfolio.html não lista mais páginas que não existem lá.
- **TUI**: `n`-nota no Resumo (paridade com o painel), rascunho com canal,
  e a régua de cobertura dos testes anda até a folha do argparse (os
  `memory models …` deixaram de escapar da checagem).

## 2.9.0 — provedores da memória + face Configurações

- **Provedores LLM · embeddings · reranker** (plano memory-providers.md): o wizard pergunta
  os três slots (recomendados — Haiku/Sonnet cenário B, Qwen3-Embedding/Reranker-8B na Fireworks —
  ou custom), o `brain memory providers show|set` grava sem wizard, e o compose injeta o
  config/.env (`env_file`). Chave só no .env, nunca no config/view/painel.
- **Face [Configurações] na TUI** (Execução · Portfólio · Configurações): Memória
  (Provedores · Harnesses) e Instância (Saúde — que saiu de Execução › 1). Wizard da memória
  abre num terminal suspenso (w); provedor muda por formulário (s).
- **Painel**: mesma face Configurações — stack atual, harnesses e formulário de troca
  (mesma linha da TUI/CLI, pela ponte do serve).
- **Doctor**: provedor de nuvem sem chave = erro; conexão harness↔Hindsight verificada
  (banco existe, recall responde, configs apontando para cá) com o comando que corrige.
- Reranker local segue reprovado (benchmark 2026-11-07, §4.2 do plano): default `off`/RRF;
  nuvem entra pelo menu, com o aviso de egress.

# Novidades — Segundo Cérebro

O que mudou em cada versão, em linguagem humana. Para atualizar: `brain update`
(ou `brain setup --only comando` se o `brain` ainda não estiver no PATH).
Mantido pelo dono do framework a cada remessa — veja `guides/commands.md` § upstream.

## 2.8.0 — 2026-11-06

- **Rubric do ICE — a metodologia de pontuação faz parte do Brain.** O que cada nota
  (1–5) significa em impacto, confiança e facilidade — critério, horas/proveniência/prazo e
  vínculo com as medidas de sucesso — mora num único lugar (`brainlib/ice_rubric.py`) e chega
  a todas as superfícies:
  - **CLI:** `brain opportunity rubric` (tabela plana, `--md`, `--json`); o erro de escala e o
    `score --help` apontam para ele.
  - **TUI:** o formulário do ICE (`i`) troca os campos livres por **dropdowns** com o rótulo de
    cada nota e a pergunta do eixo; apoio embaixo de cada campo mostra o critério completo e,
    com horas declaradas, a faixa sugerida (acima dela: aviso "vale a menor nota"). `?` abre a
    **Metodologia · ICE** por cima do formulário (esc volta com tudo preservado), e o comando
    "Metodologia ICE" da paleta abre a mesma tela. Sem as 3 escolhas, não confirma.
  - **Painel:** os mesmos dropdowns e apoio por nota; `?` (mesmo com foco no select), o botão
    "? orientações", o item da paleta e o link "metodologia" na Visão abrem a metodologia
    empilhada — esc fecha só a ajuda. A ficha da oportunidade (TUI e painel) passa a ler o ICE
    pelo rótulo de cada eixo.
  - **Agente e guias:** a triagem (`/opportunity triage`) pontua pelo rubric com fonte por eixo;
    o bloco "Como pontuar o ICE" do guia é **gerado** do módulo (um teste impede divergência);
    MCP `opportunity` aceita `rubric: true`.
  - O score continua I×C×F (1–125), calculado pelo CLI — mudou a orientação, não a contabilidade.

## 2.7.0 — 2026-11-05

- **Dossiê determinístico — `brain memory dossier <ID|alias>` (Fase 5)** — a página
  "onde estamos com X?" montada na hora da leitura: ficha viva do índice, decisões e
  entregas ligadas, e os melhores trechos da memória com as tags da entidade — todo
  parágrafo com fonte, nada pré-computado, nunca velho. Funciona até com a memória
  desligada (ficha + DEC/WIN). O `/person` e o `/project` ganham a "Leitura atual", e o
  `/ask` usa o dossiê quando a rota detecta a entidade. **Setup `embed` completo.**
- **Mental models (Fase 8, modo full)** — `brain memory models sync|refresh|list|show`:
  páginas vivas por goal, projeto e pessoa, criadas com o estado do ledger colado na
  pergunta-fonte, tags da entidade e refresh delta com intervalo mínimo de 24h; projetos
  que fecham saem sozinhos no próximo sync. Exige `full` + `mental_models = true` (o
  refresh usa a sua chave — meça com `brain memory cost`). Contrato validado ao vivo na
  1.2.0; o refresh completo se valida na instância real, com a chave.
- **Eval do conjunto-ouro (Fase 0)** — `brain memory eval`: roda ~60 perguntas curadas
  (`vault/eval/memory-gold.jsonl`, exemplo genérico no `template/`) contra roteador e
  banco, com recall@k, MRR, citação, itens injetados, abstenção e tokens por tipo —
  determinístico, sem LLM no julgamento. O agente propõe as perguntas; você revisa.

## 2.6.0 — 2026-11-05

- **O hook de recall do Claude Code ficou cirúrgico (Fase 4 do plano)** — cada mensagem
  recebe só o contexto da camada certa: pergunta de **estado** (`TASK-…`, "o que está
  atrasado?", título de projeto) injeta até 3 linhas exatas do ledger e **nem consulta**
  o banco vetorial; pergunta **literal** ("o que foi dito", "exatamente", aspas) traz
  1–2 trechos de origem; **pessoa** junta ledger + contexto com a consulta expandida
  pelos aliases; o resto recebe até 3 itens de contexto. Teto de **5 itens** por
  mensagem e **abstenção**: nada relevante (corte 0.62) = silêncio.
- **Degradação com prazo** — a perna vetorial tem 700 ms de orçamento próprio; Hindsight
  lento ou fora deixa a perna do ledger responder sozinha. O velho comportamento (toda
  mensagem ≥12 caracteres virava busca semântica com até 8 itens) acabou.
- **`brain route "<pergunta>"`** — o mesmo classificador na CLI (o `/ask` passou a usá-lo
  antes de buscar). Configurável: `BRAIN_RECALL_ROUTE` (`off` | `ledger` | `embed`, padrão
  `embed`), corte, teto e prazo por variável de ambiente.
- Corrigido no caminho: nomes com hífen ("Marina-demo") agora casam nos aliases do
  roteador (o tokenizador cortava no hífen e a perna de pessoa nunca disparava).

## 2.5.0 — 2026-11-05

- **O banco de memória emagrou e ficou mais inteligente (Fase 3 do plano)** — o que
  entra no Hindsight agora é o que memória semântica resolve: **o RAW como está** (a
  letra exata) + **decisões e entregas como documentos curtos** (`ledger/DEC`, com
  projeto e quem decidiu). Artefatos do PROCESSED, páginas de ação/pessoa e
  PLANNING/PROFILE **saem do vetor** — busca por palavra já é do índice SQLite/FTS5,
  estado já é do `brain query`, e nada fica velho entre syncs.
- **Cada documento nasce com identidade** — tags do ledger (`pessoa:`, `proj:`,
  `goal:`, `sem-artefato:1`), **data do mundo** e **entidades por alias** (top-level,
  alimentando o grafo do servidor); os aliases das pessoas são registrados no banco no
  `memory setup`. O sha do documento cobre texto + identidade: alias novo ou `/dump`
  reprocessado ⇒ o documento reenvia sozinho com a identidade nova.
- **RAW sem `/dump` espera** — no `embed`, arquivo arquivado sem processamento espera
  7 dias (`degraded_after_days`) e então entra **degradado** (tag `sem-artefato:1`,
  sem entidades) — melhor ter a letra exata indexada do que não ter; quando o `/dump`
  processa, ele é reenviado com identidade plena.
- **Ao atualizar**: o próximo `memory sync` faz a limpeza por deleção sombra (os docs
  que saíram do corpus são apagados do banco) e reenvia os RAW com as tags novas —
  custo US$ 0 no embed. Não precisa de `rebuild`.

## 2.4.0 — 2026-11-05

- **Memória em banco único (`brain`)** — os dois bancos antigos do modo `embed`
  (`brain-raw` + `brain-mem`) viraram **um**, nos dois modos. Quem já usava roda
  `brain memory rebuild` e pronto: os bancos legados são apagados do servidor e o
  vault é reenviado (no `embed`, custo US$ 0). O doctor avisa enquanto houver bancos
  legados vivos no servidor.
- **Hindsight 1.2.0** — o servidor subiu de versão (pin por digest no compose). Entre
  outras: conserta a regressão que travava o reflect no Sonnet/Opus (mental models
  voltam a ser viáveis) e passa a validar o endpoint de embeddings no boot — **suba o
  LM Studio antes do `docker compose up -d`**. Máquina que já roda outro Hindsight no
  :8888 adota o servidor existente ou sobrepõe as portas por env (`HINDSIGHT_API_PORT`).
- **O servidor agora também guarda a memória dos seus agentes de código** —
  `brain memory harness install claude-code | cursor-cli | codex | hermes`: Claude
  Code, Cursor e Codex são cablados pelo instalador oficial apontados ao servidor do
  cérebro, o Hermes ganha a config local_external escrita pra você (o plugin em si
  pede confirmação interativa — o comando imprime a linha que falta). Memória dos
  agentes mora no banco próprio `hermes`, nunca tocada pelo `memory rebuild` e com
  proveniência por repo/harness. O wizard pergunta tudo isso no passo Memória, e o
  `brain memory harness verify` confere (banco, recall ping, configs).
- **Fresnness** — o `brain doctor --online` compara a versão do servidor com a última
  publicada lá fora (≤1×/dia, offline tolerado) e avisa quando há atualização —
  informação, nunca bloqueio. O caminho de atualização completo está no
  `guides/memory.md` (§ *Atualizar o Hindsight de versão* e § *Migração de instâncias
  antigas*).

## 2.3.0 — 2026-11-05

- **Promover oportunidade em qualquer nível** — `brain opportunity promote` ganhou `--level
  goal|project|deliverable`: a oportunidade pode virar um **goal novo** (`--level goal`), um
  **projeto num goal** (`--goal GOAL-#`, como antes) ou um **entregável num projeto**
  (`--project PROJ-#`) — as 5 oportunidades do mesmo processo agora cabem como entregáveis do
  mesmo projeto. Sem `--level`, o alvo decide: `--goal` ⇒ projeto, `--project` ⇒ entregável.
  O gate continua o mesmo: sem o seu "ok" literal, só o diff do `goals.md`. `em-andamento`
  continua nascendo só da promoção, de qualquer nível. TUI (`p`) e painel têm o seletor de nível.

## 2.2.0 — 2026-11-05

- **Plano com abas de status (TUI)** — o painel **[3] Plano** agora troca entre
  `Todos · Ativo · Congelado · Depois · Finalizado` (`[` `]` como em qualquer painel).
  A aba filtra goals e projetos pelo status: goal no status abre com todos os projetos;
  projeto no status aparece dentro do goal, como contexto. Cada aba mostra a contagem.
- **Status novo para goal/projeto: `depois` e `finalizado`** — além de `ativo` e
  `congelado`. `depois` é o que fica de lado por escolha (sai da saúde normal, sem
  alertar); `finalizado` é o encerramento (o antigo `fechado` continua valendo na
  entrada e nas linhas antigas do `goals.md` — o cérebro lê como `finalizado`).
  Vale na CLI (`brain plan edit … --status`), no formulário da TUI (`e`) e no painel HTML.

## 2.1.0 — 2026-11-05

- **Setup assistido (`brain setup`)** — o cérebro nasce com um wizard: identidade, rotina,
  comando `brain` no PATH, TUI, noturno, portas e memória. Re-executável, pula o pronto.
  Para máquina nova: `install.sh` (uma linha, do zero ao wizard).
- **Memória em dois modos — `embed` e `full`** — `embed` segue igual (dois bancos, zero
  LLM, nada sai da máquina); `full` é o novo modo com extração de fatos (banco único,
  sua chave de API, medidor de custo mensal). Trocar de modo é um comando, e voltar também.
- **Consultas de estado exatas (`brain query`)** — "o que está atrasado?", "o que a
  Marina me deve?" deixam de depender de busca semântica: um índice SQLite próprio
  responde com precisão, na hora, e o painel de busca usa o mesmo índice.
- **Hook mais calmo** — perguntas de prazo/atraso/ID agora recebem a resposta exata do
  livro-razão (até 3 linhas) em vez de trechos soltos de transcrição; o resto silencia.
- **Versão visível + aviso de atualização** — o número da versão aparece no canto do
  painel e da TUI, com aviso de atualização disponível e as novidades a um clique.
- Dezenas de correções de estabilidade na TUI, no painel, no serve e no lock do estado
  (ondas 2.0.x).

## 2.0.0

- A constituição v2: zonas, livro-razão único, portas estreitas com aprovação, IDs novos
  (`TASK-####`, `DEC-####`…) aceitando os antigos, TUI Textual, painel HTML offline,
  portfólio de processos e oportunidades, portas de foco/mensagens/publicação/backup,
  noturno e MCP somente-leitura.
