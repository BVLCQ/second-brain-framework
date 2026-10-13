---
name: brief
description: "O dia do dono em uma tela: hoje, ações atrasadas, próximos 3 dias, goal em foco, contexto recente. Use toda manhã, ou quando o dono pedir 'meu dia'."
---

# /brief — o dia

1. `./brain render` (colhe checkboxes/status e atualiza o painel).
2. Leia `vault/FRESH/home.md` e `vault/FRESH/todo.md`. Não recalcule atraso/progresso — o CLI já fez.
3. Escreva `vault/FRESH/notes/brief.md` (reescreve; é narrativa, não verdade nova) com:
   - **Hoje** — o que vence hoje + o que já está `fazendo`
   - **Atrasadas** — minhas, com dias e o que as bloqueia
   - **Próximos 3 dias**
   - **Me devem** — `waiting` atrasada ou que vence cedo (não cobra `watching`)
   - **Goal em foco** — o mais em risco / o que o dono declarou
   - **Aguardando você** — propostas, plano de foco, rascunhos
4. No chat: o mesmo em ≤15 linhas, escaneável. Aponte o painel (`FRESH/dashboard/index.html`).
5. Se o doctor tiver `error`, uma linha no topo.
