---
name: backup
description: "Backup do vault: zip → pasta do Google Drive (script backup.py, OAuth com escopo drive.file — a única exceção de escrita, estreita e documentada). Semanal no noturno ou sob demanda (/backup, /backup status). Restauração é procedimento manual guiado."
---

# /backup — o cofre externo do vault

**É a única exceção de escrita da constituição — estreita por design:** o
escopo OAuth extra `drive.file` permite APENAS criar/apagar os próprios
arquivos `brain-backup-*.zip` dentro da pasta configurada. Nada mais do Drive
é lido ou tocado. O LLM nunca dispara backup por conta própria; gatilhos são
o noturno semanal e o comando do dono.

## Uso

- `/backup` → `python3 scripts/connectors/backup.py` — zipa o vault inteiro,
  envia pra pasta (`GOOGLE_BACKUP_FOLDER_ID` no `.env`), aplica retenção
  (mantém 8, apaga só `brain-backup-*.zip` dele mesmo).
- `/backup status` → `--status`: último backup + contagem (saúde de uma linha).

## Rotina

Noturno semanal (domingo, no `scripts/nightly-update.sh` — dia 0 da semana).
O vault inteiro é pequeno (texto); semanal é suficiente E suficiente pra
perder pouco. Se o dono pedir mais frequência, muda o dia — não invente
schedules paralelos.

## O que entra (e o que nunca entra)

- **Entra:** tudo de `vault/` (zonas, índices, logs, reports) — o cérebro inteiro.
- **Nunca entra:** `config/.env` e `config/.state.json` — moram FORA do vault
  por construção; segredo não tem ido pra backup JAMAIS. Se um dia aparecer
  arquivo de segredo dentro do vault, isso é defeito grave — escalar.

## Restauração (manual, guiada)

1. Baixar o zip mais recente da pasta do Drive.
2. Fechar sessões do agente. 3. Deszipar sobre o vault (substitui).
4. Rodar `/update` e conferir `generated-at:` das views. 5. Se o backup for
anterior a dias de uso, o que faltar está perdido — registrar a lacuna no
PLANNING/log (honestidade de memória vale pra desastres também).

## Diagnóstico

- `invalid_grant` → mesmo fix do OAuth (app em produção).
- 404 na pasta → `GOOGLE_BACKUP_FOLDER_ID` errado (pegue da URL …/folders/\<id\>).
- Pasta sem backups + `/backup status` antigo → incluir na próxima fala com o dono.
