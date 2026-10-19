---
name: dump
description: "Arquiva vault/RAW/inbox/ no mês correto e processa cada item: extrai decisões, ações, fatos e menções, grava no ledger via ./brain e escreve o artefato em PROCESSED. Use sempre que houver itens novos na inbox."
---

# /dump — a esteira de processamento

Siga o pipeline da constituição (AGENTS.md, seção "O pipeline"), sem pular passo.
Toda entidade (ação, decisão, pessoa, artefato) entra pelo `./brain` — nunca edite `events.jsonl`.

## Classificação e extração por tipo

| Tipo | Sinais | O artefato contém |
|---|---|---|
| **reunião** | transcrição, ata, gravação com falantes | contexto · decisões com base (quem/min) · ações por dono e lista · threads abertas · citações-chave com minuto · menções |
| **documento** | PDF, política, apresentação, doc extenso | do-que-trata · TL;DR (≤5 linhas) · mapa de seções com página/âncora · pontos que afetam goals · perguntas que o doc responde |
| **nota** | anotação curta, ideia, lembrete | nota limpa · ligações com entidades existentes |
| **conector** | snapshot prefixado (`jira-…`, `gmail-…`, `gcal-…`, `slack-…`) | **change digest**: só o que mudou vs. o snapshot anterior da mesma `--key`; primeira vez = estado inicial. Cabeçalho `desde <data>` (janela `auto`) = o arquivo já é só o delta: extraia tudo dele, sem comparar com o anterior |

**Ações — detecte na extração:**
- dono da ação → `mine` se for o dono do cérebro, `waiting` se for terceiro que deve a ele, `watching` se for só contexto
- `blocked_by` / `unblocks` quando o texto ligar uma ação a outra
- `proj:` / entregável se casar com `PLANNING/goals.md`
- esforço (`90m`, `2h`) se alguém falou tempo
- **não feche** ação só porque o texto "parece" resolver — abra `brain proposal add --kind fechar-acao` com a evidência

**Notas do dono (`<A-####|G#|P#|P#.n|note>-AAAA-MM-DD-note.md`)** — criadas pelo TUI (`N`) ou por
`./brain note add`. O frontmatter traz `vinculo:` e `criada:`. Trate como **nota** sem reclassificar: arquive
no RAW **sem renomear** (o TUI as acha pelo nome, no detalhe do vínculo) e registre o artefato com
`--projects` = o projeto do vínculo (`P#`/`P#.n` → `P#`; `A-####` → o projeto da ação; goal → deixe vazio e cite
o `G#` no resumo). Extraia ações/decisões só do que a nota afirmar; o vínculo já é a ligação.

Regras transversais: proveniência em toda extração · `brain person resolve` antes de qualquer menção · IDs só o CLI numera.

## Como gravar

Para cada item da inbox (ignore `.keep.md`):

0. **Atalho opcional** — se `[extractor]` estiver ligado (LM Studio), rode
   `./brain extract vault/RAW/<ano>/<mês>/<arquivo>`: o modelo local devolve
   um rascunho **já validado** (pessoas resolvidas, datas, escopo). Revise,
   complete o que faltar e use como lote do passo 4. Modelo erra → o CLI
   recusa; o rascunho não substitui seu julgamento.
1. Mova para `vault/RAW/<ano>/<mês>/` pela data de **captura** (hoje, se não souber). Colisão de nome → sufixo `-2`.
2. Escreva o artefato em `vault/PROCESSED/<ano>/<mês>/<slug>.md`.
3. Registre pessoas novas (`brain person add`) e o artefato:

```
./brain artifact PROCESSED/<ano>/<mês>/<slug>.md --kind reuniao|documento|nota|conector \
  --title "…" --raw RAW/<ano>/<mês>/<arquivo> --people a,b --projects P1 --summary "…" \
  --prov observado --source RAW/<ano>/<mês>/<arquivo>
```

4. Extrações em lote (preferível quando houver várias):

```
./brain add <<'JSON'
[
  {"type":"decision.made","prov":"observado","source":"PROCESSED/…/x.md",
   "data":{"title":"…","decided_by":["ana"],"project":"P1","rationale":"…"}},
  {"type":"action.opened","prov":"observado","source":"PROCESSED/…/x.md",
   "data":{"title":"…","owner":"eu","due":"AAAA-MM-DD","effort_min":90,"project":"P1"}}
]
JSON
```

Fonte já registrada (`artifact.added` com o mesmo `raw`) = **pule**. Re-rodar = zero duplicatas.

## Recibo (chat)

~5 linhas por item: tipo, quantas extrações, menções, estranheza.
Termine com `inbox: N itens restantes`.
Se houve ação/decisão/pessoa nova: `./brain render` (ou ofereça `/update`).
Se `[memory] engine = "hindsight"`: `./brain memory sync` — o índice fica
fresco no mesmo dia, sem esperar o noturno.
