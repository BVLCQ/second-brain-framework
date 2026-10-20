---
name: todo
description: "Cria uma ação A-#### a partir do que o dono digitou: '/todo preciso ler X até quarta' → ledger com prazo resolvido, pessoas e projeto linkados. Use quando o dono disser 'preciso', 'tenho que', 'lembra de', ou pedir criação direta."
---

# /todo — declaração do dono vira ação

Isto é `[declarado]`. Não passe pela inbox.

1. Resolva o prazo ("quarta", "amanhã", "15/10") para `AAAA-MM-DD` com a data de hoje do sistema. Sem prazo = ação sem `due` (o foco não a agenda — avise).
2. Resolva pessoas citadas (`brain person resolve`). Ambíguo → pergunte. Inexistente → ofereça `person add`.
3. Case projeto/entregável com `PLANNING/goals.md` se for óbvio; senão deixe sem.
4. Esforço se o dono falou tempo (`90m`, `2h`).
5. Lista: padrão `mine`. Se a ação é de outra pessoa para o dono, `--list waiting --owner <id>`.

```
./brain action open "<título>" --due AAAA-MM-DD --effort 90m --project P1 \
  --people marina-demo --by owner
```

6. `./brain render` e mostre a linha da ação (id, prazo, projeto).
7. Uma frase: o que ficou aberto e o que falta (prazo? projeto?).
