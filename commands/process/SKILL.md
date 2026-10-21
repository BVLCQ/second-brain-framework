---
name: process
description: "Panorama de um processo (PROC-####) ou cadastro guiado: área, responsável, recorrência, duração, playbook, dores, maturidade. Horas/mês quem calcula é o CLI. Use quando o dono perguntar 'como funciona X?' ou citar um processo que ainda não existe."
---

# /process — um processo

`/process <termo|PROC-####>`

## Panorama (o processo existe)

1. Achar: `./brain search "<termo>"` ou `./brain process list [--area …]`. Várias possibilidades → mostre e pergunte; nenhuma → vá ao cadastro.
2. `./brain process show PROC-#### --json` (os números — horas/mês, lacunas — vêm do CLI; **nunca** calcule).
3. No chat (≤12 linhas):
   - quem é o responsável e quem executa; recorrência, duração por execução e **horas/mês**
   - ferramentas e "entradas → saídas"; dores registradas; maturidade
   - playbook: ligado? lido em que data? (o `/update` relê só quando o doc muda)
   - oportunidades ligadas (`OPP-####`, status, ICE) e lacunas (`⚠ sem playbook`, `sem responsável`, `sem recorrência/duração`)
4. O que não consta, não consta. Não deduza recorrência nem duração.

## Cadastro guiado (o processo não existe)

1. Resolva as pessoas: `./brain person resolve "<nome>"` (código 2 = ambíguo, pergunte; 3 = não consta, ofereça `person add`).
2. A **área** precisa existir (`./brain area list`). Não existe → proponha `./brain area add <slug> --name "…"` e espere o ok do dono.
3. Pergunte só o que falta, uma coisa de cada vez: responsável (1 pessoa), executores, recorrência (`diaria` · `semanal` · `quinzenal` · `mensal` · `trimestral` · `sob-demanda` · `por-evento`; as duas últimas pedem `--per-month`), duração por execução (`45m`, `1h30m`), ferramentas, entradas → saídas, dores, maturidade 1–5.
4. Grave (declaração do dono): `./brain process add "<título>" --area <slug> --owner <id> [--executor <id> …] --recurrence … --duration … --by owner`.
5. Playbook: `./brain doc link PROC-#### --kind playbook --ref <url|id do Drive> --watch --by owner` (vigia o doc; o `/update` só relê quando o `modifiedTime` muda).
6. `./brain render`.

## Quando é o agente que cadastra (dentro do `/dump`)

`./brain process add "<título>" --area <slug> --by agent --prov observado --source <artefato>` — `--source` é obrigatório. Só o que o texto afirma; campo sem base fica vazio (vira lacuna, e lacuna é informação).

Aposentar: só o dono, com motivo (`./brain process retire PROC-#### --reason "…" --by owner`).
