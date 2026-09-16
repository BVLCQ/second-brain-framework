# Backup do vault — guia de configuração (~3 min)

> O vault é cegado pro git (certo — contra leak) e por isso vive numa cópia
> única. Este backup é a outra metade da segurança: **contra perda**.
> Destino: uma pasta do SEU Google Drive. O mesmo OAuth do Gmail/Drive,
> com um escopo adicional mínimo.

## 1. Escopo adicional (uma linha)

Google Cloud Console → Auth Platform → Data Access → adicione ao lado dos
readonly existentes:

```
https://www.googleapis.com/auth/drive.file
```

`drive.file` = criar/apagar **apenas arquivos criados por este app**. Ele não
vê nem toca no resto do seu Drive — é a exceção de escrita mais estreita que
o Google oferece. (Sempre em **In production**, como o resto — ver
`guides/google-oauth.md`.)

## 2. Reautorizar (o token antigo não tem o escopo novo)

```bash
python3 scripts/connectors/google_auth.py
```

Authorize de novo (o app pede o escopo extra); cole o NOVO refresh token no
`config/.env` (substitui o anterior — o antigo continua válido só pros
escopos antigos; use sempre o novo).

## 3. A pasta de destino

1. Crie a pasta no Drive (ex.: `brain-backups`).
2. Da URL (`drive.google.com/drive/folders/<ID>`), copie o `<ID>`.
3. No `config/.env`:

```
GOOGLE_BACKUP_FOLDER_ID=<ID>
```

## 4. Rodar

```bash
python3 scripts/connectors/backup.py          # primeiro backup AGORA
python3 scripts/connectors/backup.py --status # conferir
```

Daí em diante: **domingo, no noturno** (já embutido no nightly-update.sh).
Retenção automática: 8 backups; o script só apaga arquivos `brain-backup-*.zip`
que ELE criou naquela pasta — nada mais.

## O que é protegido

`vault/` inteiro (zonas, índices, logs, reports). `config/.env` (segredos) e
`config/.state.json` NÃO vão — ficam fora do vault por construção. Se trocar
de máquina: reclone o framework + restaure o zip do vault + recrie o `.env`.

## Problemas comuns

- **`invalid_grant`** → app em Testing (7 dias) — publique, como no guia OAuth.
- **404 na pasta** → ID errado (use o da URL, não o nome da pasta).
- **Escopo negado no consent** → o passo 1 não foi salvo; refaça e reautorize.
