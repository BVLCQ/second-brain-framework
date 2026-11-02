---
name: feedback
description: "Registra sugestão ou bug do próprio cérebro e cria a issue no repo público do framework (porta 7). Use quando o dono sugerir uma melhoria ou relatar um bug no Segundo Cérebro."
---

# /feedback — sugestões e bugs do próprio cérebro

1. **De quem é a ideia?** O dono pediu ("isso deveria…", "achou um bug") → o pedido dele é a
   aprovação: registre e publique direto. Foi o agente que percebeu → mostre o rascunho e espere
   um "ok" antes de publicar.
2. **O issue é público.** Título e corpo não carregam nada do dono: sem nomes de pessoas do
   ledger, e-mails, canais, caminhos da máquina ou segredos. A porta recusa sozinha (mesmas regras
   do `upstream`) — descreva o problema, não a pessoa.
3. Registre e publique:

```
./brain feedback add "Título curto e claro" --kind sugestao|bug \
  --body "O que acontece, onde, como reproduzir" --context TASK-…,PROC-… --by owner
```

`--by owner` quando o dono pediu; `--by agent --source chat` quando você observou. O `add` já
cria a issue na sequência e devolve o link. Sem pressa: `--no-push` deixa `FB-####` pendente.

4. **Não publicou** (sem `GITHUB_TOKEN` em `config/.env`, rede, GitHub fora)? O item fica
   `pendente`/`falhou` — nada se perde:

```
./brain feedback list          # a fila do que falta publicar
./brain feedback push FB-####  # tenta de novo
```

5. Push morreu DEPOIS de criar a issue (o link apareceu, o registro não):
   `brain feedback pushed FB-#### --number N --url <link>`.
6. Título igual ao de um FB existente é recusado — acrescente detalhe ao existente ou `--force`.
7. No noturno a porta não publica: registre sem push e empurre no dia seguinte.
8. Reporte ao dono: `FB-####` + o link da issue.
9. **Acompanhar:** `./brain feedback sync` relê o estado de cada issue no GitHub (aberta/fechada · concluída/não
   será feita) e grava as mudanças — o dono vê no painel (aba Sugestões) e na TUI (log › Feedback). O `/update`
   roda no passo 6; a pedido, rode na hora. Sem `GITHUB_TOKEN`, pula com aviso (não é erro).
