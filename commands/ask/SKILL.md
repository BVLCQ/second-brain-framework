---
name: ask
description: "Pergunta livre ao cérebro ('o que sabemos sobre X?'). Responde sempre citando a fonte do artefato e a proveniência; 'não consta' é resposta válida."
---

# /ask — pergunta livre

1. `./brain search "<pergunta>"` — índice determinístico, sem LLM.
2. Se `[memory] engine = "hindsight"` e `brain doctor` não reclamar do servidor: `./brain memory recall "<pergunta>"` como atalho. Cada trecho precisa de `document_id` do vault; sem ele, é pista — confirme no arquivo.
3. Abra o artefato / evento citado. Desça ao RAW só pela letra exata (página, minuto).
4. Responda diferenciando proveniência: "a política diz" ≠ "alguém comentou numa reunião" ≠ "você declarou".
5. **Não consta** é resposta válida. Não complete com conhecimento de mundo se o vault não tem.

Cite caminho (`PROCESSED/…`, `ledger/A-####`, `PLANNING/goals.md`) em toda afirmação.
