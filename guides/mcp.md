# MCP somente-leitura — outras IAs no mesmo cérebro

```json
{
  "command": "/home/VOCÊ/brain-v2/brain",
  "args": ["mcp"]
}
```

Stdio, JSON-RPC. Nenhuma ferramenta escreve. Cada chamada relê o ledger.

| Ferramenta | Para quê |
|---|---|
| `brain_overview` | goals, saúde, agenda 7d, o que aguarda você |
| `brain_search` | busca sem LLM |
| `brain_project` | página de um `P#` |
| `brain_person` | por nome/alias/e-mail |
| `brain_decisions` | filtro por projeto/pessoa/data |
| `brain_actions` | `mine` / `waiting` / `watching` |
| `brain_timeline` | passado + prazos |
| `brain_wins` | conquistas por semana |
| `brain_read` | arquivo de texto do vault (caminho relativo) |

A IA cliente deve citar `source_label` / caminho e a proveniência. "Não
consta" é resposta válida. Para escrever (ações, mensagens), ela usa o
agente **desta** instância, não este servidor.

`openWorldHint: false` — o servidor não sai do vault.
