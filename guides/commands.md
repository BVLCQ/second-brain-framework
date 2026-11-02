# Referência de comandos do `brain`

Todos os comandos do CLI, com todas as opções, variações e exemplos testados.
Para o *porquê* do sistema, veja [`user-guide.md`](user-guide.md); para o
detalhe de cada fluxo, [`manual.md`](manual.md). Para operar sem decorar
comandos, use o cockpit de terminal (`brain tui`); o guia interativo está em [`tui-mockup.html`](tui-mockup.html).

> Esta referência foi gerada a partir do parser real do CLI (`brain 2.0.0`):
> 32 comandos, com seus subcomandos. Se uma versão nova acrescentar algo,
> `brain <comando> --help` é sempre a fonte final.

## Índice

1. [Como chamar](#1-como-chamar)
2. [Conceitos que aparecem em todo comando](#2-conceitos-que-aparecem-em-todo-comando)
3. [Instância e saúde](#3-instância-e-saúde) — `init` · `demo` · `doctor` · `validate` · `status` · `update` · `upstream` · `watch` · `tui`
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
16. [Fontes](#16-fontes--snapshot) — `snapshot`
17. [Sugestões e bugs](#17-sugestões-e-bugs--feedback) — `feedback`
18. [Memória e MCP](#18-memória-e-mcp--memory--mcp) — `memory` · `mcp`
19. [Rotina noturna e backup](#19-rotina-noturna-e-backup--nightly--schedule--backup) — `nightly` · `schedule` · `backup`
20. [Slash commands do agente → CLI](#20-slash-commands-do-agente--cli)
21. [Serviços desta máquina](#21-serviços-desta-máquina-fora-do-cli)
22. [Receitas rápidas](#22-receitas-rápidas)
23. [Portfólio](#23-portfólio--area--process--opportunity--doc) — `area` · `process` · `opportunity` · `doc`
24. [Migração](#24-migração--migrate-ids) — `migrate ids`

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
| `TASK-####` | ação (tarefa) | `TASK-0014` |
| `DEC-####` | decisão | `DEC-0005` |
| `WIN-####` | entrega (conquista com resultado) | `WIN-0002` |
| `PROP-####` | proposta (o agente sugere, você decide) | `PROP-0001` |
| `MSG-####` | mensagem no outbox | `MSG-0001` |
| `PUB-####` | pedido de publicação | `PUB-0001` |
| `FOCUS-####` | plano de foco | `FOCUS-0001` |
| `FB-####` | sugestão/bug do cérebro (vira issue no repo público) | `FB-0001` |
| `PROC-####` | processo (portfólio) | `PROC-0003` |
| `OPP-####` | oportunidade / iniciativa (portfólio) | `OPP-0007` |
| slug | área do portfólio (`area.added`) | `operacoes` |
| `GOAL-#` / `PROJ-#` / `PROJ-#.#` | goal / projeto / entregável (em `PLANNING/goals.md`) | `GOAL-1`, `PROJ-1`, `PROJ-1.2` |

Pessoas usam um id curto (`marina-demo`) e aliases (`Marina-demo`, `M.-demo`). Em qualquer opção que
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
| `--owner-id ID` | seu id curto (ex.: `voce`) |
| `--owner-name NOME` | nome completo |
| `--alias ALIAS` | como você aparece nos textos |
| `--email EMAIL` | seu e-mail |

```bash
brain init --owner-id voce --owner-name "Seu Nome" --alias Você \
  --email voce@example.com
```
Depois, no chat do agente: `/init` (entrevista que preenche PROFILE e PLANNING).

### `brain demo`
Cria uma instância fictícia, completa, para ver o painel ou mostrar a alguém. Não toca no seu vault.

| Opção | Uso |
|---|---|
| `--dir PASTA` | **obrigatório**: onde criar |
| `--open [execucao\|portfolio]` | abre no navegador o painel (padrão) ou o mapa de oportunidades (`dashboard/portfolio.html`) |

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

### `brain watch`
Edita o `config/watch.toml`, o **universo observável**: o `/update` e o noturno só puxam as fontes listadas ali.
O comando mexe só nos blocos `[[source]]`; comentários, exemplos comentados e outras tabelas ficam como estão. Antes
de gravar, o arquivo inteiro é relido como TOML e as keys são checadas (única, `a-z0-9._-`); se algo não parseia,
nada é escrito. Quem *lê* as fontes é o agente (`/update`, `/connect`); o `brain snapshot` só grava o que ele leu.

| Subcomando | Uso |
|---|---|
| `list [--json]` | fontes cadastradas |
| `since KEY [--json]` | início da janela de leitura da fonte (`since`, `epoch`, `jql`) — é o que o agente usa; ele não calcula datas |
| `folders KEY [--file F] [--margin 3d] [--full] [--json]` | de uma pasta do Drive, quais subpastas descer: lê `[{id, name, modifiedTime?}]` (arquivo ou stdin) e compara a data da call no nome com o carimbo do último pull, menos a folga. Nome sem data ou pasta modificada desde o pull sempre desce; `--full` desce em todas |
| `add KEY --kind K` | `--window auto\|12h\|1d\|2w` · `--note "…"` · `--set campo=valor` (ex.: `channel=#time-dados`, `jql=…`; repita a opção) |
| `edit KEY` | mesmas opções, mais `--rename NOVA_KEY` e `--unset CAMPO`. `key` e `kind` não saem |
| `remove KEY` | tira do watch; snapshots já gravados e o ledger ficam |

```bash
brain watch add slack-time-dados --kind slack --window 1d --set channel=#time-dados
brain watch edit slack-time-dados --window 7d --unset note
brain watch list
brain watch since slack-time-dados
```
`window = "auto"` lê **desde o último pull bem-sucedido** (menos 2h de sobreposição; primeiro pull 7d; teto 14d), então
nada se repete e uma noite perdida é coberta sozinha. Pull sem novidade é `brain snapshot --key K --empty` (conta como
ok; vazio por erro do MCP continua sendo `--fail`). Janela fixa (`1d`, `7d`…) relê tudo a cada pull e repete mensagens
no RAW. `gcal` usa janela à frente e `drive` hash por arquivo — `auto` vale para slack, gmail e jira.
Códigos de saída: `4` key inválida ou repetida, ou arquivo que ficaria inválido; `3` fonte inexistente. Renomear uma
key deixa o histórico de pulls na key antiga.

### `brain tui`
Cockpit de terminal (Textual): cinco painéis numerados (status, ações, plano, aprovações, registro), o
detalhe do item, o log de comandos (o painel `6`, que expande quando selecionado) e uma barra com as teclas do contexto, como no lazygit. A leitura é
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
Sem o extra, `brain tui` sai com código 3 e a instrução. A aba **Fontes** do painel 1 gerencia o `watch.toml` (`n` adiciona, `e` edita, `x` remove, `w` inclui um pull avulso) e mostra o
último pull e as falhas de cada fonte. `u` (`/update`) atualiza tudo e `c` (`/connect`) puxa uma fonte: rodam o agente de `[runner]`,
que precisa de permissão para as ferramentas MCP de leitura (`[runner].allow`, ou `[runner].command`). Teclas: `?` ajuda do contexto · `:` paleta de
comandos · `g` busca · `/` filtro (com um id exato, `TASK-####`, `GOAL-#`, `PROJ-#`, `PROJ-#.#`, `DEC-####`…, mostra tudo que está associado a ele: o plano acima e abaixo, ações, decisões, entregas, pessoas; texto livre continua sendo busca no texto) · `N` nova nota (veja `brain note`) · `1`–`6` painéis (só pelos números; `6` é o log: `j` `k` rolam, `c` limpa) · `[` `]` ou `←` `→` abas · `⏎` ou duplo clique amplia o detalhe · `ctrl+t` troca o tema · `q` sai. O mouse também funciona: clique nas abas, nas linhas e nas dicas da barra, e a roda rola a lista. O TUI relê o vault sozinho quando ele muda fora dele (agente, outro terminal). O mapa
completo por contexto, a legenda e uma versão para experimentar com dados fictícios estão em
[`tui-mockup.html`](tui-mockup.html). Fora do TUI ficam só o que é do agente (`init`, `snapshot`, `add`,
`proposal add`; `outbox sent` e `publish done` ele registra ao enviar e publicar) e `demo`; o teste
`tests/test_tui.py::CoverageTest` garante que nenhum subcomando novo da CLI fique sem lugar ou sem justificativa. `[runner].allow` do `brain.toml` lista as ferramentas MCP de leitura do agente headless (noturno e TUI). Em `[tui]`, `model` e `effort` escolhem o modelo e o esforço do claude nas ações ⚡ (ex.: `haiku` · `high`; vazio = padrão; não valem com `[runner].command`), e `agent_allow` lista ferramentas extras, só do TUI, que o
agente pode usar nas ações ⚡ (por exemplo as de escrita do MCP do Slack, só para enviar uma mensagem aprovada).

### `brain serve`
Ponte CLI do painel HTML: o mesmo `FRESH/dashboard/index.html` que abre por `file://`, mas executando
os comandos de verdade — exatamente as linhas que o TUI dispara (`tui/bridge.run_brain`), com os gates
do CLI valendo igual (`--quote`, aprovações, `--by owner` nos fatos do dono).
```bash
brain serve            # imprime http://127.0.0.1:8787/#t=<token> — abra no navegador
brain serve --open     # já abre o navegador com o token na URL
brain serve --port 8791
```

No terminal, `brain <TAB>` completa os dois níveis de subcomando (e as opções na folha) se o
seu shell estiver apontado para `brain --completions` — no zsh, um `_brain` em `~/.zsh/completions`
resolve; a lista vem do próprio argparse, então nunca desencontra do CLI.
`brain render --open` usa a ponte sozinho: se ela estiver no ar abre o painel vivo; se não, sobe
uma (daemon, log em `logs/serve.log`) e abre do mesmo jeito — o retrato file:// fica para leitura pura.
Só escuta em `127.0.0.1`, com token (vem no fragmento da URL, guardado no `localStorage`; a `/api/*`
recusa sem ele). A allowlist é fechada: os subcomandos que o painel emite (ação, foco, perguntas,
mensagens, portfólio, plano…); todo o resto — `update`, `migrate`, `serve`, `init`, `backup` — é 403,
mesmo com o token. O noturno nunca serve. `file://` continua sendo retrato somente-leitura: os gestos
de escrita mostram a linha pronta e copiam para o terminal. Nenhuma porta nova para o mundo exterior:
a ponte só conversa com o `./brain` local.

### `brain pdf text` · `brain pdf render`
Leitura de PDF para o `/dump`, sem instalar nada obrigatório e sem tocar no vault (a saída vai para o stdout ou para uma pasta temporária).
```bash
brain pdf text "vault/RAW/inbox/glossario.pdf" --pages 1-3     # texto, com `=== PÁGINA n ===` entre as páginas
brain pdf render "vault/RAW/inbox/escaneado.pdf" --pages 1-2   # PNGs (--out DIR · --dpi 110); o agente lê a imagem
```
Ordem de leitores — texto: `pdftotext` (poppler) → PDFKit do macOS (via `swift`; o programa é compilado uma vez e fica em `~/Library/Caches/segundo-cerebro`) → `pypdf`, se instalado. Imagem: `pdftoppm` → PDFKit. Sem nenhum, sai com código 3 e a dica (`brew install poppler` ou `xcode-select --install`). Texto vazio = PDF escaneado: use `render` e leia as páginas como imagem.

### `brain video transcribe` · `brain video frames`
Análise de vídeo e áudio para o `/dump` — **todo vídeo na inbox é analisado**, sem pedir confirmação. Roda no dispositivo, sem ffmpeg e sem enviar nada para a nuvem (macOS 26+ com as Command Line Tools); não grava no vault.
```bash
brain video transcribe "gravacao.mp4" --locales pt-BR,es-MX --out rascunho.txt   # [hh:mm:ss] texto; --start/--length em segundos
brain video frames "gravacao.mp4" --every 150 --width 900                        # PNGs numa pasta temporária (--out DIR)
```
Com mais de um idioma (reunião bilíngue), cada idioma é transcrito por inteiro e, por minuto, vale o texto do idioma que de fato se fala. A transcrição automática erra nomes próprios e termos técnicos; confirme nos quadros (slides) e, para a letra exata, no próprio vídeo. Uma gravação de 80 min leva poucos minutos.

### `brain raw archive` · `brain raw sort` · `brain raw where`
O RAW é organizado por tipo: `RAW/<ano>/<mês>/<tipo>/<arquivo>`. Tipos: `slack` (snapshots do Slack), `meetings`
(transcrições do Meet, `.vtt`/`.srt`), `documents` (PDF, Office, `.md`/`.txt` soltos), `videos` (vídeo e áudio),
`artifacts` (`.html`), `notes` (notas do `brain note`), `images`, `connectors` (Jira, Gmail, Calendar, Databricks e
listagens do Drive), `github` (snapshots dos repositórios, `brain repos pull`) e `misc` (o resto). A classificação é por prefixo do snapshot e extensão — o mesmo arquivo cai
sempre na mesma pasta.

- `archive [arquivo…] [--type T] [--date AAAA-MM-DD]` — move da inbox para a pasta do tipo (o passo de arquivar do
  `/dump`). Sem argumento, tudo que está na inbox. `--type` força o tipo quando o conteúdo mostra outra coisa.
- `sort [--dry-run]` — arruma o RAW antigo, com arquivos soltos em `<ano>/<mês>/`. Idempotente. Grava o mapa
  origem → destino em `vault/logs/raw-sort-*.jsonl`. O ledger não é tocado.
- `where <caminho>` — onde está hoje um `RAW/…` guardado no ledger. O arquivo é achado pelo nome dentro do mesmo mês;
  é o que o TUI (`o`, abrir RAW) e o MCP `brain_read` usam.

Com a memória (Hindsight) ligada, rode `./brain memory rebuild` depois de um `sort`: os ids dos documentos são os caminhos, e o `sync` não remove os antigos.

### `brain note add` · `brain note edit` · `brain note list`
Notas avulsas do dono. `add` grava `<VÍNCULO>-AAAA-MM-DD-note.md` na **inbox** (a porta única): `TASK-0146-…`, `GOAL-1-…`,
`PROJ-2-…`, `PROJ-2.1-…`; sem vínculo, `note-…`; no mesmo dia e alvo vem o sufixo `-note-2.md`. O arquivo abre com um
frontmatter (`vinculo:`, `criada: AAAA-MM-DD HH:mm`) e depois o texto. O `/dump` arquiva em `RAW/<ano>/<mês>/notes/` sem
renomear, então o TUI acha a nota (inbox ou RAW) e a mostra no detalhe do vínculo, abaixo do histórico, com data e hora.
No TUI, `N` abre o formulário (caixa grande, vínculo opcional já preenchido com o item selecionado); `ctrl+o` abre o texto no seu `$VISUAL`/`$EDITOR` como Markdown e traz o resultado de volta. Se já existe nota **de hoje** para o mesmo vínculo e ela ainda está na inbox, o TUI pergunta: editar a existente (`brain note edit`, o texto novo entra no fim) ou criar outra (`…-note-2.md`). Nota já arquivada no RAW é imutável: só cria outra.

| Opção | Uso |
|---|---|
| `--link ID` | `TASK-####`, `GOAL-#`, `PROJ-#` ou `PROJ-#.#` (opcional; precisa existir). Em `list`, filtra |
| `--text TEXTO` | conteúdo da nota (padrão: stdin) |
| `--json` | saída em JSON |

`edit CAMINHO --text …` reescreve só nota ainda na inbox (`RAW/inbox/….md`), mantém vínculo e `criada:` e grava `editada:`.

Códigos de saída: `3` vínculo inexistente, nota vazia ou nota fora da inbox; `4` com `BRAIN_NIGHTLY=1` (nota é do dono). Não escreve no ledger.

---

## 4. Pessoas — `person`

### `brain person add NOME`
| Opção | Uso |
|---|---|
| `--id ID` | id curto (padrão: derivado do nome) |
| `--alias ALIAS` | apelido; repita a opção para vários |
| `--role PAPEL` | ex.: "Sócia, chef de confeitaria" |
| `--relation RELAÇÃO` | ex.: gestor, par, stakeholder |
| `--email EMAIL` | |
| + opções de registro | `--by --prov --source --date --actor --json` |

```bash
brain person add "Marina-demo" --id marina-demo --alias "Marina-demo" --role "Sócia, chef de confeitaria" --by owner
```

### `brain person alias ID ALIAS [ALIAS ...]`
Acrescenta aliases a uma pessoa existente (evita ficha duplicada).
```bash
brain person alias marina-demo "M.-demo" "Mari-demo" --by owner
```

### `brain person update ID`
Muda `--name`, `--role`, `--relation` ou `--email`, mais as opções de registro.
```bash
brain person update marina-demo --role "Sócia-gerente" --by owner
```


### `brain person merge ID --into ID`
Funde uma ficha duplicada em outra: a duplicada deixa de existir, e nome, id, e-mail e aliases dela viram aliases da que fica. Ações, decisões, artefatos e mensagens que apontavam para ela passam a apontar para a ficha que fica. Grava `person.merged` no ledger (append-only; as linhas antigas não mudam).
```bash
brain person merge marina-demo-2 --into marina-demo --reason "duplicada (mesmo e-mail)" --by owner
```

### `brain person resolve TEXTO`
Diz a quem um texto se refere (sem gravar nada). Ambíguo sai com código 2.
```bash
brain person resolve "a Marina-demo"     # marina-demo  Marina-demo  Sócia, chef de confeitaria
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
| `--project PROJ-#` | projeto do PLANNING |
| `--deliverable PROJ-#.#` | entregável ligado |
| `--blocked-by TASK-####` | esta ação espera aquela |
| `--unblocks TASK-####` | esta ação destrava aquela |
| `--people PESSOAS` | envolvidos (ids/aliases, vírgula) |
| `--priority alta\|normal\|baixa` | |
| `--link URL` | link externo |
| `--origin TEXTO` | de onde surgiu |
| `--force` | grava mesmo parecida com outra ação (você conferiu: é outra). Sem ele, parecida demais = código 2, nada gravado |
| + opções de registro | `--by --prov --source --date --actor --json` |

Antes de gravar, o CLI compara com as ações abertas e as fechadas há até 30 dias (radicais do título ponderados pela
raridade no ledger, mesmo link, mesmo entregável/projeto, pessoas). Parecida demais → recusa e mostra as candidatas;
parecida de leve → grava e avisa no stderr. Com `--force`, as candidatas ficam marcadas como julgadas (`not_dup`).
O mesmo vale para `action.opened` no `brain add` (`"not_dup": [ids]` no `data` faz o papel do `--force`).

```bash
brain action open "Ler a política de dados v3" --by owner --due 2026-10-20 --effort 1h --project PROJ-1
brain action open "Enviar orçamento da reforma" --by owner --owner marina-demo --due 2026-10-20   # → waiting
brain action open "Acompanhar o regulamento de exaustão da prefeitura" --by owner --owner sonia-demo --list watching
```

### `brain action update ID`
Muda qualquer campo da ação.

| Opção | Uso |
|---|---|
| `--note TEXTO` | anotação na linha do tempo da ação |
| `--status aberta\|fazendo\|aguardando` | status de trabalho |
| `--title`, `--owner`, `--list`, `--due`, `--effort`, `--project`, `--deliverable`, `--blocked-by`, `--unblocks`, `--people`, `--priority` | como no `open` |
| `--clear-due` | remove o prazo |
| `--park` / `--unpark` | "não agora": adia de propósito (só `--by owner`); o foco não agenda e a ação sai da vista "esta semana" da TUI. `--unpark` desfaz |
| + opções de registro | |

```bash
brain action update TASK-0012 --status fazendo --by owner
brain action update TASK-0012 --due 2026-10-25 --note "Marina-demo pediu mais 5 dias" --by owner
brain action update TASK-0012 --clear-due --by owner
```

### `brain action close ID`
| Opção | Uso |
|---|---|
| `--how TEXTO` | como foi fechada |
| `--outcome TEXTO` | resultado observável. **Vira entrega `WIN-####`** se houver projeto |
| `--delivery` | força o registro como entrega |
| `--delivery-title TÍTULO` | título da entrega gerada |
| `--evidence TEXTO/LINK` | prova |
| + opções de registro | |

```bash
brain action close TASK-0012 --how "enviei o draft, Heitor-demo confirmou" --by owner
brain action close TASK-0014 --how "publicado" --outcome "Manual de rotinas v1 no ar" --evidence https://… --by owner
```
Ações que esperavam por esta recebem nota de "destravada"; elas não fecham sozinhas.

### `brain action drop ID --reason MOTIVO`
Descarta (não foi feita e não será). `--reason` é obrigatório.
```bash
brain action drop TASK-0009 --reason "projeto cancelado" --by owner
```

Com `--duplicate-of TASK-####`, registra que foi descartada por ser duplicada daquela.

### `brain action dupes`
Sem `--title`: pares de ações **abertas** parecidas que ainda não foram julgados (nem `not-dup`, nem proposta sobre o par).
Com `--title` (e `--project`, `--deliverable`, `--people`, `--link`): candidatas para uma ação que vai nascer.
`--threshold 0.35` muda o corte; `--json` para o agente.
```bash
brain action dupes
brain action dupes --title "Pedir acesso de editor ao BigQuery" --project PROJ-2
```
Quem julga se é a mesma coisa é o agente (o CLI só aponta); quem decide é o dono, por proposta
`descartar-acao`/`unificar-acao`.

### `brain action not-dup ID OUTRO --reason MOTIVO`
Marca o par como ações diferentes; ele sai da varredura.

### `brain action merge ID --into OUTRO --by owner`
Unifica: `ID` (a duplicada) é descartada com `duplicate_of`; a que fica recebe pessoas (e o dono da outra, se diferente),
link (se não tinha), o prazo firme mais cedo, `blocked_by`/`unblocks` somados e uma nota "unificada com …". Quem esperava
pela duplicada passa a esperar pela que fica. Só `--by owner` (decisão do dono); `--title` renomeia a que fica.
```bash
brain proposal accept PROP-0007 --quote "ok"
brain action merge TASK-0074 --into TASK-0067 --by owner
```

### `brain action reopen ID --reason MOTIVO`
```bash
brain action reopen TASK-0012 --reason "faltou a parte do México" --by owner
```

### `brain action show ID`
Ficha completa com histórico.
```bash
brain action show TASK-0012
```

### `brain action list`
| Opção | Uso |
|---|---|
| `--list mine\|waiting\|watching` | filtra por lista |
| `--project PROJ-#` | filtra por projeto |
| `--owner PESSOA` | filtra por dono |
| `--all` | inclui fechadas e descartadas |
| `--json` | |

```bash
brain action list                    # abertas
brain action list --list waiting     # o que me devem
brain action list --project PROJ-1 --all
```

---

## 6. Decisões — `decision`

### `brain decision add TÍTULO --decided-by PESSOAS`
| Opção | Uso |
|---|---|
| `--decided-by PESSOAS` | **obrigatório**: quem decidiu (ids/aliases) |
| `--project PROJ-#` | |
| `--context TEXTO` | situação em que foi decidida |
| `--rationale TEXTO` | por quê |
| `--supersedes DEC-####` | substitui uma decisão anterior |
| + opções de registro | |

```bash
brain decision add "Congelar a compra do forno até o orçamento" --decided-by marina-demo \
  --rationale "qualidade dos dados abaixo do SLA" --project PROJ-1 --by owner --date 2026-10-10
```

### `brain decision supersede ID --reason MOTIVO`
Marca uma decisão como superada. `--by-decision DEC-####` aponta a decisão nova.
```bash
brain decision supersede DEC-0002 --by-decision DEC-0006 --reason "mudou o padrão" --by owner
```

### `brain decision list`
```bash
brain decision list
brain decision list --project PROJ-1
```

---

## 7. Entregas — `delivery`

### `brain delivery TÍTULO`
Entrega avulsa (conquista com resultado), sem precisar fechar uma ação.

| Opção | Uso |
|---|---|
| `--ref TASK-####\|PROJ-#\|PROJ-#.#\|GOAL-#` | a que se liga |
| `--result TEXTO` | o resultado |
| `--evidence TEXTO/LINK` | prova |
| `--impact TEXTO` | impacto (alimenta recaps e reviews) |
| + opções de registro | |

```bash
brain delivery "Cardápio do novo ponto fechado" --ref PROJ-2 --result "equipe usando a ficha técnica todo dia" \
  --impact "reduziu 3h/semana de conferência" --by owner
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
| `--projects PROJ-#,PROJ-#` | projetos |
| `--summary TEXTO` | resumo curto |
| + opções de registro | |

```bash
brain artifact PROCESSED/2026/10/vistoria-imovel.md --kind reuniao --title "Vistoria dados" \
  --raw RAW/2026/10/vistoria-imovel.md --people marina-demo,heitor-demo --projects PROJ-1 --by agent --prov observado \
  --source RAW/2026/10/vistoria-imovel.md
```

---

## 9. Propostas — `proposal`

O agente sugere; só você aceita ou rejeita. O noturno nunca aprova nada: ele cria propostas.

### `brain proposal add --kind TIPO --summary TEXTO`
| Opção | Uso |
|---|---|
| `--kind fechar-acao\|atualizar-acao\|descartar-acao\|unificar-acao\|mudar-plano\|reestimar\|outro` | **obrigatório** |
| `--summary TEXTO` | **obrigatório** |
| `--target ID` | alvo (ex.: `TASK-0012`, `PROJ-1`); em `descartar-acao`/`unificar-acao`, a duplicada (sai) |
| `--into ID` | `descartar-acao`/`unificar-acao`: a ação que fica |
| `--evidence TEXTO` | por que sugerir agora |
| + opções de registro | |

```bash
brain proposal add --kind fechar-acao --target TASK-0012 --summary "Heitor-demo confirmou no Slack" \
  --evidence "slack #dados 14/10" --by agent --prov observado --source RAW/2026/10/slack-dados.md
```

### `brain proposal accept ID --quote "RESPOSTA"` / `brain proposal reject ID --quote "RESPOSTA"`
`--quote` é obrigatório: a sua resposta **literal** fica registrada.
```bash
brain proposal accept PROP-0001 --quote "ok, pode fechar"
brain proposal reject PROP-0002 --quote "não, ainda falta o México"
```
Rejeitada não volta sem evidência nova. `descartar-acao`/`unificar-acao` se encerram sozinhas quando o dono descarta a
duplicada (aceita) ou quando uma das duas fecha por outro caminho (rejeitada).

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

### `brain plan deliverable PROJ-#.# --status STATUS`
Marca o estado de um entregável. É fato, não gate. Atualiza o checkbox em `goals.md` e grava no log.

| Opção | Uso |
|---|---|
| `--status nao-iniciado\|em-andamento\|feito\|cancelado` | **obrigatório**. `feito` grava a data |
| `--evidence TEXTO` | prova |
| + opções de registro | |

```bash
brain plan deliverable PROJ-1.2 --status feito --evidence "subiu em produção" --by owner
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
brain plan log --diff "PROJ-5 nasce sob GOAL-2" --reason "nova frente de retenção MX" --approval "ok"
```

### `brain plan add-goal` · `add-project` · `add-deliverable`
Criam nós em `PLANNING/goals.md` com o próximo id livre (`GOAL-#`, `PROJ-#`, `PROJ-#.#`; nunca reaproveitam número) e o texto no formato do
parser, no fim da seção certa. Se o arquivo não ficar válido, nada é gravado.

| Comando | Gate | Efeito |
|---|---|---|
| `plan add-goal TÍTULO [--horizon DATA] [--why TEXTO]` | **sim** | goal novo no fim do arquivo |
| `plan add-project GOAL-# TÍTULO [--owner PESSOA]` | **sim** | projeto no fim do goal |
| `plan add-deliverable PROJ-# TÍTULO [--due DATA] [--weight N]` | não | entregável no fim do projeto (título sem `·`) |

Goal e projeto são mudança estrutural: exigem `--approval "ok"` (resposta literal do dono) e gravam `plan.changed` no ledger e uma
linha em `PLANNING/log.md`; `--reason` e `--evidence` são opcionais. Entregável não é goal nem projeto: entra com uma linha no log, sem gate.
Código `4` sem `--approval` ou com `BRAIN_NIGHTLY=1`; `3` para pai inexistente ou título inválido. No TUI, no painel 3, `n` cria o que
o item selecionado comporta (goal → projeto, projeto → entregável, entregável → ação ligada a ele) e `G` cria um goal.

### `brain plan edit ID`
Edita um nó que já existe em `PLANNING/goals.md`, mantendo o id e o resto do arquivo como está. Só os campos passados mudam; `""`
remove o campo opcional. Se o arquivo não ficar válido, nada é gravado.

| Nó | Campos | Gate |
|---|---|---|
| `GOAL-#` | `--title` · `--status ativo\|congelado\|fechado` · `--horizon DATA` · `--why TEXTO` | **sim** |
| `PROJ-#` | `--title` · `--status` · `--owner PESSOA` | **sim** |
| `PROJ-#.#` | `--title` (sem `·`) · `--due DATA` · `--weight N` | não |

Goal e projeto exigem `--approval "ok"` e gravam `plan.changed` (com o antes → depois) no ledger e em `PLANNING/log.md`; `--reason` e
`--evidence` são opcionais. Entregável entra só com uma linha no log. O estado do entregável (feito, em andamento) continua em
`plan deliverable`. Código `4` sem `--approval` ou com `BRAIN_NIGHTLY=1`; `3` para nó inexistente, campo que não é do tipo ou valor inválido.
```bash
brain plan edit PROJ-1 --title "Padronização de métricas" --approval "ok"
brain plan edit PROJ-1.3 --due 2026-12-15 --weight 2
```
No TUI, no painel 3, `e` abre o formulário do item selecionado (goal e projeto pedem a aprovação digitada).

### `brain progress NÓ PCT`
Seu percentual "de feeling" para um goal/projeto. Aparece **ao lado** do calculado, nunca o substitui.
```bash
brain progress GOAL-1 45 --note "cardápio andou; reforma não"
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
   "source": "PROCESSED/2026/10/vistoria-imovel.md", "date": "2026-10-10",
   "data": {"title": "Congelar a compra do forno até o orçamento", "decided_by": ["marina-demo"]}},
  {"type": "action.opened", "by": "agent", "prov": "observado",
   "source": "PROCESSED/2026/10/vistoria-imovel.md",
   "data": {"title": "Enviar orçamento da reforma", "owner": "marina-demo", "list": "waiting", "due": "2026-10-20"}}
]
```
```bash
brain add lote.json          # ✓ decision.made DEC-0006 · ✓ action.opened TASK-0011
cat lote.json | brain add
```

Tipos aceitos e os campos obrigatórios em `data`:

| `type` | obrigatórios | | `type` | obrigatórios |
|---|---|---|---|---|
| `person.added` | `name` | | `proposal.opened` | `kind`, `summary` |
| `person.updated` | — | | `proposal.accepted` / `.rejected` | `quote` |
| | | | `proposal.superseded` (sistema) | `reason` |
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
brain search "forno"
brain search "manual" --limit 5 --json      # padrão: 20 resultados
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

### `brain focus approve FOCUS-#### --quote "RESPOSTA"`
```bash
brain focus approve FOCUS-0001 --quote "ok"
```

### `brain focus apply FOCUS-####`
| Opção | Uso |
|---|---|
| `--mode ics\|google` | `ics` gera `FRESH/focus/FOCUS-####.ics` para importar; `google` cria os eventos (exige OAuth). Padrão: `[focus] mode` |

```bash
brain focus apply FOCUS-0001
brain focus apply FOCUS-0001 --mode google
```

### `brain focus sync`
Remove os blocos futuros de ações já fechadas (o noturno faz isso sozinho).
```bash
brain focus sync --dry-run    # mostra o que sairia
brain focus sync
```

### `brain focus show [FOCUS-####]`
```bash
brain focus show            # plano vigente
brain focus show FOCUS-0001
```

> Para mudar um horário, não arraste o evento no calendário: mude o prazo ou o esforço da ação e gere outro plano.

---

## 14. Mensagens — `outbox`

Fluxo: **rascunho → você aprova o texto exato → envio → registro**. O texto aprovado
é travado por hash. Destinatário precisa estar em `[outbound].allow`, e há teto
diário em `daily_max`.

| Subcomando | Uso |
|---|---|
| `draft --to DEST --text TEXTO` | cria rascunho `MSG-####`. Opções: `--ref ID`, `--why TEXTO`, `--channel` (padrão `slack`) |
| `show ID` | mostra o rascunho inteiro |
| `approve ID --quote "RESPOSTA"` | aprova com sua resposta literal (ex.: `enviar 1`) |
| `sent ID [--link URL]` | registra que foi enviado (permalink) |
| `failed ID --error TEXTO` | registra falha de envio |
| `cancel ID [--reason TEXTO]` | cancela |
| `list [--all]` | pendentes (ou todas) |

```bash
brain outbox draft --to caio-demo --text "Oi Caio-demo, como está o orçamento da reforma?" --ref TASK-0005 --why "prazo venceu"
brain outbox show MSG-0001
brain outbox approve MSG-0001 --quote "enviar 1"
brain outbox sent MSG-0001 --link https://seu-workspace.slack.com/archives/…
brain outbox list --all
```
Quer editar depois de aprovado? `cancel` e um novo `draft`: a aprovação não é herdada.

---

## 15. Exportar e publicar — `share` · `publish`

### `brain share TIPO [ALVO]`
Gera um export **autocontido** em `vault/reports/share/`, sem jargão interno, para mandar a um colega.

| Forma | Exemplo |
|---|---|
| `project PROJ-#` | `brain share project PROJ-1` |
| `goal GOAL-#` | `brain share goal GOAL-1` |
| `status` | `brain share status` |
| `period AAAA-MM-DD:AAAA-MM-DD` | `brain share period 2026-09-01:2026-09-30` |
| `portfolio [--area ÁREA]` | `brain share portfolio --area Growth` — roadmap priorizado (ranking, matriz, status) |
| `opportunity OPP-####` | `brain share opportunity OPP-0003` — one-pager de uma oportunidade |
| `--format html\|md` | padrão `html` |

```bash
brain share project PROJ-1 --format md
```

### `brain publish`
Porta de publicação no espaço do time. Destino precisa estar em `[publish].destinations`.

| Subcomando | Uso |
|---|---|
| `request REPORT --to DESTINO` | pede publicação (`PUB-####`). Destino: `slack:#canal` ou `drive:<pasta>` |
| `approve ID --quote "RESPOSTA"` | aprova com sua resposta literal |
| `done ID [--link URL]` | registra que foi publicado |
| `cancel ID` | cancela |
| `list` | pedidos |

```bash
brain publish request reports/share/2026-10-14-project-p1.md --to "slack:#seu-canal"
brain publish approve PUB-0001 --quote "ok, publica"
brain publish done PUB-0001 --link https://…
```
O conteúdo é travado por hash: se o arquivo mudar depois da aprovação, refaça o pedido.

---

## 16. Fontes — `snapshot`

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
| `--item ID` | arquivo ou subpasta de uma **pasta observada** (id do Drive): hash próprio por item |
| `--rev REV` | revisão do item (ex.: `modifiedTime`); igual à do último pull = nada a ler nem gravar |
| `--name TÍTULO` | nome legível do item (só para o nome do arquivo na inbox) |
| `--check` | só pergunta se `--rev` já foi lido (`inalterado` / `mudou`), sem ler nem gravar |

```bash
echo "# notas" | brain snapshot --key notas-1on1 --prefix nota
brain snapshot --key gcal-14d --prefix gcal --ext json --file agenda.json
brain snapshot --key slack-gtm --fail "token expirado"
# pasta do Drive: um item por arquivo/subpasta
brain snapshot --key drive-reunioes --item 1AbC --rev 2026-10-15T18:02:11Z --check
brain snapshot --key drive-reunioes --item 1AbC --rev 2026-10-15T18:02:11Z --name "Ata 15/10" --prefix drive --file ata.md
```
Em pasta observada só o item que mudou gera arquivo. O mesmo conteúdo já guardado sob outra
chave ou item (atalho, arquivo movido de subpasta, chave antiga) não é duplicado. O `doctor`
continua vendo uma fonte só (a `--key`).
Depois: `/dump` no agente para processar.

---

## 17. Sugestões e bugs — `feedback`

O próprio cérebro tem uma porta de melhoria: cada sugestão ou bug registrado vira uma issue no
repo público do framework (`[feedback].repo` no `brain.toml`). Título `[sugestão] …` / `[bug] …`
+ label do tipo; o número e a URL do issue voltam para o ledger (`FB-####`).

```bash
brain feedback add "Painel demora a abrir" --kind bug --body "Abre em ~2s" --by owner
# ✓ FB-0001 · criado · [bug] Painel demora a abrir · #12 https://github.com/…
```

| Comando | O que faz |
|---|---|
| `add <título> --kind sugestao\|bug` | registra (`FB-####`) **e publica a issue na sequência** |
| `--no-push` / `push FB-####` | só registra / tenta publicar depois (a fila é o `list`) |
| `sync` | relê o estado dos issues no GitHub (aberta/fechada) e grava as mudanças — também no `/update` |
| `pushed FB-#### --number N --url U` | registra issue criada por fora (o push morreu depois de criar) |
| `failed FB-#### --error "…"` | registra falha de tentativa |
| `show FB-####` | o item e o issue **exato** que a porta publica |
| `list` / `list --all` | a fila (pendente/falhou) / tudo |

Regras da porta (AGENTS.md, porta 7): o pedido do dono no chat é a aprovação; sugestão que partiu
do agente só publica com um "ok". O issue é público — a porta recusa título/corpo com dado do dono
(nomes, e-mails, caminhos da máquina), sem override. Token: `GITHUB_TOKEN` em `config/.env`
(permissão de criar issues no repo). No noturno nada é publicado. Título repetido do mesmo tipo é
recusado — complete o existente ou use `--force`.

Superfícies: painel HTML (aba **Sugestões** — `n` registra e publica, `p` retry, `s` sincroniza; pela ponte do
`brain serve` executa de verdade), TUI (painel do **log (6) › aba Feedback** — `n` formulário, `p`
publica o pendente, `T` todas) e chat (`/feedback`). Os formulários do painel e da TUI cobrem os
campos da CLI: tipo, título, descrição, contexto (`--context`), publicar agora ou depois
(`--no-push`) e título repetido (aviso + criar mesmo assim = `--force`); `pushed`/`failed`
(recuperação manual) ficam no terminal.

---

## 18. Memória e MCP — `memory` · `mcp`

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
brain memory recall "o que foi decidido sobre o forno?"
brain memory recall "política de dados" --bank raw
brain memory recall "prazos" --tags proj:PROJ-1,pessoa:marina-demo
brain memory reflect "como está o projeto de churn?"
brain memory rebuild
```
Tags disponíveis: `tipo:<reuniao|documento|…|pessoa|planejamento|perfil|raw>`,
`proj:PROJ-#`, `pessoa:<id>`, `ext:<pdf|md|…>`.

### `brain mcp`
Servidor MCP **somente leitura** (stdio) para outras IAs consultarem o cérebro sem poder escrever.
```bash
claude mcp add segundo-cerebro -- brain mcp
```

---

## 19. Rotina noturna e backup — `nightly` · `schedule` · `backup`

### `brain nightly`
A rotina noturna na mão: render → agente (`/update`) → foco sync → memória → backup
(se for o dia) → render final. Log em `vault/logs/nightly.log`.
```bash
brain nightly
brain nightly --skip-agent     # pula o LLM (só render, memória, backup)
```
Sem agente de linha de comando instalado, a etapa do agente é pulada com aviso.

### `brain schedule install|remove|status`
Agenda o noturno: LaunchAgent no macOS (roda na sessão de login, onde o agente está autenticado), crontab nos demais.
```bash
brain schedule install --time 05:00    # padrão 05:00
brain schedule status
brain schedule remove
```
No macOS o launchd recupera o horário perdido quando o Mac acorda; no cron ele é pulado. Rode `brain nightly` de manhã se precisar.

### `brain backup`
Zip do vault para o Google Drive (`[backup]`, OAuth) ou uma pasta local. Retenção de 8 cópias.
```bash
brain backup                     # Drive
brain backup --local ~/Backups   # pasta local
brain backup --status            # últimos backups
```

---

## 20. Slash commands do agente → CLI

No chat do Claude Code (na pasta `~/brain`), os comandos `/` orquestram o CLI. O agente
lê, julga e mostra; o `brain` valida e grava.

| Slash | Para quê | CLI por baixo |
|---|---|---|
| `/init` | entrevista inicial: PROFILE + PLANNING | `person`, `plan log` |
| `/brief` | o dia em uma tela | `render`, lê `FRESH/home.md` + `todo.md` |
| `/week` | cockpit semanal | `render`, `proposal` |
| `/todo <texto>` | criar ação falando | `action open --by owner` |
| `/done TASK-#### <como>` | fechar ação | `action close` |
| `/dump` | processar a inbox | `artifact`, `add`, `render`, `memory sync` |
| `/update` | puxar todas as fontes do `watch.toml` | `snapshot`, `/dump` |
| `/connect <fonte>` | uma fonte, agora | `snapshot`, `/dump` |
| `/gmail` · `/slack` · `/calendar` · `/drive` | atalhos por fonte | `snapshot` |
| `/ask <pergunta>` | pergunta livre com fonte | `search`, `memory recall` |
| `/person <nome>` | dossiê de alguém | `person resolve`, `action list`, `decision list` |
| `/project PROJ-#` | status de projeto | `plan show`, `action list` |
| `/goal` | árvore e gate estrutural | `plan show`, `plan deliverable`, `plan log`, `progress` |
| `/map` · `/timeline` | visão de cima | `render` |
| `/focus` | blocos de foco | `focus plan/approve/apply` |
| `/outbox` | redigir e enviar no Slack | `outbox draft/approve/sent` |
| `/share` | export para colega | `share` |
| `/recap` | histórico e impacto datado | `search`, ledger |
| `/publish` | postar no espaço do time | `publish` |
| `/feedback` | sugerir/corrigir o próprio cérebro (issue no repo público) | `feedback add/push` |
| `/process <termo\|PROC-####>` | panorama ou cadastro guiado de um processo | `process`, `area`, `doc link` |
| `/opportunity <termo\|OPP-####>` · `onepager` · `triage` | oportunidades, one-pager e ICE sugerido | `opportunity`, `share opportunity` |
| `/backup` | zip do vault | `backup` |
| `/upgrade` | atualizar o framework e devolver melhorias da instância | `update`, `upstream scan`, `git`, `doctor` |

---

## 21. Serviços desta máquina (fora do CLI)

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

## 22. Receitas rápidas

```bash
# Manhã
brain doctor --online && brain render --open

# Criar e fechar uma tarefa sem agente
brain action open "Revisar proposta de pricing MX" --by owner --due 2026-10-17 --effort 2h
brain action close TASK-0015 --how "revisado e enviado à Lucía" --by owner

# O que me devem
brain action list --list waiting

# Registrar uma decisão que você tomou
brain decision add "Adiar o lançamento para março" --decided-by marina-demo --by owner

# Achar algo
brain search "lançamento"
brain memory recall "o que a Marina-demo decidiu sobre o forno?"

# Planejar foco da semana
brain focus plan && brain focus approve FOCUS-0001 --quote "ok" && brain focus apply FOCUS-0001

# Status para mandar ao gestor
brain share status --format md

# Conferir tudo
brain validate && brain doctor --online
```

---

## 23. Portfólio — `area` · `process` · `opportunity` · `doc`

Mapa de processos (`PROC-####`) e oportunidades/iniciativas (`OPP-####`) por área. Opções de registro (`--by`, `--prov`,
`--source`, `--date`) valem como nas outras entidades; `status`, `score` e `promote` já assumem `--by owner`.

### `brain area add|update|list`
`area add <slug> --name "…" [--alias …]` · `area update <slug> [--name] [--alias] [--note]` · `area list`.

### `brain process`
| Subcomando | Uso |
|---|---|
| `add "título" --area ÁREA` | `[--owner P] [--executor P…] [--recurrence diaria\|semanal\|quinzenal\|mensal\|trimestral\|sob-demanda\|por-evento] [--per-month N] [--duration 1h30m] [--tools …] [--io "entradas → saídas"] [--pain …] [--maturity 1-5] [--note …]`. Agente: `--by agent --source …` obrigatório |
| `update PROC-####` | mesmos campos; executores/ferramentas substituem a lista, dor e nota acrescentam |
| `retire PROC-#### --reason "…"` | aposenta |
| `show PROC-####` · `list [--area] [--gaps]` | leitura. **Horas/mês** = execuções/mês × duração × nº de executores, calculado pelo CLI |

### `brain opportunity`
| Subcomando | Uso |
|---|---|
| `add "título" --area ÁREA` | `[--process PROC-####] [--kind melhoria-de-processo\|novo-processo\|estruturante] [--problem] [--suggestion] [--gain] [--hours-saved N] [--person …] [--goal GOAL-#]`. Antes de gravar roda o **detector de duplicatas** (código 2, nada gravado; `--force` grava). Agente: só status `ideia`, `--source` obrigatório |
| `update OPP-####` | mesmos campos |
| `status OPP-#### STATUS [--reason]` | `ideia · triagem · priorizada · em-andamento · piloto · validando · entregue · em-espera · descartada`; vai e volta livremente; `em-espera`/`descartada` exigem `--reason`; `em-andamento` só com projeto (use `promote`); agente só grava `ideia` |
| `score OPP-#### --impact I --confidence C --ease F` | ICE 1–5 cada (score 1–125, calculado pelo CLI). `--suggest --reason "…"` (agente) grava só uma sugestão; o dono confirma ou muda |
| `evidence OPP-#### --source ARTEFATO` | mais uma fonte que reforça a oportunidade |
| `promote OPP-#### --goal GOAL-# [--title] [--approval "ok"]` | **gate**: sem `--approval` imprime o diff proposto do `goals.md` e sai com código 4; com ele cria o projeto, liga OPP ↔ PROJ-# e põe `em-andamento` (mesmo lote do ledger + linha em `PLANNING/log.md`). Proibido no noturno |
| `show OPP-####` · `list [--status] [--area] [--sort score]` | leitura |

### `brain doc`
`doc link PROC-####|OPP-#### --kind playbook\|one-pager\|planilha\|artefato\|apresentacao\|outro --ref <url|id|caminho> [--title] [--watch]` ·
`doc unlink <alvo> --ref …`. `--kind playbook --watch` com um doc do Drive cria a fonte `drive-doc` no `watch.toml`
(`playbook-proc-0001`): o `/update` só relê o doc quando o `modifiedTime` muda. Um artefato do `/dump` ligado ao processo
(`brain artifact … --link PROC-####`) mostra "playbook lido em …".

### `brain oppdrive` (porta 6 — pastas e one-pagers no Drive)
| Comando | O que faz |
|---|---|
| `status [OPP-####] [--pending] [--json]` | o que falta por OPP: pasta, one-pager, pasta Fontes, `template` (antigo/novo), arquivos fora do Resumo, `upload` (documentos a enviar para Fontes) e `mention` (reunião/Slack/nota: só menção) |
| `record OPP-#### --folder\|--onepager\|--sources-folder\|--source-file <id> --parent <parentId> [--raw R]` | registra pasta (direto na raiz), one-pager ou subpasta `Fontes` (na pasta da OPP), uma vez só; `--source-file` registra um documento enviado à `Fontes` (`--raw` = o RAW; o CLI recusa reunião, Slack, nota e o que não é da OPP) |
| `onepager OPP-#### [--detail F] [--out F]` | prévia em Markdown: Resumo em tabelas + Detalhamento |
| `build OPP-#### --detail F --end N --out plano.json` | pedidos `batchUpdate` que escrevem o doc inteiro (criação ou troca do template antigo); cada célula de valor vira intervalo nomeado `brain:<campo>`. Recusa doc já no template novo sem `--force` |
| `sync OPP-#### [--snapshot export.md] [--force] [--out plano.json]` | compara o Resumo com o Brain: `ok` · `desatualizado` (pedidos `replaceNamedRangeContent` só dos campos que mudaram) · `divergente`/`resumo-ausente` (alguém mexeu e o texto não bate: grava `ASK-####`, nada a escrever) · `template-antigo` |
| `links OPP-#### --doc-json read_doc.json --out plano.json` | pedidos de link no Resumo: `OPP-####: Título` com one-pager vira link para ele; documento enviado à `Fontes` vira link na linha de fontes. Só nas tabelas; roda depois do `update_doc` |
| `restyle OPP-#### --doc-json read_doc.json --out plano.json` | padrão de tabela da marca (`[oppdrive.brand]`: cabeçalho/rótulo na cor da marca com texto branco, corpo preto 10 pt, bordas cinza) nas tabelas de um doc já escrito; só estilo |
| `synced OPP-#### --plan plano.json` | registra o Resumo escrito (`doc.synced`), depois do `update_doc` |
| `suggested OPP-#### --doc <id> --what "…"` | registra uma sugestão no Detalhamento (`writeMode=SUGGEST`) |

---

## 24. Migração — `migrate ids`

`brain migrate ids [--apply] [--include-external]` — leva uma instância dos nomes antigos (`A-0146`, `D-`, `E-`, `R-`, `M-`, `S-`, `F-`,
`G1`, `P3`, `P3.2`) para os declarativos (`TASK-0146`, `DEC-`, `WIN-`, `PROP-`, `MSG-`, `PUB-`, `FOCUS-`, `GOAL-1`, `PROJ-3`, `PROJ-3.2`).
É a **exceção histórica** à regra de que o ledger só cresce: reescreve o ledger uma vez (mantém `seq` e `ts`, recalcula `text_sha`,
`content_sha` e o `sha` do plano de foco, grava `ids.migrated` no fim) e também as notas, `PROCESSED/`, `PLANNING/`, `reports/`,
`PROFILE/`, `config/watch.toml` e os nomes de arquivo que carregam um ID.

| Passo | O que acontece |
|---|---|
| sem `--apply` (dry-run) | não muda nada: escreve `vault/reports/migration/ids-<data>.md` com arquivos e substituições por zona, o diff do `goals.md` e cada ocorrência ambígua em RAW externo (±40 caracteres) |
| `--apply` | recusa no noturno e se já migrada; backup zip de `vault/` + `watch.toml` **fora** do vault, conferido; valida o ledger novo antes de trocar; renomeia; marcador `PROCESSED/_ledger/MIGRATED-ids`; apaga e regenera `FRESH/` |
| `--include-external` | migra também `G#`/`P#` em RAW externo (reuniões, Slack, conectores): lá "P1" costuma ser outra coisa. IDs longos (`A-0146`) sempre migram |

Só IDs que **existem** entram no mapa. `logs/` não é migrado. Com o Hindsight ligado, rode `brain memory rebuild` depois. Em instância
já nos nomes novos, o comando diz "nada a migrar". Peça ao agente para mostrar o relatório do dry-run antes do `--apply`.
