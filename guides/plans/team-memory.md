# Plano — Memória de equipe (porta 8), v2: automática por padrão, privada por construção

> **Estado: PROPOSTA ATIVA (não implementada — porta 8 não existe no CLI nem na
> constituição).** Duas ressalvas ao executar: a decisão 11 de `memory-setups.md`
> (servidor também serve os harnesses) foi **revogada** em 2026-11-18 (v2.25.0); e a
> mecânica de "resposta literal" nos gates foi superada pela v2.24.0 (confirmar o
> formulário no painel/TUI já é a aprovação — a resposta digitada ficou só na CLI e
> no consentimento de nuvem do modo full).

Executor: agente de código da instância. Regime dos outros planos: testes verdes
(`python3 -m pytest tests/`), **um commit local por passo**, nada do dono no repo,
`./brain upstream scan` antes de propor o push.

Depende de: `guides/plans/memory-setups.md` (banco único `brain`, setups `embed`/`full`,
decisões 1–11 — não re-litigar) e do padrão das portas estreitas da `AGENTS.md`.

> **v2 substitui a v1.** A v1 pedia que o dono escolhesse e aprovasse cada item.
> Isso dava trabalho demais e ia matar o engajamento: sem engajamento, o banco do
> time gera **falso negativo** (projeto andou, nada subiu, e o time acha que está
> parado). A v2 inverte o padrão. **Tudo que é trabalho do time sobe sozinho.** O
> que é da pessoa nunca sobe, e só o caso duvidoso pede a mão do dono. O desenho
> assume o setup **`full`** (LLM em todo o processo). Gateway, namespace e LGPD da
> v1 continuam valendo.

---

## 0. Resumo para decidir

| | v1 (descartada) | v2 |
|---|---|---|
| O que o IC faz no dia a dia | escolhe e aprova cada item | **nada**: liga a porta uma vez e vincula os projetos ao time |
| O que sobe sem toque | nada | estado de trabalho dos projetos vinculados + fatos de time extraídos de reuniões e canais de time |
| Quem decide o que é de time | o dono, item a item | **regra determinística** (vínculo + tipo de fonte) e, dentro dela, **o LLM** classificando cada fato |
| O que pede o dono | tudo | só a **quarentena**: fato sensível, pessoa de fora, ou classificação incerta |
| Falso negativo | alto (depende de lembrar) | baixo, e o que sobra **fica visível** ("sem sinal há N dias") |
| LLM | opcional | `full`: projeção de time local + consolidação e mental models por tema no servidor |

**A ideia central em uma frase:** o "automático" se ancora em uma **árvore de
projetos compartilhada**, não no julgamento do LLM. Quando um projeto local está
vinculado a um projeto do time, tudo que acontece nele (entregável, decisão,
entrega, bloqueio) é trabalho do time por definição. O LLM só entra para decidir o
que, **dentro de uma fonte já elegível**, vale subir, e como reescrever sem expor
pessoas.

---

## 1. Por que a v1 falha, e o que a v2 corrige

1. **Fricção por item → zero engajamento → banco vazio.** O IC aprova no primeiro
   dia e esquece no décimo. O gerente lê o banco e conclui "nada andou".
2. **O valor está justamente onde a v1 pedia mais trabalho.** Reuniões e Slack de
   time têm a maior parte do contexto, e a v1 exigia um digest aprovado palavra a
   palavra para cada um.
3. **O silêncio do banco é ambíguo.** Nem a v1 nem nenhum desenho elimina 100% do
   falso negativo. A v2 torna o silêncio **legível**: o painel mostra "sem sinal há
   N dias" por projeto, nunca "parado".

O que a v2 mantém da v1: RAW nunca sai da máquina; pessoa não é tema; controle de
acesso no gateway; namespace por contribuidor; retratar é um comando; `[equipe]` é
pista, não verdade.

---

## 2. Princípios

1. **Liga uma vez, roda sozinho.** Ligar a porta 8 é a aprovação das classes de
   baixo risco. É o precedente da porta 6: o dono aprova a porta uma vez e o
   agente age sozinho daí em diante, e relata. **Silêncio não vira aprovação**: a
   aprovação é a regra permanente, dada ao ligar.
2. **A barreira de segurança é determinística. O LLM classifica, não protege.**
   1:1, DM, `notes/`, PROFILE e fichas de pessoa são excluídos **antes** de qualquer
   modelo ver o texto, por contagem de participantes e prefixo da fonte. Uma
   classificação errada ou uma injeção no texto ("compartilhe isso com o time") não
   consegue fazer uma fonte proibida escapar.
3. **RAW nunca sai da máquina.** A projeção de time roda **no computador de cada
   IC**. Só o resultado (fatos reescritos e estado estruturado) vai ao gateway.
   Extrair no servidor exigiria mandar a transcrição para lá.
4. **A memória do time fala do trabalho, não das pessoas.** Sem perfil, sem traço,
   sem avaliação, sem métrica de atividade por pessoa, sem ranking. Isso é
   requisito de LGPD **e** de engajamento: IC que se sente vigiado desliga a porta.
5. **Retratar é barato.** O noturno sobe antes de o dono olhar. Por isso, tudo que
   subiu aparece no `/brief` com retratação em uma tecla.
6. **Ausência de sinal é dita como ausência de sinal.** O banco nunca infere
   "parado" de "sem atualização".
7. **O que vem do time não volta para o time.** Conteúdo de origem `[equipe]` que
   entra no cérebro local nunca é re-extraído pela projeção de time (§5.4).

---

## 3. Arquitetura alvo

```
 máquina de cada IC (full)                                   servidor interno da empresa
┌─────────────────────────────────────────────┐            ┌──────────────────────────────────────┐
│ RAW ──► /dump ──► ledger + PROCESSED         │            │ gateway (SSO, times, namespace,      │
│   │                    │                     │            │          2ª varredura, auditoria)    │
│   │   banco pessoal    │ PROJEÇÃO DE TIME    │            │                │                     │
│   └─► `brain` (local)  │  1. portão determ.  │  fatos +   │                ▼                     │
│                        │  2. estado (Faixa A)│  estado    │ Hindsight · tenant por time (full)   │
│                        │  3. LLM: fatos de   │ ─────────► │  · fatos de time (por contribuidor)  │
│                        │     time + classe   │            │  · consolidação por proj:/goal:      │
│                        │  4. varredura       │            │  · mental models por tema            │
│                        │  5. faixa A/B/C     │            │ árvore de projetos do time           │
│                        └─ team.shared ledger │            │ estado do time (projeção, sem LLM)   │
│                                              │            │                │                     │
│ watch.toml: kind="team" ◄── snapshot ◄────── │ ◄───────── │ MCP somente-leitura (SSO)            │
│   → /dump → watching / propostas             │  leitura   │   ↑ Claude Code, Cursor, painel      │
│ hook: perna team · /ask · /brief · /week     │            │   ↑ painel do time (gerente e ICs)   │
└─────────────────────────────────────────────┘            └──────────────────────────────────────┘
```

### 3.1 Duas camadas no servidor

| Camada | O que é | Quem produz | LLM? | Responde |
|---|---|---|---|---|
| **Estado do time** | projeção estruturada: projetos do time, entregáveis, progresso, DEC, WIN, OPP/PROC, bloqueios entre membros, último sinal por projeto | eventos da Faixa A de cada IC, dobrados no gateway | não | "onde estamos", "o que está atrasado", "o que foi decidido" |
| **Memória do time** | fatos de time extraídos por cada IC + observações e mental models por tema | Faixa B dos ICs → Hindsight do time | sim | "por que mudamos X", "o que sabemos sobre o cliente Y", "o que já tentamos" |

Estado nunca passa pelo vetor (princípio 2 do plano da memória). É o que impede o
falso negativo de virar falso status.

### 3.2 A árvore de projetos do time (o vínculo)

- O gateway guarda a árvore do time: `TGOAL-#`, `TPROJ-#` e entregáveis. Quem a
  cria e edita é o coordenador (o mesmo gate estrutural do `goals.md`, só que do
  time).
- Cada IC vincula **uma vez** os projetos locais que fazem parte de um projeto do
  time: `brain team link PROJ-3 --to TPROJ-2`. O vínculo é um evento no ledger
  (`team.linked`). O `/init` e o `/week` propõem vínculos pendentes ("o PROJ-5
  parece com o TPROJ-4 — vincular?").
- Áreas também podem ser vinculadas (`brain team link area:operacoes --to
  <time>`), para OPP/PROC que ainda não viraram projeto.
- **Sem vínculo, nada da Faixa A sobe.** Esse é o único passo manual da v2, e
  acontece uma vez por projeto, não uma vez por item.

---

## 4. As faixas de risco (o coração da v2)

Toda unidade que pode subir cai em **uma** faixa. A faixa é decidida por regra
determinística e, só dentro das fontes elegíveis, pelo LLM.

| Faixa | O que é | Como sobe | O dono |
|---|---|---|---|
| **X — nunca** | 1:1 e DM (≤ 2 participantes ou prefixo `dm`), `notes/`, PROFILE, fichas de pessoa, ações pessoais (`mine` fora de projeto vinculado), `ASK`/`PROP`/`MSG`/`FOCUS`, RAW bruto de qualquer tipo, conteúdo de origem `[equipe]` | não sobe. **O CLI recusa, sem override** | não vê |
| **A — estado** | em projeto/área **vinculado**: entregável marcado/desmarcado, progresso, `DEC`, `WIN`, mudança de status de `OPP`/`PROC`, `blocked_by` entre membros do time, prazo de entregável | **automático e determinístico**, no mesmo `/dump` ou `/update` | vê no `/brief` ("subiu 7 itens"), retrata com uma tecla |
| **B — fatos de time** | fatos extraídos pelo LLM de **fontes de contexto coletivo**: reunião com ≥ 3 membros do time, canal de time (não DM), documento ligado a projeto vinculado. Classificados como `time` com confiança alta e sem alerta | **automático após uma janela** (padrão: até o próximo `/brief` ou 24 h). Na janela, aparecem em "vai subir" | pode segurar (`x`) ou retratar depois. A janela é conveniência; a aprovação é a regra dada ao ligar |
| **C — quarentena** | fato que o LLM ou a varredura marcou: tema sensível (saúde, desempenho, salário, desligamento, conflito), pessoa de fora do time (cliente, candidato), número/contrato confidencial, confiança baixa, ou fonte ambígua | **só com "ok"** do dono, item a item ou em lote (`subir 1 3 5`) | decide. Sem resposta em N dias, **expira sem subir** |

Por que funciona para engajamento: no regime normal o IC não toca em nada. A
quarentena é pequena por construção, porque a maioria do volume é Faixa A
(estado) e Faixa B (fatos de reunião de time). E o que cai em C é exatamente o que
o dono **quer** ver antes de sair.

### 4.1 A projeção de time (passo novo do `/dump`, modo full)

Para cada artefato novo, **depois** da extração pessoal:

1. **Portão determinístico.** Calcula a faixa X pela fonte: participantes (resolvidos
   por `brain person resolve` e casados com a lista de membros que o gateway
   publica), prefixo do canal, tipo do RAW, origem `[equipe]`. Se cair em X, para
   aqui e nenhum LLM vê o texto para fins de time.
2. **Faixa A.** Eventos do ledger ligados a projeto/área vinculado viram itens de
   estado, sem LLM.
3. **Extração de time (LLM).** Uma chamada com **missão de time** recebe o
   artefato (não o RAW) e o contexto do projeto do time, e devolve fatos no
   formato:
   `{fato, tipo: decisao|combinado|contexto|risco|aprendizado, projeto_time,
   classe: time|sensivel|pessoal, motivo, confianca}`.
   A missão proíbe citação literal, fala atribuída, traço/avaliação de pessoa e
   nome de fora do time, e manda **reescrever** em vez de omitir quando possível
   ("o cliente pediu prazo" em vez do nome do cliente).
4. **Verificações determinísticas na saída.** Anti-citação (n-grama de 8+ palavras
   em comum com o RAW → Faixa C), varredura `scrub` (e-mails, CPF/CNPJ, telefone,
   tokens, termos sensíveis), nome de pessoa fora da lista do time → Faixa C.
5. **Faixa.** `classe=time` + confiança alta + sem alerta → **B**. Qualquer outro caso
   → **C**. `classe=pessoal` → descartado (não sobe, não vai para a quarentena).
6. **Ledger.** `team.queued` (B/C) e, ao subir, `team.shared` com `text_sha`. O
   texto subido é o texto gravado. Se mudar, vira outro item.

### 4.2 Custo no `full`

A projeção de time é uma chamada por artefato elegível, do mesmo porte do retain.
Ordem de grandeza: **parecida com a linha de retain do cenário B**
(`memory-setups.md` §4.4, ~US$ 2,30/mês por IC com Haiku), porque só as fontes
coletivas passam do portão. Premissa: o volume de reunião e canal de time da
instância de referência. **Medido de verdade** por `brain memory cost`, com a
operação `team` separada. No servidor, a consolidação e os mental models do time
são custo **do time**, não dos ICs: um conjunto por projeto do time, com o mesmo
gatilho delta e o intervalo mínimo de 24 h dos mental models pessoais.

### 4.3 Provedor de LLM da projeção de time (decisão D2)

A decisão 2 do plano da memória (chave do dono, provedor livre) **continua valendo
para o banco pessoal**. A projeção de time é outra coisa: o resultado vai para a
infraestrutura da empresa e é lido por colegas. **Recomendação:** o time usa um
provedor aprovado pela empresa (contrato corporativo ou modelo interno), e o
`[team]` tem o próprio `llm_provider`, independente do `[memory]`.

### 4.4 O banco do time em `full`

- **Extração no servidor: desligada.** Os fatos já chegam extraídos. O retain do
  time é em `chunks` sobre fatos prontos, para não reprocessar.
- **Consolidação: ligada, mas só por tema.** É ela que junta a visão de vários ICs
  sobre o mesmo projeto, e esse é o valor do banco. Escopo pelas tags `proj:`/`goal:`.
- **Observações:** missão só sobre projetos, processos e modo de trabalho do
  **time**. A missão sozinha não basta (o prompt "não fale de pessoas" pode
  falhar), e por isso há dois controles que não dependem do LLM:
  1. o banco do time **não registra entidade PERSON nem aliases de pessoa**, só
     projetos, processos e áreas;
  2. o gateway **amostra as observações** e descarta as que têm pessoa como
     sujeito (verificação de saída, com log).
- **Mental models:** um por `TPROJ`/`TGOAL` e um "semana do time". **Nunca** por
  pessoa.

---

## 5. Como o contexto chega à IA e ao cérebro local de cada IC

### 5.1 Puxar na hora (consulta)

- **Hook de recall**: perna `team` no roteador (`services/hooks/recall_context.py`),
  ligada quando a porta está ativa. Ela entra **depois** da perna ledger e da
  pessoal, com prazo próprio, dentro do teto de 5 itens, e com marca
  `[equipe · <contribuidor> · <ref>]`.
- **`/ask`**: consulta local primeiro (índice → artefato → RAW), depois a memória do
  time. `[equipe]` fica abaixo de `[doc]`. Se divergirem, vale o vault do dono, e a
  divergência é dita.
- **Agentes fora do cérebro** (Claude Code, Cursor, Codex): o gateway expõe um
  **MCP somente-leitura** autenticado por SSO (`team.recall`, `team.state`,
  `team.decisions`, `team.model`). Qualquer agente do IC passa a saber o que o time
  decidiu sem que ninguém cole contexto.

### 5.2 Empurrar para o cérebro local (atualização)

É o caminho de leitura que a constituição já prevê: **fonte no `watch.toml` →
snapshot na inbox → `/dump`**.

- Fonte nova `kind = "team"` no `watch.toml`. O `/update` lê o **feed de mudanças**
  do gateway nos projetos vinculados e grava `team-<tproj>-<ts>.md` em
  `RAW/<ano>/<mês>/team/` (tipo novo de RAW).
- O `/dump` processa esse tipo como conector. O que vem do time cai em
  **`watching`** ou vira **proposta**, nunca `mine`/`waiting`, e nunca fecha nada
  sozinho. Exemplos:
  - entregável de outro IC concluído → proposta de destravar a sua ação que
    dependia dele;
  - decisão do time que muda o seu projeto → `watching` com link;
  - alguém do time marcou você em `blocked_by` → proposta de ação (você decide se
    ela é sua).
- `/brief` ganha a seção **"Time"**: o que mudou nos projetos vinculados desde
  ontem e o que você subiu ou tem na quarentena. `/week` ganha o **radar do time**.
- `/person <colega>` passa a mostrar o trabalho **compartilhado** com o colega
  (projetos do time em comum, decisões conjuntas), nunca nada privado dele.

### 5.3 Proveniência

`[equipe]` é a quinta proveniência (`[doc]` · `[observado]` · `[declarado]` ·
`[sem-fonte]` · `[equipe]`). Evento gravado a partir dela leva
`--source team:<contribuidor>/<ref>` e passa pelo fluxo normal de proposta.

### 5.4 O laço de eco (bug a evitar)

Sem cuidado, o fato do IC1 sobe, entra no cérebro do IC2 como RAW `team/`, a
projeção do IC2 re-extrai e sobe de novo com o IC2 como autor: duplicata e autoria
errada. Regras:

- o tipo de RAW `team/` é **Faixa X** no portão determinístico;
- evento com `source` `team:*` nunca vira Faixa A;
- **teste dedicado**: duas instâncias demo com o gateway falso; um fato sobe uma
  única vez, com um único contribuidor.

---

## 6. Benefícios

### 6.1 Para o IC

- **Para de repetir contexto.** O agente já sabe o que o time decidiu e por quê. A
  sessão começa informada.
- **Menos retrabalho.** "Alguém já tentou isso?" passa a ter resposta, com quem e
  quando.
- **Dependências visíveis.** O que outro IC entregou e destrava o seu trabalho
  chega como proposta, sem precisar perguntar no canal.
- **Handoff e férias.** Quem assume um projeto herda decisões, combinados e riscos.
- **Onboarding.** Quem chega pergunta ao banco do time em vez de ler 3 meses de
  Slack.
- **Custo de participar: zero.** Liga a porta, vincula os projetos e segue o
  trabalho normal.

### 6.2 Para o coordenador/gerente

- **Status sem reunião de status.** O painel do time é o estado do time (camada
  determinística), sempre atual: projetos, entregáveis, progresso calculado,
  prazo, bloqueios entre pessoas.
- **O porquê, não só o status.** Jira tem o card. O banco do time tem a
  **decisão**, quem decidiu, o motivo e o que foi descartado. É isso que falta no
  1:1 e na revisão do trimestre.
- **Radar de risco.** Entregável perto do prazo sem sinal, decisão sem dono,
  dependência cruzada bloqueada, projeto "sem sinal há N dias".
- **Portfólio do time.** OPP e PROC de todos os ICs num só mapa (o
  `portfolio.html` em escala de time), com ICE e estágio, para priorizar no
  planejamento.
- **Relatório semanal pronto.** Mental model "semana do time" + estado = rascunho
  de report que o gerente revisa e publica pela porta 3.
- **Memória institucional.** Quando alguém sai, o porquê das coisas fica.

### 6.3 O que o gerente **não** recebe (princípio 4)

Nenhuma visão por pessoa de "quanto compartilhou", "quanto trabalhou" ou "quantas
reuniões teve". Nenhum ranking, nenhum perfil. O painel organiza por **projeto**,
nunca por pessoa. Isso fica escrito, entra na `AGENTS.md` e é verificado por teste:
a API do gateway não tem consulta agregada por contribuidor.

---

## 7. Gateway, acesso e LGPD (mantidos da v1, com ajustes)

- **Auth:** OIDC do SSO corporativo (ou o header de identidade do proxy do portal
  interno). Nenhuma chave compartilhada nos clientes.
- **Autorização:** `membro → times`. Escrita só no próprio namespace; leitura nos
  próprios times; árvore do time editável só pelo coordenador.
- **Isolamento:** um tenant/schema por time via `TenantExtension` própria (spike na
  Fase 4 contra a 1.2.0). Fallback: banco por time com a chave do Hindsight guardada
  só no gateway, e o Hindsight sem porta publicada.
- **Segunda varredura** no recebimento, **verificação de saída** das observações,
  **auditoria** (consulta registrada com o hash da pergunta).
- **LGPD:** retratar (`brain team unshare`), purge quando um membro sai (decisão
  D7), remoção a pedido do titular pelo admin, com aviso ao contribuidor,
  retenção (D6).

---

## 8. Porta 8 — CLI e ledger

```
brain team enable                       # mostra o que a porta faz; grava a regra com "ok" (aprovação única)
brain team link PROJ-3 --to TPROJ-2     # vínculo (uma vez por projeto/área)
brain team links                        # vínculos + sugestões pendentes
brain team status                       # subiu hoje, na janela (B), na quarentena (C), retratados
brain team queue                        # quarentena com motivo; `subir 1 3` / `descartar 2`
brain team hold <ref> · unshare <ref>   # segura na janela · retrata depois
brain team sync                         # empurra A/B vencidos, retrata o que saiu do vínculo
brain team recall "<pergunta>"
brain team disable                      # para de subir; oferece retratar tudo
```

Eventos em `brainlib/schema.py`: `team.enabled`, `team.linked`/`unlinked`,
`team.queued` (faixa, motivo), `team.shared` (`text_sha`, faixa, `doc_id` remoto),
`team.held`, `team.retracted`, `team.disabled`.

**Noturno** (`BRAIN_NIGHTLY=1`): roda a projeção e sobe A e B vencidas (regra já
aprovada ao ligar, como a porta 6). Pode retratar. **Nunca** sobe C, nunca cria
vínculo e nunca liga a porta. Essa exceção vai escrita na `AGENTS.md`.

Superfícies: seção "Time" no `/brief`, radar no `/week`, aba **Equipe** na TUI
(Configurações › Memória e Execução) e no painel, com quarentena, janela e
retratação. Os botões de "subir" na quarentena pedem a resposta literal, como nas
outras portas.

---

## 9. Fases

As Fases 1–3 rodam **sem rede**: o dono já vê o que subiria (`brain team status
--dry-run`) antes de existir servidor.

| Fase | Entrega | Pronto quando |
|---|---|---|
| 0 | Decisões D1–D8, modelo de ameaça (colega curioso, admin, injeção no texto, inferência cruzada, eco) | decisões registradas aqui |
| 1 | Eventos `team.*`, vínculo, portão determinístico (Faixa X) e Faixa A, `scrub` comum (padrões do `upstream` + CPF/CNPJ/telefone/termos) | numa instância demo com DMs, 1:1, notas e reuniões, a Faixa X pega 100% e a Faixa A é determinística |
| 2 | Projeção LLM (missão de time, saída estruturada), anti-citação, faixas B/C, fila e janela, medição no `memory cost` | amostra de 50 artefatos revisada pelo dono: zero fato pessoal em B; C ≤ ~10% do volume |
| 3 | Laço de eco: tipo RAW `team/`, regras do §5.4 | teste das duas instâncias verde |
| 4 | Gateway de referência (`services/team-gateway/`): SSO, árvore do time, namespace, estado do time, 2ª varredura, auditoria, MCP somente-leitura; spike do tenant | membro de A não lê B; nenhuma consulta agregada por pessoa; item com CPF dá 422 |
| 5 | Cliente: `enable/link/sync/queue/hold/unshare`, passo no `/update` e no noturno | noturno sobe A/B, nunca C; retratar funciona com o gateway fora (retenta) |
| 6 | Leitura: fonte `kind="team"` no watch, `/dump` do tipo `team`, seção Time no `/brief`/`/week`, perna `team` no hook, `[equipe]` no `/ask` | o que vem do time cai só em `watching`/proposta |
| 7 | Banco do time em `full`: consolidação por tema, verificação de saída das observações, mental models por `TPROJ`/`TGOAL` e "semana do time", painel do time | amostragem de observações sem pessoa como sujeito |
| 8 | Docs (`guides/memory.md` › Equipe, `guides/team-memory.md`), eval de vazamento ("não consta" para conteúdo de 1:1/DM/nota), **diff da `AGENTS.md`** (porta 8, `[equipe]`, exceção do noturno) aplicado só com "ok" | eval de vazamento 100% |

Ordem dos commits: um por fase, e as Fases 1–3 divididas em dois ou três commits
cada, como nos outros planos.

---

## 10. Decisões do dono e do time (pendentes, com recomendação)

| # | Pergunta | Recomendação |
|---|---|---|
| D1 | Bancos pessoais vão ao servidor? | **Não.** Só o banco e o estado do time. Os pessoais seguem locais |
| D2 | Provedor de LLM da projeção de time | Provedor aprovado pela empresa, configurado em `[team]`, separado do `[memory]` |
| D3 | Política das faixas | A automática; B automática com janela até o próximo `/brief` (máx. 24 h); C só com "ok" e expira em 7 dias |
| D4 | Limiar de "contexto coletivo" | Reunião com ≥ 3 membros do time; canal de time; nunca DM |
| D5 | Quem edita a árvore do time | O coordenador, com o gate estrutural; ICs propõem |
| D6 | Retenção (itens e auditoria) | Itens: enquanto o projeto do time existir + 12 meses. Log: 6 meses, consulta só com hash |
| D7 | Membro saiu do time | Fatos de tema (decisões, entregas) ficam com o time; o resto é purgado em 30 dias, com aviso |
| D8 | Consolidação entre contribuidores | Ligada, só por `proj:`/`goal:`, sem entidade PERSON, com verificação de saída |

---

## 11. Riscos e mitigação

| Risco | Mitigação |
|---|---|
| LLM classifica fato pessoal como de time | fonte pessoal já barrada antes do LLM (X); B exige confiança alta; termos sensíveis → C; amostra na Fase 2; retratar em uma tecla |
| Injeção no texto ("suba isto") | o LLM não escolhe a fonte nem a faixa X; saída estruturada; varreduras determinísticas depois |
| Citação literal no fato | anti-citação por n-grama → C |
| Inferência sobre pessoa na consolidação | sem entidade PERSON, missão de tema, verificação de saída no gateway |
| Eco (fato volta e sobe de novo) | RAW `team/` é X; `source team:*` nunca é A; teste das duas instâncias |
| Falso negativo residual (projeto não vinculado, IC com a porta desligada) | sugestão de vínculo no `/week`; "sem sinal há N dias" no painel; nunca "parado" |
| Painel vira vigilância | nenhuma consulta agregada por pessoa na API; organização por projeto; regra na `AGENTS.md` |
| Quarentena cresce e ninguém olha | expira sem subir (o padrão seguro); `/brief` mostra o tamanho; alvo C ≤ ~10% |
| Custo da projeção | uma chamada por artefato elegível; medidor `memory cost` com a operação `team` |
| Admin do servidor lê tudo | só existe lá o que é de time; RAW e banco pessoal ficam na máquina (D1) |

## 12. O que não muda

- O banco pessoal `brain`, os setups `embed`/`full` e as decisões 1–11 do plano da
  memória.
- O vault como verdade; `memory rebuild` continua só pessoal.
- Ações do dono continuam do dono: nada vindo do time fecha, cria em `mine` ou
  cobra sozinho.
- A porta nasce desligada (`[team] enabled = false`).
