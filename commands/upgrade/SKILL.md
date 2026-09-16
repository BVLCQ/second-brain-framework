---
name: upgrade
description: "Atualiza o framework da instância reconciliando edições locais do agente: git pull com autostash, classificação drift-vs-edit, re-aplicação ou graduação pra upstream. Use quando o dono pedir atualização do framework, ou quando o git pull puro falhar por divergência."
---

# /upgrade — atualizar o framework sem perder o que a instância criou

O problema real (provado no dia 1 de uso): o agente da instância melhora scripts
e skills in place → o clone diverge → `git pull --ff-only` recusa. A resposta
não é proibir edições (elas são valiosas) — é **reconciliar com julgamento**.

## Sequência

1. **Radiografia**: `git fetch origin && git status` + `git diff --stat origin/main`.
   Classifique cada arquivo alterado:
   - **drift**: instância clonada de versão antiga (arquivo igual a algum
     commit anterior do origin) — nada a preservar, só atualizar;
   - **edit local**: mudança genuína da instância (diff não casa histórico) —
     candidato a re-aplicar ou graduar;
   - **untracked em `scripts/local/`**: inocente por design (gitignored).
   Vault/ e config da instância nunca aparecem (gitignore) — o pull não pode
   tocá-los; se aparecerem no status, ALGO ESTÁ ERRADO: pare e reporte.
2. **Atualizar**: limpo → `git pull --ff-only`. Sujo → `git stash` →
   `git pull --ff-only` → `git stash pop`.
3. **Conflitos no pop**: resolva JUNTANDO (base upstream + a melhoria local),
   não escolhendo um lado às cegas. Edit que não junta: preserve o conteúdo
   em `scripts/local/<nome>` (ou anexe ao final da skill como seção
   "ajustes locais da instância") e deixe o arquivo voltar ao upstream.
4. **Auto-cura de vault**: semeie arquivos de zona faltantes a partir de
   `template/` (nunca sobrescrever existentes — regra da constituição).
5. **Saúde**: `python3 -m py_compile scripts/connectors/*.py` · `bash -n` nos
   .sh tocados. Quebrou? o edit local é incompatível com o upstream novo —
   reporte ao dono com o erro.
6. **Reporte (≤8 linhas)**: o que veio de novo (changelog por comando do
   `git log HEAD@{1}..`), quais edits locais foram re-aplicados, e quais são
   **candidatos a graduar pro upstream** (o dono mantém o repo — melhorias
   boas voltam pra todo mundo via commit).

## Regra de convivência (edições locais futuras)

- Script NOVO que resolve problema da instância → nasce em `scripts/local/`
  (não bloqueia pull; se provar valor, o dono gradua).
- Edit em arquivo do framework → mínimo e cirúrgico; reportar no /upgrade.
- Nunca editar AGENTS.md na instância (constituição é do upstream).

## Diagnóstico

- pull recusa mesmo com stash vazio → commits locais no clone (alguém commitou
  na instância): `git log origin/main..HEAD` para ver; reportar antes de agir.
- `--ff-only` impossível após tudo → o clone tem histórico próprio; escala.
