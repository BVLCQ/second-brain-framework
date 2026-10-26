---
name: opportunity
description: "Oportunidades/iniciativas (OPP-####): panorama, one-pager e triagem com ICE sugerido. O agente cria só em status 'ideia'; mover, pontuar de verdade e promover a projeto são do dono (promover é o gate)."
---

# /opportunity — oportunidades e iniciativas

Oportunidade e iniciativa são a **mesma entidade** (`OPP-####`) em estágios:
`ideia → triagem → priorizada → em-andamento → piloto → validando → entregue`, e os laterais `em-espera` e `descartada` (ambos exigem motivo).
O dono vai e volta livremente entre eles. **O agente só grava status `ideia`**; `em-andamento` só nasce da promoção.

`/opportunity <termo|OPP-####>` · `/opportunity onepager OPP-####` · `/opportunity triage`

## Panorama

1. Achar: `./brain search "<termo>"` ou `./brain opportunity list [--status …] [--area …] [--sort score]`.
2. `./brain opportunity show OPP-#### --json` (score, quadrante e histórico vêm do CLI).
3. No chat (≤10 linhas): problema, sugestão, ganho esperado (texto + `horas/mês` **declaradas** — não estime), ICE (`I×C×F = score`; rosa/"sugerido" se for sugestão do agente), status e histórico, evidências (quantas e de onde), processo ligado, projeto/goal (e progresso) se promovida.

## onepager

Com a porta 6 ligada (`[oppdrive].enabled`), o one-pager mora no Drive — siga **Drive** abaixo. Desligada, o fluxo local:

1. Confira os campos: o que não consta, não consta (não preencha com palpite).
2. `./brain share opportunity OPP-#### --format md` → `vault/reports/share/…`. É ponto no tempo, sem jargão interno: pontuação de prioridade, problema, sugestão, ganho, evidências.
3. Ligue ao registro: `./brain doc link OPP-#### --kind one-pager --ref reports/share/<arquivo> --by owner`.
4. Mostre o caminho e peça revisão. Publicar é `/publish` (outro gate, aprovação por publicação).

## Drive — pastas e one-pagers (porta 6, `brain oppdrive`)

A porta foi aprovada pelo dono uma vez; rode sozinho no fim do `/dump` e do `/update` (noturno incluso) e relate.
**Só cria e sugere.** Nunca `writeMode: EDIT`, nunca apague, renomeie, mova, compartilhe ou crie atalho. Nada fora da raiz.

1. `./brain oppdrive status --pending --json` → `root` e, por OPP, `todo` (`pasta`, `one-pager`) e `related` sem `in_onepager`.
2. **Pasta** (`todo` tem `pasta`): procure antes (`search_files`: `parentId = '<root>' and title = '<folder_title>'`,
   `excludeContentSnippets`) — se já existir, só registre. Senão, `create_file` com `title = folder_title`,
   `contentMimeType = application/vnd.google-apps.folder`, `parentId = root`. Registre com o `parentId` que o Drive devolveu:
   `./brain oppdrive record OPP-#### --folder <id> --parent <parentId>` (o CLI recusa pasta fora da raiz).
3. **One-pager** (`todo` tem `one-pager`, pasta já existe): `./brain oppdrive onepager OPP-#### --out <scratch>/OPP-####.md`,
   leia o arquivo e `create_file` com `title = "One-pager — <folder_title>"`, `textContent` = o Markdown,
   `contentMimeType = text/markdown`, `parentId` = pasta da OPP (vira Google Doc). Registre:
   `./brain oppdrive record OPP-#### --onepager <id> --parent <parentId>` — o doc passa a ser vigiado (`drive-doc`).
   Uma vez só: o CLI recusa o segundo.
4. **Arquivo relacionado** (`related` com `in_onepager: false`): `read_doc` do one-pager, ache o fim da seção
   "Arquivos relacionados" (se o dono a apagou, use o fim do corpo) e `update_doc` com
   `writeControl: {"writeMode": "SUGGEST"}` e um `insertText` `"\n<título>: <url>"`. Depois:
   `./brain oppdrive suggested OPP-#### --doc <one-pager> --what "Arquivos relacionados: <url>"`.
5. **Mudança de conteúdo** (fato novo no ledger que contradiz ou completa o one-pager — problema, ganho, evidência):
   só como sugestão, mesmo `update_doc` com `SUGGEST`; trecho curto, com a fonte. Registre com `oppdrive suggested`.
   Não reescreva seções inteiras; não sugira de novo o que o dono já recusou (sugestão sumiu e o texto não entrou).
6. Recibo: `pastas criadas: N · one-pagers: N · sugestões: N` com os links. Erro do MCP = pare naquela OPP, siga as outras
   e conte no recibo; 2 rodadas seguidas falhando → `ask add`.

De onde vêm os arquivos relacionados:
- **No `/dump`**: link do Drive/Docs/Sheets/Slides citado num item (Slack, e-mail, reunião) que trata de uma OPP →
  `./brain doc link OPP-#### --kind planilha|apresentacao|artefato|outro --ref <url> --title "<nome>" --prov observado --source <RAW>`.
  Na dúvida sobre qual OPP, não ligue (pergunte com `ask add`).
- **Na pasta**: a fonte `oppdrive` do watch (criada pelo primeiro `record --folder`) desce nas pastas; arquivo que alguém
  soltou na pasta `OPP-####: …` e que não é o one-pager → mesmo `doc link` (`--source` = o snapshot).
- O conteúdo que o dono escreveu no one-pager chega pelo `drive-doc` (`[doc]`): registre o artefato com `--link OPP-####` e
  atualize a OPP só pelo que o CLI permite ao agente (evidência, ICE sugerido); status é do dono.

## triage

Percorre as oportunidades em `ideia` (`./brain opportunity list --status ideia`) **sem ICE** e, para cada uma:
1. Leia `opportunity show` e as evidências (artefatos citados); se faltar base, deixe sem ICE.
2. Sugira, com motivo curto e verificável (≤1 frase por eixo — impacto, confiança, facilidade, cada um 1–5):
   `./brain opportunity score OPP-#### --impact I --confidence C --ease F --suggest --reason "…" --by agent --prov observado --source <artefato>`
3. A sugestão aparece em **rosa** até o dono confirmar (`c` no TUI, ou `opportunity score … --by owner`) ou mudar. Você **não** muda status.
4. Termine com: quantas sugeridas, quantas ficaram sem base.

## Promover (gate estrutural)

Promover cria um projeto num goal: é mudança estrutural.
1. `./brain opportunity promote OPP-#### --goal GOAL-#` (sem `--approval`) imprime o diff proposto do `goals.md` e sai com código 4.
2. Mostre o diff ao dono. Só com resposta literal ("ok", "aprovo"): `./brain opportunity promote OPP-#### --goal GOAL-# --approval "ok"` — cria o projeto, grava `plan.changed` + `opportunity.promoted` + status `em-andamento` e a linha em `PLANNING/log.md`.
3. Proibido no noturno. Silêncio não é aprovação.

## Duplicata

`./brain opportunity add` avisa de possível duplicata (código 2, nada gravado). Mesma ideia → `./brain opportunity evidence OPP-#### --source <artefato>`; ideia nova → repita com `--force`.
