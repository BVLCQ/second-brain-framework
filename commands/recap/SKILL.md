---
name: recap
description: "Gera documento datado e COMPARTILHÁVEL em vault/reports/ com o histórico e impacto de um goal, projeto ou período: o que foi entregue (com fontes), resultados, próximos passos. Use quando o dono pedir recap, impacto, retrospectiva ou 'o que fizemos de X'."
---

# /recap [goal|projeto|período] — o dossiê compartilhável

**Entrega:** um arquivo autocontido em `vault/reports/<AAAA-MM-DD>-<slug>.md` —
escrito pra ser **lido por humanos de fora** (coordenador, gerente): sem jargão
interno, sem IDs crus no corpo (IDs ficam nas fontes), números e datas reais.

## Fontes (leia todas antes de escrever)

1. `vault/PLANNING/goals.md` + `log.md` — objetivo, mudanças de rumo
2. `vault/PROCESSED/_logs/deliveries.md` — **a espinha dorsal**: entregas com resultado/evidência
3. `vault/PROCESSED/_logs/actions.md` — ações fechadas no período (e as que ficaram)
4. `vault/PROCESSED/_indices/` — menções, timeline, pessoas envolvidas
5. Artefatos citados — para o "como" (resultados quantitativos vêm das declarações do dono e de docs; **não invente números**)

## Estrutura do documento

```markdown
# <Goal/Projeto/Período> — recap & impacto
_Gerado em <data> · cobre <período> · fontes no fim_

## Objetivo
1-2 linhas: por que isto existia.

## O que foi entregue
- <entrega> — <data> · resultado: <declarado/evidenciado> [proveniência]
(uma linha por entrega, do deliveries.md; agrupe por projeto se fizer sentido)

## Resultado & impacto
O que mudou: números declarados pelo dono, evidências de docs/reuniões.
Sem número? Diga qualitativo — nunca fabrique métrica.

## Pendências & próximos passos
Abertas relevantes + próximo marco (do PLANNING).

## Fontes
- A-####/D-####/entregas/artefatos com data — rastreabilidade completa.
```

## Regras

- **Autocontido**: quem lê não tem acesso ao cérebro — sem links internos como
  única referência; o essencial vem no corpo, fontes ao fim pra auditoria.
- **Reports são point-in-time**: nunca edite um report gerado; regerar cria
  arquivo novo com nova data (são exports, como PDFs).
- Impacto quantitativo só do que tem fonte (declaração do dono `[observado]`
  ou doc `[doc]`); senão qualitativo explícito.
- Pergunta vaga ("impacto de XYZ")? Confirme o escopo (goal? projeto? mês?)
  em 1 linha antes de gerar — report errado é retrabalho compartilhado.
