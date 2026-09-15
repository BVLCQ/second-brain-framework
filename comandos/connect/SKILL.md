---
name: connect
description: "Puxa fontes externas AGORA (Jira, GitHub, Slack) via conectores de leitura, fora do cron noturno — e processa o que chegou. Use quando o dono quiser o estado atual de uma fonte antes de uma reunião/decisão."
---

# /connect [fonte] — puxar do mundo agora

## Argumentos

`/connect` = todas as fontes do `watch.yaml` · `/connect jira` (ou github,
slack, gmail, drive) = só aquela fonte.

## Sequência

1. Executar o(s) conector(es) de `scripts/connectors/` correspondentes
   (gmail→`gmail.py`, drive→`gdrive.py`) — leitura pura, snapshots em
   `RAW/inbox/` com prefixo.
2. Relatório curto por fonte: **só o que é novo** (change digest contra
   `.state.json`): "PR #142 +2 comentários (sem resposta sua)".
3. Processar via `/dump` (o dono raramente quer o dado cru esperando).
4. Se algo relevante para o dia (resposta de stakeholder, card que andou):
   1 linha no final: "→ relevante p/ sua reunião com Ana às 15h".

## Regras

- Nunca escrever em ferramenta externa. Nunca responder/comentar por conta própria.
- Fonte sem credencial: dizer qual variável falta do `.env.example`, sem
  imprimir valor nenhum.
- Erro de API: reportar a mensagem BRUTA do conector, não interpretar demais.
