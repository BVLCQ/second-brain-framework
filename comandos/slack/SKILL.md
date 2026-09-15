---
name: slack
description: "Puxa mensagens do Slack sob demanda: /slack #canal [@user] [período] — janela padrão 7d. Snapshots caem na inbox e são processados como qualquer dump. Use quando o dono pedir o histórico de um canal ou conversa."
---

# /slack — puxar Slack sob demanda

## Parsing

`/slack #canal` · `/slack @user` · `/slack #canal 30d` · `/slack @user desde 01/09`
Período ausente = janela padrão do `watch.yaml` (default 7d).

## Sequência

1. Executar `scripts/connectors/slack.py` com os argumentos (canal OU usuário +
   janela). O snapshot cai em `vault/RAW/inbox/slack-<alvo>-<janela>.md`.
2. Processar via `/dump` — artefato tipo "dump de conector": transcrição limpa
   da janela, threads reconstruídas, quem disse o quê (resolver aliases!).
3. Resposta ao dono: o digest (temas da janela, decisões, menções a ele),
   com âncora de volta ao snapshot.

## Regras

- DMs podem falhar por permissão da app (API do Slack restringe histórico de
  DM conforme escopo do token). Se vier vazio: reportar como limitação do
  token, sugerir verificar escopo — não tentar 3 vezes.
- `@user` numa thread de canal: trazer a thread toda, não só as falas dele.
- Este comando LÊ Slack. Qualquer resposta/envio está fora da constituição.
