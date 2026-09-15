# PLANNING — goals, projetos, entregáveis

> A hierarquia: **goal → projeto → entregável → ação**. Ações (A-####) vivem no
> log do PROCESSED; aqui mora a árvore e o estado de cada nó.
> **Único gate do sistema:** criar/mudar/fechar goal ou projeto exige aprovação
> explícita do dono. Estado factual (datas observadas, links) o agente atualiza
> com log em `log.md`.

## Goals ativos

### G1 — <nome do goal>
- **Por quê:** <o que isto destrava / por que existe>
- **Horizonte:** <data ou evento>
- **Status:** ativo | congelado | fechado · **Progresso:** 0–100% (declarado pelo dono)

#### Projeto: <nome>  `(P1)`
- Entregável: <nome> — deadline <data> — status
- Entregável: <nome> — deadline <data> — status

<!-- Duplique o bloco por goal. Ações não moram aqui — moram no log A-####. -->

## Goals fechados
<!-- mova pra cá ao fechar (não apague nunca — histórico é o produto) -->

<!--
CONVENÇÕES:
- IDs: G# (goal), P# (projeto) — sequenciais, nunca reusados.
- Progresso é DECLARADO pelo dono (não auto-estimado pelo agente).
- O agente pode propor mudanças (diff: antigo → novo · por quê · evidência);
  só aplica com aprovação explícita. Proposta descartada não volta sem
  evidência nova.
-->
