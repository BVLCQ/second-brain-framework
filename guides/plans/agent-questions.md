# Plano — Responder ao agente pela TUI (perguntas `ASK-####`, resposta livre, permissões)

Executor: Sonnet. Roda **depois** da migração de IDs (`guides/plans/ids-migration.md`):
usa o registro `brainlib/ids.py` e os prefixos novos. Mesmo regime: testes verdes
(inclusive TUI, com o venv `.venv-tui`), um commit local por passo, sem push, nada do
dono no repo.

## Problema

As ações ⚡ da TUI rodam o agente headless (`claude -p`, em `brainlib/tui/bridge.py`).
Quando ele precisa do dono (identidade ambígua, pessoa sem ficha, permissão negada), a
dúvida só aparece no log e a rodada termina. O dono não tem como responder, e a
pergunta se perde quando o log rola.

## Decisões do dono (não re-litigar)

1. **Dois canais**: perguntas estruturadas, respondidas uma a uma, e uma resposta livre
   que continua a conversa do agente.
2. **Persistência no ledger**: entidade `ASK-####`.
3. **Retomada na hora, com fila de reserva**: a TUI retoma a mesma sessão do agente com
   as respostas. Se não der, as respostas ficam na fila e o próximo `/update` (ou ⚡) as
   processa antes de qualquer outra coisa.
4. **Permissão negada → liberar sempre**: a TUI mostra o que foi negado e grava a regra
   em `[tui].agent_allow` (e em `[runner].allow` quando for ferramenta de leitura).
   Exceção constitucional: ferramenta MCP de **escrita no mundo exterior** (enviar,
   postar, criar, mover…) nunca é liberada por aqui. A TUI explica que isso passa pelas
   portas (`/outbox`, `/publish`).

## Passo 1 — Entidade `ASK-####`

Arquivos: `brainlib/ids.py`, `schema.py`, `state.py`, `cli.py`.

- Eventos:
  - `question.asked` (new, prefix `ASK`, req `text`), com campos opcionais:
    `options` (lista curta), `context` (refs a IDs: `ACT-…`, `PROJ-…`, pessoa, RAW),
    `run` (id da rodada do agente) e `kind` (`identidade` · `classificacao` ·
    `permissao` · `confirmacao` · `outro`).
  - `question.answered` (req `answer`, `by owner`).
  - `question.applied` (req `how`, `by agent`): o agente registrou o efeito da resposta.
  - `question.dropped` (req `reason`).
- Regras: só o agente pergunta; só o dono responde; o noturno pode perguntar, mas não
  responder. `answer` com `options` aceita uma opção ou texto livre (marcar
  `free: true`). Estado: `aberta → respondida → aplicada`, ou `descartada`.
- Dedupe: `question.asked` com texto normalizado igual ao de uma pergunta aberta, e
  mesmo `context`, não cria outra. Devolve o ID existente.
- CLI:
  - `brain ask add "texto" [--option …] [--context …] [--kind …] [--run …] --by agent --source …`
  - `brain ask answer ASK-#### "resposta" --by owner`
  - `brain ask applied ASK-#### --how "…"`
  - `brain ask drop ASK-#### --reason`
  - `brain ask list [--open|--answered]`
- Testes de cada regra.

## Passo 2 — Rodada do agente com sessão e saída estruturada

Arquivos: `brainlib/tui/bridge.py`, `brainlib/runner.py`.

- Preset `claude` na TUI: `--output-format stream-json --verbose`. O `run_agent`
  parseia cada linha JSON. O texto do assistente vai para o log como hoje, e da rodada
  ele captura `session_id`, o `result` final e `permission_denials`
  (`[{tool_name, tool_input}]`). Linha que não é JSON → log como texto (os outros agentes
  continuam funcionando).
- Cada rodada ganha um id (`run-<timestamp>`), passado ao agente no prompt
  (`OWNER_PREFIX` + "id desta rodada: …; registre dúvidas com `./brain ask add --run …`").
  O registro da rodada vai para `vault/logs/agent-runs.jsonl`: id, argv sem o prompt,
  `session_id`, código de saída, negações, ASKs abertos nesta rodada.
- `resume_argv(cfg, session_id, prompt, extra_allow)`: `claude -p --resume <id> "<prompt>"`
  com os mesmos flags e o allowlist atualizado. Para agentes sem resume conhecido, devolve
  `None` e a fila de reserva assume.
- Testes: parser com amostras de stream-json (texto, tool_use, result com
  `permission_denials`); argv de resume.

## Passo 3 — Skills: o agente pergunta pelo CLI

Arquivos: `commands/dump/SKILL.md`, `commands/update/SKILL.md`, `AGENTS.md` e as demais
skills que hoje mandam "perguntar ao dono".

- Toda dúvida que bloqueia ou que o dono precisa decidir → `./brain ask add` com opções
  quando houver, mais o `context`. O relatório final só resume ("3 perguntas abertas:
  ASK-0004…").
- **Passo 0 do `/update` e do `/dump`**: ler `brain ask list --answered`, aplicar cada
  resposta (ex.: `person alias`, `action open`, reclassificar) e gravar
  `ask applied`. É a fila de reserva.
- **Corrigir a negação do `./brain add`**: a skill usa heredoc (`./brain add <<'JSON'`),
  que o allowlist `Bash(./brain:*)` não cobre de forma confiável. Trocar por escrever o
  lote com Write em `vault/RAW/inbox/.tmp/` (ou no scratch do agente) e rodar
  `./brain add --file <caminho>`. Se `--file` não existir, criar. Revisar as outras skills
  com heredoc ou pipe para o `./brain`.

## Passo 4 — TUI

Arquivos: `brainlib/tui/store.py`, `app.py`, `modals.py`, `rows.py`.

- **Painel 4 (Aprovar), aba nova "Perguntas"** (primeira aba, com o contador no título):
  abertas no topo, respondidas aguardando aplicação abaixo. O detalhe mostra o texto, as
  opções, o contexto (com `jump`), a rodada e a fonte.
- Teclas na aba:
  - `enter`/`a`: responder. Um picker com as opções e "outra resposta…" (texto livre);
    roda `./brain ask answer`.
  - `x`: descartar, com motivo.
  - `R`: retomar o agente agora com todas as respostas ainda não aplicadas.
- **Fim de cada ⚡**: se a rodada abriu ASKs ou teve negações, o log mostra uma linha
  clara e acionável: `⚠ o agente deixou 3 perguntas e 1 permissão negada · 4 para
  responder · r resposta livre`. O painel 1 (Resumo) também mostra o contador.
- **Resposta livre `r`** (global, vale para a última rodada com `session_id`): modal de
  texto → `resume_argv` com a resposta → nova rodada ligada à anterior, que pode abrir
  novas perguntas. Sem sessão retomável, avisa e oferece gravar como nota
  (`brain note add`), para o próximo `/update` ler.
- **Retomada automática**: depois de responder a última pergunta aberta de uma rodada, a
  TUI pergunta "retomar o agente agora? (enter)". Ao confirmar, faz o resume com o
  prompt: "O dono respondeu: ASK-0004 = …; ASK-0005 = …. Aplique (passo 0) e continue de
  onde parou." Se o resume falhar (sessão expirada, outro agente), as respostas ficam na
  fila e o log diz isso.
- **Permissões negadas**: cada negação vira um ASK `kind=permissao` com o comando exato.
  Responder "liberar" grava a regra pelo CLI (passo 5) e entra no próximo resume.
  Ferramenta de escrita no mundo exterior: o ASK nasce com uma explicação, só com a opção
  "entendi", e não libera nada.
- Testes (pilot): aba renderiza; resposta por opção e por texto; `r` monta o argv de
  resume; negação vira ASK; escrita externa não libera.

## Passo 5 — `brain agent allow` (gravar permissão validada)

Arquivo: `brainlib/cli.py` (+ helper em `config.py`).

- `brain agent allow "<regra>" [--scope tui|runner]`: valida o formato da regra (`Bash(…)`,
  `mcp__…`, nomes de ferramenta), recusa ferramenta MCP de escrita externa (heurística por
  verbo no nome: `send`, `post`, `create`, `update`, `delete`, `move`, `schedule`, `add`,
  `upload`, `share`, `transition`, `edit`, `reply`, `forward`, `trash`, mais lista
  explícita em `config.py`) e grava em `config/brain.toml` preservando os comentários.
  Reaproveite o mecanismo de escrita validada do `brain watch` se der.
- Teste: regra válida grava; escrita externa recusada; arquivo continua parseável.

## Passo 6 — Views e docs

- `home.md` e `/brief`: "Perguntas abertas: N", com as 3 mais antigas.
- `AGENTS.md`: tabela de IDs (`ASK-####`), regra "dúvida do agente vira ASK; o dono
  responde; o agente aplica no passo 0", porta de permissão.
- `guides/user-guide.md` e `guides/tui-mockup.html` (se descrever as abas do painel 4).
- `./brain upstream scan`.

## Fora do escopo

Chat interativo completo dentro da TUI (PTY). O caminho é resume por rodada, sem
conversa ao vivo.
