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
