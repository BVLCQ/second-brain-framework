# Log de ações (append-only)

> Ações A-#### extraídas de qualquer fonte. Estados em sequência, nunca reescritos.
> Atraso é calculado na leitura — nada de "varredura de vencidos" escrevendo aqui.
>
> **Campos opcionais por ação** (use quando existirem; detecção é do /dump):
> `blocked-by: A-####` (por que não anda) · `unblocks: A-####, P#` (o que destrava)
> · `proj: P#` · `link: <artefato/doc>` · estado `waiting` (esperando terceiro —
> dependência externa, não atraso). Ação complexa (multi-passo, contexto próprio)
> → ficha em `_actions/A-####.md`; o ledger marca `ficha: sim`.
> Ação que FECHA com resultado → linha correspondente em `_logs/deliveries.md`.

<!-- MODELO (apague o comentário ao criar a primeira real):

A-0146 · aberta · <data> · enviar draft dicionário p/ Bruno · dono: VOCÊ ·
  deadline <data> · proj: P1 · unblocks: P1-entregável-1 · origem: D-0092
A-0147 · aberta · <data> · revisar draft dicionário · dono: Bruno · waiting
A-0146 · blocked · <data> · blocked-by: A-0147 (revisão do Bruno)
A-0147 · fechada · <data> · aprovado sem ressalvas
A-0146 · fechada · <data> · enviado; confirmado no gmail digest → deliveries.md

-->
