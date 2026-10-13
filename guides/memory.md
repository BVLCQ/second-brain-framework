# Memória para IA — Hindsight

O vault é a verdade. Hindsight é um índice que outra IA (e o `/ask`) usam
para achar mais rápido. Se o servidor cair, nada se perde.

## Dois bancos

| Banco (`config/brain.toml`) | Conteúdo | Extração |
|---|---|---|
| `brain-raw` | arquivos do RAW como estão (texto e binários até `max_file_mb`) | `chunks` — sem interpretação |
| `brain-mem` | artefatos do PROCESSED + uma página por ação/decisão/entrega/pessoa + PLANNING/PROFILE | `concise` — fatos duráveis |

`document_id` = caminho no vault (ou `ledger/A-####`). Toda lembrança aponta
para algo que você pode abrir.

## Subir o servidor

### Recomendado: daemon local, sem Docker (LM Studio)

A receita completa e verificável está no **`setup.md`** (seção 5). Resumo:

```bash
uv tool install hindsight-embed          # daemon + PostgreSQL embutido (pg0)
export HINDSIGHT_API_LLM_PROVIDER=lmstudio
export HINDSIGHT_API_LLM_BASE_URL=http://localhost:1234/v1
export HINDSIGHT_API_LLM_MODEL=<id do `lms ls`>
export HINDSIGHT_API_LLM_API_KEY=lm-studio   # placeholder; o LM Studio ignora
hindsight-embed configure
hindsight-embed daemon status             # sobe na primeira chamada
curl localhost:8888/health
```

O LLM de extração roda no **LM Studio local** — conteúdo do vault não sai da
máquina. Embeddings e reranker usam os modelos locais embutidos do Hindsight
por padrão; se o recall em pt-BR ficar fraco, aponte os embeddings para um
modelo multilíngue do LM Studio (ex.: `bge-m3`, 1024 dims) via
`HINDSIGHT_API_EMBEDDINGS_PROVIDER=openai` +
`HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL=http://localhost:1234/v1`.

### Alternativa: API Service (Docker) com nuvem

Para uma instância que pode sair da máquina, siga o
[Hindsight](https://github.com/vectorize-io/hindsight) (Docker ou binário) e
configure lá o provedor de nuvem (Fireworks, OpenAI, Anthropic…). URL padrão:
`http://localhost:8888`.

Se o servidor exigir token: `HINDSIGHT_API_TOKEN` no `config/.env`.

## Ligar nesta instância

```
# config/brain.toml
[memory]
engine = "hindsight"
url = "http://localhost:8888"
```

```
./brain memory setup
./brain memory sync          # incremental; pode --limit 50 --dry-run
./brain memory status
./brain memory recall "quem decidiu congelar o agente?"
```

O noturno chama `sync` sozinho. Após um `/dump` pesado, rode `./brain memory
sync` para o índice ficar fresco no mesmo dia. `rebuild` apaga os dois bancos
e reconstrói — use quando mudar o mission ou suspeitar de lixo.

## O que NÃO vai

- inbox (ainda não processada)
- arquivos maiores que `max_file_mb` (aparecem no doctor como "grandes")
- `config/.env` (nem está no vault)

## Sem Hindsight

`engine = "none"` (padrão). `/ask` usa `./brain search` → artefato → RAW.
O MCP somente-leitura (`./brain mcp`) também funciona sem memória.
