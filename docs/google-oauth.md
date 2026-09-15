# Gmail + Drive via OAuth — guia de configuração

> Modelo: **scripts pull-only com OAuth**, igual Jira/GitHub/Slack. Nada de MCP,
> nada ativo durante suas sessões com o agente — os conectores rodam só no
> noturno ou sob demanda, custo zero de contexto. Escopos **somente leitura**
> (`gmail.readonly`, `drive.readonly`): sem escopo de escrita, o script
> fisicamente não consegue enviar email nem editar doc.

## 1. Projeto no Google Cloud (uma vez, ~5 min)

1. [console.cloud.google.com](https://console.cloud.google.com) → novo projeto
   (ex.: `second-brain`).
2. **APIs & Services → Library** → habilitar **Gmail API** e **Google Drive API**.
3. **OAuth consent screen** (Google Auth Platform → Branding):
   - User type **External** · app name `second-brain` · seu email nos contatos.
   - **Data Access → Add or Remove Scopes** → adicione APENAS:
     - `https://www.googleapis.com/auth/gmail.readonly`
     - `https://www.googleapis.com/auth/drive.readonly`
4. **Auth Platform → Clients → Create Client** → tipo **Desktop app** → criar.
   Copie **Client ID** e **Client Secret** (não precisa de redirect URI — o
   fluxo usa `localhost` efêmero).

## 2. Publicar em produção (o passo que quase todo mundo pula)

Consent screen → **Audience → Publishing status → Publish to production**.
App não-verificado tudo bem pra uso pessoal (aviso amarelo na primeira
autorização; irrelevante pra 1 usuário).

> **Por que importa:** app em *Testing* = refresh token expira em **7 dias** —
> toda semana morre com `invalid_grant`. Em *production* (mesmo não-verificado)
> o refresh token é de longo prazo.

## 3. Autorizar (uma vez, ~1 min)

```bash
# preencha GOOGLE_CLIENT_ID/SECRET no config/.env antes
python3 scripts/connectors/google_auth.py
```

Abre o navegador → você autoriza → o script imprime `GOOGLE_REFRESH_TOKEN=…`
no terminal → cole no `config/.env`. Pronto: noturno e `/gmail`, `/drive`
funcionam sem ninguém mexer em token nunca mais.

## 4. Ligar no cérebro

`config/watch.yaml` (instância):

```yaml
gmail:
  window: daily          # digest do dia anterior, noturno
gdocs:
  - id: "<idDoDoc>"      # id do doc (parte da URL do Drive)
    name: "dicionario-de-dados"
```

## Problemas comuns

- **`invalid_grant` após ~7 dias** → passo 2 não feito. Publique e rode
  `google_auth.py` de novo.
- **"Access blocked: app not verified"** → "Advanced → go to app (unsafe)"
  no consentimento (normal para apps pessoais).
- **Doc sem comentários no snapshot** → é PDF/arquivo comum no Drive? Só
  Google Docs/Sheets/Slidos exportam conteúdo + comentários.
- **Troca de conta** → rode `google_auth.py` de novo com a conta certa.
