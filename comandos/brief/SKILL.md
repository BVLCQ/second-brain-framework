---
name: brief
description: "O dia do dono em uma tela: hoje, ações atrasadas, próximos 3 dias, goal em foco, contexto recente. Use toda manhã, ou quando o dono pedir 'meu dia'."
---

# /brief — a manhã do dono

## Antes de responder: checagem de frescor

1. Ler `vault/FRESH/brief-de-hoje.md` (se existir) e seu `generated-at:`.
2. Se algo mudou desde (`PROCESSED` ganhou artefatos, inbox tem itens, ou a
   data de hoje ≠ data do generated-at): rodar `/update` primeiro (ou, no
   mínimo, dump da inbox + regeneração deste brief). Avisar o dono do catch-up
   em 1 linha: "nightly não rodou — atualizei agora (~40s)".
3. Se nada mudou: entregar a view como está.

## Estrutura da view `brief-de-hoje.md`

```
☀ BRIEF — <dia da semana>, <data> · gerado <hh:mm> (<origem: nightly|agora>)

HOJE          compromissos de hoje (hora · o quê · com quem · → card de prep se houver)
ATRASADAS     ações A-#### abertas com deadline < hoje (idade em dias)
PRÓXIMAS 72H  deadlines e compromissos na janela
GOAL EM FOCO  o goal mais urgente por PLANNING + próxima pedra
CONTEXTO      3–5 linhas: o que mudou ontem (digests, decisões, movimentos)
```

Regras: atraso calculado na leitura (nunca escrito em log) · nada de informação
que não derive de PROFILE+PLANNING+PROCESSED · cabeçalho `generated-at:` +
`fontes:` sempre.
