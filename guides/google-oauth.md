# OAuth Google — as duas portas de escrita

Leituras de Gmail, Drive e Calendar passam pelos **MCPs do seu agente**.
Este repo só pede OAuth para o que o CLI **escreve**:

| Escopo | Porta | O que pode |
|---|---|---|
| `calendar.events.owned` | foco | criar/apagar **somente** eventos com `extendedProperties.private.brain_focus=1` |
| `drive.file` | backup | criar/apagar **somente** os próprios `brain-backup-*.zip` na pasta configurada |

Nada de `gmail.readonly`, `drive.readonly` ou `calendar.readonly` aqui.
Se um dia aparecer outro escopo neste arquivo, é violação.

## Uma vez

1. Google Cloud Console → projeto seu → OAuth client tipo **Desktop app**.
2. Tela de consentimento: app em **Testing**, você como test user. (App em
   Testing expira o refresh token em 7 dias. Quando estiver estável,
   publique em produção — senão o domingo quebra.)
3. Cole em `config/.env`:

```
GOOGLE_CLIENT_ID=….apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=…
```

4. Na raiz da instância: `python3 scripts/google_auth.py`
5. Autorize no navegador. O script imprime o refresh token **uma vez** no
   terminal. Cole:

```
GOOGLE_REFRESH_TOKEN=…
GOOGLE_BACKUP_FOLDER_ID=…   # só se for usar backup no Drive
```

6. `chmod 600 config/.env`
7. Foco: em `config/brain.toml`, `[focus] mode = "google"`.
8. `./brain doctor --online` — calendário some da lista de erros.

## O que o CLI faz com o token

- Troca o refresh por access (nunca loga o valor).
- Calendar: `insert` com a marca; `get` + checagem da marca antes de `delete`.
  Evento sem marca → recusa, não apaga.
- Drive: upload resumível do zip; lista só arquivos `brain-backup-*` na
  pasta; apaga os que passam de `[backup].keep`.

Conta sem Google Workspace: o Calendar pode recusar `eventType=focusTime`.
O CLI cai para evento opaco comum, com a mesma marca.

## Reautorizar

`invalid_grant` = token morto. Rode `scripts/google_auth.py` de novo.
Não commite o `.env`. Não cole o token no chat.
