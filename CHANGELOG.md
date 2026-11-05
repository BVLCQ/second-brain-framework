# Novidades — Segundo Cérebro

O que mudou em cada versão, em linguagem humana. Para atualizar: `brain update`
(ou `brain setup --only comando` se o `brain` ainda não estiver no PATH).
Mantido pelo dono do framework a cada remessa — veja `guides/commands.md` § upstream.

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
