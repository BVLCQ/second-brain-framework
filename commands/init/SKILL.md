---
name: init
description: "Primeira entrevista do cérebro: descobre quem é o dono, seus goals, projetos e pessoas, e monta PROFILE + PLANNING como proposta. Use quando PROFILE e PLANNING estiverem vazios (cérebro novo). Arquivos soltos na inbox viram o primeiro dump."
---

# /init — o nascimento do cérebro

**Gatilho:** `vault/PROFILE/profile.md` e `vault/PLANNING/goals.md` sem conteúdo real (só template).

Antes de perguntar: `./brain init --owner-id <slug> --owner-name "<nome>"` se o ledger ainda não tiver o dono. Confira com `./brain doctor`.

## Princípios

1. **Pergunte em blocos** — 3 a 5 perguntas por vez, respondíveis numa mensagem só.
2. **Arquivos valem mais que respostas** — se cair coisa em `vault/RAW/inbox/`, rode `/dump` e ancore as próximas perguntas no que leu.
3. **Proposta, nunca imposição** — PROFILE e PLANNING saem como PROPOSTA; o dono aprova/edita. Isto é o gate da primeira vez.
4. **10 minutos, não 60** — se não souber, siga; o cérebro aprende com dados reais.

## Roteiro (4 blocos)

**Bloco 1 — Quem é você:** papel e empresa/squad · frentes · como gosta de operar · o que importa nos próximos 6 meses.

**Bloco 2 — Para onde vai:** 2–4 goals com horizonte · projetos por goal · entregáveis com prazo real (se souber; senão deixe sem `prazo:`).

**Bloco 3 — Quem te cerca:** pessoas recorrentes — nome + como grafam + apelido + e-mail · relação com os goals. Grave com `./brain person add`.

**Bloco 4 — O que observar** (opcional): oferecer editar `config/watch.toml` (canais, boards, caixas). Leituras são MCP; sem fonte listada o `/update` não puxa.

## Fechamento

1. Mostre o diff de `PROFILE/profile.md` e `PLANNING/goals.md`.
2. Espere aprovação explícita ("ok", "aprovo"). Silêncio não é aprovação.
3. Aplique. Registre a árvore: `./brain plan log --diff "nascimento" --reason "entrevista /init" --approval "<literal>"`.
4. `./brain render --open` e mostre o painel.
5. Ofereça `/update` se já houver fontes no watch.toml.

O dono pode recusar um goal: não reescreva a proposta inteira — corte o que ele cortou e reapresente o resto.
