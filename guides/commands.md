# Referência de comandos do `brain`

Todos os comandos do CLI, com todas as opções, variações e exemplos testados.
Para o *porquê* do sistema, veja [`user-guide.md`](user-guide.md); para o
detalhe de cada fluxo, [`manual.md`](manual.md). Para operar sem decorar
comandos, use o cockpit de terminal (`brain tui`); o guia interativo está em [`tui-mockup.html`](tui-mockup.html).

> Esta referência foi gerada a partir do parser real do CLI (`brain 2.0.0`):
> 31 comandos, com seus subcomandos. Se uma versão nova acrescentar algo,
> `brain <comando> --help` é sempre a fonte final.

## Índice

1. [Como chamar](#1-como-chamar)
2. [Conceitos que aparecem em todo comando](#2-conceitos-que-aparecem-em-todo-comando)
3. [Instância e saúde](#3-instância-e-saúde) — `init` · `demo` · `doctor` · `validate` · `status` · `update` · `upstream` · `tui`
4. [Pessoas](#4-pessoas--person) — `person`
5. [Ações](#5-ações--action) — `action`
6. [Decisões](#6-decisões--decision) — `decision`
7. [Entregas](#7-entregas--delivery) — `delivery`
8. [Artefatos](#8-artefatos--artifact) — `artifact`
9. [Propostas](#9-propostas--proposal) — `proposal`
10. [Plano](#10-plano--plan-e-progress) — `plan` · `progress`
11. [Lote de eventos](#11-lote-de-eventos--add) — `add`
12. [Busca e views](#12-busca-e-views--search--render--sync) — `search` · `render` · `sync`
13. [Foco](#13-foco--focus) — `focus`
14. [Mensagens](#14-mensagens--outbox) — `outbox`
15. [Exportar e publicar](#15-exportar-e-publicar--share--publish) — `share` · `publish`
16. [Fontes e extração](#16-fontes-e-extração--snapshot--extract) — `snapshot` · `extract`
17. [Memória e MCP](#17-memória-e-mcp--memory--mcp) — `memory` · `mcp`
18. [Rotina noturna e backup](#18-rotina-noturna-e-backup--nightly--schedule--backup) — `nightly` · `schedule` · `backup`
19. [Slash commands do agente → CLI](#19-slash-commands-do-agente--cli)
20. [Serviços desta máquina](#20-serviços-desta-máquina-fora-do-cli)
21. [Receitas rápidas](#21-receitas-rápidas)

---

## 1. Como chamar

```bash
brain <comando> [subcomando] [opções]
brain --help                 # lista os comandos
brain <comando> --help       # opções de um comando
brain --version              # brain 2.0.0
```

- **`brain` funciona de qualquer pasta.** Ele está em `~/.local/bin/brain`, um link
  para `~/brain/brain`. `./brain` dentro do repo continua valendo; é o mesmo programa.
- **Qual instância ele usa:** se `BRAIN_HOME` estiver definido, usa essa. Senão, sobe da
  pasta atual até achar `config/brain.toml`. Senão, usa o próprio repo (`~/brain`).
  ```bash
  BRAIN_HOME=/tmp/brain-demo brain status    # opera numa instância de demo
  ```
- **Python:** exige 3.11+. Se o shell cair no Python do sistema (3.9), o `brain` se
  reexecuta sozinho pelo mise, e não é preciso `mise exec`.
- **Saída para máquina:** quase todo comando aceita `--json`.
- **Códigos de saída:** `0` ok · `1` uso errado · `2` ambíguo · `3` não achei ·
  `4` validação recusada · `5` livro-razão corrompido.

---

## 2. Conceitos que aparecem em todo comando

### IDs

| Prefixo | Entidade | Exemplo |
|---|---|---|
| `A-####` | ação (tarefa) | `A-0014` |
| `D-####` | decisão | `D-0005` |
| `E-####` | entrega (conquista com resultado) | `E-0002` |
| `R-####` | proposta (o agente sugere, você decide) | `R-0001` |
| `M-####` | mensagem no outbox | `M-0001` |
| `S-####` | pedido de publicação | `S-0001` |
| `F-####` | plano de foco | `F-0001` |
| `G#` / `P#` / `P#.n` | goal / projeto / entregável (em `PLANNING/goals.md`) | `G1`, `P1`, `P1.2` |

Pessoas usam um id curto (`ana`) e aliases (`Ana`, `Ana R.`). Em qualquer opção que
pede pessoa, vale o id ou o alias.

### Opções de registro (quem, de onde, quando)

Aparecem em todo comando que **grava** um fato no livro-razão:

| Opção | Valores | Padrão | Significado |
|---|---|---|---|
| `--by` | `owner` · `agent` · `system` | **`agent`** | quem está registrando: você (`owner`), o agente (`agent`) ou o motor (`system`) |
| `--prov` | `doc` · `observado` · `declarado` · `sem-fonte` | — | de onde veio o fato. **Obrigatório quando `--by agent`** |
| `--source` | caminho relativo ao vault, ou `chat` | — | artefato/RAW de origem (ex.: `PROCESSED/2026/10/ata.md`) |
| `--date` | `AAAA-MM-DD` | hoje | quando aconteceu **no mundo**, não quando você digitou |
| `--actor` | id de pessoa | — | quem fez a coisa, no mundo |
| `--json` | — | — | saída em JSON |

> **Digitando na mão? Use `--by owner`.** Como o padrão é `agent`, um comando sem
> `--by` exige `--prov` e falha com `ERRO: … proveniência obrigatória` (código 4).
> Com `--by owner` o fato vira declaração sua (`[declarado]`, `source: chat`).

Proveniência, em uma linha cada:
`[declarado]` você disse · `[doc]` está escrito num documento · `[observado]` o agente
extraiu de reunião/e-mail/Slack · `[sem-fonte]` sem base (evite) · `[sistema]` o
próprio motor.

### Listas de ação

| Lista | Quem deve | Cobrado no TODO? | Entra no foco? |
|---|---|---|---|
| `mine` | você | sim | sim |
| `waiting` | outra pessoa, a você | aparece no brief | não |
| `watching` | o time, a si mesmo | não | não |

Ao abrir uma ação com `--owner` de outra pessoa, ela cai em `waiting` automaticamente.

---

## 3. Instância e saúde

### `brain init`
Semeia o vault e a config a partir de `template/`. **Nunca sobrescreve** nada que já exista.

| Opção | Uso |
|---|---|
| `--owner-id ID` | seu id curto (ex.: `ana`) |
| `--owner-name NOME` | nome completo |
| `--alias ALIAS` | como você aparece nos textos |
| `--email EMAIL` | seu e-mail |

```bash
brain init --owner-id ana --owner-name "Ana Souza" --alias Ana \
  --email ana@example.com
```
Depois, no chat do agente: `/init` (entrevista que preenche PROFILE e PLANNING).

### `brain demo`
Cria uma instância fictícia, completa, para ver o painel ou mostrar a alguém. Não toca no seu vault.

| Opção | Uso |
|---|---|
| `--dir PASTA` | **obrigatório**: onde criar |
| `--open` | abre o painel no navegador |

```bash
brain demo --dir /tmp/brain-demo --open
BRAIN_HOME=/tmp/brain-demo brain status     # brincar com a demo pelo CLI
```

### `brain doctor`
Saúde da instância: config, zonas do vault, integridade do ledger, avisos do PLANNING,
alias ambíguo, inbox parada, noturno atrasado ou falho, fontes com erro, rascunhos,
plano de foco parado, OAuth.

| Opção | Uso |
|---|---|
| `--online` | também testa o servidor de memória (Hindsight) |
| `--json` | saída estruturada |

```bash
brain doctor
brain doctor --online
```

### `brain validate`
Relê o livro-razão inteiro, o PLANNING e os aliases; aponta qualquer inconsistência.
Sai com código 4 se houver problema. Sem opções.

```bash
brain validate      # ✓ ledger íntegro (N eventos)
```

### `brain status`
Contagens rápidas: minhas abertas, atrasadas, próximos 7 dias, aguardando outros,
conquistas em 30 dias, propostas, rascunhos, inbox.

```bash
brain status
brain status --json
```

### `brain update`
Traz as melhorias do framework (`git pull` seguro) **sem tocar no vault nem na config**.
Faz `fetch`, lista o que chegou (commits e arquivos por área), puxa só em avanço rápido com
autostash, semeia a partir de `template/` o que for novo no vault (nunca sobrescreve) e roda o
`doctor` com o código já atualizado. Se um arquivo de template que já é seu mudou no upstream,
ele avisa e mantém o seu — peça ao agente o diff. Recusa se `vault/` ou `config/.env` estiverem
rastreados pelo git.

| Opção | Uso |
|---|---|
| `--check` | só mostra o que há de novo; não altera nada |
| `--rebase` | seus commits locais ainda não enviados são re-aplicados por cima do upstream (sem isto, divergência é erro, código 2) |
| `--remote R` · `--branch B` | padrão `origin` e o branch atual |
| `--json` | saída estruturada |

```bash
brain update --check
brain update
brain update --rebase     # depois de commitar melhorias locais e o upstream ter andado
```

### `brain upstream scan` · `brain upstream hook`
O caminho de volta é **git puro**: melhoria nascida na instância (código, skill, guia, template,
teste) sobe ao repo do framework com `git add` · `commit` · `push`, para as outras instâncias se
beneficiarem. O `.gitignore` já protege `vault/` e a config pessoal; o que ele não pega é dado
pessoal **dentro** de arquivo do framework — e o repo é **público**. A varredura procura, no que
ainda não foi enviado (linhas adicionadas, arquivos novos, mensagens de commit): seu
nome/id/e-mail e domínio da empresa, pessoas do ledger, destinatários e destinos da config,
caminhos da sua máquina (`/Users/<você>`), workspace do Slack e padrões de segredo. Achado =
código 4. É rede de segurança — leia o diff.

| Comando | Uso |
|---|---|
| `scan` | à frente/atrás (sem rede), arquivos pendentes, achados, e o que está em `scripts/local/` (ignorado pelo git; gradue movendo para `scripts/` ou `brainlib/`) |
| `scan --committed` | só commits — o que um `git push` enviaria (é o que o hook roda) |
| `scan --fetch` · `--json` | atualiza o remoto antes · saída estruturada |
| `hook install\|remove\|status` | hook `pre-push` que roda `scan --committed` e **barra o push** se achar algo. `brain init` e `brain update` instalam; `git push --no-verify` ignora; não sobrescreve um pre-push que não seja do brain |

O `brain doctor` avisa de melhorias locais ainda não enviadas, de achados e de hook ausente.

```bash
brain upstream scan
git add -A brainlib guides && git commit -m "Hindsight: ajusta lote de consolidação"
git push                    # o hook roda a varredura; achado = push bloqueado
```

### `brain tui`
Cockpit de terminal (Textual): cinco painéis numerados (status, ações, plano, aprovações, registro), o
detalhe do item, o log de comandos e uma barra com as teclas do contexto, como no lazygit. A leitura é
em processo; **toda escrita é `./brain …` como subprocesso**, e a linha exata aparece no formulário (antes
de confirmar) e no log (depois). Gates e portas pedem a sua resposta digitada, e as ações do agente (⚡)
rodam o agente de `[runner]` em modo headless. O TUI se recusa a abrir com `BRAIN_NIGHTLY=1` (código 4).

É um extra **opcional**: o núcleo do brain continua só com a stdlib.

| Opção | Uso |
|---|---|
| `--setup` | cria `.venv-tui` e instala o Textual com versões e hashes travados (`requirements-tui.txt`) |

```bash
brain tui --setup     # uma vez
brain tui             # abre; usa a .venv-tui sozinho
```
Sem o extra, `brain tui` sai com código 3 e a instrução. Teclas: `?` ajuda do contexto · `:` paleta de
comandos · `g` busca · `/` filtro · `1`–`5` painéis (só pelos números) · `[` `]` ou `←` `→` abas · `⏎` ou duplo clique amplia o detalhe · `ctrl+t` troca o tema · `q` sai. O mouse também funciona: clique nas abas, nas linhas e nas dicas da barra, e a roda rola a lista. O TUI relê o vault sozinho quando ele muda fora dele (agente, outro terminal). O mapa
completo por contexto, a legenda e uma versão para experimentar com dados fictícios estão em
[`tui-mockup.html`](tui-mockup.html). Fora do TUI ficam só o que é do agente (`init`, `snapshot`, `add`, `extract`,
`proposal add`; `outbox sent` e `publish done` ele registra ao enviar e publicar) e `demo`; o teste
`tests/test_tui.py::CoverageTest` garante que nenhum subcomando novo da CLI fique sem lugar ou sem justificativa. Em `[tui]` do `brain.toml`, `agent_allow` lista ferramentas extras que o
agente pode usar nas ações ⚡ (por exemplo as de escrita do MCP do Slack, só para enviar uma mensagem aprovada).

---

## 4. Pessoas — `person`

### `brain person add NOME`
| Opção | Uso |
|---|---|
| `--id ID` | id curto (padrão: derivado do nome) |
| `--alias ALIAS` | apelido; repita a opção para vários |
| `--role PAPEL` | ex.: "Gestora de dados" |
| `--relation RELAÇÃO` | ex.: gestor, par, stakeholder |
| `--email EMAIL` | |
| + opções de registro | `--by --prov --source --date --actor --json` |

```bash
brain person add "Ana Ribeiro" --id ana --alias Ana --role "Gestora de dados" --by owner
```

### `brain person alias ID ALIAS [ALIAS ...]`
Acrescenta aliases a uma pessoa existente (evita ficha duplicada).
```bash
brain person alias ana "Ana R." "Aninha" --by owner
```

### `brain person update ID`
Muda `--name`, `--role`, `--relation` ou `--email`, mais as opções de registro.
```bash
brain person update ana --role "Head de Dados" --by owner
```

### `brain person resolve TEXTO`
Diz a quem um texto se refere (sem gravar nada). Ambíguo sai com código 2.
```bash
brain person resolve "a Ana"     # ana  Ana Ribeiro  Gestora de dados
```

### `brain person list`
```bash
brain person list
brain person list --json
```

---

## 5. Ações — `action`

### `brain action open TÍTULO`
| Opção | Uso |
|---|---|
| `--owner PESSOA` | dono da ação (padrão: você) |
| `--list mine\|waiting\|watching` | lista (padrão: `mine` se é sua, `waiting` se é de outro) |
| `--due AAAA-MM-DD` | prazo. **Sem prazo, o foco ignora a ação** |
| `--effort 90m\|2h\|1h30\|1d` | esforço estimado (usado pelo foco) |
| `--project P#` | projeto do PLANNING |
| `--deliverable P#.n` | entregável ligado |
| `--blocked-by A-####` | esta ação espera aquela |
| `--unblocks A-####` | esta ação destrava aquela |
| `--people PESSOAS` | envolvidos (ids/aliases, vírgula) |
| `--priority alta\|normal\|baixa` | |
| `--link URL` | link externo |
| `--origin TEXTO` | de onde surgiu |
| + opções de registro | `--by --prov --source --date --actor --json` |

```bash
brain action open "Ler a política de dados v3" --by owner --due 2026-10-20 --effort 1h --project P1
brain action open "Enviar diagnóstico do pipeline" --by owner --owner ana --due 2026-10-20   # → waiting
brain action open "Acompanhar migração de parceiros" --by owner --owner diego --list watching
```

### `brain action update ID`
Muda qualquer campo da ação.

| Opção | Uso |
|---|---|
| `--note TEXTO` | anotação na linha do tempo da ação |
| `--status aberta\|fazendo\|aguardando` | status de trabalho |
| `--title`, `--owner`, `--list`, `--due`, `--effort`, `--project`, `--deliverable`, `--blocked-by`, `--unblocks`, `--people`, `--priority` | como no `open` |
| `--clear-due` | remove o prazo |
| + opções de registro | |

```bash
brain action update A-0012 --status fazendo --by owner
brain action update A-0012 --due 2026-10-25 --note "Ana pediu mais 5 dias" --by owner
brain action update A-0012 --clear-due --by owner
```

### `brain action close ID`
| Opção | Uso |
|---|---|
| `--how TEXTO` | como foi fechada |
| `--outcome TEXTO` | resultado observável. **Vira entrega `E-####`** se houver projeto |
| `--delivery` | força o registro como entrega |
| `--delivery-title TÍTULO` | título da entrega gerada |
| `--evidence TEXTO/LINK` | prova |
| + opções de registro | |

```bash
brain action close A-0012 --how "enviei o draft, Bruno confirmou" --by owner
brain action close A-0014 --how "publicado" --outcome "Dicionário v1 no ar" --evidence https://… --by owner
```
Ações que esperavam por esta recebem nota de "destravada"; elas não fecham sozinhas.

### `brain action drop ID --reason MOTIVO`
Descarta (não foi feita e não será). `--reason` é obrigatório.
```bash
brain action drop A-0009 --reason "projeto cancelado" --by owner
```

### `brain action reopen ID --reason MOTIVO`
```bash
brain action reopen A-0012 --reason "faltou a parte do México" --by owner
```

### `brain action show ID`
Ficha completa com histórico.
```bash
brain action show A-0012
```

### `brain action list`
| Opção | Uso |
|---|---|
| `--list mine\|waiting\|watching` | filtra por lista |
| `--project P#` | filtra por projeto |
| `--owner PESSOA` | filtra por dono |
| `--all` | inclui fechadas e descartadas |
| `--json` | |

```bash
brain action list                    # abertas
brain action list --list waiting     # o que me devem
brain action list --project P1 --all
```

---

## 6. Decisões — `decision`

### `brain decision add TÍTULO --decided-by PESSOAS`
| Opção | Uso |
|---|---|
| `--decided-by PESSOAS` | **obrigatório**: quem decidiu (ids/aliases) |
| `--project P#` | |
| `--context TEXTO` | situação em que foi decidida |
| `--rationale TEXTO` | por quê |
| `--supersedes D-####` | substitui uma decisão anterior |
| + opções de registro | |

```bash
brain decision add "Congelar o pipeline até o diagnóstico" --decided-by ana \
  --rationale "qualidade dos dados abaixo do SLA" --project P1 --by owner --date 2026-10-10
```

### `brain decision supersede ID --reason MOTIVO`
Marca uma decisão como superada. `--by-decision D-####` aponta a decisão nova.
```bash
brain decision supersede D-0002 --by-decision D-0006 --reason "mudou o padrão" --by owner
```

### `brain decision list`
```bash
brain decision list
brain decision list --project P1
```

---

## 7. Entregas — `delivery`

### `brain delivery TÍTULO`
Entrega avulsa (conquista com resultado), sem precisar fechar uma ação.

| Opção | Uso |
|---|---|
| `--ref A-####\|P#\|P#.n\|G#` | a que se liga |
| `--result TEXTO` | o resultado |
| `--evidence TEXTO/LINK` | prova |
| `--impact TEXTO` | impacto (alimenta recaps e reviews) |
| + opções de registro | |

```bash
brain delivery "Dashboard de churn no ar" --ref P2 --result "time de CS usando diariamente" \
  --impact "reduziu 3h/semana de planilha" --by owner
```

---

## 8. Artefatos — `artifact`

### `brain artifact CAMINHO --kind TIPO --title TÍTULO`
Registra um texto de `PROCESSED/` (o resumo de uma fonte). É a trava de idempotência
do `/dump`: a mesma fonte não é processada duas vezes. Normalmente quem chama é o agente.

| Opção | Uso |
|---|---|
| `--kind reuniao\|documento\|nota\|conector` | **obrigatório** |
| `--title TÍTULO` | **obrigatório** |
| `--raw CAMINHO` | arquivo bruto de origem no RAW |
| `--people PESSOAS` | envolvidos |
| `--projects P#,P#` | projetos |
| `--summary TEXTO` | resumo curto |
| + opções de registro | |

```bash
brain artifact PROCESSED/2026/10/kickoff.md --kind reuniao --title "Kickoff dados" \
  --raw RAW/2026/10/kickoff.md --people ana,bruno --projects P1 --by agent --prov observado \
  --source RAW/2026/10/kickoff.md
```

---

## 9. Propostas — `proposal`

O agente sugere; só você aceita ou rejeita. O noturno nunca aprova nada: ele cria propostas.

### `brain proposal add --kind TIPO --summary TEXTO`
| Opção | Uso |
|---|---|
| `--kind fechar-acao\|atualizar-acao\|mudar-plano\|reestimar\|outro` | **obrigatório** |
| `--summary TEXTO` | **obrigatório** |
| `--target ID` | alvo (ex.: `A-0012`, `P1`) |
| `--evidence TEXTO` | por que sugerir agora |
| + opções de registro | |

```bash
brain proposal add --kind fechar-acao --target A-0012 --summary "Bruno confirmou no Slack" \
  --evidence "slack #dados 14/10" --by agent --prov observado --source RAW/2026/10/slack-dados.md
```

### `brain proposal accept ID --quote "RESPOSTA"` / `brain proposal reject ID --quote "RESPOSTA"`
`--quote` é obrigatório: a sua resposta **literal** fica registrada.
```bash
brain proposal accept R-0001 --quote "ok, pode fechar"
brain proposal reject R-0002 --quote "não, ainda falta o México"
```
Rejeitada não volta sem evidência nova.

### `brain proposal list`
```bash
brain proposal list          # pendentes
brain proposal list --all    # inclui respondidas
```

---

## 10. Plano — `plan` e `progress`

### `brain plan show`
A árvore goals → projetos → entregáveis, com progresso calculado e declarado.
```bash
brain plan show
brain plan show --json
```

### `brain plan deliverable P#.n --status STATUS`
Marca o estado de um entregável. É fato, não gate. Atualiza o checkbox em `goals.md` e grava no log.

| Opção | Uso |
|---|---|
| `--status nao-iniciado\|em-andamento\|feito\|cancelado` | **obrigatório**. `feito` grava a data |
| `--evidence TEXTO` | prova |
| + opções de registro | |

```bash
brain plan deliverable P1.2 --status feito --evidence "subiu em produção" --by owner
```

### `brain plan log --diff DIFF --reason MOTIVO --approval "RESPOSTA"`
O **único gate estrutural**: registra uma mudança **já aprovada** de goal/projeto
(criar, renomear, fechar). O agente mostra o diff, você diz "ok", ele edita o
`goals.md` e chama este comando com a sua resposta literal.

| Opção | Uso |
|---|---|
| `--diff TEXTO` | **obrigatório**: o que mudou |
| `--reason TEXTO` | **obrigatório**: por quê |
| `--approval TEXTO` | **obrigatório**: sua resposta literal (ex.: `ok`) |
| `--evidence TEXTO` | base da mudança |

```bash
brain plan log --diff "P5 nasce sob G2" --reason "nova frente de retenção MX" --approval "ok"
```

### `brain progress NÓ PCT`
Seu percentual "de feeling" para um goal/projeto. Aparece **ao lado** do calculado, nunca o substitui.
```bash
brain progress G1 45 --note "dicionário andou; pipeline não"
```

---

## 11. Lote de eventos — `add`

### `brain add [ARQUIVO]`
Grava vários eventos de uma vez: **ou entram todos, ou nenhum**. Lê de um arquivo JSON
ou da entrada padrão (`-` ou sem argumento). Aceita um objeto ou uma lista. É o que o
`/dump` usa quando uma ata gera várias decisões e ações.

Cada evento: `type`, `by`, `prov`, `source`, `date` (opcional), `actor` (opcional), `data`.

```json
[
  {"type": "decision.made", "by": "agent", "prov": "observado",
   "source": "PROCESSED/2026/10/kickoff.md", "date": "2026-10-10",
   "data": {"title": "Congelar o pipeline até o diagnóstico", "decided_by": ["ana"]}},
  {"type": "action.opened", "by": "agent", "prov": "observado",
   "source": "PROCESSED/2026/10/kickoff.md",
   "data": {"title": "Enviar diagnóstico do pipeline", "owner": "ana", "list": "waiting", "due": "2026-10-20"}}
]
```
```bash
brain add lote.json          # ✓ decision.made D-0006 · ✓ action.opened A-0011
cat lote.json | brain add
```

Tipos aceitos e os campos obrigatórios em `data`:

| `type` | obrigatórios | | `type` | obrigatórios |
|---|---|---|---|---|
| `person.added` | `name` | | `proposal.opened` | `kind`, `summary` |
| `person.updated` | — | | `proposal.accepted` / `.rejected` | `quote` |
| `action.opened` | `title`, `owner` | | `progress.declared` | `pct` |
| `action.updated` | — | | `plan.changed` | `diff`, `reason`, `approval` |
| `action.closed` | `how` | | `deliverable.updated` | `status` |
| `action.dropped` / `.reopened` | `reason` | | `artifact.added` | `kind`, `title` |
| `decision.made` | `title`, `decided_by` | | `delivery.recorded` | `title` |
| `decision.superseded` | `reason` | | | |

Mensagens (`message.*`), publicação (`share.*`), foco (`focus.*`) e conectores
(`connector.*`) também são eventos, mas são gravados pelos próprios comandos
`outbox`, `publish`, `focus` e `snapshot`, que calculam os hashes de travamento. Não os escreva à mão.

---

## 12. Busca e views — `search` · `render` · `sync`

### `brain search CONSULTA`
Busca determinística (sem LLM) no ledger e nos artefatos.
```bash
brain search "pipeline"
brain search "dicionário" --limit 5 --json      # padrão: 20 resultados
```

### `brain render`
Colhe as suas edições (checkbox no `todo.md`, `status:` na ficha da ação, checkbox em
`goals.md`) e **regenera todo o `FRESH/`**: Markdown e painel HTML.

| Opção | Uso |
|---|---|
| `--open` | abre o painel no navegador |
| `--no-harvest` | regenera **sem** colher edições |
| `--json` | |

```bash
brain render --open
```

### `brain sync`
Só colhe as suas edições, sem redesenhar as views.
```bash
brain sync
```

---

## 13. Foco — `focus`

Fluxo: **planejar → você aprova → aplicar**. Blocos EDF (prazo mais próximo primeiro)
nas suas ações `mine` abertas, com prazo, respeitando expediente, almoço, férias,
teto diário e folga entre reuniões (`[focus]` e `[work]` no `brain.toml`).

### `brain focus plan`
| Opção | Uso |
|---|---|
| `--days N` | horizonte (padrão: `horizon_days` do config, 7) |
| `--busy-file ARQUIVO` | JSON de eventos ocupados (snapshot do calendário) |
| `--json` | |

```bash
brain focus plan --days 5
```
Mostra a tabela, o que não cabe, o que está sem esforço e o comando de aprovação.

### `brain focus approve F-#### --quote "RESPOSTA"`
```bash
brain focus approve F-0001 --quote "ok"
```

### `brain focus apply F-####`
| Opção | Uso |
|---|---|
| `--mode ics\|google` | `ics` gera `FRESH/focus/F-####.ics` para importar; `google` cria os eventos (exige OAuth). Padrão: `[focus] mode` |

```bash
brain focus apply F-0001
brain focus apply F-0001 --mode google
```

### `brain focus sync`
Remove os blocos futuros de ações já fechadas (o noturno faz isso sozinho).
```bash
brain focus sync --dry-run    # mostra o que sairia
brain focus sync
```

### `brain focus show [F-####]`
```bash
brain focus show            # plano vigente
brain focus show F-0001
```

> Para mudar um horário, não arraste o evento no calendário: mude o prazo ou o esforço da ação e gere outro plano.

---

## 14. Mensagens — `outbox`

Fluxo: **rascunho → você aprova o texto exato → envio → registro**. O texto aprovado
é travado por hash. Destinatário precisa estar em `[outbound].allow`, e há teto
diário em `daily_max`.

| Subcomando | Uso |
|---|---|
| `draft --to DEST --text TEXTO` | cria rascunho `M-####`. Opções: `--ref ID`, `--why TEXTO`, `--channel` (padrão `slack`) |
| `show ID` | mostra o rascunho inteiro |
| `approve ID --quote "RESPOSTA"` | aprova com sua resposta literal (ex.: `enviar 1`) |
| `sent ID [--link URL]` | registra que foi enviado (permalink) |
| `failed ID --error TEXTO` | registra falha de envio |
| `cancel ID [--reason TEXTO]` | cancela |
| `list [--all]` | pendentes (ou todas) |

```bash
brain outbox draft --to carla --text "Oi Carla, como está o MVP da planilha?" --ref A-0005 --why "prazo venceu"
brain outbox show M-0001
brain outbox approve M-0001 --quote "enviar 1"
brain outbox sent M-0001 --link https://seu-workspace.slack.com/archives/…
brain outbox list --all
```
Quer editar depois de aprovado? `cancel` e um novo `draft`: a aprovação não é herdada.

---

## 15. Exportar e publicar — `share` · `publish`

### `brain share TIPO [ALVO]`
Gera um export **autocontido** em `vault/reports/share/`, sem jargão interno, para mandar a um colega.

| Forma | Exemplo |
|---|---|
| `project P#` | `brain share project P1` |
| `goal G#` | `brain share goal G1` |
| `status` | `brain share status` |
| `period AAAA-MM-DD:AAAA-MM-DD` | `brain share period 2026-09-01:2026-09-30` |
| `--format html\|md` | padrão `html` |

```bash
brain share project P1 --format md
```

### `brain publish`
Porta de publicação no espaço do time. Destino precisa estar em `[publish].destinations`.

| Subcomando | Uso |
|---|---|
| `request REPORT --to DESTINO` | pede publicação (`S-####`). Destino: `slack:#canal` ou `drive:<pasta>` |
| `approve ID --quote "RESPOSTA"` | aprova com sua resposta literal |
| `done ID [--link URL]` | registra que foi publicado |
| `cancel ID` | cancela |
| `list` | pedidos |

```bash
brain publish request reports/share/2026-10-14-project-p1.md --to "slack:#seu-canal"
brain publish approve S-0001 --quote "ok, publica"
brain publish done S-0001 --link https://…
```
O conteúdo é travado por hash: se o arquivo mudar depois da aprovação, refaça o pedido.

---

## 16. Fontes e extração — `snapshot` · `extract`

### `brain snapshot --key CHAVE`
Grava uma leitura de fonte (MCP de Slack, Gmail, Calendar, Drive…) na inbox. Conteúdo
idêntico ao anterior não grava nada (dedup por hash).

| Opção | Uso |
|---|---|
| `--key CHAVE` | **obrigatório**: identidade estável da fonte (ex.: `slack-gtm`) |
| `--prefix PREFIXO` | prefixo do arquivo (`slack`, `gmail`, `gcal`…) |
| `--ext md\|json\|txt\|csv` | padrão `md` |
| `--file ARQUIVO` | conteúdo (padrão: entrada padrão) |
| `--fail "ERRO"` | registra falha do pull em vez de conteúdo |

```bash
echo "# notas" | brain snapshot --key notas-1on1 --prefix nota
brain snapshot --key gcal-14d --prefix gcal --ext json --file agenda.json
brain snapshot --key slack-gtm --fail "token expirado"
```
Depois: `/dump` no agente para processar.

### `brain extract [ARQUIVO]`
Rascunho de extração com o modelo local do LM Studio (`[extractor]`). Mostra eventos
propostos, validados contra o ledger (`✓`/`✗`).

| Opção | Uso |
|---|---|
| `--kind auto\|reuniao\|documento\|nota\|conector` | padrão `auto` |
| `--record` | grava **somente** os eventos válidos |
| `--selftest` | prova ponta a ponta numa reunião do vault de demo (não toca no seu) |
| `--json` | |

```bash
brain extract --selftest
brain extract vault/RAW/2026/10/reuniao-1a1-ana.md
brain extract vault/RAW/2026/10/reuniao-1a1-ana.md --record
```

---

## 17. Memória e MCP — `memory` · `mcp`

A memória (Hindsight) é um **índice** do vault em mão única. O vault é a verdade:
se o servidor cair ou for apagado, `rebuild` reconstrói tudo.

| Subcomando | Uso |
|---|---|
| `setup` | cria/atualiza os bancos `brain-mem` e `brain-raw` |
| `sync [--limit N] [--dry-run]` | envia o que mudou (incremental). O noturno roda sozinho |
| `rebuild [--limit N] [--dry-run]` | apaga os dois bancos e reenvia tudo |
| `status` | estado dos bancos e pendências |
| `recall CONSULTA [--bank mem\|raw] [--tags a,b]` | busca semântica. Padrão `mem` (fatos); `raw` = texto original |
| `reflect CONSULTA [--bank] [--tags]` | resposta sintetizada pelo LLM a partir das memórias |

```bash
brain memory sync
brain memory sync --dry-run
brain memory recall "o que foi decidido sobre o pipeline?"
brain memory recall "política de dados" --bank raw
brain memory recall "prazos" --tags proj:P1,pessoa:ana
brain memory reflect "como está o projeto de churn?"
brain memory rebuild
```
Tags disponíveis: `tipo:<reuniao|documento|…|pessoa|planejamento|perfil|raw>`,
`proj:P#`, `pessoa:<id>`, `ext:<pdf|md|…>`.

### `brain mcp`
Servidor MCP **somente leitura** (stdio) para outras IAs consultarem o cérebro sem poder escrever.
```bash
claude mcp add segundo-cerebro -- brain mcp
```

---

## 18. Rotina noturna e backup — `nightly` · `schedule` · `backup`

### `brain nightly`
A rotina noturna na mão: render → agente (`/update`) → foco sync → memória → backup
(se for o dia) → render final. Log em `vault/logs/nightly.log`.
```bash
brain nightly
brain nightly --skip-agent     # pula o LLM (só render, memória, backup)
```
Sem agente de linha de comando instalado, a etapa do agente é pulada com aviso.

### `brain schedule install|remove|status`
Agenda o noturno no crontab.
```bash
brain schedule install --time 05:00    # padrão 05:00
brain schedule status
brain schedule remove
```
Mac dormindo no horário = o cron é pulado. Rode `brain nightly` de manhã se precisar.

### `brain backup`
Zip do vault para o Google Drive (`[backup]`, OAuth) ou uma pasta local. Retenção de 8 cópias.
```bash
brain backup                     # Drive
brain backup --local ~/Backups   # pasta local
brain backup --status            # últimos backups
```

---

## 19. Slash commands do agente → CLI

No chat do Claude Code (na pasta `~/brain`), os comandos `/` orquestram o CLI. O agente
lê, julga e mostra; o `brain` valida e grava.

| Slash | Para quê | CLI por baixo |
|---|---|---|
| `/init` | entrevista inicial: PROFILE + PLANNING | `person`, `plan log` |
| `/brief` | o dia em uma tela | `render`, lê `FRESH/home.md` + `todo.md` |
| `/week` | cockpit semanal | `render`, `proposal` |
| `/todo <texto>` | criar ação falando | `action open --by owner` |
| `/done A-#### <como>` | fechar ação | `action close` |
| `/dump` | processar a inbox | `artifact`, `add`, `extract`, `render`, `memory sync` |
| `/update` | puxar todas as fontes do `watch.toml` | `snapshot`, `/dump` |
| `/connect <fonte>` | uma fonte, agora | `snapshot`, `/dump` |
| `/gmail` · `/slack` · `/calendar` · `/drive` | atalhos por fonte | `snapshot` |
| `/ask <pergunta>` | pergunta livre com fonte | `search`, `memory recall` |
| `/person <nome>` | dossiê de alguém | `person resolve`, `action list`, `decision list` |
| `/project P#` | status de projeto | `plan show`, `action list` |
| `/goal` | árvore e gate estrutural | `plan show`, `plan deliverable`, `plan log`, `progress` |
| `/map` · `/timeline` | visão de cima | `render` |
| `/focus` | blocos de foco | `focus plan/approve/apply` |
| `/outbox` | redigir e enviar no Slack | `outbox draft/approve/sent` |
| `/share` | export para colega | `share` |
| `/recap` | histórico e impacto datado | `search`, ledger |
| `/publish` | postar no espaço do time | `publish` |
| `/backup` | zip do vault | `backup` |
| `/upgrade` | atualizar o framework e devolver melhorias da instância | `update`, `upstream scan`, `git`, `doctor` |

---

## 20. Serviços desta máquina (fora do CLI)

Específicos desta instalação (OrbStack + LM Studio + watchdog + hook).

| O quê | Comando |
|---|---|
| Subir/atualizar o Hindsight | `docker compose -f ~/brain/services/compose.yaml up -d` |
| Parar o Hindsight | `docker compose -f ~/brain/services/compose.yaml down` |
| Logs do Hindsight | `docker logs --tail 50 hindsight` |
| Saúde do Hindsight | `curl -s localhost:8888/health` |
| UI do Hindsight | http://localhost:9999 |
| Modelos carregados no LM Studio | `lms ps` |
| Servidor do LM Studio | `lms server start` / `lms server stop` |
| Pausar o watchdog | `touch ~/.brain-watchdog-off` (retomar: `rm ~/.brain-watchdog-off`) |
| Rodar o watchdog agora | `launchctl kickstart gui/$(id -u)/com.segundo-cerebro.watchdog` |
| Log do watchdog | `cat ~/brain/vault/logs/watchdog.log` |
| Descarregar modelos ociosos | automático, a cada minuto (LaunchAgent `com.segundo-cerebro.idle`): sem trabalho no LM Studio nem operações pendentes no Hindsight, o LLM sai após 5 min e o embedding após 15; se um modelo volta logo depois de descarregado, o tempo dele dobra (até 60 min); com pouca memória livre, metade da base. O JIT recarrega na próxima chamada |
| Ver o que o descarregador faria agora | `/usr/bin/python3 ~/brain/services/idle_unload.py ~/brain/vault/logs/idle-state.json --dry-run` |
| Log / estado do descarregador | `cat ~/brain/vault/logs/idle.log` · `cat ~/brain/vault/logs/idle-state.json` (tempo atual de cada modelo) |
| Instalar o descarregador | da raiz da instância: `sed "s\|__BRAIN_DIR__\|$PWD\|g" services/com.segundo-cerebro.idle.plist > ~/Library/LaunchAgents/com.segundo-cerebro.idle.plist && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.segundo-cerebro.idle.plist` (o plist do repo traz o placeholder `__BRAIN_DIR__`, nunca um caminho) |
| Ajustar o descarregador | `BRAIN_IDLE_LLM_MIN` (`5`), `BRAIN_IDLE_EMBED_MIN` (`15`), `BRAIN_IDLE_MAX_MIN` (`60`), `BRAIN_IDLE_KEEP` (nunca descarregar, ex.: `text-embedding-bge-m3`), `BRAIN_IDLE_UNLOAD_OFF=1` — em `EnvironmentVariables` de `services/com.segundo-cerebro.idle.plist`, depois `launchctl bootout gui/$(id -u)/com.segundo-cerebro.idle`, refazer o `sed` da linha acima e `bootstrap` |
| Desligar o contexto automático do Claude | `BRAIN_RECALL_OFF=1` no ambiente, ou remover o hook de `~/.claude/settings.json` |
| Ajustar o filtro do contexto automático | `BRAIN_RECALL_MIN_SCORE` (padrão `0.55`), `BRAIN_RECALL_MAX` (padrão `8`) |

---

## 21. Receitas rápidas

```bash
# Manhã
brain doctor --online && brain render --open

# Criar e fechar uma tarefa sem agente
brain action open "Revisar proposta de pricing MX" --by owner --due 2026-10-17 --effort 2h
brain action close A-0015 --how "revisado e enviado à Lucía" --by owner

# O que me devem
brain action list --list waiting

# Registrar uma decisão que você tomou
brain decision add "Adiar o lançamento para março" --decided-by ana --by owner

# Achar algo
brain search "lançamento"
brain memory recall "o que a Ana decidiu sobre o pipeline?"

# Planejar foco da semana
brain focus plan && brain focus approve F-0001 --quote "ok" && brain focus apply F-0001

# Status para mandar ao gestor
brain share status --format md

# Conferir tudo
brain validate && brain doctor --online
```
