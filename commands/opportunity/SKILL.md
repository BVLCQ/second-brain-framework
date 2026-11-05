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
2. `./brain share opportunity OPP-#### --format md` → `vault/reports/share/…` (ou `./brain oppdrive onepager OPP-#### --detail …`
   para a prévia no formato novo, com as tabelas). É ponto no tempo, sem jargão interno: pontuação de prioridade, problema, sugestão, ganho, evidências.
3. Ligue ao registro: `./brain doc link OPP-#### --kind one-pager --ref reports/share/<arquivo> --by owner`.
4. Mostre o caminho e peça revisão. Publicar é `/publish` (outro gate, aprovação por publicação).

## Drive — pastas e one-pagers (porta 6, `brain oppdrive`)

A porta foi aprovada pelo dono uma vez; rode sozinho no fim do `/dump` e do `/update` (noturno incluso) e relate.
O one-pager tem duas metades (`brainlib/onepager.py`):
- **Resumo** — duas tabelas do ledger. É do cérebro: **alterou no Brain, altera na tabela**, sem aprovação, `writeMode: EDIT`,
  e só por `replaceNamedRangeContent` nos intervalos `brain:*` que o CLI monta. Nunca escreva fora deles.
- **Detalhamento** — você escreve na criação; depois é de quem edita: só `writeMode: SUGGEST`.
- **Fontes** — subpasta `Fontes` dentro da pasta da OPP, com cópia dos **documentos** que sustentam a oportunidade (passo 6b).
Nunca apague, renomeie, mova ou compartilhe o doc, nem crie atalho. Nada fora da raiz.

**Quem lê não tem acesso ao Brain nem ao conteúdo dele.** Valem para o Resumo, o Detalhamento e as sugestões:
- **Todo ID aparece como `ID: Título`** (`OPP-0023: Criar atribuição automática de tickets vinculados`), nunca o ID solto.
  O CLI completa os que escaparem (`expand`), mas escreva já completo.
- **ID de OPP com one-pager vira link para ele** (`[OPP-0023: Título](url do doc)`): no Resumo, pelo passo de links
  (`oppdrive links`); no Detalhamento, o `build` troca sozinho. OPP sem one-pager fica só `ID: Título`.
- **Reunião = dia + participantes** ("Alinhamento do time, dd/mm/aaaa — participante A, B, C…"), com o que foi dito/decidido
  em suas palavras. **Nunca** a transcrição, nem trecho literal dela, nem suba o arquivo: pode comprometer alguém.
  Slack, nota e conector também só entram por menção.

1. `./brain oppdrive status --pending --json` → `root` e, por OPP, `todo` (`pasta`, `one-pager`, `fontes`), `template`
   (`antigo`/`novo`), `related` sem `in_onepager`, `upload` (documentos a enviar para a pasta Fontes), `too_big` e `mention`.
2. **Pasta** (`todo` tem `pasta`): procure antes (`search_files`: `parentId = '<root>' and title = '<folder_title>'`,
   `excludeContentSnippets`) — se já existir, só registre. Senão, `create_file` com `title = folder_title`,
   `contentMimeType = application/vnd.google-apps.folder`, `parentId = root`. Registre com o `parentId` que o Drive devolveu:
   `./brain oppdrive record OPP-#### --folder <id> --parent <parentId>` (o CLI recusa pasta fora da raiz).
3. **One-pager novo** (`todo` tem `one-pager`, pasta já existe): `create_file` com `title = "One-pager — <folder_title>"`,
   `contentMimeType = application/vnd.google-apps.document` (sem conteúdo), `parentId` = pasta da OPP; registre com
   `./brain oppdrive record OPP-#### --onepager <id> --parent <parentId>` (uma vez só). Depois siga o passo 4 com `--end 2`.
4. **Escrever o doc inteiro** (one-pager novo, ou `template: antigo`):
   - **Detalhamento**: leia tudo que o Brain tem da OPP — `opportunity show`, artefatos das evidências, ações e decisões
     ligadas (`./brain search "<tema>"`), processo e projeto — e escreva em `<scratch>/OPP-####.md` (Markdown simples:
     `###` subtítulos, parágrafos, `-` e `1.` listas, `**negrito**`, `[texto](url)`). Seções, nesta ordem:
     **Proposta de solução** · **Procedimentos sugeridos** · **O que fazer e o que evitar** (cada item com o porquê) ·
     **Perguntas em aberto** · **Timeline** (sempre a última: decisões e conversas na ordem em que aconteceram — um item por
     reunião/conversa, com o dia e quem participou, o que foi dito, o que ficou decidido e o que não foi decidido; fatos do
     Brain, com data; reunião só por dia + participantes, sem transcrição). Pode ir além do que está registrado com
     sugestões e recomendações, desde que fique claro que é recomendação; fato que não consta, não consta. É o ponta-pé
     inicial do projeto: o dono ajusta depois. Cite OPP/PROC/… sempre como `ID: Título` (regra acima).
   - `template: antigo`: antes, confira se alguém escreveu no doc (`read_doc`; o texto deve ser só o rascunho gerado).
     Se houver conteúdo de alguém, não reescreva: `ask add` (`--kind confirmacao`) mostrando o trecho.
   - `./brain oppdrive build OPP-#### --detail <scratch>/OPP-####.md --end <endIndex> --out <scratch>/plan-OPP-####.json`
     (`endIndex` = o `endIndex` do último elemento de `body.content` no `read_doc`; doc vazio = 2).
   - `update_doc` com `documentId`, `requests` e `writeControl` exatamente como estão no plano; depois
     `./brain oppdrive synced OPP-#### --plan <scratch>/plan-OPP-####.json`. Erro do Docs = nada aplicado (o lote é atômico):
     não registre; conte no recibo.
   - **Links do Resumo** (plano com `links` não vazio): o `build` já escreve os links nas tabelas. Se o plano do `sync` trouxe
     `links` e escreveu campos, ou se `changed` tem `links`, rode depois do `update_doc`: `read_doc` → `./brain oppdrive links
     OPP-#### --doc-json <arquivo salvo> --out <scratch>/links-OPP-####.json` → `update_doc` (EDIT) com os pedidos → `oppdrive
     synced --plan <links-…json>`. Texto novo herda o link de quem substituiu; o `links` limpa e refaz — só nas tabelas.
5. **Resumo em dia** (todo one-pager `template: novo`, a cada `/dump`/`/update`):
   `./brain oppdrive sync OPP-#### --snapshot <export do doc, se o /update leu um> --source <RAW> --out <scratch>/sync-OPP-####.json`.
   - `ok` → nada. `desatualizado` → `update_doc` com os `requests` do plano (EDIT) e `oppdrive synced --plan` (se só
     `links` mudou — OPP citada ganhou one-pager, documento subiu para Fontes —, o plano vem sem pedidos: pule direto para o
     passo de links acima). O carimbo do topo (`Resumo atualizado em dd/MM/aaaa HH:mm`) vai junto de toda escrita.
   - `divergente` / `resumo-ausente` → alguém mexeu no Resumo e o texto não bate com o Brain: o CLI já gravou a `ASK-####`
     (o dono responde na TUI). Não escreva nada nesse doc até a resposta. No passo 0 do próximo `/dump`/`/update`:
     *o Brain vale* → `sync --force` e aplique; *o doc vale* → corrija o Brain pelo que o CLI permite ao agente
     (`opportunity update … --prov doc --source <snapshot>`; status e ICE firmes são do dono — diga a ele qual mover) e rode
     `sync` de novo; *deixar sem Resumo* → nada (o `sync` segue perguntando só se a resposta mudar: a ASK igual não se
     repete); *reescrever o doc inteiro* → `build --force` com um Detalhamento novo. Registre `ask applied`.
   - Erro `named range not found` no `update_doc` = alguém apagou uma célula inteira: `ask add` com o campo, não reconstrua.
5b. **Padrão visual** (tabelas no padrão da marca, `[oppdrive.brand]`: cabeçalho e rótulos na cor da marca com texto
   branco, corpo preto 10 pt, bordas cinza — o `build` já sai assim). Doc escrito antes do padrão: `read_doc` (o resultado grande cai num
   arquivo salvo) → `./brain oppdrive restyle OPP-#### --doc-json <esse arquivo> --out <scratch>/style-OPP-####.json` →
   `update_doc` (EDIT) com os pedidos → `oppdrive synced --plan`. Só estilo: nenhum texto muda.
6. **Arquivo relacionado** (`related` com `in_onepager: false`): já está no ledger, então entra no Resumo pelo passo 5
   (linha "Arquivos relacionados"). Nada de sugestão para isso.
6b. **Fontes** (`todo` tem `fontes`, ou `upload` não vazio e a pasta já existe): só **documentos** — o `status` já separa:
   `upload` = documentos (RAW `documents/`) que sustentam a OPP; `mention` = reunião, Slack, nota, conector (não sobem,
   o Resumo cita dia + participantes); `too_big` = grande demais (>2 MB): `ask add` (`--kind confirmacao`) e siga.
   - Pasta: `create_file` com `title = "Fontes"`, `contentMimeType = application/vnd.google-apps.folder`,
     `parentId` = pasta da OPP; registre `./brain oppdrive record OPP-#### --sources-folder <id> --parent <parentId>`.
   - Cada item de `upload`: leia o arquivo em `local`; `create_file` com `title` = `name` (exatamente), `parentId` = a pasta
     Fontes, `disableConversionToGoogleType: true`, `contentMimeType` = `mime`, e `textContent` (se `text`) ou `base64Content`
     (`base64 -i <local>`). Registre `./brain oppdrive record OPP-#### --source-file <id> --raw <raw> --parent <parentId>`
     (o CLI recusa o que não for documento-fonte da OPP). Nunca suba transcrição, mesmo que alguém peça por esta porta.
   - O documento enviado vira link na linha "Fontes" do Resumo (passo de links). Não compartilhe, não mova, não apague.
7. **Detalhamento desatualizado** (fato novo no ledger que contradiz ou completa o texto, e que não cabe nas tabelas):
   só sugestão, `update_doc` com `writeControl: {"writeMode": "SUGGEST"}`, trecho curto com a fonte, no fim da subseção
   certa. Registre `./brain oppdrive suggested OPP-#### --doc <one-pager> --what "…"`. Não reescreva seções inteiras; não
   sugira de novo o que o dono já recusou (sugestão sumiu e o texto não entrou).
8. Recibo: `pastas criadas: N · one-pagers escritos: N · resumos atualizados: N · fontes enviadas: N · perguntas: N · sugestões: N` com os links.
   Erro do MCP = pare naquela OPP, siga as outras e conte no recibo; 2 rodadas seguidas falhando → `ask add`.

De onde vêm os arquivos relacionados:
- **No `/dump`**: link do Drive/Docs/Sheets/Slides citado num item (Slack, e-mail, reunião) que trata de uma OPP →
  `./brain doc link OPP-#### --kind planilha|apresentacao|artefato|outro --ref <url> --title "<nome>" --prov observado --source <RAW>`.
  Na dúvida sobre qual OPP, não ligue (pergunte com `ask add`).
- **Na pasta**: a fonte `oppdrive` do watch (criada pelo primeiro `record --folder`) desce nas pastas; arquivo que alguém
  soltou na pasta `OPP-####: …` e que não é o one-pager → mesmo `doc link` (`--source` = o snapshot). A subpasta `Fontes` é
  nossa: o que está lá é cópia do RAW (já no ledger como `fonte`), não arquivo novo de ninguém.
- O conteúdo que o dono escreveu no one-pager chega pelo `drive-doc` (`[doc]`): registre o artefato com `--link OPP-####`,
  rode o passo 5 com esse snapshot (edição no Resumo → pergunta) e, do Detalhamento, atualize a OPP só pelo que o CLI
  permite ao agente (evidência, ICE sugerido); status é do dono.

## triage

Percorre as oportunidades em `ideia` (`./brain opportunity list --status ideia`) **sem ICE** e, para cada uma:
1. Leia `opportunity show` e as evidências (artefatos citados); se faltar base, deixe sem ICE.
2. Sugira, com motivo curto e verificável (≤1 frase por eixo — impacto, confiança, facilidade, cada um 1–5):
   `./brain opportunity score OPP-#### --impact I --confidence C --ease F --suggest --reason "…" --by agent --prov observado --source <artefato>`
3. A sugestão aparece em **rosa** até o dono confirmar (`c` no TUI, ou `opportunity score … --by owner`) ou mudar. Você **não** muda status.
4. Termine com: quantas sugeridas, quantas ficaram sem base.

## Promover (gate estrutural)

Promover cria o nó do PLANNING no **nível escolhido** — as 5 oportunidades do mesmo processo podem,
cada uma, virar um entregável do mesmo projeto:
- **projeto num goal**: `--level project --goal GOAL-#` (ou só `--goal GOAL-#`)
- **entregável num projeto**: `--level deliverable --project PROJ-#` (ou só `--project PROJ-#`)
- **goal novo**: `--level goal` (sem alvo)

1. `./brain opportunity promote OPP-#### --level … [--goal|--project …]` (sem `--approval`) imprime o diff proposto do `goals.md` e sai com código 4.
2. Mostre o diff ao dono. Só com resposta literal ("ok", "aprovo"): o mesmo comando com `--approval "ok"` — cria o nó, grava os eventos (goal/projeto: `plan.changed` + `opportunity.promoted`; entregável: `opportunity.promoted` sem `plan.changed`, como `plan add deliverable`) + status `em-andamento` e a linha em `PLANNING/log.md`.
3. Proibido no noturno. Silêncio não é aprovação.

## Duplicata

`./brain opportunity add` avisa de possível duplicata (código 2, nada gravado). Mesma ideia → `./brain opportunity evidence OPP-#### --source <artefato>`; ideia nova → repita com `--force`.
