---
name: dump
description: "O comando central: arquiva tudo que está em vault/RAW/inbox/ no mês correto (vault/RAW/ano/mes/) e processa cada item — extrai decisões, ações, fatos e menções, escreve artefatos em PROCESSED e apensa aos índices. Use sempre que houver itens novos na inbox."
---

# /dump — a esteira de processamento

Siga o pipeline da constituição (AGENTS.md, seção "O pipeline"), sem pular passo.

## Classificação e extração por tipo

| Tipo | Sinais | O artefato contém |
|---|---|---|
| **reunião** | transcrição, ata, gravação com falantes | contexto · decisões `D-####` com base (quem/min) · ações `A-####` por dono · threads abertas (não-ações a acompanhar) · citações-chave com minuto · menções |
| **documento longo** | PDF, política, apresentação, doc extenso | do-que-trata · TL;DR executivo (≤5 linhas) · **mapa de seções com página/âncora** (★ nos pontos relevantes ao dono) · pontos que afetam goals do PLANNING · perguntas que o documento responde (com página) |
| **nota solta** | anotação curta, ideia, lembrete | nota limpa · tags · ligações com entidades existentes |
| **dump de conector** | arquivo prefixado (`jira-…`, `github-…`, `slack-…`, `gmail-…`, `gdoc-…`) | **change digest**: comparar com o snapshot anterior da MESMA fonte (via `config/.state.json` + índice) e extrair SÓ o que mudou; primeira vez = estado inicial |

Regras transversais: proveniência em toda extração (`[doc]`/`[observado]`/`[sem fonte]`) ·
aliases resolvem pessoas antes de qualquer menção · IDs A-/D- globais e zero-padded,
consultar os logs antes de numerar.

**Fontes vigiadas → registro de itens vivos:** todo artefato de digest de fonte
da watchlist (gdocs, boards Jira, canais/pessoas Slack) apenda 1 linha à seção
do item em `_indices/indice-itens-vivos.md` (`data · snapshot · o que mudou`);
primeira vez cria a seção com o estado inicial. Pull sem mudança não escreve
nada. Fluxos sem identidade por item (digest diário do Gmail) não entram — o
artefato diário já é o registro.

## O recibo (chat)

~5 linhas por item — tipo, contagem de extrações, menções, qualquer estranheza
("transcrição sem falante identificado em 30% do texto"). Terminar com:
`inbox: N itens restantes`.

## Idempotência (verificação obrigatória)

Fonte que já tem artefato = pulada. Antes de escrever, confira que não existe
artefato apontando para a mesma fonte. Re-rodar /dump no mesmo material = zero
duplicatas — se não for isso que aconteceu, algo quebrou: reporte.

Arquivos `.keep.md` (âncoras de pasta vazia) são **ignorados** — nunca
processados, nunca arquivados.

## Depois do dump

Se houve qualquer mudança relevante (novas ações, decisões, pessoas), as views
de FRESH ficam velhas — ofereça `/update` ou regenere as views afetadas.
