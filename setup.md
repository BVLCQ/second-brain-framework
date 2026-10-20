# setup.md — instalação completa do Segundo Cérebro em máquina nova

> **Para o agente (Claude Code):** este documento é executável. Rode cada seção
> na ordem, verifique a saída indicada **antes** de avançar e, se algo falhar,
> pare e resolva antes de continuar — não declare sucesso sem a verificação.
> Tudo aqui é local: nenhuma chave de API externa é necessária.

Alvo: macOS Apple Silicon, usuário com permissão de administrador, Homebrew
disponível (seção 1 cobre se não estiver). A máquina de referência é um
MacBook Pro M4 de 24 GB.

O stack final:

| Peça | O que é | Como verifica |
|---|---|---|
| Python 3.12 (mise) | runtime do `./brain` | `./brain doctor` |
| LM Studio | modelos locais (extração + embeddings) | `curl localhost:1234/v1/models` |
| Hindsight (daemon local) | memória semântica do vault | `curl localhost:8888/health` |
| crontab | noturno às 05:00 | `./brain schedule status` |

---

## 0. Pre-flight

```bash
uname -m          # esperado: arm64
which brew        # se faltar, instalar Homebrew primeiro (abaixo)
df -h /           # ter ≥ 8 GB livres (modelos + Postgres embutido)
```

Se `brew` faltar:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
# depois siga a instrução final do instalador (eval "$(...brew shellenv)")
```

## 1. Toolchain: mise, uv, git

```bash
brew install mise uv
echo 'eval "$(mise activate zsh)"' >> ~/.zprofile   # se ainda não estiver
exec zsh
```

Verificação: `mise --version && uv --version` — ambos imprimem versões.

## 2. Este repo + smoke test

```bash
git clone <URL-do-repo> ~/brain   # ou a pasta escolhida
cd ~/brain
mise trust                        # autoriza o mise.toml do repo
mise install                      # baixa o Python 3.12 do mise.toml
./brain doctor                    # deve responder sem erro de versão
python -m unittest tests.test_brain | tail -3   # esperado: OK
./brain demo --dir /tmp/brain-demo --open       # painel abre no navegador
```

Se `./brain doctor` reclamar de Python: `which python3` e `python3 --version`
precisam apontar para o mise (3.12). Rode `mise exec -- ./brain doctor` como
diagnóstico — se funcionar, o problema é o PATH do shell (revise a seção 1).

### 2.1 TUI (opcional)

```bash
./brain tui --setup     # cria .venv-tui com o Textual (versões e hashes travados)
./brain tui             # cockpit de terminal; guia: guides/tui-mockup.html
```

O núcleo do brain não depende disso. Sem o extra, `./brain tui` explica como instalar.

## 3. LM Studio (modelos locais)

```bash
brew install --cask lm-studio
open -a "LM Studio"        # abre o app uma vez (exigência do CLI lms)
lms --help >/dev/null      # confirma o CLI
```

### 3.1 Modelo de extração (chat)

O extrator precisa de um modelo de instrução pequeno, bom em JSON e em
português. Recomendado para 24 GB:

```bash
lms get qwen3-4b-2507      # ~2.5 GB (4-bit) · ~100 tok/s no M4 · multilíngue sólido
```

Se a busca devolver mais de uma opção, escolha a variante **Instruct 4-bit/MLX**.
Alternativa conhecida: `gemma-4-e4b`. **Não** suba para 27B+ — aperta a RAM
com tudo aberto e o ganho para extração não compensa.

### 3.2 Modelo de embeddings (para o Hindsight)

O Hindsight traz embeddings locais embutidos (extras `local-ml`) — tente com eles
primeiro. Se a qualidade em português decepcionar (verifique em 5.4), baixe um
multilíngue dedicado e aponte o Hindsight para ele:

```bash
lms get bge-m3             # 1024 dims · multilíngue forte
```

### 3.3 Servidor local na porta 1234

```bash
lms server start
lms load qwen/qwen3-4b-2507 --context-length 8192
```

O `lms daemon` (ver `lms daemon --help`) mantém o servidor vivo sem o app aberto
— recomendado. O identificador exato do modelo sai de `lms ls`; use-o em 4.1.

**Chave de API:** LM Studio não exige chave. Se quiser exigir (Settings → Server),
defina uma, exporte `LMSTUDIO_API_KEY` no `~/.zprofile` e ajuste
`api_key_env = "LMSTUDIO_API_KEY"` em 4.1.

### 3.4 Verificação

```bash
curl -s http://localhost:1234/v1/models | head -c 400
curl -s http://localhost:1234/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model": "<id do lms ls>",
  "messages": [{"role":"user","content":"responda só: OK"}],
  "max_tokens": 10
}'
```

Esperado: lista de modelos; resposta com `"OK"` em `choices[0].message.content`.

## 4. Extrator do brain

### 4.1 Configuração — `config/brain.toml`

```toml
[extractor]
enabled = true
base_url = "http://localhost:1234/v1"
model = "qwen/qwen3-4b-2507"    # o id exato de `lms ls`
api_key_env = ""                # ou "LMSTUDIO_API_KEY", se você ativou chave
```

### 4.2 Prova de fogo (ponta a ponta, sem tocar no vault real)

```bash
./brain extract --selftest
```

Esperado: o selftest cria um vault de demo temporário, extrai de uma reunião
fictícia com o modelo local e mostra os eventos **validados** contra o
livro-razão (`propostos: N` com `✓`/`✗` por item). Se o modelo não achar
eventos num texto com eventos óbvios, teste um modelo maior — mas 4B costuma
bastar.

Uso real depois: `./brain extract vault/RAW/<ano>/<mês>/<arquivo>` (rascunho
revisável) e `--record` para gravar só o que passou na validação.

## 5. Hindsight (memória semântica, sem Docker)

Daemon local com PostgreSQL embutido (pg0), só `127.0.0.1:8888`.

### 5.1 Instalação (uv — nunca pip)

```bash
uv tool install hindsight-embed
# prova imediata, sem instalar nada: uvx hindsight-embed@latest --help
```

### 5.2 Configuração — LLM no LM Studio

Os bancos do brain usam `retain_extraction_mode = chunks` (aplicado por `./brain memory setup`):
o retain não chama o LLM; ele só entra se você voltar a `concise`. Configure-o mesmo assim.

```bash
export HINDSIGHT_API_LLM_PROVIDER=lmstudio
export HINDSIGHT_API_LLM_BASE_URL=http://localhost:1234/v1
export HINDSIGHT_API_LLM_MODEL=<id do lms ls>      # mesmo da seção 4
export HINDSIGHT_API_LLM_API_KEY=lm-studio          # placeholder; o LM Studio ignora
hindsight-embed configure
```

> Se a versão instalada não reconhecer o provider `lmstudio`, use o padrão
> OpenAI-compatible: `HINDSIGHT_API_LLM_PROVIDER=openai` +
> `HINDSIGHT_API_LLM_OPENAI_BASE_URL=http://localhost:1234/v1`. Confira o que
> foi aceito em `~/.hindsight/embed` e nos logs do daemon.

Embeddings e reranker: deixe os **locais embutidos** do Hindsight (padrão).
Se aparecerem erros de MPS/XPC no macOS, os arquivos de config aceitam
`HINDSIGHT_API_EMBEDDINGS_LOCAL_FORCE_CPU=1` e
`HINDSIGHT_API_RERANKER_LOCAL_FORCE_CPU=1`.

### 5.3 Subir e verificar

```bash
hindsight-embed daemon status    # o primeiro comando sobe o daemon sozinho
sleep 5
curl -s http://127.0.0.1:8888/health     # esperado: database connected
tail -n 50 ~/.hindsight/daemon.log       # providers devem aparecer verificados
```

O daemon não desliga sozinho. Reinício de máquina: ele volta no primeiro uso,
ou crie um LaunchAgent que rode `hindsight-embed daemon status` no login.

### 5.4 Prova em português

```bash
hindsight-embed memory retain brain-mem "Decidimos congelar o pipeline até o diagnóstico, na reunião com a Ana"
sleep 90    # a extração é assíncrona
hindsight-embed memory recall brain-mem "o que foi decidido sobre o pipeline?"
```

Esperado: a resposta cita o fato. Se o recall em pt-BR vier fraco, é o sinal
para trocar os embeddings embutidos pelo `bge-m3` do LM Studio (seção 3.2).

## 6. Ligar a memória no brain

`config/brain.toml`:

```toml
[memory]
engine = "hindsight"
url = "http://localhost:8888"
```

```bash
./brain memory setup
./brain memory sync           # primeira carga: alguns minutos
./brain memory recall "quem decidiu congelar o pipeline?"
./brain doctor --online       # deve ficar verde incluindo o servidor de memória
```

O noturno chama `sync` sozinho. Após `/dump` pesado, um `./brain memory sync`
manual mantém o índice fresco no mesmo dia.

## 7. Noturno

```bash
./brain schedule install --time 05:00
./brain schedule status
```

**Atenção:** Mac dormindo às 05:00 → o cron é pulado em silêncio (o macOS não
recupera jobs perdidos). O ritual mais confiável é manual: `./brain nightly`
logo ao abrir a máquina de manhã. Use os dois.

## 8. Claude Code

Os comandos (`/brief`, `/todo`, `/dump`, `/focus`…) já estão em
`.claude/commands/` — dentro da pasta do repo, estão disponíveis como slash
commands nativos. Primeira sessão: `/init`.

O MCP somente-leitura (`./brain mcp`) pode ser registrado no Claude Code para
perguntas de outras sessões:

```bash
claude mcp add segundo-cerebro -- ~/brain/brain mcp
```

## 9. Checklist final

```bash
python -m unittest tests.test_brain | tail -3   # OK
./brain doctor --online                          # verde, memória incluída
./brain extract --selftest                       # funil ponta a ponta
./brain render --open                            # painel abre
./brain memory recall "qualquer coisa"           # responde (mesmo que vazio)
```

## Problemas comuns

| Sintoma | Provável causa | Saída |
|---|---|---|
| `brain requer Python 3.11+` | PATH sem mise | seção 2, `mise doctor` |
| extrator: `localhost:1234 não respondeu` | LM Studio parado | `lms server start` |
| extrator: `model vazio` | `lms ls` para o id certo no brain.toml | seção 4.1 |
| daemon não sobe | porta 8888 ocupada | `lsof -i :8888`, mate o processo ou mude de porta |
| recall fraco em pt-BR | embeddings embutidos | `bge-m3` no LM Studio (seção 5.4) |
| cron não rodou | Mac dormia | `./brain nightly` manual (seção 7) |

## Depois (não é hoje)

- **Google OAuth** (foco no calendário + backup no Drive): `guides/google-oauth.md`.
- **Fontes Slack/Gmail/Calendar**: conectores MCP no agente + `config/watch.toml`
  — `guides/manual.md` §Update.
