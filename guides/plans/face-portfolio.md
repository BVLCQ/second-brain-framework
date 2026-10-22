# Plano — Face "Portfólio" (Processos · Oportunidades) + carrossel de faces na TUI

Executor: Sonnet. Cada passo termina com `python3 -m unittest discover tests` verde
e um commit local (sem push — o push passa pelo gate `upstream`). Leia `AGENTS.md`
e `guides/user-guide.md` antes de começar. Repo público: nenhum dado do dono no
código, nos testes ou nos exemplos (use `marina-demo`, `example.com`, áreas
genéricas como `Operações`, `Growth`).

## Decisões já tomadas (não re-litigar)

- **Face** = conjunto de painéis 1–5 com abas próprias; o painel 6 (Log) é comum.
  `Tab` avança em carrossel (última → primeira); `Shift+Tab` volta. Faces:
  `Execução` (os painéis atuais) e `Portfólio` (novos). Novas faces entram só
  declarando-se em `FACES`.
- **Oportunidade e iniciativa são a mesma entidade** (`OPP-####`) em estágios.
  `tipo`: `melhoria-de-processo` · `novo-processo` · `estruturante`.
- **Prefixos longos para entidades novas**: `PROC-####` (processo), `OPP-####`
  (oportunidade). As entidades antigas (`A`, `D`, `E`, `R`, `M`, `S`, `F`, `G#`,
  `P#`) **não mudam** neste plano (ver passo 12, opcional).
- **Áreas** são entidade do ledger (`area.added`), com id slug, nome e aliases —
  o dono cadastra quantas quiser (`brain area add`). Não ficam em config.
- **Processo**: área, título, responsável (1 pessoa), executores (lista de
  pessoas), recorrência, duração por execução, playbook (doc do Drive),
  documentos, ferramentas, entradas→saídas, dores, maturidade 1–5, notas.
  O CLI calcula **horas/mês** = execuções/mês × duração × nº de executores.
- **Oportunidade**: área, processo (opcional), tipo, título, problema, sugestão,
  ganho esperado (texto + `horas_mes_poupadas` opcional), documentos, status,
  ICE, goal, projeto, pessoas, notas.
- **ICE** = Impacto × Confiança × Facilidade, cada um 1–5 (score 1–125). O CLI
  calcula; o LLM nunca. O agente pode **sugerir** ICE (`ice_suggested`, como o
  `due_suggested` das ações): aparece em rosa até o dono confirmar ou mudar.
- **Status** (o dono pode ir e voltar livremente entre eles):
  `ideia → triagem → priorizada → em-andamento → piloto → validando → entregue`,
  e os laterais `em-espera` e `descartada` (ambos exigem `--reason`).
  `em-andamento` só é alcançado por `promote` (exige projeto vinculado).
- **O agente cria oportunidade sozinho** (`by agent`, `prov observado`,
  `--source` obrigatório), sempre com status `ideia`. Daí em diante só o dono move.
- **Promover** = criar projeto num goal (gate estrutural): diff → "ok" do dono →
  `plan add-project --approval` + evento `opportunity.promoted` ligando OPP↔P#.
- **Playbooks** moram no Drive. Vínculo processo↔doc via watch: o `/update` só
  re-lê o doc quando o `modifiedTime` mudou (mecanismo `--item/--rev` do
  `brain snapshot`, que já existe).
- **Fora do escopo**: sync/escrita em Jira/Sheets/Notion; R$; aprovação de
  terceiros; versionamento de playbook.

## Passo 1 — Schema e estado (núcleo)

Arquivos: `brainlib/schema.py`, `brainlib/state.py`.

1. Constantes novas em `schema.py`:
   - `PROC_ID = re.compile(r"^PROC-\d{4,}$")`, `OPP_ID = re.compile(r"^OPP-\d{4,}$")`,
     `AREA_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")`.
   - `RECURRENCE = {"diaria","semanal","quinzenal","mensal","trimestral","sob-demanda","por-evento"}`.
   - `OPP_STATUS = {"ideia","triagem","em-espera","descartada","priorizada","em-andamento","piloto","validando","entregue"}`.
   - `OPP_KINDS = {"melhoria-de-processo","novo-processo","estruturante"}`.
   - `DOC_KINDS = {"playbook","one-pager","planilha","artefato","apresentacao","outro"}`.
2. Tipos de evento em `TYPES`:
   - `area.added` (new, req `name`) · `area.updated`.
   - `process.added` (new, prefix `PROC`, req `title`, `area`) · `process.updated` ·
     `process.retired` (req `reason`).
   - `opportunity.added` (new, prefix `OPP`, req `title`, `area`) ·
     `opportunity.updated` · `opportunity.status` (req `status`) ·
     `opportunity.scored` (req `impact`, `confidence`, `ease`) ·
     `opportunity.evidence` (req `source`) · `opportunity.promoted` (req `project`, `goal`).
   - `doc.linked` (req `target`, `kind`, `ref`) — `target` é `PROC-…` ou `OPP-…`;
     `ref` é URL, id do Drive ou caminho RAW/PROCESSED · `doc.unlinked` (req `target`, `ref`).
3. `validate()`:
   - pessoas (`owner`, `executors[]`, `people[]`) via `_person`; `area` existe;
     `process` (na OPP) existe; `goal`/`project` via `_plan_node`.
   - `recurrence ∈ RECURRENCE`; `sob-demanda`/`por-evento` exigem `per_month` (número > 0).
   - `duration` aceita o formato de `util` (`_DUR_RE`: `1h30m`, `45m`); guarde em minutos.
   - `maturity`, `impact`, `confidence`, `ease` inteiros 1–5.
   - `opportunity.status`: `em-espera`/`descartada` exigem `reason`; `em-andamento`
     só se a OPP já tem `project`; **agente** só pode gravar status `ideia`
     (`by agent` com outro status → erro). `opportunity.added` por agente exige `source`.
   - `ice_suggested` só com `by agent`; `opportunity.scored` do dono limpa a sugestão.
   - `opportunity.promoted`: `project` existe no PLANNING e pertence a `goal`.
   - Incluir `area`, `process`, `opportunity` na lista de entidades que precisam existir
     em eventos não-`new`.
4. `state.py`:
   - dataclasses `Area`, `Process`, `Opportunity`, `DocLink` (dentro de Process/Opportunity
     como lista). `Opportunity.score` = propriedade (I×C×E ou `None`).
     `Process.hours_month` = propriedade: execuções/mês (`diaria`=21, `semanal`=4.33,
     `quinzenal`=2.17, `mensal`=1, `trimestral`=1/3, demais = `per_month`) × minutos/60 ×
     `max(1, len(executors))`. Constante `RUNS_PER_MONTH` num lugar só.
   - `State.areas`, `State.processes`, `State.opportunities`; `collection()` conhece-as.
   - `next_id`: troque o dict fixo por um mapa `PREFIX_COLL` que aceite prefixos de
     qualquer tamanho; `PROC`/`OPP` → 4 dígitos. Não mude o formato dos antigos.
   - `apply()`: um ramo por tipo novo; `opportunity.status` guarda histórico
     `(date, from, to, reason)`; `opportunity.evidence` acumula fontes (contador).
   - `person.merged` deve trocar ids em `owner`/`executors`/`people` das entidades novas
     (siga o `swap` existente).
5. Testes (`tests/test_brain.py`): validação de cada regra acima, horas/mês, score,
   agente barrado de mover status, merge de pessoa propagando.

Pronto quando: `brain validate` passa no vault real e os testes novos passam.

## Passo 2 — CLI

Arquivo: `brainlib/cli.py` (siga o padrão de `action`/`decision`).

- `brain area add <slug> --name "…" [--alias …]` · `area update` · `area list`.
- `brain process add "título" --area … --owner … [--executor … (repetível)]
  [--recurrence …] [--per-month N] [--duration 1h30m] [--tools …] [--io "entradas → saídas"]
  [--pain … (repetível)] [--maturity 1-5] [--note …] [--by owner|agent] [--source …]`
  · `process update PROC-#### …` · `process retire PROC-#### --reason` ·
  `process show` · `process list [--area] [--gaps]`.
- `brain opportunity add "título" --area … [--process PROC-####] [--kind …]
  [--problem …] [--suggestion …] [--gain "…"] [--hours-saved N] [--person … (repetível)]
  [--goal G#] [--by …] [--source …]`. Antes de gravar, roda o **detector de
  duplicatas** (passo 4) e avisa; `--force` grava mesmo assim.
  · `opportunity update` · `opportunity status OPP-#### <status> [--reason]` ·
  `opportunity score OPP-#### --impact N --confidence N --ease N [--suggest --reason "…"]` ·
  `opportunity evidence OPP-#### --source <artefato>` ·
  `opportunity promote OPP-#### --goal G# [--title …] [--approval "…"]` ·
  `opportunity show` · `opportunity list [--status] [--area] [--sort score]`.
- `brain doc link PROC-####|OPP-#### --kind … --ref <url|id|caminho> [--title …] [--watch]`
  · `doc unlink`. Com `--kind playbook --watch` e `ref` do Drive, também cria a fonte no
  watch (passo 3).
- **promote** sem `--approval` imprime o diff proposto do `goals.md` (título, `dono`,
  `por quê` = problema resumido, entregáveis iniciais vazios) e sai com código de gate.
  Com `--approval`, reutiliza a função de `plan add-project` (não duplique) e depois
  grava `opportunity.promoted` + `opportunity.status em-andamento`, tudo no mesmo
  `commit` do ledger. `BRAIN_NIGHTLY=1` recusa.
- `brain search` passa a indexar processos e oportunidades (título, problema, sugestão,
  dores, notas).
- Testes de CLI para cada subcomando (há exemplos em `test_brain.py`).

## Passo 3 — Playbooks via watch

Arquivos: `brainlib/watch.py`, `config/watch.toml.example`, `commands/update/SKILL.md`.

- Aceitar fonte `kind = "drive-doc"` com campos `doc` (id do Drive) e `link`
  (`PROC-…`/`OPP-…`). Validação: `link` existe no ledger.
- `brain doc link … --watch` chama a mesma função de `brain watch add`
  (key estável `playbook-<proc-id-minúsculo>`).
- No `/update`: para cada `drive-doc`, pegar `modifiedTime` pelo MCP do Drive →
  `brain snapshot --key … --item <doc> --rev <modifiedTime> --check`; se já lido, pular;
  senão exportar e snapshotar. O `/dump` registra o artefato com `data.link = PROC-…`
  e o processo mostra "playbook atualizado em …".
- Teste em `tests/test_watch.py`.

## Passo 4 — Modelo e ferramentas determinísticas

Arquivos: `brainlib/model.py` (+ um módulo novo `brainlib/portfolio.py` para não inchar o model).

`portfolio.py` (sem LLM):
- `gaps(state)`: áreas sem processo; processos sem playbook, sem responsável, sem
  recorrência/duração; oportunidades sem ICE, com ICE só sugerido, ou paradas há mais de
  30 dias (`date` do último evento).
- `matrix(opps)`: quadrantes por Impacto (≥3 alto) × Facilidade (≥3 alta):
  `ganho rápido` (alto/alta), `aposta` (alto/baixa), `preencher depois` (baixo/alta),
  `evitar` (baixo/baixa).
- `duplicates(title, problem, opps)`: similaridade de Jaccard sobre tokens normalizados
  (minúsculas, sem acento, sem stopwords PT-BR curtas); limiar 0,5; devolve top 3.
- `funnel(opps)`: contagem por status. `by_area`, `by_goal`.
- `gain_hours(opp, state)`: `hours_saved` declarado ou nada (não estima sozinho).
- Em `model.build()`: seção `portfolio` com processos, oportunidades (com score,
  quadrante, evidências, histórico de status), áreas, lacunas, funil, matriz.
- Testes unitários para cada função.

## Passo 5 — Views FRESH e painel HTML

Arquivos: `brainlib/render_md.py`, `brainlib/render.py`, `brainlib/assets/dashboard.html`,
`template/FRESH/` (se houver placeholders).

- `FRESH/processes.md` (por área; horas/mês; responsável; playbook com data da última
  leitura), `FRESH/opportunities.md` (funil, ranking por score, matriz em tabela,
  lacunas), `FRESH/records/processes/PROC-*.md`, `FRESH/records/opportunities/OPP-*.md`.
  Todas com `generated-at:` e `fontes:`.
- Ficha de OPP aceita `status:` editável, como a ficha de ação: a `harvest` colhe e grava
  `opportunity.status` (by owner). Validar o valor; inválido → aviso, não grava.
- Dashboard: aba "Portfólio" (processos, oportunidades, matriz).
- `home.md`: uma linha "Portfólio: N oportunidades · M priorizadas · K lacunas".
- Atualizar a lista de views em `AGENTS.md` e no guia.

## Passo 6 — TUI: carrossel de faces (infra, sem painéis novos ainda)

Arquivos: `brainlib/tui/store.py`, `brainlib/tui/app.py`, `brainlib/tui/tui.tcss`, `tests/test_tui.py`.

1. `store.py`: `PANELS` vira `FACES = [("Execução", PANELS_EXEC), ("Portfólio", PANELS_PORT)]`,
   onde `PANELS_PORT` começa com abas placeholder. Mantenha `PANELS` como alias para a face
   atual só se simplificar; o ideal é `store.items(face, panel, tab, …)` e
   `store.locate(node) → (face, panel, tab)`.
2. `app.py`:
   - `self.face = 0`. Todo estado de navegação indexado por painel passa a ser indexado por
     face: `self.tab[(face, p)]`, chaves `(face, p, t)` em `sel_idx`, `sel_id`, `win`,
     `_items`; `self.p`/`self.lp`/`self.zoom`/`self.filt` guardados **por face**
     (dict `self.nav[face]`), para cada face voltar onde estava.
   - Teclas: `tab` → `face_move(+1)` com módulo (carrossel); `shift+tab` → `face_move(-1)`.
     **Atenção:** o Textual tem binding padrão de `tab`/`shift+tab` para foco, e os
     formulários em `modals.py` dependem dele. Trate a tecla só quando a tela ativa é a
     principal (`len(self.screen_stack) == 1`); em modal, deixe o comportamento padrão.
     Teste os dois casos.
   - `Tab` funciona também com o Detalhe ampliado (zoom) e com filtro ativo: troca de face e
     o zoom/filtro ficam salvos na face de origem.
   - Faixa de faces: `#bar` (ou um `Static` novo no topo) mostra `Execução · [Portfólio]`
     com a atual em negrito. Clique numa face troca para ela.
   - O catálogo de comandos (lista no topo de `app.py` com `(painel, aba, tecla)`) ganha a
     face: `(face, painel, aba, tecla)`. `ctx_keys`, `help` (`?`), palette (`:`) e
     `jump()` passam a considerar a face. `jump("OPP-0003")` troca de face sozinho.
   - O título de cada painel (borda) vem da face atual.
3. Testes (pilot do Textual, como os existentes): Tab cicla 0→1→0; Shift+Tab volta; seleção
   preservada por face; Tab dentro de modal continua mudando campo; `jump` entre faces.

Pronto quando: a face Execução se comporta exatamente como hoje (todos os testes antigos
verdes) e a face Portfólio abre vazia com os títulos certos.

## Passo 7 — TUI: painéis da face Portfólio

Arquivos: `brainlib/tui/store.py`, `rows.py`, `app.py`, `modals.py`.

| # | Painel | Abas | Conteúdo |
|---|---|---|---|
| 1 | Visão | Resumo · Por área · Por goal | funil, top 5 por score, contagem de lacunas; agrupados |
| 2 | Processos | Todos · Por área · Lacunas | linha: `PROC-0003 · título · área · resp. · 6,5 h/mês · ⚠ sem playbook` |
| 3 | Oportunidades | Triagem · Priorizadas · Em curso · Arquivo | Triagem = ideia+triagem; Em curso = em-andamento+piloto+validando; Arquivo = entregue+em-espera+descartada. Linha com score (rosa se sugerido) e quadrante |
| 4 | Matriz | Matriz · Ranking | 2×2 desenhado em texto com os IDs em cada quadrante; ranking por score |
| 5 | Registro | Áreas · Documentos | áreas com contagens; todos os `doc.linked` com alvo e tipo |

Detalhe (painel direito): ficha completa, histórico de status, evidências (artefatos
ligados), documentos (Enter abre URL), processo ligado, projeto/goal ligado e progresso.

Teclas (todas chamam `./brain`, com a linha exata no log):
- Processos: `n` novo · `e` editar · `l` ligar doc · `o` abrir playbook · `a` nova OPP a
  partir deste processo · `x` aposentar.
- Oportunidades: `n` nova · `e` editar · `s` status (picker com os 9 status; laterais
  pedem motivo) · `i` ICE (3 campos 1–5; mostra o score calculado pelo CLI depois de
  gravar) · `c` confirmar ICE sugerido · `l` ligar doc · `v` adicionar evidência ·
  `p` **promover** (gate: reaproveite `gate_for_plan`, mostra o diff, exige a resposta
  literal do dono) · `x` descartar.
- Áreas: `n` nova · `e` editar.
- ⚡ agente: `O` one-pager da OPP selecionada (passo 8).

Testes: cada aba renderiza com dados de demo; cada tecla monta a linha de comando certa
(siga `test_every_action_detail_renders`).

## Passo 8 — Skills e constituição

Arquivos: `commands/process/SKILL.md`, `commands/opportunity/SKILL.md`,
`commands/dump/SKILL.md`, `commands/share/SKILL.md`, `AGENTS.md`, `guides/user-guide.md`.

- `/process <termo|PROC-#>`: panorama do processo (ou cadastro guiado se não existir).
- `/opportunity <termo|OPP-#>`: panorama; subcomandos `onepager OPP-#` (gera documento em
  `vault/reports/share/` a partir dos campos + evidências, pronto para `/publish`) e
  `triage` (percorre as OPP em `ideia`, propõe ICE sugerido com motivo).
- `/dump`: ao extrair dores/sugestões de melhoria de um item, checar duplicata
  (`brain opportunity add` já avisa) → se nova, criar com `--by agent --source …`
  (status `ideia`); se já existe, `opportunity evidence`. Processos citados e ainda não
  cadastrados → `process add --by agent --source …`.
- `/share portfolio [--area …]`: export do roadmap priorizado (ranking + matriz + status),
  sem jargão interno.
- `AGENTS.md`: tabela de IDs (`PROC-####`, `OPP-####`, áreas), tabela de comandos
  (`/process`, `/opportunity`), regra "agente só cria OPP em `ideia`; promover é gate",
  views novas.
- Guia do usuário: seção "Face Portfólio".

## Passo 9 — MCP somente-leitura

Arquivo: `brainlib/mcp_server.py`. Ferramentas `portfolio_overview`, `process`,
`opportunity`, `opportunities` (filtros status/área). Teste de `call_tool`.

## Passo 10 — Demo e exemplos

`brainlib/demo.py`: 3 áreas, 3 processos, 5 oportunidades em status variados (uma
promovida) com dados genéricos. `config/watch.toml.example`: exemplo comentado de
`drive-doc`.

## Passo 11 — Fechamento

- `./brain validate`, `./brain render`, `./brain tui` aberto manualmente nas duas faces.
- `./brain upstream scan`; propor ao dono os arquivos, a mensagem do commit e o resultado
  da varredura. Push só após "ok".

## Passo 12 — (opcional, decidir depois) prefixos longos para os IDs antigos

O ledger é append-only: `A-0146` não pode ser reescrito. Caminho possível sem quebrar
nada: aceitar aliases na **entrada** (`ACT-0146` ≡ `A-0146`, `DEC-`≡`D-`, …) e,
opcionalmente, um modo de exibição. Fica fora deste plano até o dono decidir.

> A seção "Pós-implementação" do plano original é local da instância do dono (cadastros e dados reais) e não vai para o repo público.
