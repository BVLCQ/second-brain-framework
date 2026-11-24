---
name: brief
description: "O dia do dono em uma tela: hoje, ações atrasadas, próximos 3 dias, goal em foco, contexto recente. Use toda manhã, ou quando o dono pedir 'meu dia'."
---

# /brief — o dia

1. `./brain render` (colhe checkboxes/status e atualiza o painel).
2. Leia `vault/FRESH/home.md` e `vault/FRESH/todo.md`. Não recalcule atraso/progresso — o CLI já fez.
3. Escreva o brief (reescreve; é narrativa, não verdade nova) e grave com
   `./brain note write brief --file <arquivo>` (ou `--file -`, com o texto no stdin).
   O brief é **Markdown mínimo** — sem linha de título, sem seção de saúde — e o painel faz o resto:
   - **Sem título.** O cartão "Seu dia" já traz a data e o horário: não escreva `# Brief do dia — …`
     nem diga "(noturno)" ou "(manhã)" — a rotina que gerou não é informação do dia.
   - **Sem saúde.** Aviso do doctor tem tela própria; o cabeçalho do cartão já liga para ela.
     Erro do doctor vai no chat (passo 5), não no brief.
   - **Seção** com `##` (o painel mostra como rótulo), **item** com `-`, subitem com dois espaços,
     passo numerado com `1.`. Seção sem conteúdo não aparece — não escreva "nada".
   - **Id solto, sem crase e sem parênteses:** `TASK-0146`, `PROP-0012`, `ASK-0003`. O painel transforma em
     etiqueta com link para a ficha e pega título e situação do ledger — não reescreva ao lado
     ("atrasada 3d", "fechada"). Id entre parênteses vira só o chip; entre crases, fica literal.
   - Ênfase (`**negrito**`) só no nome da coisa. Sem tabela, sem bloco de código, sem imagem, sem link externo.
   - **Curto:** é uma olhada, não um relatório. O painel mostra até 3 seções abertas e recolhe o resto
     atrás de "Mostrar tudo".
   - Seções, na ordem: **Hoje** (o que vence hoje + o que já está `fazendo`) · **Atrasadas** (minhas; o que
     bloqueia) · **Próximos 3 dias** · **Me devem** (`waiting` atrasada ou que vence cedo; não cobra
     `watching`) · **Goal em foco** (o mais em risco / o que o dono declarou) · **Aguardando você**
     (propostas, plano de foco, rascunhos e **perguntas abertas**: as 3 `ASK-####` mais antigas, de `home.md`).
   - Nada mudou: `./brain note write brief --empty --text "Sem novidades desde a última atualização."`
4. No chat: o mesmo em ≤15 linhas, escaneável. Aponte o painel (`FRESH/dashboard/index.html`).
5. Se o doctor tiver `error`, uma linha no topo do chat.
