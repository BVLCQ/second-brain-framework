---
name: feedback
description: "Registra sugestão ou bug do próprio cérebro e cria a issue no repo público do framework (porta 7). Use quando o dono sugerir uma melhoria ou relatar um bug no Segundo Cérebro."
---

# /feedback — sugestões e bugs do próprio cérebro

1. **De quem é a ideia?** O dono pediu ("isso deveria…", "achou um bug") → o pedido dele é a
   aprovação: registre e publique direto. Foi o agente que percebeu → mostre o rascunho e espere
   um "ok" antes de publicar.
2. **O issue é público e segue um molde.** Título e corpo não carregam nada do dono: sem pessoas, e-mails,
   canais, caminhos, prints, links internos (Drive, Slack, Jira…), IDs do vault (`TASK-…`, `OPP-…`), telefones
   ou números reais. A porta recusa sozinha (`publicguard`) e diz o tipo e a linha — descreva o problema, não o
   caso. Exemplos **sempre** com a padaria fictícia (`marina-demo`, "Padaria Pão Quente", `contato@example.com`).
   Não escreva tag nem `FB-####` no título (a porta põe `[Sugestão]`/`[Bug]`/`[Proposta]` e nunca publica id local). O corpo segue o molde do tipo: `./brain feedback template --kind sugestao|bug` imprime os campos (guia:
   `guides/feedback-issues.md`). Escreva o corpo num arquivo e passe `--body-file` (headless não passa heredoc).
3. Registre e publique:

```
./brain feedback add "Título curto e claro" --kind sugestao|bug \
  --body-file corpo.md --by owner
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
10. **Proposta que muda o código do cérebro** (melhoria de `brainlib/`, `commands/`, `template/`, `guides/`…): não
    use `--kind outro`. Escreva o corpo no molde `framework` (`./brain feedback template --kind framework`) e abra
    `./brain proposal add --kind framework --summary "…" --issue-title "…" --issue-body-file corpo.md
    --by agent --prov observado --source <origem>`. O `--summary` é interno (pode citar IDs); título e corpo são
    **o texto público** (sem pessoas, prints, links internos nem IDs do vault — a porta recusa). O dono vê esse
    texto na proposta; ao **aceitar**, o `proposal accept` cria o `FB-####` e publica a issue sozinho (o aceite é
    a aprovação). Rejeitada, nada sobe. No noturno só se abre a proposta.
11. **Corrigir antes de publicar:** `./brain feedback show FB-####` mostra o texto exato; `./brain feedback revise
    FB-#### --title … --body-file …` o corrige enquanto não virou issue (o ledger guarda as duas versões).
