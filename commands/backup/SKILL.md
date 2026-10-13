---
name: backup
description: "Backup do vault: zip → pasta do Google Drive (escopo drive.file — só os próprios brain-backup-*.zip) ou pasta local. Semanal no noturno ou sob demanda (/backup, /backup status). Restauração é procedimento manual guiado."
---

# /backup — a porta do zip

```
./brain backup                  # Drive, se GOOGLE_BACKUP_FOLDER_ID estiver no .env
./brain backup --local ~/Backups
./brain backup --status
```

Arquivos maiores que `[backup].max_file_mb` ficam de fora e entram no `BACKUP-MANIFEST.json` dentro do zip. Segredos (`config/.env`) moram fora do vault — não vão no zip.

Restauração: o dono baixa o zip, extrai sobre um `vault/` vazio, confere o manifesto, roda `./brain doctor` e `./brain render`. Você guia; não puxa o zip sozinho da nuvem sem ele pedir.

`/backup status` sem nenhum zip = avise, não finja que está protegido.
