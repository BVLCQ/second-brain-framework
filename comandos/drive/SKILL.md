---
name: drive
description: "Docs vivos do Drive via OAuth read-only (script gdrive.py): snapshot datado em RAW/inbox/ → /dump (change digest). Noturno (watchlist gdocs do watch.yaml) ou sob demanda (/drive <termo> busca, /drive <id> exporta). Nunca cria/edita docs."
---

# /drive — docs vivos pelo canal, nunca direto

**Autenticação:** OAuth do Google via script (`google_auth.py` uma vez; refresh
token no `.env`). Guia: `docs/google-oauth.md`. Escopo: **só `drive.readonly`**.

## A regra de ouro deste comando (o canal)

Docs do Drive MUDAM — por isso cada leitura é um **snapshot datado** em
`RAW/inbox/`, e a memória fica na linha do tempo de snapshots + change digests
do PROCESSED. Responder "o que diz o doc" sem snapshotar = memória perdida.

## Modo noturno (watchlist — padrão do /update)

`python3 scripts/connectors/gdrive.py` (sem args):
1. Para cada doc da watchlist (`gdocs:` no watch.yaml): exporta conteúdo +
   comentários via API (read-only).
2. Hash contra o pull anterior da MESMA fonte: **idêntico → não escreve nada**;
   diferente → snapshot `gdoc-<nome>-<ts>.md`.
3. `/dump` → artefato = **change digest** (o que mudou — seções, comentários
   novos), citando os dois snapshots.

## Modo sob demanda

- `/drive <termo>` → `python3 scripts/connectors/gdrive.py "<termo>"` — busca
  por nome → snapshot da lista (título · tipo · modificado · id).
- `/drive <id>` → exportar aquele doc → snapshot `gdoc-…` → `/dump` →
  responder citando o artefato (com âncoras de seção quando possível).

## Proibições e diagnóstico

- NUNCA criar/editar/upload — só leitura (constituição).
- Doc fora da watchlist só entra por pedido explícito (`/drive`) — o watch.yaml
  é o universo observável do noturno.
- `invalid_grant` → ver `docs/google-oauth.md` (app em Testing = 7 dias).
