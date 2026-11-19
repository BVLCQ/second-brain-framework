# Segundo Cérebro

Sistema local de pastas, Markdown e um livro-razão que organiza a vida
profissional de **uma pessoa**. Observa e organiza. Não trabalha pelo dono
no mundo exterior — salvo as portas estreitas, cada uma com escopo mínimo e
aprovação explícita: blocos de foco no calendário, mensagem no Slack,
publicação no espaço do time, backup no Drive, pastas de oportunidade no
Drive, sugestões/bugs como issue no GitHub e as melhorias do próprio
framework (upstream). A lista completa está em `AGENTS.md`.

A constituição é `AGENTS.md`. O guia de uso A a Z — cada comando, cada conexão, a rotina normal — é
`guides/user-guide.md`. A instalação completa do stack local de IA
(LM Studio + Hindsight) é `setup.md`.

## Como ele funciona

- **Livro-razão JSONL** (`PROCESSED/_ledger/events.jsonl`) — IDs, validação,
  lock e fold determinísticos. O LLM não numera nada: toda escrita passa
  pelo `./brain`, que valida referências, proveniência e ciclo de vida.
- **O LLM extrai e julga; o CLI contabiliza.** A extração pode ser feita
  pelo agente da sessão — o ledger valida referências, proveniência e ciclo
  de vida de tudo que ele grava.
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

- **Nada pré-instalado é exigido** — o instalador cuida do que faltar: git,
  Homebrew, mise, **Python 3.12** (pin do `mise.toml`) e o runtime de
  contêiner (OrbStack no macOS, Docker Engine no Linux/WSL2) — silencioso e
  idempotente. O CLI em si usa só biblioteca padrão, sem `pip install`.
- **Agente de IA: qualquer um — ou nenhum.** O Brain é agnóstico: Claude
  Code, Hermes, Cursor e Codex leem `commands/*/SKILL.md`, e o passo "Seu
  agente" da configuração conecta o canal de leitura de quem existir na
  máquina.
- Opcional: **LM Studio** (embeddings `bge-m3`), **Hindsight**
  (memória semântica), OAuth Google (foco no calendário / backup no Drive) —
  configuração do wizard, não pré-requisito. O `setup.md` é a receita
  completa para agentes.

## Instalação

O app se chama **Brain** (Segundo Cérebro é o nome do framework). Numa máquina nova:

```bash
curl -fsSL https://raw.githubusercontent.com/BVLCQ/second-brain-framework/main/install.sh | sh -
```

ou, dentro do clone, `sh install.sh`.

Sem terminal: clonar (ou **Code → Download ZIP** no GitHub), abrir a pasta e
**duplo clique em `Abrir o Brain.command`** — ele instala o que faltar na
máquina (git · Homebrew · mise · Python · contêiner), cria o app
Brain e abre a configuração guiada; ZIP vira repositório automaticamente.

O instalador clona o repo, instala o que faltar na máquina, cria o app **Brain**
na pasta Aplicativos e abre a **configuração guiada no navegador**:

1. **Você** — nome completo, apelido, cargo e e-mail (o id interno sai do nome; ninguém escolhe id).
2. **Sobre você** — o texto vira o seu perfil; você vê a prévia antes de salvar.
3. **Rotina** — fuso, expediente e almoço.
4. **Conectores** — Slack, Gmail, Calendar, Drive, Granola e Jira, conectados uma vez no claude.ai; o Brain
   detecta o que já está ligado e libera só as ferramentas de **leitura**.
5. **Permissões** — pré-autoriza o Claude Code nesta pasta, para ele não pedir licença a cada comando.
6. **Memória** — nenhuma, **embed** (busca por significado, 100% local, grátis) ou **full** (extrai fatos e liga
   assuntos; usa a sua API key, com custo por uso). Sem chave, fica para depois.
7. **Integrações** — token do GitHub (sugestões e bugs), opcional.
8. **Goals e projetos** — escreva com as suas palavras ou envie um documento; a IA propõe a árvore, você
   revisa e aprova ali mesmo (é o gate do PLANNING).

Depois, é só abrir o **Brain** pelo ícone (Aplicativos, Launchpad, Spotlight ou Dock). Enquanto a configuração
não termina, o ícone volta a ela; depois, abre o painel. Para refazer: `./brain open --setup`.

O que continua sendo seu: a senha da sessão (sudo) e, na primeira vez num
macOS sem Command Line Tools, o botão *Instalar* da janela da Apple — o resto
o instalador resolve sozinho. Sem internet, ele para com a receita manual
(`setup.md` §0–§1).

Terminal e IAs: o wizard `./brain setup` continua (`--yes` + `./brain doctor` em loop; receita em `setup.md`).
Guias: `guides/setup.md` (wizard) · `guides/memory.md` (memória). Modo script, sem perguntas:

```bash
git clone <este-repo> ~/brain && cd ~/brain
mise install                                # Python 3.12 (ou qualquer 3.11+ já presente)
./brain init --owner-name "Seu Nome"        # o id é gerado do nome (ex.: seu-nome)
./brain demo --dir /tmp/brain-demo --open   # vê o painel sem tocar no vault
```

Painel, depois de qualquer mudança: `./brain open` (ou `./brain render --open`). `./brain app install` recria o
app (`/Applications`, ou `~/Applications` sem permissão; Linux: menu de aplicativos) — rode de novo se mover a pasta.

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
| Fechar tarefa | `/done TASK-0014 enviei o draft` |
| Processar a inbox | `/dump` |
| Puxar fontes agora | `/update` ou `/gmail` `/slack` `/drive` `/calendar` |
| Agendar foco | `/focus` (proposta → "ok" → apply) |
| Mandar mensagem | `/outbox` (rascunho → "enviar 1") |
| Compartilhar status | `/share` · `/recap` · `/publish` |
| Sugerir ou corrigir o cérebro | `/feedback` (vira issue no repo público) |
| Mapear processos e oportunidades | `/process` · `/opportunity` · `./brain tui` (Tab: face Portfólio) |
| Perguntar | `/ask o que sabemos sobre X?` |
| Saúde da instância | `./brain doctor` |

Toda escrita no livro-razão passa por `./brain`. O agente não edita
`events.jsonl` na mão. O CLI usa a instância do diretório atual (onde
existir `config/brain.toml`); `BRAIN_HOME` vence se estiver setada.

## Testes

```bash
python3 -m unittest discover -s tests          # tudo (o que o CI roda)
python3 -m unittest tests.test_brain -v        # um arquivo
```

Só biblioteca padrão. Relógio congelado em `BRAIN_NOW`. Sem rede.
O CI roda o suite em 3.11–3.14 a cada push.

## Linguagem

Conteúdo, views e skills em **português do Brasil**. Código, schema e nomes
de arquivo em inglês (kebab-case). Datas em templates são sempre relativas
("hoje"), nunca literais.

## Licença

MIT. Veja `LICENSE`.
