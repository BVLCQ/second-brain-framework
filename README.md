# Segundo Cérebro

Sistema local de pastas, Markdown e um livro-razão que organiza a vida
profissional de **uma pessoa**. Observa e organiza. Não trabalha pelo dono
no mundo exterior — salvo quatro portas estreitas, cada uma com aprovação
explícita: blocos de foco no calendário, mensagem no Slack, publicação no
espaço do time, backup no Drive.

A constituição é `AGENTS.md`. O manual completo é `guides/manual.md`.
O guia de uso A a Z — cada comando, cada conexão, a rotina normal — é
`guides/user-guide.md`. A instalação completa do stack local de IA
(LM Studio + Hindsight) é `setup.md`. O desenho da futura TUI, para
experimentar no navegador com dados fictícios, é `guides/tui-mockup.html`.

## Como ele funciona

- **Livro-razão JSONL** (`PROCESSED/_ledger/events.jsonl`) — IDs, validação,
  lock e fold determinísticos. O LLM não numera nada: toda escrita passa
  pelo `./brain`, que valida referências, proveniência e ciclo de vida.
- **O LLM extrai e julga; o CLI contabiliza.** A extração pode ser feita
  pelo agente da sessão **ou** por um modelo local barato (`./brain extract`
  via LM Studio) — o ledger valida os dois igualmente.
- **FRESH é 100% derivado** — `./brain render` regenera Markdown + painel
  HTML offline (um arquivo, abre no navegador: goals, projetos, decisões,
  TODO, timeline, Gantt, busca). Antes de sobrescrever, colhe as edições do
  dono (checkbox em `todo.md`, `status:` na ficha da ação, `PLANNING`).
- **Foco** — planejador EDF, teto diário, férias, folga entre reuniões.
  Lote semanal proposto → um "ok" → eventos no calendário (ou `.ics`, sem
  OAuth).
- **Outbox** — o cérebro redige; o dono aprova o texto exato; só então envia.
- **Memória para IA** — Hindsight opcional indexa o vault em mão única;
  Markdown + ledger continuam a verdade. Sem servidor, `/ask` usa o índice.
- **MCP somente-leitura** — `./brain mcp` para outras IAs consultarem o
  mesmo cérebro sem poder escrever.
- **Conectores** — leituras são MCP na sessão; o resultado vira snapshot na
  inbox. O noturno é agnóstico de agente (`claude`, `cursor`, `codex`,
  `agy`, `gemini`).

## Requisitos

- **Python 3.11+** — só biblioteca padrão, sem `pip install`. O repo usa
  [mise](https://mise.jdx.dev/) (`mise.toml`): `mise install` resolve a
  versão certa.
- Um agente com ferramentas MCP de leitura — **Claude Code** é o alvo de
  referência (comandos `/` em `.claude/commands/`); Cursor, Codex e outros
  funcionam lendo `commands/*/SKILL.md`.
- Opcional: **LM Studio** (extração local + embeddings), **Hindsight**
  (memória semântica), OAuth Google (foco no calendário / backup no Drive).
  O `setup.md` instala tudo — inclusive em máquina nova, executado por
  agente.

## Instalação

```bash
git clone <este-repo> ~/brain && cd ~/brain
mise install                 # Python 3.12 (ou qualquer 3.11+ já presente)
./brain init --owner-id seu-id --owner-name "Seu Nome"
./brain demo --dir /tmp/brain-demo --open   # vê o painel sem tocar no vault
```

Abra o chat do agente **nesta pasta** e digite `/init`. Ele entrevista,
propõe PROFILE + PLANNING e espera o seu "ok".

Para o stack completo local (LM Studio + extrator + Hindsight + noturno),
siga o **`setup.md`** — em uma máquina nova, basta pedir ao agente:
*execute o setup.md*.

Painel, depois de qualquer mudança:

```bash
./brain render --open
```

Noturno (render → agente `/update` → memória → backup semanal):

```bash
./brain schedule install --time 05:00
```

> No macOS o noturno roda por launchd (recupera o horário perdido com o Mac dormindo);
> no cron ele é pulado — `./brain nightly` manual de manhã é o ritual mais confiável.

## Mapa rápido

| Quero… | Comando |
|---|---|
| Ver o dia | `/brief` · `./brain render --open` |
| Criar tarefa | `/todo preciso ler X até quarta` |
| Fechar tarefa | `/done A-0014 enviei o draft` |
| Processar a inbox | `/dump` |
| Puxar fontes agora | `/update` ou `/gmail` `/slack` `/drive` `/calendar` |
| Agendar foco | `/focus` (proposta → "ok" → apply) |
| Mandar mensagem | `/outbox` (rascunho → "enviar 1") |
| Compartilhar status | `/share` · `/recap` · `/publish` |
| Perguntar | `/ask o que sabemos sobre X?` |
| Rascunho de extração com modelo local | `./brain extract vault/RAW/2026/10/x.md` |
| Saúde da instância | `./brain doctor` |

Toda escrita no livro-razão passa por `./brain`. O agente não edita
`events.jsonl` na mão. O CLI usa a instância do diretório atual (onde
existir `config/brain.toml`); `BRAIN_HOME` vence se estiver setada.

## Testes

```bash
python -m unittest tests.test_brain -v
```

Só biblioteca padrão. Relógio congelado em `BRAIN_NOW`. Sem rede.
O CI roda o suite em 3.11–3.14 a cada push.

## Linguagem

Conteúdo, views e skills em **português do Brasil**. Código, schema e nomes
de arquivo em inglês (kebab-case). Datas em templates são sempre relativas
("hoje"), nunca literais.

## Licença

MIT. Veja `LICENSE`.
