---
name: goal
description: "A árvore de goals e projetos: visualização, progresso declarado, e o ÚNICO gate do sistema — qualquer criação/mudança/fechamento é proposta de diff aprovada explicitamente pelo dono. Use quando o dono falar em goals, prioridades ou mudanças de plano."
---

# /goal [filtro] — a única porta com trava

## Visualização (sem argumentos ou com filtro)

```
◉ G2 Destravar frente de dados · ativo · 60% · horizonte 30/11
    P1 Padronização de métricas · 3/5 entregáveis · próxima pedra qua 16/09
    P4 Dicionário de dados v1 · draft (ver A-0146)
  G3 Apoio ao BI · congelado até 05/10 ⚠ (12d sem movimento)
```

Progresso de goal = declarado pelo dono; progresso de projeto = derivado dos
entregáveis. Idade de movimento vem dos índices (regra do /week).

## Mudanças (o gate)

Qualquer criar/mudar/fechar goal ou projeto = PROPOSTA:

```
PROPOSTA (nada alterado):
  <G#/P#> <campo>: <atual> → <novo>
  por quê: <motivo>
  evidência: <IDs/artefatos/datas>
aprovar? (ok / editar / descartar)
```

Aprovação explícita → aplicar + registrar em `PLANNING/log.md` (data · diff ·
motivo · evidência · "aprovado: <resposta do dono>").

## Regras

- Estado factual (deadline observada num doc, link adicionado) NÃO é gate —
  atualiza com log, sem cerimônia.
- Fechar goal que atingiu os entregáveis: ainda passa pelo gate (o dono
  confirma), mas é rotineiro — 1 linha de proposta.
- Silêncio não é aprovação. Proposta descartada não volta sem evidência nova.
- O agente JAMAIS cria goal por conta própria, nem "organiza" a árvore sem
  pedir.
