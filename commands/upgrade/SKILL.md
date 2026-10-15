---
name: upgrade
description: "Atualiza o framework da instância (brain update) e devolve ao repo as melhorias nascidas aqui (brain upstream). Use quando o dono pedir atualização/sync com o framework, ou quando um git pull puro falhar por divergência."
---

# /upgrade — o framework anda nos dois sentidos; o vault não sai daqui

## Descer: `./brain update`

1. `./brain update --check` — mostra o que há de novo sem alterar nada.
2. `./brain update` — avanço rápido com autostash, semeia `template/` novo no vault (nunca
   sobrescreve) e roda o `doctor` com o código novo. Divergência (commits locais ainda não
   enviados) → `./brain update --rebase`; conflito: mostre ao dono, nunca resolva no escuro, e
   `git rebase --abort` desfaz.
3. "template mudou em arquivo que já é seu": mostre o diff entre `template/…` e o arquivo do vault e
   **proponha** o merge; só aplique com aprovação (PROFILE/PLANNING seguem as regras da zona).
4. Divergência em arquivo do framework que não veio do dono:
   - **drift** (edição de agente não pedida) → reaplique o upstream e anote o que se perdeu.
   - **edit** (o dono pediu) → vai para o upstream, abaixo.

## Subir: git puro + varredura

Toda melhoria de **código ou estrutura** feita nesta instância (brainlib, commands, guides,
template, tests, services, scripts, `scripts/local/` que amadureceu) volta ao repo do framework.
Conteúdo do vault e `config/` pessoal nunca. O repo é **público**.

1. `./brain upstream scan` — o que está pendente e o resultado da varredura de dados pessoais.
2. Achado = não sobe. Troque o dado real por exemplo genérico (`ana`, `example.com`,
   `seu-workspace`, `#seu-canal`), mova o que é só desta máquina para `scripts/local/` ou
   `config/`, e rode de novo.
3. Leia o diff mesmo com varredura limpa: ela não pega tudo.
4. Mostre ao dono: arquivos, mensagem de commit proposta e o resultado da varredura. **Espere um
   "ok".**
5. `git add` dos arquivos específicos (nunca `-A` às cegas; nunca `vault/` ou `config/.env`),
   `git commit`, `git push`. O hook `pre-push` roda `scan --committed` e barra se achar algo
   (`./brain upstream hook install` se faltar). Se o upstream andou, `./brain update` antes.

Nunca `push --force` nem `--no-verify`. O noturno não sobe nada. O núcleo Python não se
"conserta" no calor da sessão sem o dono pedir — mas o que foi pedido e funcionou vai para o
upstream no mesmo dia, não fica só aqui.
