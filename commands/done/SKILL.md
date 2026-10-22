---
name: done
description: "Fecha uma ação: /done ACT-0146 <como> — ledger, cascata de desbloqueio e linha de entrega SE for entrega real. Use quando o dono disser 'fechei/terminei/completei X' ou pedir /done."
---

# /done — o dono declara que acabou

Isto é `[declarado]`. ID exato fecha direto. Texto fuzzy: match único confirma em 1 linha; vários matches lista; ação de terceiro ou antiga demais sempre confirma.

```
./brain action close ACT-#### --how "<como>" --outcome "<resultado observável>" --by owner
```

- `--outcome` + (projeto ou entregável ou `unblocks`) → o CLI registra entrega `WIN-####` sozinho.
- Sem resultado observável e sem projeto: é operacional — fecha, não cria entrega. Não invente resultado.
- `--delivery` força a linha de entrega quando o dono insiste.
- Ações que tinham `blocked_by: ACT-####` recebem nota de desbloqueio (não fecham sozinhas).
- Blocos de foco futuros desta ação saem no próximo `brain focus sync`.

Mostre: id, como fechou, se nasceu entrega, o que foi desbloqueado.
`./brain render` se a conversa parar aqui.
