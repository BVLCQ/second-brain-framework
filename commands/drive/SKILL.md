---
name: drive
description: "Docs vivos do Drive via MCP de leitura: snapshot datado na inbox → /dump (change digest). /drive <termo> busca, /drive <id> exporta. Nunca cria/edita docs."
---

# /drive — ler um doc

1. MCP Google Drive: busca ou exporta o arquivo (Markdown/texto).
2. `./brain snapshot --key gdoc-<id-ou-slug> --prefix gdoc`.
3. `/dump`. Primeira vez = estado inicial; seguintes = o que mudou.
4. Nunca crie, edite, comente ou compartilhe pelo MCP. Publicar um report no Drive é `/publish` (porta com gate).

## Pasta observada (`folder = "<id>"` no `watch.toml`)

Cada arquivo **e cada subpasta** é um *item* da fonte, com hash próprio — só o que mudou entra na inbox. A chave é a da fonte (`key`); o item é o id do Drive:

1. Liste **só o primeiro nível** da pasta (`search_files` com `parentId = '<id>'` e `excludeContentSnippets: true` — ids, nomes e `modifiedTime`, sem trechos). Passe as subpastas para o CLI, que decide por quais descer comparando a data da call no nome (ex.: `Retro - 2026/10/16 14:00`) com o carimbo do último pull (`watch since`), com folga de 3 dias para notas editadas depois:
   `echo '<json das subpastas>' | ./brain watch folders <key> --json` → desça **só** nas de `"descend": true`. Nome sem data, ou pasta modificada desde o último pull, sempre desce. Arquivos soltos no primeiro nível seguem o passo 2. `--full` desce em todas (varredura completa: use quando o dono pedir ou desconfiar de nota antiga editada). O modifiedTime de uma pasta não muda quando um arquivo dentro de subpasta é editado — por isso o filtro é pelo nome + folga, não pela pasta.
2. Para cada arquivo, antes de ler o conteúdo:
   `./brain snapshot --key <key> --item <id> --rev <modifiedTime> --check` → `inalterado` = pule, não gaste leitura MCP.
3. `mudou`: leia o arquivo (Markdown/texto) e grave
   `./brain snapshot --key <key> --item <id> --rev <modifiedTime> --name "<título>" --prefix drive --ext md`.
4. Cada subpasta vira um item de listagem (ids, nomes e `modifiedTime` dos filhos): `--item <id-da-pasta>`, mesmo fluxo.
5. Atalhos do Drive (`shortcut`) apontam para o arquivo-alvo: resolva o alvo e use o **id do alvo** como item. Conteúdo igual já guardado sob outra chave ou item não duplica — o CLI avisa "mesmo conteúdo já guardado" e não escreve nada.
6. Sem item novo em nenhuma subpasta = silêncio; não grave snapshot "vazio" nem `--fail` (nada mudou não é falha).
