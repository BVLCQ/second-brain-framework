---
name: dump
description: "Arquiva vault/RAW/inbox/ no mês correto e processa cada item: extrai decisões, ações, fatos e menções, grava no ledger via ./brain e escreve o artefato em PROCESSED. Use sempre que houver itens novos na inbox."
---

# /dump — a esteira de processamento

## Passo 0 — aplique o que o dono já respondeu (fila de reserva)

Antes de qualquer item da inbox: `./brain ask list --answered`. Cada pergunta respondida (`ASK-####`) é uma instrução do
dono, e a ordem da fila vale: aplique a resposta (`person alias`/`person add` para identidade, `action open`, reclassificar o
item, o que o `kind` e o `context` indicarem) e registre `./brain ask applied ASK-#### --how "o que você fez" --prov observado --source chat`.
Resposta que você não sabe aplicar: deixe respondida e diga no recibo. Só então siga para a inbox.

## Dúvida que precisa do dono → `ask add`, não só o relatório

Identidade ambígua, pessoa sem ficha, classificação duvidosa, conflito entre fontes, qualquer coisa que o dono precisa decidir:
`./brain ask add "pergunta curta e respondível" --option "A" --option "B" --context TASK-0004,marina-demo --kind identidade|classificacao|confirmacao|outro --run <id da rodada, se o prompt trouxer> --prov observado --source <artefato/RAW>`.
Texto e contexto iguais aos de uma pergunta aberta devolvem o ID dela (não duplica). Siga com o que não depende da resposta e
termine o recibo com "N perguntas abertas: ASK-0004…". Nunca decida no lugar do dono o que é dele.

Siga o pipeline da constituição (AGENTS.md, seção "O pipeline"), sem pular passo.
Toda entidade (ação, decisão, pessoa, artefato) entra pelo `./brain` — nunca edite `events.jsonl`.

## Classificação e extração por tipo

| Tipo | Sinais | O artefato contém |
|---|---|---|
| **reunião** | transcrição, ata, gravação com falantes | contexto · decisões com base (quem/min) · ações por dono e lista · threads abertas · citações-chave com minuto · menções |
| **documento** | PDF, política, apresentação, doc extenso | do-que-trata · TL;DR (≤5 linhas) · mapa de seções com página/âncora · pontos que afetam goals · perguntas que o doc responde |
| **nota** | anotação curta, ideia, lembrete | nota limpa · ligações com entidades existentes |
| **conector** | snapshot prefixado (`jira-…`, `gmail-…`, `gcal-…`, `slack-…`, `github-…`) | **change digest**: só o que mudou vs. o snapshot anterior da mesma `--key`; primeira vez = estado inicial. Cabeçalho `desde <data>` (janela `auto`) = o arquivo já é só o delta: extraia tudo dele, sem comparar com o anterior. `github-…` (cai em `RAW/…/github/`): título "leitura completa" = estado inicial do repo (histórico inteiro, árvore, documentos) — extraia do que trata, quem mexe, entregas e pendências dos docs; título "commits novos" = só o delta. Resuma por tema, ligue a projeto/entregável quando o assunto casar, e trate autor de commit como pessoa (`person resolve` pelo nome/e-mail) |

**Ações — detecte na extração:**
- dono da ação → `mine` se for o dono do cérebro, `waiting` se for terceiro que deve a ele, `watching` se for só contexto
- `blocked_by` / `unblocks` quando o texto ligar uma ação a outra
- `proj:` / entregável se casar com `PLANNING/goals.md`
- esforço (`90m`, `2h`) se alguém falou tempo
- **não feche** ação só porque o texto "parece" resolver — abra `brain proposal add --kind fechar-acao` com a evidência

**Notas do dono (`<TASK-####|GOAL-#|PROJ-#|PROJ-#.#|note>-AAAA-MM-DD-note.md`)** — criadas pelo TUI (`N`) ou por
`./brain note add`. O frontmatter traz `vinculo:` e `criada:`. Trate como **nota** sem reclassificar: arquive
no RAW (`notes/`) **sem renomear** (o TUI as acha pelo nome, no detalhe do vínculo) e registre o artefato com
`--projects` = o projeto do vínculo (`PROJ-#`/`PROJ-#.#` → `PROJ-#`; `TASK-####` → o projeto da ação; goal → deixe vazio e cite
o `GOAL-#` no resumo). Extraia ações/decisões só do que a nota afirmar; o vínculo já é a ligação.

**Portfólio (processos e oportunidades)** — ao extrair dores, ineficiências ou sugestões de melhoria de um item:
- **Oportunidade:** `./brain opportunity add "<título>" --area <slug> --problem "…" --suggestion "…" --by agent --prov observado --source <artefato>`. O CLI checa duplicata sozinho (código 2, nada gravado): se for a mesma ideia, `./brain opportunity evidence OPP-#### --source <artefato>` (mais uma fonte reforça, não duplica); se for nova, repita com `--force`. O agente **só cria em `ideia`** — nunca mova status, nunca grave ICE como firme (sugestão é `/opportunity triage`) e nunca promova.
- **Processo citado e ainda sem ficha:** `./brain process add "<título>" --area <slug> --by agent --prov observado --source <artefato>` (confira antes com `./brain search`). Só o que o texto afirma; recorrência, duração e responsável que não constam ficam vazios (viram lacuna).
- A área precisa existir (`./brain area list`); não existe → proponha ao dono, não invente.
- Artefato lido de um playbook ou one-pager vigiado (`kind = "drive-doc"` no watch): registre com `--link PROC-####`/`--link OPP-####`.
  One-pager: guarde o caminho do snapshot para o `oppdrive sync --snapshot` (edição no Resumo que diverge do Brain vira pergunta).
- **Link do Drive sobre uma oportunidade** (doc, planilha, slides citados no item) ou arquivo achado numa pasta `OPP-####: …`
  da fonte `oppdrive`: `./brain doc link OPP-#### --kind planilha|apresentacao|artefato|outro --ref <url> --title "…" --prov observado --source <RAW>`.
- **Fim do `/dump`, com `[oppdrive].enabled`:** rode a seção **Drive** de `commands/opportunity/SKILL.md` (pastas, one-pagers,
  Resumo de cada one-pager em dia com o Brain, sugestões no Detalhamento) antes do `./brain render`.

Regras transversais: proveniência em toda extração · `brain person resolve` antes de qualquer menção · IDs só o CLI numera.

## Como gravar

Para cada item da inbox (ignore `.keep.md`):

> **VÍDEO e ÁUDIO (`.mp4`, `.mov`, `.m4a`…): são analisados sempre, nunca ficam esperando confirmação, mesmo grandes** (o arquivo é lido no lugar; o vídeo vai para o RAW sem editar).
> 1. `./brain video transcribe <arquivo> --locales pt-BR,es-MX --out <rascunho>.txt` transcreve no dispositivo (reunião bilíngue: informe os dois idiomas; ele escolhe o falado em cada minuto). Erros de reconhecimento são esperados: nomes próprios e termos técnicos saem trocados.
> 2. `./brain video frames <arquivo> --every 150` extrai PNGs (slides, tela compartilhada); leia os quadros-chave como imagem para confirmar títulos, links e números.
> 3. Antes de transcrever, procure no Drive/Meet notas ou transcrição do Gemini do mesmo evento: se existirem, são a fonte primária.
> 4. Trate como **reunião**: artefato com contexto, pontos com minuto `[mm:ss]`, decisões, ações, citações-chave. A transcrição completa vai para `PROCESSED/` como documento próprio, avisando que é automática.
>
> **PDF:** `./brain pdf text <arquivo> [--pages 1-3]` devolve o texto por página (sem precisar de poppler; no macOS usa o PDFKit). Se vier vazio, o PDF é escaneado: `./brain pdf render <arquivo> --pages 1-3` gera PNGs que você lê como imagem. Nome com espaço ou acento: passe entre aspas, o arquivo no RAW não é renomeado.

1. Arquive com `./brain raw archive "<arquivo>"` (sem argumento arquiva a inbox toda). O CLI move para
   `vault/RAW/<ano>/<mês>/<tipo>/` pela data de **captura** (hoje; `--date AAAA-MM-DD` se souber outra) e escolhe o
   tipo por nome/extensão: `slack` · `meetings` · `documents` · `videos` · `artifacts` · `notes` · `images` ·
   `connectors` · `github` · `misc`. Se a sua classificação pelo conteúdo discordar (um `.md` solto que é transcrição de
   reunião → `meetings`), force com `--type`. Colisão de nome → sufixo `-2`. O comando imprime o caminho final:
   use-o em `--raw` e `--source`.
2. Escreva o artefato em `vault/PROCESSED/<ano>/<mês>/<slug>.md`.
3. Registre pessoas novas (`brain person add`) e o artefato:

```
./brain artifact PROCESSED/<ano>/<mês>/<slug>.md --kind reuniao|documento|nota|conector \
  --title "…" --raw RAW/<ano>/<mês>/<tipo>/<arquivo> --people a,b --projects PROJ-1 --summary "…" \
  --prov observado --source RAW/<ano>/<mês>/<tipo>/<arquivo>
```

4. Extrações em lote (preferível quando houver várias). Escreva o lote com a ferramenta **Write** num arquivo
   (`vault/RAW/inbox/.tmp/lote.json` ou o scratch do agente) e rode `./brain add --file <caminho>` — heredoc (`<<'JSON'`) e pipe
   não passam no allowlist `Bash(./brain:*)` e a rodada fica negada. Conteúdo do arquivo:

```
[
  {"type":"decision.made","prov":"observado","source":"PROCESSED/…/x.md",
   "data":{"title":"…","decided_by":["marina-demo"],"project":"PROJ-1","rationale":"…"}},
  {"type":"action.opened","prov":"observado","source":"PROCESSED/…/x.md",
   "data":{"title":"…","owner":"eu","due":"AAAA-MM-DD","effort_min":90,"project":"PROJ-1"}},
  {"type":"action.opened","prov":"observado","source":"PROCESSED/…/x.md",
   "data":{"title":"…","owner":"eu","due":"AAAA-MM-DD","due_suggested":true,
           "due_reason":"entregável PROJ-1.6 vence 30/11; folga de 1 semana","project":"PROJ-1"}}
]
```

`./brain add --file vault/RAW/inbox/.tmp/lote.json` (apague o arquivo depois).

**Prazo de toda ação nova (`mine`/`waiting`) é decisão sua, não opcional** — o CLI recusa `action.opened` do agente sem
`due`, a menos que traga `due_none_reason`:

- o documento/conversa **diz** o prazo ("até sexta") → `due` normal, sem `due_suggested`;
- não diz → **sugira** pelo contexto: `"due":"AAAA-MM-DD","due_suggested":true,"due_reason":"…"` (método e ordem de base
  em `commands/todo/SKILL.md`, seção *Sugerir prazo*: entregável/projeto → acordos → agenda e carga → prioridade).
  Consulte `./brain project PROJ-#`, `./brain action list` e o último snapshot `gcal-*.json` antes de escolher o dia;
- sem base nenhuma → `"due_none_reason":"sem entregável, acordo ou agenda ligados"` (não invente data);
- `watching` não leva prazo.

Ao fim do lote, rode `./brain action list --undated`: o que sobrar sem prazo precisa ter motivo no recibo.

## Ações duplicadas — sempre que criar ações

**Antes de gravar:** compare cada ação extraída com as existentes (`./brain action list --all`, ou
`./brain action dupes --title "…"` por ação). O mesmo pedido costuma chegar por reunião, Slack e Jira — a mesma coisa
não vira duas ações:
- é a mesma → **não crie**: `action update TASK-#### --note "também em <fonte>" --people … --source <artefato>`;
- é outra → crie. O CLI recusa (código 2, nada gravado) a que for parecida demais; se você julgou que é outra, repita com
  `--force` (CLI) ou `"not_dup": ["TASK-####", …]` no `data` do lote.

**Depois de gravar (fim do `/dump`, antes do `./brain render`):** `./brain action dupes` lista os pares de ações abertas
parecidos que ninguém julgou ainda. Para cada par, julgue pelo sentido (o CLI só aponta palavras em comum):
- **não são a mesma** → `./brain action not-dup TASK-A TASK-B --reason "…" --prov observado --source chat` (o par sai da varredura);
- **uma já cobre a outra, nada a aproveitar** → `./brain proposal add --kind descartar-acao --target <a que sai> --into <a que fica>
  --summary "…" --evidence "…" --prov observado --source <artefato>`;
- **as duas têm pedaços** (pessoas, link, prazo, bloqueios, contexto) → `--kind unificar-acao`, mesmos campos.
  Fica a mais antiga, a mais completa ou a que tem link/projeto; diga no `--summary` qual sai, qual fica e por quê.

O cérebro **não descarta nem unifica sozinho**: é proposta, e o dono decide. Com o "ok" dele:
`./brain proposal accept PROP-#### --quote "ok"` e então
`./brain action merge <a que sai> --into <a que fica> --by owner` (unificar: pessoas, link, prazo firme mais cedo e bloqueios
passam para a que fica; quem esperava pela que sai passa a esperar pela que fica) ou
`./brain action drop <a que sai> --duplicate-of <a que fica> --reason "duplicada de …" --by owner` (descartar).
Recusada (`proposal reject`) não volta sem evidência nova. Sem dono na conversa (noturno, rodada ⚡), só proponha.
No recibo: `duplicadas: N propostas · M pares julgados diferentes`.

Fonte já registrada (`artifact.added` com o mesmo `raw`) = **pule**. Re-rodar = zero duplicatas.

## Recibo (chat)

~5 linhas por item: tipo, quantas extrações, menções, estranheza.
Termine com `inbox: N itens restantes`.
Se houve ação/decisão/pessoa nova: `./brain render` (ou ofereça `/update`).
Se `[memory] engine = "hindsight"`: `./brain memory sync` — o índice fica
fresco no mesmo dia, sem esperar o noturno.
