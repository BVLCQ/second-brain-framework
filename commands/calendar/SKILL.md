---
name: calendar
description: "Lê a agenda via MCP (janela padrão 14d) e grava snapshot gcal-*.json na inbox — combustível do planejador de foco. Não cria evento: isso é /focus depois da aprovação."
---

# /calendar — ler a agenda

1. MCP Google Calendar: `list_events` no calendário primário, daqui até +14 dias (ou o que o dono pediu).
2. Grave o JSON cru:

```
./brain snapshot --key gcal-primary --prefix gcal --ext json
```

3. Não extraia ações de reunião aqui (a menos que o dono peça `/dump` explícito nesse snapshot).
4. Se o dono quiser blocos de foco: `/focus` usa este snapshot como ocupado.

Criar/apagar evento = só `brain focus apply` com plano aprovado. Qualquer outro write no calendário é violação.
