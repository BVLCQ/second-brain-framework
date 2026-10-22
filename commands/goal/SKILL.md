---
name: goal
description: "A árvore de goals e projetos: visualização, progresso declarado, e o ÚNICO gate do sistema — qualquer criação/mudança/fechamento é proposta de diff aprovada explicitamente pelo dono."
---

# /goal — a árvore e o gate

## Só ver

`./brain plan show` e `FRESH/goals.md`. Progresso calculado (entregáveis) e declarado (`brain progress GOAL-1 45`) aparecem lado a lado. Não misture.

## Mudar estado factual de um entregável

Com evidência (artefato, declaração):

```
./brain plan deliverable PROJ-1.2 --status feito --evidence "…" --by agent --prov observado --source PROCESSED/…
```

Isso não é o gate. É checkbox + data + linha no log.

## Mudar a estrutura (gate)

Criar, renomear, fundir, fechar, reabrir goal ou projeto:

1. Mostre o diff exato de `PLANNING/goals.md` (antes/depois).
2. Uma frase: por quê, com evidência.
3. Espere "ok" / "aprovo" / equivalente. Silêncio = não.
4. Aplique o diff no arquivo.
5. `./brain plan log --diff "<resumo>" --reason "<por quê>" --evidence "<fonte>" --approval "<literal>"`.
6. `./brain render`.

Não reapresente proposta rejeitada sem evidência nova. No noturno, nunca mude a árvore — abra `brain proposal add --kind mudar-plano`.
