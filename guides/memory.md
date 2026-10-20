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
Com `chunks`, o retain não chama o LLM: sync rápido, sem consolidação. O custo é
perder as observações cruzadas geradas pela consolidação — nenhum comando consome
`reflect`, e `/ask` e o hook ancoram em `recall` por `document_id`. Por isso os
avisos ligados ao LLM (`gave_up`, `failed_consolidation`, consolidação presa) ficam
raros. **Reversível:** voltar a `concise` = `patch_config` do `mem_bank` +
`./brain memory rebuild`; se um dia importar, use um extrator de verdade (nuvem, se a
política de chaves permitir), não um modelo local pequeno.

Ao atualizar uma instância existente: `./brain memory setup` (reaplica o modo) e
`./brain memory rebuild`.

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

O LLM é só configuração do servidor (os bancos usam `chunks`, sem extração); se
você reativar `concise`, ele roda no **LM Studio local** — conteúdo do vault não sai da
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
