---
name: done
description: "Fecha uma ação: /done A-0146 <como> — ledger, cascata de desbloqueio e linha em deliveries.md SE for entrega real. Use quando o dono disser 'fechei/terminei/completei X' ou pedir /done."
---

# /done — o fecho do /todo

**Nunca registre TODO/DONE como arquivo na inbox** — declarações do dono vão
DIRETO ao ledger (arquivo na inbox é para material bruto; se o dono soltar um
.md anotando tarefas, o /dump extrai — mas declaração falada/comando é ledger).

## Sequência

1. **Resolva a ação e CONFIRME proporcionalmente ao risco de errar:**
   - `/done A-0146 …` (**ID exato**) → fecha direto: o ID já É a confirmação.
   - `/done <texto>` com **1 match forte** → **1 linha de confirmação antes de
     escrever**: `fechar A-0146 "enviar draft ao Bruno" — é essa? (s/n / nº)`.
     Fuzzy match erra; ledger errado vira ruído em cascata (desbloqueios,
     delivery, brief). Um "n" mostra os próximos candidatos.
   - **Vários matches** → liste até 5 (ID · título · idade) e pergunte qual.
   - **Nada casa** → diga ("não achei aberta — era /todo?") e pare.
   - **Ação de terceiro** ou ação antiga (>30d) → sempre confirme em 1 linha
     (fechar o que não é seu/velho por engano é o erro mais caro).
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
  (append-only vale pra estados também) — errar o fecho é recuperável, mas
  confirmar antes (passo 1) é mais barato que reabrir depois.
- Proveniência destas linhas: **`[declarado]`** — afirmação direta do dono,
   nível acima de `[observado]`; nunca rebaixe pra observado.
- `/week` usa este mesmo protocolo: cada "fechei X" da semana = um /done
  (lote: confirmações agrupadas numa rodada só, mesmo formato 1/2/3).
- Fecho não mexe em goals/PLANNING (progresso declarado é outra conversa).
