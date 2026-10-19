# Guia do usuário — o Segundo Cérebro do zero

> Este guia assume que você **nunca viu a ferramenta**. Ele cobre o que ela é,
> como pensar sobre ela, como ligar cada fonte externa, cada comando (o que
> você digita, o que acontece, o que volta pra você) e a rotina normal de uso.
> A referência profunda é `guides/manual.md`; a lei do agente é `AGENTS.md`;
> a instalação completa está no `setup.md`. Se algo aqui contradisser o
> `AGENTS.md`, o `AGENTS.md` vence.

## Índice

1. [O que é (e o que nunca vai ser)](#1-o-que-é-e-o-que-nunca-vai-ser)
2. [As cinco ideias que sustentam tudo](#2-as-cinco-ideias-que-sustentam-tudo)
3. [Primeira vez: do clone ao cérebro vivo](#3-primeira-vez-do-clone-ao-cérebro-vivo)
4. [O que conectar e como conectar](#4-o-que-conectar-e-como-conectar)
5. [Um dia normal com a ferramenta](#5-um-dia-normal-com-a-ferramenta)
6. [A semana: foco, recap e o 1:1](#6-a-semana-foco-recap-e-o-11)
7. [Comandos de A a Z](#7-comandos-de-a-a-z)
8. [O painel — um passeio](#8-o-painel--um-passeio)
9. [Editar arquivos na mão: o que é colhido e o que é descartado](#9-editar-arquivos-na-mão-o-que-é-colhido-e-o-que-é-descartado)
10. [Limites e segurança — o que ele NUNCA faz](#10-limites-e-segurança--o-que-ele-nunca-faz)
11. [Problemas comuns e soluções](#11-problemas-comuns-e-soluções)
12. [Glossário](#12-glossário)

---

## 1. O que é (e o que nunca vai ser)

O Segundo Cérebro é um **arquivista pessoal com memória total** para a sua
vida profissional. Ele mora numa pasta no seu computador, é feito de
Markdown (arquivos de texto que você pode abrir em qualquer editor) e é
operado por conversa: você fala com um agente de IA (Claude Code) dentro da
pasta do projeto, e o agente organiza tudo usando um programa local
determinístico chamado `./brain`.

A divisão do trabalho é fixa e importa:

| Quem | Faz o quê |
|---|---|
| **Você** | Joga informação na entrada (arquivos, transcrições, prints), dá comandos curtos (`/todo`, `/done`, `/brief`) e aprova as poucas coisas que saem para o mundo |
| **O agente (IA)** | Lê, classifica, extrai decisões e ações, redige textos, julga |
| **O `./brain` (programa local)** | Numera IDs, valida, calcula prazos/progresso/atraso, desenha o painel, agenda foco, guarda o histórico |

O `./brain` é propositalmente burro e confiável: não usa IA para contar.
Se a contagem não fecha, o erro é do programa, não "do modelo" — e é
rastreável.

**O contrato (memorize este parágrafo):** ele **observa e organiza**. Ele
NÃO trabalha por você no mundo exterior. Não cria card no Jira, não responde
e-mail, não comenta PR, não manda mensagem, não marca reunião. As únicas
quatro exceções — quatro "portas" — exigem a sua aprovação explícita, uma a
uma: blocos de foco no calendário, mensagem no Slack, publicação no espaço
do time e backup no Drive. Nem um "responde esse aqui rapidinho" no calor
do momento autoriza pular isso; a resposta certa do agente é lembrar da
regra e usar a porta certa.

**O que você ganha de concreto:**

- "O que foi decidido sobre o pipeline, quem decidiu e quando?" — respondido
  com fonte em segundos, não "deixa eu procurar naquele doc".
- O que você deve, o que te devem e o que é só ruído — em três listas
  separadas que não se misturam.
- Tempo de foco protegido no calendário, planejado pelos prazos reais.
- Um painel de Monday-morning com goals, saúde, atrasos e agenda.
- Um histórico que não apodrece: cada fato tem data, autor e de onde veio.

---

## 2. As cinco ideias que sustentam tudo

### 2.1 Tudo mora em pastas Markdown — nada é escondido

O "cérebro" é uma pasta chamada `vault/` com subpastas. Não há banco de dados
invisível: qualquer arquivo abre num editor de texto. A organização:

```
vault/
├── RAW/inbox/          ← a ÚNICA porta de entrada. Jogue qualquer coisa aqui.
├── RAW/<ano>/<mês>/    ← arquivo morto imutável (o original nunca é editado)
├── PROCESSED/<ano>/<mês>/  ← o resumo extraído de cada fonte (append-only)
├── PROCESSED/_ledger/events.jsonl  ← O LIVRO-RAZÃO (explicado abaixo)
├── PLANNING/goals.md   ← sua árvore de goals → projetos → entregáveis
├── PROFILE/profile.md  ← quem você é, como opera
├── FRESH/              ← o "quadro branco": views derivadas + painel HTML
└── reports/            ← documentos datados que saem da máquina (status, recaps)
```

### 2.2 O livro-razão: cada fato é um evento com ID

`events.jsonl` é um arquivo onde **cada linha é um fato** da sua vida
profissional, numerado e validado. É a verdade do sistema; o agente jamais
edita esse arquivo na mão — toda escrita passa pelo `./brain`, que numera,
valida referências e recusa besteira (pessoa inexistente, fechar ação duas
vezes, prazo sem data…).

Os prefixos que você vai ver o dia inteiro:

| Prefixo | Entidade | Exemplo |
|---|---|---|
| `A-####` | ação (tarefa) | `A-0014` |
| `D-####` | decisão | `D-0005` |
| `E-####` | entrega (conquista com resultado) | `E-0002` |
| `R-####` | proposta (o agente sugere, você decide) | `R-0001` |
| `M-####` | mensagem rascunhada no outbox | `M-0001` |
| `S-####` | publicação | `S-0001` |
| `F-####` | plano de foco | `F-0001` |
| `G#` / `P#` / `P#.n` | goal / projeto / entregável | `G1`, `P1`, `P1.2` |

O `#` é para você não precisar decorar: cite "A-0014" e pronto.

### 2.3 Proveniência: de onde veio cada fato

Todo fato carrega uma etiqueta de origem. Isso parece burocracia até o dia
em que salva você:

- `[declarado]` — **você** disse ("fechei o relatório"). Nível máximo.
- `[doc]` — está escrito num documento (a política, o RFC).
- `[observado]` — o agente extraiu de uma fonte (reunião, e-mail, Slack).
- `[sem-fonte]` — registrado sem origem (evite; serve para não perder fio).

Na prática: quando você perguntar algo, a resposta distingue *"a política
diz"* de *"alguém comentou numa reunião"* de *"você me disse"*. E quando o
cérebro não sabe, ele responde **"não consta"** — inventar memória é o único
erro imperdoável do sistema, e essa resposta honesta é um recurso, não uma
falha.

### 2.4 FRESH é um retrato descartável — e é por isso que nunca mente

`FRESH/` (home, todo, goals, dashboard…) é **100% derivado** do
livro-razão + PLANNING. Qualquer hora, `./brain render` apaga e redesenha
tudo do zero. Você nunca precisa "manter" nada ali — e nada que você
estragar ali tem valor perdido. As três exceções colhidas antes de
sobrescrever (seção 9): checkbox no `todo.md`, `status:` na ficha da ação e
checkbox de entregável em `PLANNING/goals.md`.

### 2.5 Aprovação explícita: silêncio não é "sim"

Para qualquer coisa que mude estrutura ou saia para o mundo — criar/fechar
um goal, aplicar foco no calendário, enviar mensagem, publicar — o agente
**para e espera** um "ok", "aprovo", "enviar 1" literal seu. Isso vale às
três da tarde e às três da manhã (o noturno, que roda sem você, é
proibido pelo próprio ledger de aprovar ou enviar qualquer coisa).

---

## 3. Primeira vez: do clone ao cérebro vivo

Pré-requisito único: a máquina preparada (Python, LM Studio, Hindsight) —
o `setup.md` cobre tudo, e foi escrito para ser executado pelo próprio
agente: *"execute o setup.md"* resolve.

### Passo 1 — criar a instância

No terminal, na pasta do repo:

```bash
./brain init --owner-id ana --owner-name "Ana Souza"
```

Isso semeia o `vault/` vazio a partir do template. Nada de conteúdo falso,
nada importado: cérebros nascem vazios de propósito. Confira com
`./brain doctor` — deve reclamar de "cérebro novo, PROFILE vazio", o que é
o esperado.

### Passo 2 — a entrevista de nascimento (`/init`)

Abra o chat do agente **na pasta do repo** e digite `/init`. Ele entrevista
você em **4 blocos curtos** (3–5 perguntas por vez, tudo numa resposta só):

1. **Quem é você** — papel, empresa, frentes, como gosta de operar.
2. **Para onde vai** — 2 a 4 goals com horizonte; projetos; entregáveis com
   prazo (se souber; sem prazo também vale).
3. **Quem te cerca** — pessoas recorrentes (nome, apelido, e-mail). Cada uma
   vira uma ficha com aliases — é o que impede o cérebro de criar "Ana R."
   e "Ana Ribeiro" como duas pessoas.
4. **O que observar** (opcional) — canais/caixas/boards que ele deve puxar
   sozinho (vira o `watch.toml`, seção 4).

Dica de ouro: **se você tem um documento de onboarding, um planejamento
trimestral, qualquer material** — jogue na pasta `vault/RAW/inbox/` ANTES da
entrevista e diga ao agente. Ele processa o material e ancora as perguntas
no que leu, em vez de te entrevistar às cegas. Documento vale mais que
memória.

No fim, o agente mostra a **proposta** de `PROFILE/profile.md` e
`PLANNING/goals.md` e espera seu "ok". Você pode cortar qualquer goal — ele
corta e reapresenta o resto; não reescreve tudo.

### Passo 3 — o primeiro `/dump`

Todo arquivo que estiver na inbox (o doc de onboarding, por exemplo) vira
material. Peça `/dump` — o pipeline completo, explicado de leigo:

1. O agente **move** o arquivo da inbox para o arquivo morto (`RAW/2026/10/`),
   pela data de captura. O original nunca mais é editado.
2. **Classifica**: reunião, documento, nota ou snapshot de conector.
3. **Extrai** para um artefato em `PROCESSED/2026/10/`: do que trata, decisões
   (com quem decidiu e a base), ações por dono, prazos, menções a pessoas.
   Cada extração leva proveniência.
4. **Registra no livro-razão** cada ação (`A-####`), decisão (`D-####`),
   pessoa nova. Pessoas já conhecidas são resolvidas por alias — nunca uma
   segunda ficha.
5. Roda `./brain render` e o **painel nasce**: `vault/FRESH/dashboard/index.html`,
   abre no navegador.

Rodar `/dump` de novo no mesmo arquivo? Nada acontece — o pipeline é
idempotente (fonte já processada é pulada). Não existe "processar duas
vezes por acidente".

### Passo 4 — o primeiro `/brief`

Digite `/brief`. Você recebe o seu dia numa tela: o que vence hoje, o que
está atrasado, os próximos 3 dias, o que te devem, o goal em risco e o que
espera você (propostas, planos). A partir daqui a rotina da seção 5 vale
para sempre.

---

## 4. O que conectar e como conectar

### A filosofia antes da fiação

O cérebro **lê** o mundo externo pelas ferramentas de leitura do agente
(conectores MCP configurados no Claude Code), e **toda leitura vira um
arquivo seu antes de ser usada**: o agente grava um *snapshot* na inbox com
`./brain snapshot`. Se amanhã o Slack mudar a API, você não perde nada —
o snapshot está no seu disco, datado. Snapshots idênticos ao pull anterior
(= nada mudou) são silêncio: nada é gravado, nada é reprocessado.

Duas regras de ouro:

1. **O universo observável é fechado**: o arquivo `config/watch.toml` lista
   o que pode ser puxado no `/update` automático. Fonte fora da lista não é
   puxada, sem exceção. Isso evita o agente "curioso" bisbilhotando canais
   que você não autorizou.
2. **Ler é sempre permitido (se listado); escrever é sempre porta com gate.**
   O Slack de leitura e o Slack de envio são coisas diferentes no sistema —
   o segundo é o `/outbox`, seção 7.

### O que dá para conectar (tabela geral)

| Fonte | Comando de leitura | O que vira | Pré-requisito |
|---|---|---|---|
| Gmail | `/gmail` | digest do dia (ou filtro), ações/decisões extraídas | conector MCP Gmail no agente |
| Google Calendar | `/calendar` | snapshot da agenda (14d) — combustível do `/focus` | conector MCP Calendar |
| Slack | `/slack #canal` | change digest do canal (7d) | conector MCP Slack |
| Google Drive | `/drive <doc>` | snapshot datado do doc vivo | conector MCP Drive |
| Jira/GitHub/qualquer coisa com MCP de leitura | `/connect <fonte>` | snapshot na inbox + `/dump` | conector MCP correspondente |
| Reuniões | (sem conector) | você solta a transcrição (.md/.vtt/.srt) na inbox | gravador/transcrição qualquer — o cérebro não grava nem transcreve |

### Como ligar cada um, na prática

**Gmail.** No Claude Code, adicione o conector MCP do Gmail (Google) e
autorize com a conta certa. Feito isso, `/gmail` funciona: o agente busca as
threads (padrão: hoje; filtro seu vira query, ex. `/gmail da Ana`),
snapshota e processa. O digest destaca o que **cobra você** e o que
**parece fechar** alguma ação — e atenção: isso último vira uma *proposta*
(`R-####`) com a evidência, nunca um fechamento automático.

**Google Calendar.** Adicione o conector MCP do Calendar. `/calendar` grava
o snapshot `gcal-primary.json` na inbox — ele NÃO extrai ações daí; a agenda
serve para uma coisa: o planejador de foco saber onde você está ocupado.
Escrever no calendário é porta exclusiva do `/focus` (abaixo).

**Slack.** Adicione o conector MCP do Slack. `/slack #time-dados` (ou
`/slack @ana`) puxa a janela (padrão 7 dias), snapshota e resume o que
mudou: menções a você, decisões, promessas. **Para enviar**, nada disso:
é `/outbox`, com allowlist e aprovação do texto exato.

**Google Drive.** Conector MCP Drive. `/drive política de dados` busca,
`/drive <id>` exporta o doc. Docs vivos ganham um snapshot datado a cada
pull — o primeiro é o "estado inicial", os seguintes mostram **só o que
mudou** desde o último. O doc vivo continua lá fora; aqui dentro, cada
estado ficou congelado e citável.

**O `watch.toml` — a lista do que roda sozinho.** Abra
`config/watch.toml.example` e repare na estrutura; cada bloco é uma fonte:

```toml
[[source]]
key = "gmail-today"        # nome estável (o snapshot deduplica por ele)
kind = "gmail"
window = "1d"
note = "digest do dia"

[[source]]
key = "slack-time-dados"
kind = "slack"
channel = "#time-dados"
window = "1d"

[[source]]
key = "gcal-primary"
kind = "gcal"
window = "14d"
note = "agenda ocupada — alimenta o planejador de foco"
```

Copie para `config/watch.toml` (o seu é privado, não vai pro git) e ajuste.
A partir daí, o noturno (e o `/update` manual) puxa exatamente essas fontes
— nem mais, nem menos.

**As duas portas Google que precisam de OAuth** (opcionais — sem elas tudo
funciona, só o foco sai como arquivo `.ics` e o backup como pasta local):
`python scripts/google_auth.py` autoriza **apenas** dois escopos mínimos:
`calendar.events.owned` (para criar/apagar os próprios blocos de foco) e
`drive.file` (para gravar os próprios zips de backup). O passo a passo com
telas está em `guides/google-oauth.md`. O token fica no `config/.env`, que
nunca sai da máquina e nunca aparece no chat.

---

## 5. Um dia normal com a ferramenta

A rotina inteira consome **poucos minutos ativos**. O resto é hábito de
jogar coisa na inbox.

**Ao acordar / abrir o mac (2 min)**

- Se o noturno não rodou às 05:00 (Mac dormindo — normal), rode
  `./brain nightly` — ou simplesmente digite `/brief`, que renderiza antes.
- `/brief` → hoje, atrasadas, próximos 3 dias, o que me devem, goal em
  risco, o que espera você. ≤15 linhas.
- Se houver proposta (`R-####`) esperando: decida — "aceita R-0001" ou
  "rejeita R-0001" com uma linha de por quê.

**Durante o dia (zero esforço — só captura)**

- Precisa lembrar de algo? `/todo falar com o Bruno sobre o draft até sexta`.
- Terminou algo? `/done A-0014 enviado, ele confirmou`.
- Meeting gravada/transcrita? Arraste o arquivo para `vault/RAW/inbox/`.
- Doc importante, print, nota solta? Mesma coisa: inbox. Sem organizar,
  sem renomear bonito — organizar é trabalho do agente, não seu.
- Curiosidade pontual? `/ask o que decidimos sobre o agente de suporte?`
- Vai entrar numa conversa com alguém? `/person ana` — card de preparação:
  quem é, o que ela te deve, o que você deve a ela, últimas decisões dela.

**Fim do dia (nada)**

Não existe "fechar o dia". Se houver material acumulado na inbox, processe
com `/dump` (2 min) — ou deixe: o noturno faz às 05:00, ou você faz de
manhã. O sistema não pune atraso de captura; ele pune só a não-captura.

---

## 6. A semana: foco, recap e o 1:1

**Sexta (ou domingo à noite, ~15 min):**

1. `/week` → cockpit de 14 dias: lookahead, radar de goals (progresso
   calculado vs. o que você declarou, lado a lado — nunca misturados),
   ações envelhecendo, conquistas da semana.
2. `/focus` → o plano de blocos da semana (explicado na seção 7). Confira a
   tabela, diga "ok", e os blocos nascem no calendário como *Focus time*
   (ou baixam um `.ics` para importar).
3. Preparando 1:1? `/share status` (ou `/share project P1`) gera um HTML
   limpo para enviar ao gestor; `/person ana` é o seu lado da mesa.
4. Fechando mês/ciclo? `/recap G1` monta o dossiê datado com histórico e
   impacto — cada afirmação com fonte.

---

## 7. Comandos de A a Z

Formato de cada verbete: **quando usar → o que digitar → o que acontece por
dentro → o que você recebe → pegadinhas**. Todos são digitados no chat do
agente, na pasta do repo. (No Claude Code eles são slash commands nativos;
em outros agentes, o texto é entendido do mesmo jeito.)

### Rotina diária

#### `/brief` — o dia
- **Quando:** toda manhã, ou "meu dia".
- **Digita:** `/brief`
- **Por dentro:** renderiza as views (colhendo antes os checkboxes que você
  marcou) e lê `FRESH/home.md` + `FRESH/todo.md` — números já calculados,
  o agente não recalcula nada.
- **Recebe:** ≤15 linhas — hoje · atrasadas (com dias de atraso e bloqueio)
  · próximos 3 dias · o que me devem · goal em foco · o que espera você
  (propostas, plano de foco, rascunhos). Aponta o painel para o resto.
- **Pegadinha:** nenhuma. É o comando mais seguro do sistema.

#### `/week` — a semana
- **Quando:** sextas (ou "minha semana").
- **Digita:** `/week`
- **Por dentro:** renderiza e lê `FRESH/home.md`, `goals.md`, `wins.md`,
  `focus.md`; escreve a narrativa em `FRESH/notes/semana.md` (narrativa é
  descartável, como tudo em FRESH).
- **Recebe:** o cockpit em ≤20 linhas — lookahead de 14 dias (minhas +
  o que me devem) · radar por goal (progresso calculado vs. declarado,
  saúde, próximo marco) · ações envelhecendo (abertas há mais de
  `aging_warn_days` sem movimento) · conquistas da semana · e a oferta de
  rodar `/focus` se não houver plano vigente.
- **Pegadinhas:** (1) propostas de mudança de plano só entram com evidência
  nova, uma de cada vez; (2) se você listar várias conclusões de uma vez,
  as ambíguas são confirmadas em lote, as claras fecham direto.

#### `/todo` — criar tarefa falando
- **Quando:** "preciso…", "tenho que…", "lembra de…".
- **Digita:** `/todo preciso ler a política de dados até quarta`
- **Por dentro:** prazo relativo ("quarta") vira data absoluta usando o dia
  de hoje; pessoas citadas são resolvidas por alias (ambíguo → ele pergunta;
  desconhecida → oferece cadastrar); projeto casado se for óbvio; esforço se
  você falou tempo ("2h"). Registrado como `[declarado]`, direto no ledger —
  não passa pela inbox.
- **Recebe:** a linha da ação: `✓ A-0012 · Ler a política de dados · vence
  15/10 · P1`. E a tarefa já está no painel.
- **Pegadinha:** tarefa sem prazo fica sem `due` — e o planejador de foco
  **ignora** o que não tem data. Ele avisa; escute.

#### `/done` — fechar tarefa
- **Quando:** "fechei/terminei X".
- **Digita:** `/done A-0014 enviei o draft, Bruno confirmou`
- **Por dentro:** ID exato fecha direto. Se você escrever texto em vez do
  ID, ele casa: achou uma única → confirma em 1 linha; várias → lista para
  você escolher; ação de terceiro ou muito antiga → sempre confirma antes.
  Se o fechamento tem resultado observável ligado a projeto, entregável ou desbloqueio, nasce automaticamente
  uma **entrega `E-####`** (isso alimenta suas conquistas). Ações que
  esperavam por essa recebem nota de "destravada" — não fecham sozinhas.
- **Recebe:** id, como fechou, se virou entrega, o que desbloqueou.
- **Pegadinha:** "operacional" não é entrega. Responder um e-mail não gera
  `E-####`; entregar o dicionário v1 gera. Não force — o sistema já julga.

### Entrada de informação

#### `/dump` — processar a inbox
- **Quando:** sempre que houver itens novos na inbox; é o coração do sistema.
- **Digita:** `/dump`
- **Por dentro:** para cada item — arquiva no mês certo (original intacto),
  classifica (reunião · documento · nota · conector), extrai o artefato
  (decisões com quem/quando/base, ações por dono, citações com minuto, no
  caso de reunião), resolve identidades, grava no ledger, renderiza.
  Se o extrator local (`[extractor]`) estiver ligado, o passo de extração
  usa o modelo local e o agente só revisa — mais barato e igualmente
  validado.
- **Recebe:** ~5 linhas por item (tipo, extrações, menções, estranheza) e o
  contador final `inbox: 0 restantes`.
- **Pegadinha:** nada. Rodar duas vezes não duplica (idempotente).

#### `/update` — puxar todas as fontes
- **Quando:** "atualiza tudo"; é o que o noturno roda sozinho.
- **Digita:** `/update`
- **Por dentro:** lê o `watch.toml`, puxa cada fonte pelo MCP de leitura,
  grava snapshot (idêntico = silêncio), roda `/dump` no que chegou,
  renderiza e sincroniza a memória.
- **Recebe:** recibo por fonte (puxado / sem novidade / falhou) + itens
  processados + avisos do doctor. Duas falhas seguidas da mesma fonte = ele
  escala para você em vez de fingir que está tudo bem.

#### `/connect` — uma fonte, agora
- **Quando:** "puxa o #seu-canal antes da reunião".
- **Digita:** `/connect slack-#seu-canal` (a key do watch ou algo ad hoc)
- **Recebe:** o snapshot processado na hora, só dessa fonte.
- **Pegadinha:** não confundir com `/update` (todas as fontes).

#### `/gmail` · `/slack` · `/calendar` · `/drive` — atalhos por fonte
- **Quando:** quer aquela fonte específica, com filtro seu.
- **Digita:** `/gmail da Ana` · `/slack #time-dados 3d` · `/calendar` ·
  `/drive política de dados v3`
- **Recebe:** digest/encaixe correspondente. `/calendar` é especial: não
  extrai ações — a agenda existe para o `/focus` saber seus buracos.
- **Pegadinha:** nenhum desses **escreve** nada em lugar nenhum. Enviar
  e-mail/mensagem é sempre `/outbox` ou você mesmo.

### Perguntas e navegação

#### `/ask` — pergunta livre
- **Quando:** "o que sabemos sobre X?".
- **Digita:** `/ask o que foi decidido sobre o congelamento do agente?`
- **Por dentro:** busca no índice determinístico (+ memória semântica se
  ligada), abre o artefato citado, desce ao original só se precisar da
  letra exata.
- **Recebe:** a resposta com fonte (`PROCESSED/2026/10/kickoff.md`) e
  proveniência ("decidido pela Ana em 02/10 [observado]"). Se não sabe:
  **"não consta"** — e isso é a resposta certa, não uma falha.
- **Pegadinha:** ele não completa com "conhecimento geral". Isso é feature.

#### `/person` — dossiê de alguém
- **Digita:** `/person ana`
- **Recebe:** quem é (papel, relação, aliases) · o que ela te deve (waiting)
  · o que você deve a ela · decisões dela (quem/quando/fonte) · última
  interação · threads abertas. É o card de prep de reunião.
- **Pegadinha:** nome ambíguo → ele lista candidatos e para. Cadastro novo
  é com `person add`, com aliases (evita ficha duplicada).

#### `/project` — status de um projeto
- **Digita:** `/project P1` (ou pelo título)
- **Recebe:** progresso calculado + declarado, saúde e o motivo, entregáveis,
  decisões ativas, minhas vs. waiting, próximo marco, evidência recente.
- **Pegadinha:** mudar a árvore do projeto não é aqui — é `/goal`.

#### `/map` · `/timeline` — a visão de cima
- **Digita:** `/map` (grafos: áreas→goals→projetos, pessoas×projetos,
  dependências entre ações) · `/timeline` (o que aconteceu + Gantt 30–45d)
- **Recebe:** 5–8 linhas do que o desenho revela AGORA (travas, projeto
  órfão, pessoa sobrecarregada; o que aperta nos próximos 30 dias).

### Plano

#### `/goal` — a árvore e o único gate estrutural
- **Quando:** ver a árvore; mudar estrutura (criar/fechar/renomear goal ou
  projeto); ou marcar entregável.
- **Ver:** `/goal` → árvore com progresso calculado e o declarado, lado a
  lado. Você pode declarar seu percentual de feeling (`brain progress G1 45`)
  — ele aparece AO LADO do calculado, nunca o substitui.
- **Marcar entregável feito:** é fato, não gate — com evidência: o agente
  atualiza o checkbox em `goals.md` e loga.
- **Mudar a estrutura:** o agente mostra o **diff exato** (antes/depois de
  `goals.md`), uma frase do porquê, e espera seu "ok" literal. Depois aplica
  e registra no `PLANNING/log.md` com a sua aprovação citada.
- **Pegadinha:** proposta rejeitada não volta sem evidência nova. Silêncio
  não aprova nada.

#### `/focus` — tempo protegido no calendário
- **Quando:** sexta (via `/week`) ou "agenda meu foco".
- **Digita:** `/focus`
- **Por dentro:** ele lê suas ações `mine` abertas (com prazo e esforço), a
  sua agenda (snapshot do `/calendar`) e monta blocos **EDF** — prazo mais
  próximo primeiro — respeitando horário comercial, almoço, férias, teto
  diário (padrão 180 min) e folga entre reuniões.
- **Recebe:** a tabela do lote (dia · hora · ação · prazo) + as ações **em
  risco** (não cabem na semana) + as que estão sem esforço estimado.
- **Aprovar:** responda "ok" (literal — é o que trava o hash do plano).
  Aí sim: blocos nascem no calendário como *Focus time* marcados
  (`brain_focus=1`) — eventos SEM essa marca nunca são tocados — ou baixa
  um `.ics` se você não ligou o OAuth.
- **Depois:** fechou a ação? Os blocos futuros dela somem no próximo sync
  (automático no noturno). **Pegadinha clássica:** não arraste o evento no
  calendário esperando o cérebro "entender" — mude o prazo da ação e gere
  outro plano.

### Mundo externo (as portas)

#### `/outbox` — o cérebro redige, você manda
- **Quando:** "cobra a Carla", "avisa o time do atraso".
- **Digita:** `/outbox cobrar a Carla sobre o MVP da planilha`
- **Por dentro:** destinatário precisa estar na allowlist
  (`[outbound].allow` no brain.toml — se não estiver, ele te mostra a linha
  e PARA). Ele redige um texto curto e mostra **inteiro**, numerado.
- **Aprovar:** `enviar 1` (ou "ok, manda"). O texto é travado por hash: o
  que sai é byte a byte o que você aprovou. Ele envia pelo Slack **como
  você** e registra o permalink.
- **Pegadinha:** pediu edição depois de aprovar? Cancela e rascunha de
  novo — aprovação não é herdada. Teto diário (`daily_max`) e noturno
  trancado por padrão.

#### `/share` — export para um colega
- **Quando:** "me dá um status do P1 pra mandar pra Ana".
- **Digita:** `/share project P1` (também: `/share goal G1`,
  `/share status`, `/share period 2026-09-01:2026-09-30`) — HTML ou MD.
- **Recebe:** um arquivo **autocontido** em `vault/reports/share/`, sem
  jargão interno, sem lista "observando", sem rascunhos. Revise e mande.
- **Pegadinha:** é um retrato datado — não atualiza sozinho. Para postar no
  canal do time (em vez de mandar para uma pessoa), existe a próxima porta.

#### `/recap` — história e impacto
- **Quando:** retrospectiva, review de trimestre, "o que fizemos de X?".
- **Digita:** `/recap G1` (ou projeto, ou período)
- **Recebe:** dossiê datado com o histórico e o impacto, cada afirmação com
  fonte; narrativa extra só com fatos do ledger. Nunca reescreve recap
  antigo — gera outro.

#### `/publish` — postar no espaço do time
- **Quando:** o report precisa ir para um canal/canvas/pasta do time.
- **Por dentro:** destino precisa estar em `[publish].destinations`; cada
  publicação tem pedido (`S-####`), conteúdo mostrado, "ok" seu, e o
  arquivo sai com hash travado — mudou depois de aprovado, refaz o pedido.

#### `/backup` — o zip do vault
- **Digita:** `/backup` (Drive, se ligado) · `/backup --local ~/Backups` ·
  `/backup --status`
- **Por dentro:** zip do vault → Drive (só cria/apaga os PRÓPRIOS
  `brain-backup-*.zip`, escopo mínimo `drive.file`) ou pasta local;
  retenção de 8; semanal no domingo (noturno). Segredos ficam fora por
  construção (`config/.env` não mora no vault). Arquivos gigantes ficam de
  fora do zip e entram no manifesto.
- **Restaurar:** baixar, extrair sobre um `vault/` vazio, conferir
  manifesto, `./brain doctor`, `./brain render` — o agente guia.
- **Pegadinha:** `/backup status` vazio = avise; não finja protegido.

### Manutenção

#### `/init` — nascer (uma vez por instância)
Já coberto na seção 3. Gatilho: PROFILE e PLANNING vazios.

#### `/upgrade` — o framework anda nos dois sentidos
- **Quando:** "atualiza o brain" / "sobe isso pro framework" / depois de um `git pull` que brigou.
- **Descer (`./brain update`):** o repo (framework) anda; o seu vault/config não tocam no git.
  Faz pull em avanço rápido com autostash, semeia arquivos novos de template sem sobrescrever
  nada seu, avisa quando um template que você já tem mudou e roda o doctor no fim.
- **Subir (git puro):** melhoria de código ou estrutura nascida na sua instância volta ao repo do
  framework com `git add`/`commit`/`push`, depois do seu "ok". Um hook `pre-push` roda
  `./brain upstream scan` e barra o envio se houver dado pessoal (nome, e-mail, pessoas do ledger,
  caminho da máquina, tokens) — o repo é público.
- **Pegadinha:** nunca force-push; nunca commitar `vault/` ou `.env`.

### Direto no terminal (sem agente)

| Comando | Para quê |
|---|---|
| `./brain render --open` | regenerar tudo e abrir o painel |
| `./brain status` | contagens rápidas |
| `./brain search "termo"` | busca sem LLM no ledger + artefatos |
| `./brain doctor [--online]` | saúde da instância (inclui memória) |
| `./brain validate` | revalida o ledger inteiro |
| `./brain extract <raw>` | rascunho de extração com modelo local (valida, não grava) |
| `./brain nightly` | o noturno na mão (render → /update → memória → backup-dom) |
| `./brain schedule install --time 05:00` | agendar o noturno |
| `./brain memory sync` / `recall "…"` | índice semântico (se ligado) |
| `./brain demo --dir /tmp/demo --open` | instancia fictícia para mostrar a alguém |

---

## 8. O painel — um passeio

`./brain render --open` abre `vault/FRESH/dashboard/index.html` — **um
arquivo**, offline, que funciona em qualquer navegador (dá para mandar para
você mesmo por Slack e abrir no celular). Tem modo escuro automático e
busca global. Abas:

- **Início** — o `/brief` visual: goals com barras de progresso (calculado
  **e** declarado), saúde, hoje + 7 dias (prazos, ações, blocos de foco),
  "precisa de você" (propostas, planos, rascunhos), conquistas e decisões
  recentes.
- **TODO** (badge: atrasadas) — três listas (minhas · aguardando ·
  observando) com atraso, esforço, projeto. Clicar numa ação abre a ficha.
- **Projetos** — ficha por projeto: entregáveis com peso, próximos marcos,
  saúde com motivo, decisões e ações ligadas. (A árvore completa de goals
  fica em `FRESH/goals.md`.)
- **Decisões** — quem decidiu, quando, com base em quê, substituídas por
  quais (cadeia de supersedes).
- **Conquistas** — wins por semana: entregas, entregáveis concluídos,
  ações fechadas.
- **Pessoas** — ficha por pessoa: papel, o que cada um deve ao outro,
  decisões que tomou, menções recentes.
- **Linha do tempo** — o que aconteceu e o que vem: prazos e marcos.
- **Foco** (badge: plano proposto) — o plano da semana e seus blocos.
- **Mensagens** (badge: rascunhos pendentes) — o outbox: rascunhos,
  enviadas, falhas. Nada sai sem sua aprovação do texto exato.
- **Saúde** (badge: avisos) — o `doctor` visual.

Fora das abas ficam dois arquivos Mermaid que o render gera e você abre no
editor/preview que renderizar Mermaid: `FRESH/map.md` (os três grafos do
`/map`) e `FRESH/timeline.md` (Gantt 30–45d).

Toda view carrega `generated-at` e `fontes` no topo — você sempre sabe o
quão fresco é o que está vendo e de onde derivou.

---

Prefere o teclado ao navegador? `./brain tui` abre o mesmo retrato num cockpit de
terminal (painéis, atalhos contextuais, paleta de comandos) e executa as escritas pelo
`./brain`, mostrando a linha exata antes de confirmar. É opcional: `./brain tui --setup`
instala o Textual numa venv à parte. Para experimentar com dados fictícios, abra
`guides/tui-mockup.html` no navegador.

## 9. Editar arquivos na mão: o que é colhido e o que é descartado

Pode abrir o `vault/` no editor que quiser. As regras de colheita (na
próxima renderização — automática no noturno ou via `/brief`):

| Você edita… | O que acontece |
|---|---|
| Checkbox em `FRESH/todo.md` (`- [x] **A-0012**…`) | fecha (ou reabre) a ação — vira declaração sua `[declarado]` |
| `status:` no frontmatter de `FRESH/records/actions/A-0012.md` | o mesmo, pelo vocabulário: `a fazer` · `fazendo` · `aguardando` · `feita` · `descartada` |
| Checkbox de entregável em `PLANNING/goals.md` | atualiza o estado factual (com data) |
| Qualquer outra coisa em `FRESH/` | **descartada** no próximo render — FRESH é retrato |

Regra geral: **estrutura vive no chat** (com gate), **fato vivo no chat ou
checkbox**, e `FRESH/` é só leitura prática.

---

## 10. Limites e segurança — o que ele NUNCA faz

- **Nunca** escreve no mundo exterior fora das 4 portas — e cada uso de
  porta exige aprovação literal sua.
- **Nunca** edita, renomeia ou apaga um original em `RAW/` (o arquivo morto
  é imutável).
- **Nunca** edita o livro-razão na mão (toda escrita é validada pelo CLI) —
  e revalida o histórico inteiro sob demanda (`./brain validate`).
- **Nunca** puxa fonte fora do `watch.toml`.
- **Nunca** mostra segredos no chat (`config/.env` é 600, fora do git,
  fora do backup).
- **Nunca** decide por você no noturno: sem dono presente, o ledger recusa
  aprovações, envios, publicações e foco no Google. O que o noturno achar
  dúbio vira proposta (`R-####`) de manhã.
- **Nunca** inventa memória: "não consta" é resposta de primeira classe.
- O **vault não sai da máquina** salvo pelas portas share/publish/backup.

---

## 11. Problemas comuns e soluções

| Sintoma | Causa provável | Saída |
|---|---|---|
| "o noturno não rodou" | Mac desligado/cron antigo (`./brain schedule status` mostra se é launchd); "Not logged in" no `nightly-agent.log` = ainda está no cron | `./brain nightly` manual de manhã — é o ritual recomendado mesmo |
| Ação nunca entra no plano de foco | sem `due` ou sem esforço estimado | `./brain action update A-#### --due … --effort 90m` e gere outro plano |
| Pessoa "não consta" ao citar alguém | ficha nova | `/person <nome>` → ele oferece cadastrar com aliases |
| Duas fichas da mesma pessoa | criadas antes dos aliases | `./brain person alias` funde por alias |
| `/ask` responde "não consta" para algo que existia | filtro muito estreito na busca | tente termo do título; se memória ligada, `./brain memory sync` |
| Extrator local não responde | LM Studio parado | `lms server start` (setup.md §3) |
| Painel "velho" | ninguém renderizou | `/brief` (renderiza antes) ou `./brain render --open` |
| Perigo/erro no doctor | ele diz exatamente o quê | siga a linha; se ledger: `./brain validate` |
| Restauro de backup | — | seção `/backup` acima; o agente guia passo a passo |

Se algo cheirar mal de verdade: `./brain doctor` e `./brain validate` são
os dois exames. Ledger corrompido (JSON inválido) é o único caso em que se
edita `events.jsonl` à mão — com backup, uma linha.

---

## 12. Glossário

- **Vault** — a pasta onde mora a sua vida profissional no sistema.
- **Ledger (livro-razão)** — `events.jsonl`, a verdade dos fatos, um evento
  por linha, append-only.
- **Artefato** — o resumo extraído de uma fonte, em `PROCESSED/<ano>/<mês>/`.
- **RAW** — originais, imutáveis. Inbox é a porta única.
- **FRESH** — views derivadas + painel; descartáveis por design.
- **Snapshot** — cópia datada de uma leitura externa (Slack/Gmail/…),
  gravada na inbox antes de ser usada.
- **Proveniência** — de onde veio o fato: `[declarado]` `[doc]`
  `[observado]` `[sem-fonte]`.
- **Gate** — ponto onde o agente para e espera sua aprovação literal.
- **Portas** — as 4 únicas escritas no mundo: foco (Calendar), mensagem
  (Slack), publicação (canvas/Drive), backup (Drive).
- **mine / waiting / watching** — as três listas: eu devo, me devem, é contexto.
- **Proposta (`R-####`)** — sugestão do agente esperando seu veredito.
- **Entrega (`E-####`)** — trabalho concluído com resultado observável.
- **Noturno** — rotina das 05:00: render → `/update` → memória → backup
  (domingo), com o dono ausente e as portas trancadas.
- **EDF** — Earliest Deadline First, a regra do planejador de foco: prazo
  mais próximo primeiro.
- **Idempotente** — rodar de novo não duplica nada (dump, snapshot, sync).
