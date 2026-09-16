---
name: done
description: "Fecha uma ação: /done A-0146 <como> — ledger, cascata de desbloqueio e linha em deliveries.md SE for entrega real. Use quando o dono disser 'fechei/terminei/completei X' ou pedir /done."
---

# /done — o fecho do /todo

## Sequência

1. **Resolva a ação**: `/done A-0146 <como>` por ID, ou texto livre → casa com
   ações ABERTAS pelo título; ambíguo → liste até 5 em 1 linha e pergunte qual;
   nada casa → diga ("não achei aberta — era /todo?") e pare.
2. **Feche no ledger** (append): `A-#### · fechada · <data real> · <como>` —
   o texto do dono, limpo; sem texto → "concluída".
3. **Entrega ou só fechamento?** (a regra que mantém o recap limpo)
   - **Linha em `_logs/deliveries.md`** SE a ação tinha `proj:`/`unblocks:` OU
     o "como" descreve resultado observável ("em produção", "aprovado",
     "publicado", número). Formato: `data · A-####/P# · o quê · resultado ·
     evidência (se citada) · [declarado]`.
   - **Só fechar** (sem delivery) se operacional: ler material, responder msg,
     rotina — checkbox não é entrega; deliveries é do que o recap conta.
   - Na dúvida: feche sem delivery — delivery espúria polui recap; a real
     ainda pode ser declarada no /week depois.
4. **Cascata**: ações que esta `unblocks:` (ou bloqueadas por ela via
   `blocked-by:`) ganham linha: `A-#### · atualizada · <data> · desbloqueada
   (A-#### fechada)` — o grafo reage ao fecho.
5. **Confirme em 1-2 linhas**: "A-0146 fechada (enviado, Bruno confirmou) ·
   delivery registrada · A-0151 desbloqueada".

## Regras

- Ação de terceiro ("o Bruno fechou a revisão") → fecha com
  `· fechada · reportado pelo dono` — registra quem reportou, sem inventar.
- **Reabrir não reescreve**: nova linha `A-#### · reaberta · <data> · motivo`
  (append-only vale pra estados também).
- Proveniência destas linhas: **`[declarado]`** — afirmação direta do dono,
   nível acima de `[observado]`; nunca rebaixe pra observado.
- `/week` usa este mesmo protocolo: cada "fechei X" da semana = um /done.
- Fecho não mexe em goals/PLANNING (progresso declarado é outra conversa).
