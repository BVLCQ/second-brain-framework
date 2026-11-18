---
name: slack
description: "Puxa mensagens do Slack sob demanda: /slack #canal [@user] [período] — fonte do watch usa a janela dela (auto = desde o último pull). Lê também as threads. Snapshots caem na inbox e são processados. Para ENVIAR mensagem, use /outbox — este comando só lê."
---

# /slack — ler um canal ou conversa

1. **Janela.** Fonte do `watch.toml`: `./brain watch since <key> --json` e use `since` / `epoch` como início da leitura
   (`window = "auto"` é "desde o último pull"; o cérebro calcula, você não). Leitura avulsa: o período que o dono pediu,
   padrão 7 dias.
2. **Histórico** do canal ou DM pelo MCP de leitura do Slack, do início da janela até agora.
   - Para fontes `kind = "slack-dm"` (DMs e DMs em grupo do dono): liste todas as DMs (`im`) e DMs em grupo (`mpim`) com atividade na janela — inclua mensagens recebidas **e** enviadas. Ignore qualquer usuário ou conversa listada em `exclude` (id de usuário, `@handle` ou id da conversa).
3. **Threads são parte da conversa — leia todas.** Para cada mensagem com respostas (`reply_count > 0`), leia a thread
   (`slack_read_thread`) e inclua as respostas. Não pare no primeiro nível.
4. **Resposta nova em thread antiga.** O histórico por janela não mostra uma resposta de hoje a um post de 3 dias atrás.
   Por isso releia também as threads cujo post inicial é dos últimos 7 dias e tem atividade, e inclua **só as respostas
   posteriores ao início da janela**, com o post inicial como contexto (`— thread de <data>, post inicial como contexto`).
5. **Formato** do snapshot (Markdown): cabeçalho `# Slack #canal (ID) — desde <since> (leitura <data>)`; depois, por
   mensagem, `## Autor — data hora (ts …) — thread com N respostas` e, quando houver, uma seção `### Respostas` com
   `- Autor — hora: texto`. Cite links e anexos como estão.
6. `./brain snapshot --key slack-<canal-ou-user> --prefix slack`. Em `kind = "slack-dm"`, grave **um snapshot por conversa ativa**: `./brain snapshot --key <key> --item <id-da-conversa> --name "<interlocutor>" --prefix slack --ext md`. Janela sem nada novo (nem em thread, ou nenhuma DM ativa) → `./brain snapshot --key <key> --empty` (conta como pull ok; **não** é falha). Conteúdo vazio por erro do MCP → `--fail "<erro>"`.
   - **Privacidade (`slack-dm`):** conteúdo de DM fica só no vault local (`RAW/.../slack/`) — nunca vai para `share`, `publish` ou `oppdrive` (em relatórios externos, cite no máximo dia + participantes).
7. `/dump` (tipo conector → change digest). Recibo: o que mudou, menções ao dono, decisões/ações extraídas.

**Enviar** é outra porta: `/outbox`. "Responde a fulano" → redija em `/outbox`, nunca `chat.postMessage` direto.
