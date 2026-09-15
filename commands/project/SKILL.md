---
name: project
description: "Status de um projeto: árvore de entregáveis, ações abertas, saúde de prazo, pessoas envolvidas, evidência recente. Use quando o dono perguntar por um projeto."
---

# /project <nome> — status de projeto

## Passo 0 — resolver o projeto

Pelo `projects-index.md` (P#) e pela árvore em `vault/PLANNING/goals.md`.

## A view (seção em `vault/FRESH/projects.md`)

```
▣ <P# Nome> · goal: <G#> · status: <…> · deadline mais próximo: <data>

ENTREGÁVEIS   árvore com status e deadlines (do PLANNING)
AÇÕES ABERTAS as do projeto (A-####, dono, idade) — suas e de outros
PESSOAS       envolvidas + papel delas no projeto (via índice)
EVIDÊNCIA     3–5 menções mais recentes (data · 1 linha · fonte)
SAÚDE         on track | em risco | travado — JUSTIFICADO em 1 linha
```

"Saúde" deriva de: deadlines vs. progresso, idade das ações, movimentos
recentes. Se travado: apontar onde (qual entregável/dependência) e — se houver
evidência — sugerir escalonamento como NOTA, nunca como ação automática.
