---
name: gmail
description: "Puxa emails via OAuth read-only (script gmail.py — mesma família do jira/github/slack): snapshot em RAW/inbox/ → /dump → digest. Noturno (digest do dia, conforme watch.yaml) ou sob demanda (/gmail [janela|filtro]). Nunca compõe/envia email."
---

# /gmail — email pelo canal, nunca direto

**Autenticação:** OAuth do Google via script (`scripts/connectors/google_auth.py`,
uma vez; depois o refresh token trabalha no `.env`). Guia: `docs/google-oauth.md`.
Escopo: **só `gmail.readonly`** — o script não contém nenhuma chamada de envio.

## A regra de ouro deste comando (o canal)

**Nenhuma leitura de email vira resposta direto.** O script grava o snapshot
em `RAW/inbox/gmail-…` primeiro; o `/dump` produz o artefato; só então você
responde/usa o conteúdo — citando o artefato. Email lido sem snapshot = memória
que o cérebro não ganhou.

## Modo noturno (digest do dia — padrão do /update)

`python3 scripts/connectors/gmail.py` (sem args = dia anterior):
- snapshot `gmail-daily-<ts>.md` — uma linha por email (de · assunto · snippet),
  com hash-vs-pull-anterior (idêntico = silêncio);
- `/dump` processa como dump de conector → digest.

## Modo sob demanda: `/gmail [janela|filtro]`

- `/gmail` → **7d** (execute `python3 scripts/connectors/gmail.py 7d`)
- `/gmail 30d` → janela · `/gmail from:ana` / `/gmail subject:orçamento` → filtro Gmail
- Executar `python3 scripts/connectors/gmail.py <arg>` → snapshot → `/dump` →
  responder com o digest CITANDO o artefato.

(Sem argumentos o script puxa o **dia anterior** — esse é o modo noturno; sob
demanda, passe sempre a janela explícita, default 7d.)

## Proibições e diagnóstico

- NUNCA compor/enviar email — constituição. Pedido de resposta → lembrar da constituição.
- Nunca imprimir tokens ou conteúdo do `.env`.
- Erro `invalid_grant` → app em "Testing" no GCP (refresh token de 7 dias):
  publique em produção e rode `google_auth.py` de novo (`docs/google-oauth.md`).
