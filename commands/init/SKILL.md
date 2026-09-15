---
name: init
description: "Primeira entrevista do cérebro: descobre quem é o dono, seus goals, projetos e pessoas, e monta PROFILE + PLANNING como proposta. Use quando PROFILE e PLANNING estiverem vazios (cérebro novo). O dono pode soltar arquivos a qualquer momento durante a entrevista — viram o primeiro dump."
---

# /init — o nascimento do cérebro

**Gatilho:** vault/PROFILE/profile.md e vault/PLANNING/goals.md sem conteúdo real (só template).

## Princípios da entrevista

1. **Pergunte em blocos, não em gotejamento** — 3 a 5 perguntas por vez,
   respondíveis numa mensagem só. Entrevista de formulário um-a-um é abandonada.
2. **Arquivos valem mais que respostas** — a qualquer momento o dono pode
   soltar arquivos (CV, doc de onboarding, apresentação, export, notas).
   Ao detectar arquivos novos em `vault/RAW/inbox/`: processe-os JÁ pelo pipeline do
   `/dump` (eles alimentam as próximas perguntas: "vi no seu CV que…"),
   e continue a entrevista de onde parou.
3. **Proposta, nunca imposição** — PROFILE e PLANNING são escritos como
   PROPOSTA ao final; o dono aprova/edita. Isto é o gate de goals da primeira vez.
4. **10 minutos, não 60** — se o dono não souber algo, siga adiante; o cérebro
   aprende depois, com dados reais.

## Roteiro (4 blocos)

**Bloco 1 — Quem é você:** papel atual e empresa/squad · frentes de trabalho ·
como gosta de operar · o que importa nos próximos 6 meses.

**Bloco 2 — Para onde vai:** 2–4 goals com horizonte · projetos ativos por goal ·
entregáveis com deadline real (se souber; senão `?`).

**Bloco 3 — Quem te cerca:** pessoas recorrentes (gestor, pares, parceiros) —
nome + como grafam + apelido + e-mail se souber (alimentam aliases) · relação
de cada uma com seus goals.

**Bloco 4 — O que observar** (opcional, pode ficar pra depois): se
`config/watch.yaml` existir, oferecer editá-lo (repos, boards, canais, pessoas).

Se arquivos já caíram na inbox antes de um bloco: leia os artefatos processados
e FAÇA perguntas ancoradas neles ("seu goal G2 aparece na apresentação X — é
seu goal principal?").

## Entrega final

1. Escrever `vault/PROFILE/profile.md` preenchido (proposta).
2. Escrever `vault/PLANNING/goals.md` com a árvore G#/P# (proposta).
3. Se houver pessoas: fichas no `people-index.md` com aliases coletados
   (append-only — já é escrita normal, sem gate).
4. Mostrar o resumo das duas propostas e pedir aprovação explícita.
5. Aprovação → registrar em `vault/PLANNING/log.md` (entrada de nascimento) ·
   processar qualquer restante da inbox · gerar o primeiro
   `vault/FRESH/daily-brief.md`.
6. Encerrar com o caminho do dia a dia: "jogue coisas em vault/RAW/inbox/ e rode
   /dump; amanhã, /brief".

## Pitfalls

- Não inventar goals que o dono não disse — espaço em branco é honesto, goal
  fictício corrompe o radar pra sempre.
- Não processar arquivos soltos "depois": o valor do /init é a entrevista
  ancorada em evidência.
- Datas: sempre relativas ao dia real do sistema — nunca escrever data literal
  derivada de "hoje" em arquivo permanente sem checar.
