# Plano — Provedores da memória (LLM · embeddings · reranker) + Configurações

Executor: agente. Estágios com teste verde e commit cada; push pela porta 5 com "ok" do dono.

## Problema

O modo `full` pede provider/modelo de LLM no wizard, mas embeddings e reranker são fixos:
embeddings sempre locais (LM Studio bge-m3), reranker sempre `rrf`. O dono pode querer
embeddings e reranker de nuvem (ex.: Fireworks Qwen3-Embedding-8B / Qwen3-Reranker-8B —
o mesmo stack do Hermes dele), e rever a escolha depois sem re-instalar tudo. Falta uma
**seção de configuração** viva (não "setup uma vez"): CLI, TUI e painel.

## Decisões do dono (2026-11-07, não re-litigar)

1. **Wizard pergunta os três slots.** LLM (só full): provider → chave → modelos
   recomendados ou por operação. Embeddings e reranker (ambos os modos): provider →
   chave → recomendados (Qwen3 Embedding 8B / Qwen3 Reranker 8B na Fireworks) ou custom.
   Sem provider de embeddings = o local de hoje (LM Studio). Reranker default = off (`rrf`).
2. **Configuração é seção, não evento.** `brain setup --only memoria` re-roda com os
   valores atuais como default; `brain memory providers` lê/escreve sem wizard.
3. **TUI ganha face `[Configurações]`** (Execução · Portfólio · Configurações); a aba
   Saúde sai de Execução › 1 e mora lá.
4. **Doctor detecta quebra harness↔Hindsight** (config existe, servidor responde, banco
   existe, recall ping) e inconsistências de provedor (chave faltando, env não aplicado).

## Princípios

- **Segredo só no `.env`** (0600); `brain.toml` registra a *escolha* (provider/modelo),
  nunca chave. Nada de chave em log, view ou painel.
- **Egress é consentido na tela.** Qualquer provedor de nuvem (LLM, embeddings ou
  reranker) manda texto do vault para fora: o wizard diz isso e exige continuar; o
  `providers set` grava `[memory] cloud_embeddings/cloud_reranker` para o doctor narrar.
- **Recomendado ≠ obrigatório.** O menu traz curadoria (poucos provedores testáveis),
  `custom` cobre o resto via base_url compatível.
- **Troca de embeddings avisa rebuild.** Modelo/dimensão diferente = vetores antigos
  incompatíveis → o comando diz para rodar `brain memory rebuild`.

## Registro de provedores (providers.py)

| Slot | Provider | Env (HINDSIGHT_API_…) | Modelo recomendado |
|---|---|---|---|
| llm | `anthropic` | `LLM_PROVIDER/_MODEL/_API_KEY` + `RETAIN_LLM_MODEL`… | Haiku 5.5 extração+consolidação · Sonnet 5.5 mental models+reflect (cenário B) |
| llm | `openai`/`fireworks`/`zai`/`custom` | idem + `LLM_BASE_URL` | — |
| embeddings | `local` (default) | `EMBEDDINGS_PROVIDER=openai` + `_OPENAI_BASE_URL/_MODEL/_API_KEY` (LM Studio) | bge-m3 local, zero egress |
| embeddings | `fireworks` | idem, base_url api.fireworks.ai | `fireworks/qwen3-embedding-8b` @1536 |
| embeddings | `openai`/`cohere`/`custom` | `_OPENAI_*` / `_COHERE_*` | text-embedding-3-small / embed-multilingual-v3.0 |
| reranker | `off` (default) | `RERANKER_PROVIDER=rrf` | — (veredito 2026-11-07) |
| reranker | `fireworks` | `RERANKER_PROVIDER=litellm-sdk` + `_LITELLM_SDK_MODEL/_API_KEY/_API_BASE` | `fireworks_ai/fireworks/qwen3-reranker-8b` (top-50) |
| reranker | `cohere`/`zeroentropy`/`openrouter`/`custom` | `_COHERE_*` / `_ZEROENTROPY_*` / `_OPENROUTER_*` | rerank-v3.5 · zerank-2 |

`jina-mlx` fica FORA do menu (benchmark 2026-11-07: reprovado no gate de latência).

## Estágios

1. **providers.py + CLI** (`brain memory providers [show|set]`): registro, leitura
   (config+.env), apply (env+config+aviso rebuild), `--json`. Testes: set/show round-trip,
   chave nunca no config, off/local limpos.
2. **Wizard**: `_run_memoria` pergunta os três slots (recomendado/custom), usa
   providers.apply, sobe o compose com `--env-file`, egress dito em cada escolha de nuvem.
3. **Doctor**: por slot — provedor escolhido sem chave = erro; harness cablado sem
   config/servidor/banco/ping = erro com o comando que corrige; recall de validação.
4. **TUI**: face Configurações (Memória [Provedores, Harnesses] · Instância [Saúde]),
   Saúde sai de Execução › 1, sys-ops de memória migram, `external()` abre o wizard.
5. **Painel**: seção Configurações (stack atual + form `memory providers set`),
   ALLOWED ganha `memory providers`, assets rebuild.
6. **Docs + versão**: guides/memory.md (seção provedores), guides/setup.md, commands.md,
   user-guide, CHANGELOG, 2.9.0. AGENTS.md (registro de egresso estendido a
   embeddings/reranker de nuvem): diff proposto, gate do dono.

## Riscos / armadilhas

- **Compose**: `environment:` estático na base — virar `${VAR:-default}` e o embed também
  sobe com `--env-file config/.env` (padrão já provado no full). Teste: `docker compose config`.
- **Trocar embeddings sem rebuild** = recall silenciosamente pior (vetores de dimensão/
  treino diferente): o apply AVISA e o doctor relembra enquanto `memory-state` indicar
  docs sincronizados sob outro modelo (metadado `embeddings_model` no estado).
- **Cobertura de superfícies**: novo subcomando precisa de TUI+panel ou justificativa
  nos conjuntos do teste; teclas/abas movidas exigem sequências de navegação atualizadas.
- **jina-mlx no provider list do servidor** existe, mas o menu não oferece: gate de
  latência reprovado (plano memory-setups §4.2).

## Rollback

Cada estágio é additive (chaves novas com default = comportamento atual). Voltar = git
revert do estágio; `.env` não é tocado pelo revert. `providers set embeddings --local` e
`reranker --off` restauram o stack de hoje sem reinstalar nada.
