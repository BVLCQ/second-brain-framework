---
name: opportunity
description: "Oportunidades/iniciativas (OPP-####): panorama, one-pager e triagem com ICE sugerido. O agente cria só em status 'ideia'; mover, pontuar de verdade e promover a projeto são do dono (promover é o gate)."
---

# /opportunity — oportunidades e iniciativas

Oportunidade e iniciativa são a **mesma entidade** (`OPP-####`) em estágios:
`ideia → triagem → priorizada → em-andamento → piloto → validando → entregue`, e os laterais `em-espera` e `descartada` (ambos exigem motivo).
O dono vai e volta livremente entre eles. **O agente só grava status `ideia`**; `em-andamento` só nasce da promoção.

`/opportunity <termo|OPP-####>` · `/opportunity onepager OPP-####` · `/opportunity triage`

## Panorama

1. Achar: `./brain search "<termo>"` ou `./brain opportunity list [--status …] [--area …] [--sort score]`.
2. `./brain opportunity show OPP-#### --json` (score, quadrante e histórico vêm do CLI).
3. No chat (≤10 linhas): problema, sugestão, ganho esperado (texto + `horas/mês` **declaradas** — não estime), ICE (`I×C×F = score`; rosa/"sugerido" se for sugestão do agente), status e histórico, evidências (quantas e de onde), processo ligado, projeto/goal (e progresso) se promovida.

## onepager

1. Confira os campos: o que não consta, não consta (não preencha com palpite).
2. `./brain share opportunity OPP-#### --format md` → `vault/reports/share/…`. É ponto no tempo, sem jargão interno: pontuação de prioridade, problema, sugestão, ganho, evidências.
3. Ligue ao registro: `./brain doc link OPP-#### --kind one-pager --ref reports/share/<arquivo> --by owner`.
4. Mostre o caminho e peça revisão. Publicar é `/publish` (outro gate, aprovação por publicação).

## triage

Percorre as oportunidades em `ideia` (`./brain opportunity list --status ideia`) **sem ICE** e, para cada uma:
1. Leia `opportunity show` e as evidências (artefatos citados); se faltar base, deixe sem ICE.
2. Sugira, com motivo curto e verificável (≤1 frase por eixo — impacto, confiança, facilidade, cada um 1–5):
   `./brain opportunity score OPP-#### --impact I --confidence C --ease F --suggest --reason "…" --by agent --prov observado --source <artefato>`
3. A sugestão aparece em **rosa** até o dono confirmar (`c` no TUI, ou `opportunity score … --by owner`) ou mudar. Você **não** muda status.
4. Termine com: quantas sugeridas, quantas ficaram sem base.

## Promover (gate estrutural)

Promover cria um projeto num goal: é mudança estrutural.
1. `./brain opportunity promote OPP-#### --goal G#` (sem `--approval`) imprime o diff proposto do `goals.md` e sai com código 4.
2. Mostre o diff ao dono. Só com resposta literal ("ok", "aprovo"): `./brain opportunity promote OPP-#### --goal G# --approval "ok"` — cria o projeto, grava `plan.changed` + `opportunity.promoted` + status `em-andamento` e a linha em `PLANNING/log.md`.
3. Proibido no noturno. Silêncio não é aprovação.

## Duplicata

`./brain opportunity add` avisa de possível duplicata (código 2, nada gravado). Mesma ideia → `./brain opportunity evidence OPP-#### --source <artefato>`; ideia nova → repita com `--force`.
