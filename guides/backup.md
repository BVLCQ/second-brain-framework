# Backup do vault

Uma vez por semana (se `[backup] enabled = true`) ou quando você pede
`/backup`. O zip contém o `vault/` inteiro, menos arquivos maiores que
`[backup].max_file_mb` — esses entram só no `BACKUP-MANIFEST.json` (caminho,
tamanho, sha256), para você saber o que ficou de fora.

`config/.env` **não** está no vault. Não vai no zip. Guarde o client secret
onde você guarda senhas.

## Destino

- **Drive** (padrão): pasta `GOOGLE_BACKUP_FOLDER_ID`, escopo `drive.file`.
  Só cria/apaga `brain-backup-*.zip`. Upload em pedaços de 8 MB.
- **Local**: `./brain backup --local ~/Backups`

Mantém `[backup].keep` zips (os mais novos); o resto some.

## Restaurar

1. Baixe o zip. Confira o nome (`brain-backup-AAAAMMDD-HHMM.zip`).
2. Extraia sobre um `vault/` vazio da instância (não misture com um vault
   pela metade).
3. Leia `vault/BACKUP-MANIFEST.json` — se listar arquivos pulados, copie-os
   de outro lugar se ainda existirem.
4. `./brain doctor` e `./brain validate`.
5. `./brain render`.
6. Se usava Hindsight: `./brain memory rebuild`.

Não existe "restore" automático. O agente guia; você move o arquivo.
