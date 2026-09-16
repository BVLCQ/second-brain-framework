---
name: week
description: "Cockpit semanal: lookahead de 14 dias, radar de goals por frente, ações envelhecendo, foco sugerido — e o momento de propostas de mudança em goals. Use às sextas ou quando o dono pedir 'minha semana'."
---

# /week — o cockpit

## Estrutura da view `week.md`

```
⛏ SEMANA <nº> · lookahead 14 dias

DEADLINES          entregáveis e ações com data na janela
REUNIÕES           compromissos da semana (→ cards de prep por participante)
GOALS              por goal: progresso declarado + idade do último movimento ⚠
AÇÕES ENVELHECENDO abertas há >7 dias (com nota: dependência externa? escalar? ⛔ blocked-by visível)
FOCO SUGERIDO      1–2 linhas: o que atacar primeiro e por quê
```

## Radar de goals (o coração do /week)

Para cada goal ativo em PLANNING: progresso declarado + **idade do último
movimento** (última ação fechada/atualizada OU última menção em artefato —
via índices). Meta parada >10 dias ganha ⚠ e uma proposta (abaixo).

## Propostas de mudança (o único gate)

Se a evidência justificar (goal travado sem movimento, deadline em risco,
goal concluído pelos entregáveis), PROPONHA — não aplique:

```
PROPOSTA DE MUDANÇA (nada foi alterado ainda):
  <G#/P#> <campo>: <atual> → <proposto>
  por quê: <motivo curto>
  evidência: <IDs/datas/artefatos>
aprovar? (ok / editar / descartar)
```

Regras: uma proposta por vez, no máximo 2 por /week (cerimônia mata o hábito) ·
descartada não volta sem evidência NOVA · aprovada → aplicar + registrar em
`vault/PLANNING/log.md` com a assinatura do dono.

## Progresso declarado

O /week é também onde o dono declara progresso ("G2 em 70%") — atualizar o
PLANNING (estado factual, sem gate) e refletir na view.

## Entregas da semana → deliveries.md

Todo "fechei/terminei/entreguei X" declarado no /week segue o **protocolo do
`/done`** (commands/done/SKILL.md): linha no ledger, cascata de desbloqueio,
e linha em `_logs/deliveries.md` (`data · ref · o que · resultado · evidência
· [declarado]`) — só quando for entrega real (projeto ligado ou resultado
observável); operacional só fecha. É daí que o /recap monta o histórico.

## Geração da pocket (`FRESH/pocket.md`)

Derivada, regenerada no /week (e /update): **status compartilhável pro
coordenador/gerente** — 1 página, tom sóbrio, sem jargão interno:
- **Status por goal** (1 linha cada: % e próxima pedra)
- **Foco da semana** (1-2 linhas)
- **Entregue recentemente** (do deliveries.md, ≤5 linhas)
- **Bloqueios que preciso de vocês** (dependências externas, com nome de quem)
- cabeçalho `generated-at:`; nada que não derive das zonas.
