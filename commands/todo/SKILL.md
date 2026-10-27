---
name: todo
description: "Cria uma ação TASK-#### a partir do que o dono digitou: '/todo preciso ler X até quarta' → ledger com prazo resolvido, pessoas e projeto linkados. Sem prazo dito, sugere um pelo contexto (roxo até o dono decidir). '/todo prazo TASK-####' sugere prazo para ação existente. Use quando o dono disser 'preciso', 'tenho que', 'lembra de', ou pedir criação direta."
---

# /todo — declaração do dono vira ação

Isto é `[declarado]`. Não passe pela inbox.

0. **Olhe as existentes antes de criar.** `./brain action dupes --title "<título>" [--project PROJ-#] [--people …] [--link URL]`
   lista as ações abertas (e as fechadas há até 30 dias) parecidas. Julgue pelo sentido, não pela palavra:
   - **é a mesma** → não crie. Diga ao dono qual é (`TASK-####`) e acrescente o que veio de novo nela
     (`action update TASK-#### --note … --people … --due …`, com `--by owner` se for fala dele);
   - **já foi feita** (fechada há pouco) → avise; só crie se o dono disser que é outra rodada;
   - **é outra** → crie. Se o CLI recusar por parecida demais (código 2, nada gravado), repita com `--force`: o par fica
     marcado como julgado e não volta na varredura.
1. Resolva o prazo ("quarta", "amanhã", "15/10") para `AAAA-MM-DD` com a data de hoje do sistema. Prazo dito pelo dono é firme: **sem** `--due-suggested`. Não disse prazo → siga **Sugerir prazo** abaixo (não deixe a ação sem data se houver base).
2. Resolva pessoas citadas (`brain person resolve`). Ambíguo → pergunte (sem chat — rodada ⚡ ou noturno — `./brain ask add`). Inexistente → ofereça `person add` (ou `ask add`).
3. Case projeto/entregável com `PLANNING/goals.md` se for óbvio; senão deixe sem.
4. Esforço se o dono falou tempo (`90m`, `2h`).
5. Lista: padrão `mine`. Se a ação é de outra pessoa para o dono, `--list waiting --owner <id>`.

```
./brain action open "<título>" --due AAAA-MM-DD --effort 90m --project PROJ-1 \
  --people marina-demo --by owner
```

6. `./brain render` e mostre a linha da ação (id, prazo, projeto).
7. Uma frase: o que ficou aberto e o que falta (prazo? projeto?).

## Sugerir prazo

Quando a ação nasce sem prazo (ou o dono pede `/todo prazo TASK-####`), o agente **sugere** uma data pelo contexto.
Sugestão é julgamento seu; a data fica marcada no ledger (`due_suggested`) e aparece **em roxo** na TUI e no painel
até o dono definir outra data ou confirmar. O CLI só guarda e colore — você escolhe a data.

Base, em ordem de força (cite a que usou em `--due-reason`, uma frase):

1. **Entregável/projeto** ligado: prazo do entregável em `PLANNING/goals.md` (ação deve acabar *antes*, com folga para o que depende dela), ou o próximo prazo do projeto (`./brain project PROJ-#`).
2. **Acordos com pessoas**: combinado em reunião/Slack/e-mail ("te mando até sexta"), prazo de quem espera (`unblocks`), ação da qual esta depende (`blocked_by` aberta com prazo → depois dela).
3. **Agenda e carga**: reuniões/prazos próximos (`brain action list`, `brain focus plan`, snapshot do calendário) — evite empilhar no mesmo dia; considere o esforço (`--effort`).
4. **Prioridade/idade**: `alta` pede data curta; `baixa` sem âncora pode ficar sem sugestão.

Regras: data ≥ hoje, de preferência dia útil; nunca inventar âncora — **sem base nenhuma, não sugira** ("não consta" e a ação fica sem prazo, avise). Ação `watching` não leva prazo.

O CLI não deixa o agente "esquecer": `action open --by agent` sem `--due` é recusado, a menos que venha
`--due-none-reason "…"` (o "não consta" com o motivo). Fila de ações abertas sem prazo: `./brain action list --undated`
— percorra-a com `/todo prazo TASK-####` quando o dono pedir ou ao fim de um `/dump`.

```
./brain action open "<título>" --due AAAA-MM-DD --due-suggested --due-reason "entregável PROJ-1.6 vence 30/11; folga de 1 semana" \
  --project PROJ-1 --by agent --prov observado --source chat
./brain action update TASK-#### --due AAAA-MM-DD --due-suggested --due-reason "…" --by agent --prov observado --source chat
```

Quando é o dono quem cria (`--by owner`) e não disse prazo: crie a ação com `--by owner` e, em seguida, registre a sugestão
com o `action update … --due-suggested --by agent` acima (sugestão nunca vem como `owner`).
O dono decide depois: outra data (`action update --due …`, volta às cores normais) ou aceita como está
(`action update TASK-#### --confirm-due --by owner`). Mostre a data sugerida e o porquê na linha de resposta.
