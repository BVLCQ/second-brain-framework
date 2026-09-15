---
name: update
description: "O motor completo: roda os conectores (conforme config/watch.yaml), processa a inbox (/dump) e regenera TODAS as views de FRESH. É o que o cron noturno executa; use também sob demanda quando o dono pedir atualização geral."
---

# /update — o motor completo

## Sequência

1. **Conectores** (se `config/.env` + `config/watch.yaml` existirem): executar
   `scripts/connectors/` na ordem — jira, github, slack, gmail, gdrive. Cada um
   escreve snapshots em `vault/RAW/inbox/` (prefixo da fonte). Conector ausente ou
   sem credencial: pular com 1 linha de aviso, não abortar o resto.
2. **`/dump`** — processar toda a inbox (idempotente por construção).
3. **Regenerar TODAS as views de FRESH**: daily-brief, week, open-actions,
   projects, stakeholders, live-items. Cada uma com `generated-at:` + `fontes:`.
   Views são reescritas inteiras — nada de patch incremental.

`live-items.md` (deriva de `_indices/live-items-index.md` + `config/watch.yaml`):
uma linha por item do registro — última mudança, idade, nº de snapshots; sem
mudança desde o estado inicial = "estável". **Vigência:** item presente na
watch.yaml = vigiado; item do registro que NÃO está mais na watch.yaml =
"arquivado (não vigiado)" — última linha histórica, sem idade corrente. Item
estável há >60d ganha nota: "considerar tirar da watchlist?" (sugestão, não
ação — a curadoria da watchlist é do dono, sem gate).

## Reporte (≤10 linhas)

```
⚙ UPDATE — <data hora>
  conectores: jira 3 novidades · github 2 · slack 1 · (gmail: sem credencial)
  dump: 6 itens processados (0 duplicados) · inbox: 0 restantes
  views regeneradas: 5 · duração: ~2min
```

## Regras

- Rodar 2× = zero duplicatas (idempotência de conectores por hash + dump por
  artefato). Se não for o que aconteceu, reportar o defeito.
- Erro em UMA fonte não derruba as outras — isolar, avisar, seguir.
- Sem `.env`/`watch.yaml`: pular etapa 1 em silêncio (cérebro manual é válido).
- Este comando NÃO mexe em PLANNING (gate) e NUNCA em ferramentas externas
  além de LER via conectores.
