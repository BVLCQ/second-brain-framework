---
name: upgrade
description: "Atualiza o framework da instância reconciliando edições locais: git pull com autostash, classificação drift-vs-edit, re-aplicação ou graduação pra upstream. Use quando o dono pedir atualização, ou quando o git pull puro falhar por divergência."
---

# /upgrade — o framework anda; o vault fica

1. `git status` — vault/ e config/ da instância devem estar ignorados. Se houver arquivo do dono staged, pare e avise.
2. `git pull --ff-only --autostash`. Fast-forward limpo: semeie arquivos de zona **novos** a partir de `template/` (nunca sobrescreva). Rode `./brain doctor`.
3. Divergência em arquivo do framework (skill, brainlib, guia):
   - **drift** (sua edição local de agente, não pedida) → re-aplique o upstream e anote o que se perdeu.
   - **edit** (o dono pediu aquela mudança) → mostre o diff e pergunte se gradua (commit no framework) ou descarta.
4. Nunca `push --force`. Nunca commite `vault/` ou `config/.env`.
5. Recibo: o que atualizou, o que pediu decisão, o doctor depois.

O núcleo Python (`brainlib/`) não se "conserta" no calor da sessão sem o dono pedir — bug evidente (crash) pode ter patch local e vira candidato a graduar no próximo upgrade.
