# Memória para IA — Hindsight

O vault é a verdade. Hindsight é um índice que outra IA (e o `/ask`) usam
para achar mais rápido. Se o servidor cair, nada se perde.

## Dois bancos

| Banco (`config/brain.toml`) | Conteúdo | Extração |
|---|---|---|
| `brain-raw` | arquivos do RAW como estão (texto e binários até `max_file_mb`) | `chunks` — sem interpretação |
| `brain-mem` | artefatos do PROCESSED + uma página por ação/decisão/entrega/pessoa + PLANNING/PROFILE | `chunks` — páginas como estão |

`document_id` = caminho no vault (ou `ledger/A-####`). Toda lembrança aponta
para algo que você pode abrir.

Os dois bancos são disjuntos de propósito: `brain-raw` responde "o que foi dito"
(a letra da ata); `brain-mem` responde "o que concluímos + estado atual" (a página
`ledger/D-####` traz ID, dono, projeto e se a decisão foi substituída).

**Por que `chunks` nos dois.** Tudo que entra no `brain-mem` já foi escrito por
quem é melhor que o extrator: o agente (artefatos do `/dump`, com proveniência) ou
o CLI (páginas de entidade renderizadas do ledger). Re-extrair com um LLM local
pequeno só perde ou corrompe informação, e a busca (embeddings) não depende dele.
O `setup` aplica nos dois bancos `retain_extraction_mode=chunks`, `enable_auto_consolidation=false` e
`enable_observations=false`: o retain não chama o LLM, o sync é rápido e nada fica na fila de
consolidação. O custo é perder as observações cruzadas geradas pela consolidação — nenhum comando consome
`reflect`, e `/ask` e o hook ancoram em `recall` por `document_id`. Por isso os
avisos ligados ao LLM (`gave_up`, `failed_consolidation`, consolidação presa) ficam
raros. **Reversível:** voltar a `concise` = `patch_config` do `mem_bank` +
`./brain memory rebuild`; se um dia importar, use um extrator de verdade (nuvem, se a
política de chaves permitir), não um modelo local pequeno.

Ao atualizar uma instância existente: `./brain memory setup` (reaplica o modo) e
`./brain memory rebuild`.

## Embeddings: o que carregar na memória

Sem LLM no caminho, o único modelo que importa é o de embeddings. O padrão do Hindsight
(`bge-small-en-v1.5`) é só de inglês — fraco em pt-BR e es. Benchmark (24 perguntas parafraseadas,
14 pt + 10 es, CPU de 4 núcleos, sem outra carga):

| Modelo | Top-1 | MRR | RAM do modelo | Latência/trecho |
|---|---|---|---|---|
| `bge-small-en` (padrão) | 7/24 | 0,42 | ~450 MB | 30 ms |
| `multilingual-e5-small` (`onnx`, no Hindsight) | 19/24 | 0,85 | ~1,75 GB | 55 ms |
| `bge-m3` local (`local`, CPU do container) | 20/24 | 0,91 | ~4,4 GB | 400 ms |
| `bge-m3` no LM Studio (GGUF) | 20/24 | 0,90 | ~635 MB | ~76 ms |

Recomendado: **`bge-m3` servido pelo LM Studio** (melhor qualidade com o menor RAM; 1024 dims). Sem o
LM Studio, `multilingual-e5-small` via `HINDSIGHT_API_EMBEDDINGS_PROVIDER=onnx` perde pouco, mas
tem 384 dims (exige recriar os bancos) e limite de 512 tokens (o chunk padrão de 3000 caracteres
passa disso — reduza `retain_chunk_size`). Não carregue um LLM no LM Studio só para o Hindsight.

## Subir o servidor

### Recomendado: daemon local, sem Docker (LM Studio)

A receita completa e verificável está no **`setup.md`** (seção 4). Resumo:

```bash
uv tool install hindsight-embed          # daemon + PostgreSQL embutido (pg0)
export HINDSIGHT_API_EMBEDDINGS_PROVIDER=openai
export HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL=http://localhost:1234/v1
export HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL=text-embedding-bge-m3
export HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY=lm-studio   # placeholder; o LM Studio ignora
export HINDSIGHT_API_RERANKER_PROVIDER=rrf
export HINDSIGHT_API_SKIP_LLM_VERIFICATION=true            # sem LLM carregado ao subir
hindsight-embed configure
hindsight-embed daemon status             # sobe na primeira chamada
curl localhost:8888/health
```

Os bancos usam `chunks`, então o servidor não chama LLM: só o `bge-m3` fica carregado no
LM Studio, e o conteúdo do vault não sai da máquina. Se você reativar `concise`, configure
também `HINDSIGHT_API_LLM_*` (LM Studio ou nuvem) e remova o `SKIP_LLM_VERIFICATION`.

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
./brain memory recall "quem decidiu o ponto novo?"
```

O retain do Hindsight é assíncrono: o `sync` guarda o `operation_id` de cada documento em
`config/.memory-state.json` (`_ops`) e, no sync seguinte, consulta o servidor — documento cujo retain
falhou (ex.: timeout do LLM) sai do estado e é reenviado (até 3 vezes; depois `doctor` avisa).
`brain memory status` / `brain doctor --online` também avisam de retains falhos sem retain posterior
bem-sucedido e de operações em `processing` há mais de 2h.

`brain memory status` mostra ainda a **fila** de cada banco (retain/consolidação rodando ou na fila,
memórias aguardando consolidação). `fila: vazia — LLM livre` = o Hindsight não está usando o LLM nem
o embedding; `ocupada` = não descarregue os modelos nem pese a máquina agora. Memórias que desistiram
da consolidação (`failed_consolidation`) viram aviso. `--json` traz os números em `queue`.

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
