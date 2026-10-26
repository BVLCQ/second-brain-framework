# Manual do Segundo Cérebro v2

Como usar o app de ponta a ponta: pastas, painel, comandos do chat,
CLI, calendário, Slack, memória, backup e o que o sistema se recusa a fazer.

O porquê de cada regra está em `guides/user-guide.md`. A lei, se houver
conflito, é `AGENTS.md`.

---

## 1. O que este app é

Um sistema **local**, para **uma pessoa**. Ele guarda a vida profissional em
arquivos que você pode abrir sem ele, e responde quatro perguntas:

| Pergunta | Onde a resposta mora |
|---|---|
| Para onde estou indo? | `PLANNING/goals.md` — goal → projeto → entregável |
| Quem decidiu o quê, quando, com base em quê? | decisões `DEC-####` no livro-razão |
| O que eu devo, o que me devem, o que é só contexto? | ações em três listas |
| O que foi entregue de verdade? | entregas `WIN-####` e entregáveis marcados feitos |

Há duas peças:

- **`./brain`** — o motor. Numera IDs, valida, calcula atraso, progresso e
  saúde, desenha o painel, planeja o foco e guarda as portas de saída.
  Python 3.11+ (mise.toml no repo), sem `pip`. Roda em segundos, sem rede, sem LLM.
- **O agente** (Cursor, Claude, Codex, …) — lê reunião, classifica, extrai,
  redige e julga. Toda conta e todo ID passam pelo `./brain`. O agente não
  edita o livro-razão na mão.

O app **não** substitui Jira, Slack, Gmail, Drive nem o calendário. Ele lê
esses mundos (via ferramentas do agente) e só escreve neles pelas portas do
capítulo 12.

---

## 2. Instalar e abrir pela primeira vez

```bash
cd ~/brain-v2
./brain init --owner-id seu-id --owner-name "Seu Nome"
```

Isso copia `template/` para `vault/` **sem sobrescrever** o que já existe,
cria `config/brain.toml`, `config/watch.toml` e `config/.env` (permissão 600)
e registra você como pessoa no livro-razão.

Se `vault/` e `config/brain.toml` já existem, o `init` não apaga nada: só
completa o que falta.

Ver o painel com dados fictícios, sem tocar no seu vault:

```bash
./brain demo --dir /tmp/brain-demo --open
```

Abre `vault/FRESH/dashboard/index.html`. Um arquivo só, funciona offline.
Se `--open` não achar navegador, abra esse caminho você mesmo.


No chat do agente, com a pasta `brain-v2` aberta, digite `/init`. A entrevista
tem quatro blocos (quem você é, goals, pessoas, o que observar). No fim o
agente mostra um diff de `PROFILE` e `PLANNING` e **espera um "ok"**. Silêncio
não grava a árvore.

O CLI acha a instância assim, nesta ordem: pasta passada por código de teste,
variável `BRAIN_HOME`, o diretório atual se nele (ou num pai) existir
`config/brain.toml` ou `vault/PLANNING/goals.md`, senão a pasta do próprio
`brain`. Rode os comandos de dentro de `~/brain-v2`.

---

## 3. Mapa do disco

```
brain-v2/                      framework (vai pro git)
├── brain                      comando
├── brainlib/                  motor (brainlib/tui/ é o cockpit opcional)
├── requirements-tui.txt       dependências travadas do TUI (opcional)
├── commands/                  o que o agente faz em cada /comando
├── guides/                    este manual e os guias curtos
├── config/*.example           modelos; os arquivos reais não vão pro git
├── template/                  semente do vault
├── scripts/google_auth.py     OAuth, uma vez
└── vault/                     a sua vida (cego pro git)
    ├── PROFILE/profile.md     quem você é (curado)
    ├── PLANNING/goals.md      a árvore (curada, com gate)
    ├── PLANNING/log.md        por que a árvore mudou
    ├── RAW/inbox/             porta de entrada
    ├── RAW/<ano>/<mês>/<tipo>/ originais, imutáveis (slack, meetings, documents, …)
    ├── PROCESSED/<ano>/<mês>/ texto extraído, não se reescreve
    ├── PROCESSED/_ledger/events.jsonl
    ├── FRESH/                 retrato gerado (painel, páginas Markdown)
    ├── reports/               exports datados, nunca reescritos
    └── logs/                  noturno
```

`config/` da instância (ao lado do vault, não dentro dele):

| Arquivo | O que é |
|---|---|
| `brain.toml` | dono, expediente, foco, allowlist, memória, noturno, backup |
| `watch.toml` | quais fontes o `/update` pode puxar (edite com `brain watch` ou a aba Fontes do TUI) |
| `.env` | segredos. O agente não imprime. Não entra no backup |
| `.state.json` | hash do último snapshot de cada fonte |
| `.memory-state.json` | o que já foi enviado ao Hindsight |

Regra: se é seu, mora no `vault/` ou nesses arquivos de config. O git da
raiz não leva isso.

---

## 4. Conceitos que o resto do manual usa

### Livro-razão

`vault/PROCESSED/_ledger/events.jsonl`. Uma linha = um fato já validado.
Nada se edita, nada se apaga. O estado de hoje é a soma das linhas.

Cada linha tem: `seq`, `ts` (quando foi registrada), `date` (quando aconteceu
no mundo), `type`, `id`, `by` (owner / agent / system), `prov`, `source`, `data`.

IDs, sempre com zeros à esquerda, nunca reusados:

| ID | Coisa |
|---|---|
| `TASK-0001` | ação |
| `DEC-0001` | decisão |
| `WIN-0001` | entrega (conquista) |
| `PROP-0001` | proposta para você aceitar ou rejeitar |
| `MSG-0001` | mensagem (rascunho → envio) |
| `PUB-0001` | publicação |
| `FOCUS-0001` | plano de foco |
| `GOAL-1` `PROJ-1` `PROJ-1.1` | goal, projeto, entregável — você numera, no `goals.md` |

Quem numera `A-`…`F-` é o `./brain`. Se o agente inventar um número, está errado.

### Proveniência

Todo fato carrega de onde veio:

| Tag | Significa |
|---|---|
| `[doc]` | estava escrito num documento |
| `[observado]` | foi dito em reunião, canal, e-mail |
| `[declarado]` | você afirmou (`/todo`, `/done`, checkbox) |
| `[sem-fonte]` | o agente não achou base |
| `[sistema]` | o próprio motor (plano de foco, sync) |

Fato extraído pelo agente exige a origem (`--source`: caminho do artefato ou
do RAW). Declaração sua leva `[declarado]` e `source: chat`.

### As três listas

| Lista | Quem deve | O app cobra? | Entra no foco? |
|---|---|---|---|
| `mine` (minhas) | você | sim | sim |
| `waiting` (aguardando) | outra pessoa, a você | no brief, não sozinho | não |
| `watching` (observando) | o time, a si mesmo | não | não |

Uma ação de outra pessoa não cai em "minhas" só porque você se importa.
"Observando" aparece no projeto e some do TODO que cobra.

### Bloqueio

`blocked_by: TASK-0002` — esta ação não anda enquanto a outra estiver aberta.
`unblocks: TASK-0009` — fechar esta destrava a outra (o motor anota; não fecha
a outra por você). Atraso se calcula na leitura: não existe uma varredura
que "marque vencida".

### O gate

Criar, renomear, fundir ou fechar goal ou projeto exige você dizer "ok" (ou
"aprovo", "1a", equivalente claro) **e** uma linha em `PLANNING/log.md`.
Marcar um entregável como feito, com evidência, não é o gate: é fato.

Há três gates menores, um por porta: "ok" no lote de foco, "enviar 1" em
cada mensagem, "publica" em cada post no canal do time.

Proposta rejeitada não volta sem evidência nova. Silêncio não aprova.

### O que é derivado

`FRESH/` é reescrito inteiro a cada `./brain render`. Não guarde anotação
única lá — ela some. Exceções que o render **colhe antes de apagar**:

- `[x]` numa ação em `FRESH/todo.md` → fecha (desmarcar reabre)
- `status:` em `FRESH/records/actions/A-*.md` (ficha da ação, qualquer editor) → o mesmo
- checkbox de entregável em `PLANNING/goals.md` → estado factual

Qualquer outra edição em `FRESH/` é descartada. Narrativa do agente
(`/brief`, `/week`) fica em `FRESH/notes/` e o painel mostra como nota, sem
tratar como fato.

---

## 5. O painel (HTML)

Arquivo: `vault/FRESH/dashboard/index.html`.

```bash
./brain render --open
```

O mapa de oportunidades (`vault/FRESH/dashboard/portfolio.html`) sai no
mesmo render, num arquivo à parte, só com o portfólio — para compartilhar:
`./brain render --open portfolio` (na TUI: `o` na face Portfólio).

Atualize depois de mudanças. A data no canto ("gerado …") é a do último
render, não "agora". O rodapé lembra: nada ali é informação única.

Abas:

| Aba | O que mostra |
|---|---|
| **Início** | números do dia, o que precisa de você (proposta, foco, rascunho, ação sem prazo ou sem esforço), goals com barra e saúde, agenda de 7 dias, conquistas, decisões, quem te deve |
| **TODO** | kanban das suas ações (a fazer, fazendo, bloqueada/aguardando, feitas em 14 dias), filtro por projeto, lista "aguardando de outros". "Mostrar observando" é opt-in |
| **Projetos** | um card por projeto, agrupado pelo goal |
| **Decisões** | tabela com quem, quando, projeto e fonte. Substituídas ficam riscadas. Filtros por projeto, pessoa e estado |
| **Conquistas** | gráfico de 8 semanas (entregas em verde, ações fechadas em azul) e a lista da semana |
| **Pessoas** | papel, última interação, quantas te devem, quantas você deve, decisões |
| **Linha do tempo** | Gantt dos próximos 45 dias + o que aconteceu nos últimos 90 |
| **Foco** | blocos do plano vigente, o que não cabe antes do prazo, ações sem esforço |
| **Mensagens** | rascunhos, aprovadas, enviadas, falhas |
| **Saúde** | o mesmo que `./brain doctor` |

Busca no topo: duas letras já filtram ações, decisões, projetos, pessoas,
entregas e artefatos. "Não consta" é uma resposta da busca.

Clicar num `TASK-####` ou `DEC-####` abre a ficha: histórico, bloqueio, fonte,
proveniência. O painel não edita nada. Fechar ação é no chat, no checkbox
do Markdown — e só entra no livro-razão no próximo
`./brain render`.

Badges vermelhos: atrasadas (TODO), plano de foco esperando "ok", mensagens
pendentes, avisos de saúde.

Tema claro ou escuro segue o sistema.

### Como ler progresso e saúde

A barra é **peso** dos entregáveis feitos ÷ peso dos não cancelados.
`peso: 2` vale o dobro de um entregável sem peso (peso 1). Cancelado sai da
conta.

O texto mostra a contagem e, quando o peso muda o percentual, o peso também:
`14% · 1/5 entregáveis · peso 1/7`. 1/5 não é 20% se um deles pesa mais.

Ao lado, se você declarou um feeling (`./brain progress GOAL-1 45 --note "…"`),
aparece "declarado 45%". Os dois números convivem. O declarado não substitui
a conta.

Saúde de um projeto ativo, nesta ordem:

| Estado | Por quê |
|---|---|
| em risco | algum entregável venceu, ou alguma ação **sua** no projeto está atrasada |
| travado | sem movimento há 14 dias (ajustável) e ainda há trabalho aberto — ou nunca houve movimento |
| atenção | algum entregável vence em até 7 dias |
| em dia | nada disso |
| concluído | todos os entregáveis não cancelados estão feitos |
| congelado / fechado | o `status:` do projeto no `goals.md` não é "ativo" |

A saúde do goal é a pior saúde entre os projetos dele.

"Movimento" é ação, decisão, entrega, artefato ou entregável atualizado
naquele projeto. Não é uma opinião.

---

## 6. Lendo e editando direto nos arquivos

Nada exige um app específico: o `vault/` é Markdown plano, lido em qualquer
editor. Páginas em `FRESH/` são as mesmas do painel, com links relativos.
Cada uma tem no topo `generated-at` e `fontes`.

| Arquivo | Uso |
|---|---|
| `FRESH/home.md` | o dia |
| `FRESH/todo.md` | marque `[x]` para fechar; desmarque para reabrir |
| `FRESH/goals.md` | árvore só leitura (edite a estrutura em `PLANNING/`) |
| `FRESH/projects/PROJ-1.md` | ficha do projeto |
| `FRESH/decisions.md` | lista |
| `FRESH/wins.md` | conquistas |
| `FRESH/people/<id>.md` | ficha da pessoa |
| `FRESH/timeline.md` | Mermaid: Gantt + timeline |
| `FRESH/map.md` | três grafos: goals, pessoas×projetos, dependências |
| `FRESH/focus.md` | plano da semana |
| `FRESH/outbox.md` | mensagens |
| `FRESH/health.md` | saúde |
| `FRESH/records/actions/TASK-0001.md` | uma nota por ação |
| `FRESH/records/decisions/DEC-0001.md` | uma nota por decisão |
| `FRESH/notes/` | brief e semana, escritos pelo agente |

Na ficha de ação, editar o `status:` do frontmatter vale declaração sua no
próximo render. Valores aceitos: `a fazer`, `fazendo`, `aguardando`, `feita`,
`descartada`. `bloqueada` é calculada (há um `blocked_by` aberto) — não é um
status que você grava.

Ficha já **descartada** marcada como "feita" não faz nada: descarte não vira
feito. Reabra antes (`/done` não; use o chat pedindo para reabrir, ou
`./brain action reopen TASK-#### --reason "…"`).

Depois de editar `todo.md` ou uma ficha, rode `./brain render` (ou peça
`/brief`). Sem isso, o painel e o livro-razão ainda mostram o estado antigo.

---

## 7. O dia a dia no chat

O agente carrega a skill do comando antes de agir. Frases naturais caem no
comando óbvio ("meu dia" = `/brief`, "atualiza tudo" = `/update`).

### `/brief` — o dia

Roda o render e escreve `FRESH/notes/brief.md`: hoje, atrasadas, próximos 3
dias, o que te devem, goal em foco, o que espera você. No chat, um resumo
curto. Não recalcula atraso na mão.

### `/week` — a semana

Lookahead de 14 dias, radar de goals (conta vs. declarado), ações
envelhecendo, conquistas, e o convite para `/focus` se não houver plano
aprovado. É o momento de propor mudança de goal — uma de cada vez, com
evidência.

### `/todo` — criar ação

`/todo preciso ler a política até quarta`.

O agente resolve a data ("quarta", "amanhã") para `AAAA-MM-DD` com o dia de
hoje do sistema, acha a pessoa se você citou alguém, liga ao projeto se for
óbvio, e grava:

```bash
./brain action open "Ler a política" --due 2026-10-15 --effort 45m --project PROJ-1 --by owner
```

Sem prazo, a ação existe e o foco **não** a agenda. O agente avisa.
Esforço: `90m`, `2h`, `1h30`, `1d` (um dia de trabalho = 8h). Sem esforço,
o foco usa o padrão (60 min) e lista a ação como "sem estimativa".

Lista padrão: sua. Se a ação é de outra pessoa para você, ela nasce
`waiting`.

### `/done` — fechar

`/done TASK-0014 enviei o draft pro Heitor-demo`.

ID exato fecha direto. Texto sem ID: um match só, o agente confirma em uma
linha; vários matches, ele lista; ação de terceiro ou muito antiga, ele
sempre confirma.

```bash
./brain action close TASK-0014 --how "enviei o draft" --outcome "Heitor-demo confirmou" --by owner
```

Se houver resultado observável **e** projeto, entregável ou `unblocks`, nasce
uma entrega `WIN-####` sozinha. Sem resultado e sem projeto, fecha como
operacional — não inventa conquista. `--delivery` força a entrega.

Ações que estavam `blocked_by` desta recebem uma nota de desbloqueio. Elas
não fecham sozinhas. Blocos de foco futuros desta ação saem no próximo
`./brain focus sync`.

### `/dump` — processar a inbox

Você solta um arquivo em `vault/RAW/inbox/` (ata, PDF, nota, export). O
agente:

1. Ignora `.keep.md`.
2. Pula o que já tem artefato para a mesma fonte (rodar de novo não duplica).
3. Move o original para `RAW/<ano>/<mês>/<tipo>/` (`./brain raw archive`) pela
   data de **captura**. Não edita. Nome repetido ganha sufixo `-2`.
4. Classifica: reunião, documento, nota ou conector (snapshot `gmail-…`,
   `slack-…`, `gcal-…`, `jira-…`).
5. Escreve o texto extraído em `PROCESSED/<ano>/<mês>/`. Esse arquivo não se
   reescreve.
6. Resolve pessoas (`./brain person resolve`). Ambíguo: para e pergunta.
   Pessoa nova: `./brain person add` com aliases.
7. Grava ações, decisões e o artefato via `./brain` (ou `./brain add` com um
   JSON). Não fecha ação só porque o texto "parece" resolver — abre uma
   proposta `PROP-####`.
8. Roda `./brain render` se nasceu fato novo.
9. Te devolve um recibo de ~5 linhas por item e `inbox: N restantes`.

A data do **evento** (a reunião foi semana passada) fica no artefato e no
`--date`. A pasta do RAW é a data em que o arquivo entrou.

### `/update` e `/connect`

`/update` é o motor completo, o mesmo que o noturno pede:

1. Lê `config/watch.toml`. Fonte fora da lista não é puxada.
2. Lê cada fonte com ferramenta MCP de **leitura** e grava
   `./brain snapshot --key <chave>`.
3. Hash igual ao último pull daquela chave = silêncio, nada na inbox.
4. `/dump` no que mudou.
5. `./brain render`.
6. Se a memória estiver ligada, `./brain memory sync`.

`/connect` é uma fonte só, agora (antes de uma reunião). Não aproveita para
puxar o resto.

`/gmail`, `/slack`, `/drive`, `/calendar` são leituras específicas. Nenhuma
delas envia, comenta, cria doc ou cria evento. Janelas padrão: Gmail hoje,
Slack 7 dias, Calendar 14 dias. O calendário grava um JSON `gcal-*.json` —
é ele que o foco usa como "agenda ocupada".

Dois pulls seguidos vazios ou com erro da mesma fonte: o agente para e te
avisa. Não finge que está tudo bem.

### `/ask`

`o que sabemos sobre o manual?`

Ordem: `./brain search`, artefato, RAW só se precisar da frase exata. Se o
Hindsight estiver no ar, `./brain memory recall` é atalho — cada trecho tem
de apontar para um arquivo do vault; se não apontar, é pista, não resposta.
A resposta cita caminho e proveniência. **Não consta** é resposta válida.
O app não completa com conhecimento de mundo.

### `/person` e `/project`

`/person Marina-demo` — papel, o que ela te deve, o que você deve a ela, decisões
que ela tomou (quem/quando/fonte), última interação. Nome ambíguo: o agente
lista e para. Não inventa "como ela gosta de ouvir".

`/project PROJ-1` — progresso, saúde e o motivo, entregáveis, decisões, suas
ações vs. as que você espera, próximo marco, artefatos recentes. Mudar a
árvore é `/goal`, não aqui.

### `/goal`

Ver: `./brain plan show` ou `FRESH/goals.md`.

Marcar entregável (fato, com evidência):

```bash
./brain plan deliverable PROJ-1.2 --status feito --evidence "subiu em produção" \
  --by agent --prov observado --source PROCESSED/2026/10/ata.md
```

Status: `nao-iniciado`, `em-andamento`, `feito`, `cancelado`. Feito grava a
data de hoje (ou `--date`) na linha do `goals.md` e no log.

Declarar um feeling, sem mexer na árvore:

```bash
./brain progress GOAL-1 45 --note "cardápio andou; reforma não"
```

Mudar a estrutura: o agente mostra o diff, espera "ok", aplica no
`goals.md` e registra:

```bash
./brain plan log --diff "PROJ-5 nasce sob GOAL-2" --reason "…" --evidence "…" --approval "ok"
```

No noturno a árvore não muda. Vira proposta.

### `/map` e `/timeline`

Pedem o render se a página estiver velha e te dizem, em poucas linhas, o que
o grafo mostra agora (trava, projeto parado, pessoa no meio de tudo). O
desenho em si está em `FRESH/map.md` e `FRESH/timeline.md`, e nas abas do
painel.

### `/recap`, `/share`, `/publish`

Ver capítulo 12.

---

## 8. PLANNING — a sintaxe que o parser aceita

`vault/PLANNING/goals.md` é Markdown estrito. Fora deste formato, a linha é
ignorada ou vira aviso no `./brain doctor` / `./brain validate`.

```markdown
## GOAL-1 — Título do goal
- status: ativo
- horizonte: 2026-12-31
- por quê: o que isto destrava

### PROJ-1 — Título do projeto
- status: ativo
- dono: seu-id
- [ ] PROJ-1.1 Nome do entregável · prazo: 2026-10-30 · peso: 2
- [x] PROJ-1.2 Já feito · prazo: 2026-10-01 · feito: 2026-09-28
- [ ] PROJ-1.3 Em curso · prazo: 2026-11-15 · estado: em-andamento
- [-] PROJ-1.4 Cancelado
```

- Cabeçalho de goal: `## G<número> — título` (travessão, en-dash ou hífen).
- Projeto: `### P<número> — título`, sempre debaixo de um goal.
- Entregável: `- [ ] PROJ-1.1 título · prazo: AAAA-MM-DD · peso: 2`.
- Caixas: `[ ]` não iniciado, `[x]` feito, `[-]` cancelado.
- `estado: em-andamento` marca trabalho em curso sem marcar feito.
- `?` no prazo = sem prazo.
- Comentário HTML `<!-- -->` e bloco cercado por ` ``` ` não entram na árvore.
  Por isso o template pode explicar a sintaxe sem criar um goal fantasma.
- `dono:` tem de ser o **id** da pessoa no livro-razão, não o apelido, se você
  quiser que a ficha do projeto a reconheça.

Editar o checkbox à mão funciona: o próximo `./brain render` vê a diferença
e grava um evento seu (`[declarado]`). Prefira `brain plan deliverable`
quando quem muda é o agente — assim a evidência fica no evento, não só o
checkbox.

---

## 9. Pessoas

```bash
./brain person add "Marina-demo" --alias "Marina-demo" --alias Mari-demo --email marina-demo@example.com \
  --role "Gestora" --relation gestora --by owner
./brain person alias marina-demo "M.-demo"
./brain person resolve "Mari-demo"
./brain person list
```

`resolve` devolve um id, ou código 2 se houver mais de um candidato, ou 3 se
não achar. O agente não escolhe no chute.

Casam, nesta ordem: id, nome, alias ou e-mail iguais; senão, cada palavra da
consulta é prefixo de alguma palavra do nome ("Marina-demo D" acha "Marina-demo").
Uma letra só casa com muita gente — o comando recusa a ambiguidade.

Alias repetido em duas pessoas aparece como aviso no `./brain validate` e no
doctor. Isso é para você decidir, não para o app fundir sozinho.

---

## 10. Ações, decisões, entregas, propostas

### Ação

```bash
./brain action open "Publicar o manual" --due 2026-10-20 --effort 2h \
  --project PROJ-1 --deliverable PROJ-1.1 --blocked-by TASK-0002 --people heitor-demo \
  --priority alta --by owner

./brain action update TASK-0003 --status fazendo --note "comecei a revisão"
./brain action update TASK-0003 --clear-due
./brain action list --list waiting
./brain action list --project PROJ-1 --all
./brain action show TASK-0003
./brain action drop TASK-0008 --reason "não faz mais sentido" --by owner
./brain action reopen TASK-0008 --reason "voltou a fazer" --by owner
```

Estados que você grava: `aberta`, `fazendo`, `aguardando`. `bloqueada`,
`fechada` e `descartada` têm caminho próprio. Prioridade: `alta`, `normal`,
`baixa`.

`--json` em quase todo comando devolve o evento em vez do texto.

### Decisão

```bash
./brain decision add "Manual sai como draft" --decided-by marina-demo \
  --project PROJ-1 --rationale "meio manual em produção" \
  --prov observado --source PROCESSED/2026/10/ata.md

./brain decision list --project PROJ-1
./brain decision supersede DEC-0001 --by-decision DEC-0004 --reason "a decisão nova substitui"
```

Ou, no `decision add`, `--supersedes DEC-0001`. A antiga fica `substituida` e
riscada. Não se apaga. `decided_by` é obrigatório e tem de ser gente já
cadastrada.

### Entrega avulsa

Quando a conquista não nasceu de um `/done`:

```bash
./brain delivery "Draft do manual" --ref TASK-0001 \
  --result "em revisão com o Heitor-demo" --evidence "e-mail" --by owner
```

`--ref` pode ser `TASK-####`, `PROJ-1`, `PROJ-1.1` ou `GOAL-1`. Sem resultado declarado, a
ficha diz "resultado não declarado" — o app não inventa impacto.

### Proposta

O agente acha que uma ação pode fechar, ou que o plano deveria mudar, e não
faz isso sozinho:

```bash
./brain proposal add --kind fechar-acao --target TASK-0006 \
  --summary "O report já traz a fechamento de setembro" \
  --evidence PROCESSED/2026/10/status.md \
  --prov observado --source PROCESSED/2026/10/status.md

./brain proposal accept PROP-0001 --quote "ok, pode fechar"
./brain proposal reject PROP-0001 --quote "não, ainda quero validar o número"
```

Kinds: `fechar-acao`, `atualizar-acao`, `mudar-plano`, `reestimar`, `outro`.

Aceitar **registra a sua resposta**. Não fecha a ação nem muda o goal. O
agente, depois do "ok", executa o que foi aceito (um `/done`, um diff de
goal). Rejeitada não volta sem fato novo.

**Encerrada sozinha:** se você resolver por fora do painel — fechar ou descartar
a ação (`/done`, checkbox, ficha), ou mexer nela depois da proposta (prazo,
status) — a proposta de `fechar-acao`/`atualizar-acao` sobre ela se encerra
sozinha (`proposal.superseded`, by system, com o motivo e o desfecho que o seu
gesto implica): `fechar-acao` vira **aceita** se você fechou a ação e
**rejeitada** se descartou ou mexeu e deixou aberta; `atualizar-acao` vira
**aceita** se você mexeu na ação e **rejeitada** se ela foi fechada/descartada
antes. Encerramentos antigos, sem desfecho, aparecem como `obsoleta`. Acontece a cada escrita no
ledger, no `render` e no `proposal list`; também vale no noturno.

### Lote

`./brain add arquivo.json` (ou stdin) grava vários eventos de uma vez: ou
entram todos, ou nenhum. É o que o `/dump` usa quando uma ata gera três
decisões e quatro ações.

---

## 11. Foco — tempo protegido no calendário

Uma vez por semana (ou quando você pede `/focus`):

1. Se não houver snapshot recente da agenda, o agente lê o calendário
   (`/calendar`) antes. Sem snapshot, o plano trata a agenda como livre e
   avisa.
2. `./brain focus plan` lê as **suas** ações abertas (`mine`, não bloqueadas,
   status aberta ou fazendo), com prazo e esforço.
3. Encaixa blocos: prazo mais próximo primeiro, dentro do expediente, fora do
   almoço, fora de férias, com folga ao redor de reunião, teto de minutos por
   dia, blocos entre 30 e 120 minutos (tudo configurável).
4. Você vê a tabela. Ações que não cabem antes do prazo aparecem em
   "não cabe". Sem esforço, entra o padrão e a ação é listada.
5. Você diz "ok". Ajuste de horário não se faz editando o plano: mude o prazo
   ou o esforço da ação e peça outro plano.
6. O agente grava a sua frase literal e aplica:

```bash
./brain focus approve FOCUS-0001 --quote "ok"
./brain focus apply FOCUS-0001
```

Dois modos (`[focus] mode` no `brain.toml`):

| Modo | O que acontece |
|---|---|
| `ics` (padrão) | gera `FRESH/focus/FOCUS-0001.ics`. Você importa no Google Calendar. O app não apaga evento antigo sozinho |
| `google` | cria eventos no calendário primário. Tenta *Focus time* (recusa convite novo, não perturbe). Conta sem Workspace cai para evento comum, opaco, com a mesma marca |

A marca é `extendedProperties.private.brain_focus=1` mais o id da ação.
Antes de apagar, o app relê o evento. Sem a marca, recusa. Evento seu de
verdade não é tocado.

Ocupado na agenda: o que não for cancelado, transparente, recusado por você,
ou um bloco antigo do próprio cérebro. Ausência o dia todo (*out of office*)
bloqueia o dia. Reunião ganha uma folga (`buffer_min`, padrão 10) dos dois lados.

Fechou a ação? `./brain focus sync` tira os blocos futuros dela (no modo
google, da API; no modo ics, avisa para você remover). O noturno roda esse
sync. `--dry-run` só lista.

Plano novo substitui o anterior que ainda estava "proposto" ou "aprovado" e
não aplicado. Aplicar exige aprovação **deste** plano: a frase "ok" de um
plano antigo não vale para outro.

Férias: no `brain.toml`,

```toml
[[vacations]]
start = "2026-12-24"
end = "2027-01-04"
```

Esses dias não recebem bloco.

Expediente padrão: seg–sex, 09:00–18:00, almoço 12:00–13:00, fuso
`America/Sao_Paulo`. Horizonte 7 dias, no máximo 180 minutos de foco por dia.

O que o foco ignora: lista waiting/watching, ação bloqueada, ação sem ser
sua, ação fechada, esforço já coberto por blocos passados (se ainda sobrar
tempo e a ação continuar aberta, ele avisa "reestimar?").

---

## 12. Mensagens, exports e publicação

### Mensagem (Slack)

O app escreve o texto. Você aprova **esse** texto. Só então sai, como você,
pelo Slack.

1. O destinatário (id de pessoa ou `#canal`) precisa estar em
   `[outbound].allow` no `brain.toml`. Se não estiver, o agente mostra a
   linha e para.
2. Rascunho:

```bash
./brain outbox draft --to caio-demo --text "Oi Caio-demo, …" --ref TASK-0005 \
  --why "cobrar o MVP"
```

3. Você lê o texto inteiro no chat. "enviar 1" (ou "ok, manda") aprova
   **aquela** redação.
4. `./brain outbox approve MSG-0001 --quote "enviar 1"`
5. O agente envia pelo Slack exatamente o que `./brain outbox show MSG-0001`
   imprime.
6. `./brain outbox sent MSG-0001 --link https://…` — o permalink fica no
   livro-razão. Falhou: `outbox failed`. Desistiu: `outbox cancel`.

Mudou uma vírgula depois do "enviar 1"? Cancela e faz outro rascunho.
Aprovação não herda. Teto: `[outbound].daily_max` (padrão 10 por dia).

O corpo da mensagem não leva `TASK-####`. Isso é jargão interno.

Não existe porta de e-mail. Cobrar por e-mail é você quem escreve. O
`/gmail` só lê.

### Export para um colega (`/share`)

Arquivo novo em `vault/reports/share/`, HTML ou Markdown, autocontido,
datado. Não se atualiza. Gerar de novo cria outro arquivo.

```bash
./brain share project PROJ-1
./brain share goal GOAL-1 --format md
./brain share status
./brain share period 2026-09-01:2026-09-30
```

O texto é para quem **não** tem o cérebro: sem lista "observando", sem
rascunho, IDs só na seção de fontes. Revise antes de encaminhar.

### Recap

`/recap` usa o mesmo export e, se você quiser narrativa (o que não aconteceu,
próximo passo), o agente escreve um Markdown extra em `vault/reports/`, cada
frase com fonte. Sem fonte, "não declarado". Recap antigo não se reescreve.

### Publicar no espaço do time

Destino precisa estar em `[publish].destinations` (`slack:#canal` ou
`drive:<id-da-pasta>`).

```bash
./brain publish request reports/share/2026-10-09-project-p1.html --to "slack:#time"
./brain publish approve PUB-0001 --quote "publica"
# o agente posta aquele arquivo
./brain publish done PUB-0001 --link https://…
```

O arquivo é travado por hash. Se mudar depois do pedido, a aprovação não
vale: gere outro e peça de novo. A porta só aceita arquivo **dentro** de
`vault/reports/`. Caminho com `..` é recusado.

---

## 13. Memória (Hindsight) e outras IAs

O vault continua sendo a verdade. O Hindsight é um índice opcional, mão
única: o vault alimenta, o índice não escreve de volta.

Dois bancos:

| Banco | Conteúdo | Como indexa |
|---|---|---|
| `brain-raw` | arquivos do RAW (texto e PDF/Office até o tamanho máximo), fora da inbox | pedaços, sem interpretar |
| `brain-mem` | artefatos do PROCESSED, uma página por ação/decisão/entrega/pessoa, PLANNING e PROFILE | fatos duráveis |

Cada lembrança aponta para um caminho (`PROCESSED/…` ou `ledger/TASK-0001`).

Desligado por padrão (`engine = "none"`). Para ligar: suba o servidor
([Hindsight](https://github.com/vectorize-io/hindsight); o modelo de
extração se configura lá, não aqui), depois:

```toml
[memory]
engine = "hindsight"
url = "http://localhost:8888"
```

```bash
./brain memory setup
./brain memory sync          # --dry-run lista; --limit 50 corta
./brain memory status
./brain memory recall "quem decidiu congelar o agente?"
./brain memory reflect "como está o projeto PROJ-1?" --bank mem
./brain memory rebuild       # apaga os bancos e reconstrói
```

Token, se o servidor pedir: `HINDSIGHT_API_TOKEN` no `.env`.

Não vai para o índice: inbox, arquivo maior que `max_file_mb` (padrão 25),
e o `.env` (nem está no vault). O noturno chama `sync`. Se o servidor cair,
`/ask` segue pelo search → artefato → RAW.

### MCP somente-leitura

Para outra IA consultar o mesmo cérebro sem poder escrever:

```json
{ "command": "/caminho/brain-v2/brain", "args": ["mcp"] }
```

Ferramentas: `brain_overview`, `brain_search`, `brain_project`,
`brain_person`, `brain_decisions`, `brain_actions`, `brain_timeline`,
`brain_wins`, `brain_read`. `brain_read` só lê texto de dentro do vault
(Markdown, txt, csv, json, html, vtt). PDF: leia o artefato em PROCESSED.
Detalhe em `guides/mcp.md`.

---

## 14. Noturno, backup, atualizar o framework

### Noturno

```bash
./brain schedule install --time 05:00
./brain schedule status
./brain schedule remove
```

No macOS isso instala um LaunchAgent (`com.segundo-cerebro.nightly`) e remove a
linha antiga do crontab, se houver: o cron roda fora da sessão de login e o agente
(`claude -p`) sai com "Not logged in". O launchd também executa na volta o horário
perdido com o Mac dormindo. Nos demais sistemas, entra uma linha no crontab.

O agente headless não tem como pedir permissão: liste em `[runner].allow` do
`config/brain.toml` as ferramentas MCP de **leitura** que ele pode usar
(`mcp__<servidor>__<ferramenta>`). Sem isso o `/update` sai com "negado" em toda fonte.

Cada madrugada, isolando falha (um passo quebrado não cancela os outros):

1. Render (sem LLM).
2. Agente headless com `/update`, se houver um instalado.
3. Sync de foco (tira bloco de ação já fechada).
4. Memória, se ligada.
5. Backup, se for o dia configurado (padrão: domingo) e `enabled = true`.
6. Render de novo.
7. Um evento `run.completed` no livro-razão.

Log: `vault/logs/nightly.log` e `nightly-agent.log`.

O agente noturno roda com `BRAIN_NIGHTLY=1`. O livro-razão **recusa**
declaração sua, aprovação, envio, publicação e aplicar foco no Google.
Não há você presente. Dúvida vira proposta para de manhã.

Qual agente: `[runner] agent = "auto"` procura, nesta ordem, `cursor-agent`,
`claude`, `codex`, `agy`, `gemini`. `command = "… {prompt} …"` substitui o
preset. `agent = "none"` pula o agente e só faz a parte determinística.
Timeout padrão: 45 minutos.

### Backup

```bash
./brain backup --local ~/Backups
./brain backup                  # Google Drive, se o .env tiver a pasta
./brain backup --status
```

Zip do `vault/`. Arquivo maior que `[backup].max_file_mb` (padrão 50) fica
de fora e entra no `BACKUP-MANIFEST.json` dentro do próprio zip (caminho,
tamanho, sha256). O `.env` não vai. Mantém os N zips mais novos
(`[backup].keep`, padrão 8).

No Drive, escopo `drive.file`: só cria e apaga `brain-backup-*.zip` na pasta
`GOOGLE_BACKUP_FOLDER_ID`. Upload em pedaços de 8 MB.

Restaurar é manual: baixar o zip, extrair sobre um `vault/` vazio, ler o
manifesto, `./brain doctor`, `./brain validate`, `./brain render`, e
`./brain memory rebuild` se usava Hindsight. O agente guia; não puxa o zip
sozinho. Sem nenhum zip, o status diz que não há backup — não finja o
contrário. Guia curto: `guides/backup.md`.

### Atualizar o framework (`/upgrade`)

`./brain update` traz as melhorias do framework: `git pull --ff-only --autostash`, semeia
arquivo novo de `template/` que falte no vault (o que já é seu não é sobrescrito), avisa se um
template que você já tem mudou, e roda o `doctor`. `--check` só mostra o que chegou; `--rebase`
re-aplica commits locais por cima. Se o pull brigar com uma edição local do agente, ele te mostra
o diff: ou a mudança sobe para o framework, ou se descarta. Nunca commita `vault/` nem `.env`.

O caminho de volta é git puro (`add`/`commit`/`push`): toda melhoria de código ou estrutura feita
na instância sobe ao repo do framework, depois do seu "ok". Um hook `pre-push` (instalado por
`brain update`/`brain init`) roda `./brain upstream scan --committed` e barra o push se achar dado
pessoal ou segredo; o `doctor` avisa do que ainda não subiu.

---

## 15. Configuração — todas as chaves

`config/brain.toml`. O que você omitir fica no padrão.

```toml
[owner]
id = "eu"                       # id da pessoa no livro-razão
name = "Dono do cérebro"

# timezone = "America/Sao_Paulo"

[work]
days = [1, 2, 3, 4, 5]          # 1 = segunda … 7 = domingo
start = "09:00"
end = "18:00"
lunch = "12:00-13:00"           # "" desliga

[focus]
mode = "ics"                    # "ics" | "google"
calendar = "primary"
horizon_days = 7
block_min = 30
block_max = 120
daily_max_min = 180
buffer_min = 10
default_effort_min = 60
title_prefix = "Foco"
decline_message = "Em bloco de foco planejado."

[outbound]
allow = []                      # ids de pessoa e/ou "#canal"
daily_max = 10

[publish]
destinations = []               # "slack:#canal", "drive:<folder-id>"

[memory]
engine = "none"                 # "hindsight"
url = "http://localhost:8888"
raw_bank = "brain-raw"
mem_bank = "brain-mem"
max_file_mb = 25
timeout_s = 120

[runner]
agent = "auto"                  # auto | cursor | claude | codex | agy | gemini | none
command = ""                    # se preenchido, usa isto; {prompt} vira o /update
prompt = "/update"
timeout_min = 45

[backup]
enabled = false
max_file_mb = 50
keep = 8
weekday = 7                     # domingo

[views]
wins_weeks = 8
timeline_back_days = 90
timeline_ahead_days = 45
stale_project_days = 14
aging_warn_days = 7
```

`config/watch.toml` — uma entrada por fonte. Sem entrada, o `/update` não
puxa. Exemplo comentado está no `.example`. A chave (`key`) é estável: é ela
que o snapshot usa para saber se mudou.

`config/.env`:

```
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REFRESH_TOKEN=
GOOGLE_BACKUP_FOLDER_ID=
HINDSIGHT_API_TOKEN=
```

OAuth: `python3 scripts/google_auth.py` abre o navegador e imprime o refresh
token **uma vez**. Escopos: `calendar.events.owned` e `drive.file`. Nada de
Gmail nem de leitura — leitura é MCP. App OAuth em "Testing" expira o token
em 7 dias; em produção, não. `invalid_grant` = rode o script de novo. Passo
a passo: `guides/google-oauth.md`.

Para foco no Google, além do token: `[focus] mode = "google"`. Sem as três
variáveis `GOOGLE_*`, o doctor marca calendário como erro e o modo `ics`
continua utilizável.

---

## 16. Referência do `./brain`

Códigos de saída: `0` ok · `1` uso · `2` ambíguo · `3` não achei · `4`
validação recusada · `5` livro-razão corrompido (JSON inválido no meio).

| Comando | Faz |
|---|---|
| `init` | semeia vault e config |
| `person add\|alias\|update\|resolve\|list` | pessoas |
| `action open\|update\|close\|drop\|reopen\|show\|list` | ações |
| `decision add\|supersede\|list` | decisões |
| `delivery` | entrega avulsa |
| `artifact` | registra texto do PROCESSED (trava de idempotência do dump) |
| `proposal add\|accept\|reject\|list` | propostas |
| `plan show\|deliverable\|log` | árvore, checkbox, gate |
| `progress GOAL-1 45` | percentual declarado |
| `add` | lote JSON |
| `validate` | relê o livro-razão inteiro, o PLANNING e aliases |
| `status` | contagens |
| `search "…"` | busca sem LLM |
| `render` | colhe suas edições e reescreve o FRESH. `--open` abre o painel. `--no-harvest` não colhe |
| `sync` | só colhe (checkbox, status, goals.md), não redesenha |
| `focus plan\|approve\|apply\|sync\|show` | foco |
| `outbox draft\|show\|approve\|sent\|failed\|cancel\|list` | mensagens |
| `share` | export HTML/MD |
| `publish request\|approve\|done\|cancel\|list` | publicação |
| `snapshot --key …` | grava leitura de MCP na inbox, ou `--fail "…"` |
| `doctor` | saúde. `--online` testa o Hindsight se estiver ligado. `--json` |
| `memory …` | capítulo 13 |
| `mcp` | servidor stdio, só leitura |
| `nightly` | capítulo 14. `--skip-agent` pula o LLM |
| `schedule install\|remove\|status` | crontab |
| `backup` | capítulo 14 |
| `demo --dir …` | instância fictícia |

Quase todos aceitam `--json`. Fatos do agente pedem `--prov` e, nos tipos
que criam coisa no mundo, `--source`. `--by owner` é declaração sua.
`--date AAAA-MM-DD` é quando aconteceu, não quando você digitou.

`./brain doctor` olha: config, zonas do vault, integridade do ledger, avisos
do PLANNING, alias ambíguo, inbox parada, noturno atrasado ou falho, fonte
com 2+ erros, rascunhos, plano de foco parado, OAuth faltando se o modo for
google, propostas abertas, ações suas sem prazo, idade do último render,
memória, arquivos enormes no RAW.

---

## 17. Comandos do chat

| Você diz | O agente faz |
|---|---|
| `/init` | entrevista e propõe PROFILE + PLANNING |
| `/dump` | processa a inbox |
| `/brief` | o dia |
| `/week` | a semana |
| `/todo …` | abre ação |
| `/done …` | fecha ação |
| `/ask …` | pergunta, com fonte |
| `/person …` | ficha e prep de reunião |
| `/project …` | status do projeto |
| `/goal` | árvore e o gate |
| `/update` | puxa o watch, dump, render |
| `/connect` | uma fonte, agora |
| `/gmail` `/slack` `/drive` `/calendar` | leitura daquela fonte |
| `/focus` | propõe a semana; aplica depois do ok |
| `/outbox` | rascunho; envia depois do "enviar 1" |
| `/share` | export para colega |
| `/recap` | história e impacto |
| `/publish` | posta no espaço do time |
| `/map` `/timeline` | os grafos |
| `/backup` | zip |
| `/upgrade` | atualiza o framework |

---

## 18. O que o app não faz

- Não cria card, não move card, não comenta PR, não responde e-mail.
- Não manda mensagem, não publica e não marca foco sem a sua frase explícita.
- Não lê fonte que não está no `watch.toml` durante o `/update`.
- Não edita o RAW depois de arquivado, nem reescreve artefato do PROCESSED,
  nem apaga linha do livro-razão.
- Não guarda segredo em chat, log, artefato ou view. Não imprime o `.env`.
- Não trata checkbox de `FRESH/` como verdade até o próximo render — e não
  trata edição solta de `FRESH/` como verdade nunca.
- Não fecha ação `watching` porque o Slack andou.
- Não importa o ledger da v1. A v1 fica como arquivo. Trazer um pedaço é
  copiar RAW e rodar `/dump`.
- No noturno, não age em seu nome.

Se uma conta não fecha (percentual, atraso, id), o defeito é do `./brain`,
não "do modelo". `./brain validate` e `./brain doctor` são o primeiro passo.
Livro-razão com JSON quebrado no meio (código 5) é o único caso em que se
mexe numa linha à mão — com backup, uma linha. Fora isso, só se apenda.
