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
| LM Studio | embeddings multilíngues (`bge-m3`) | `curl localhost:1234/v1/models` |
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

## 3. LM Studio (embeddings)

O brain não usa LLM local: os bancos do Hindsight guardam os trechos como estão
(`chunks`, sem extração nem consolidação), então o LM Studio só serve o modelo de
**embeddings** — o que torna a busca boa em pt-BR e es (o embedding padrão do Hindsight é só de
inglês; benchmark em `guides/memory.md`).

```bash
brew install --cask lm-studio
open -a "LM Studio"        # abre o app uma vez (exigência do CLI lms)
lms --help >/dev/null      # confirma o CLI
```

### 3.1 Modelo de embeddings

```bash
lms get bge-m3             # 1024 dims · multilíngue forte · ~635 MB em GGUF
```

### 3.2 Servidor local na porta 1234

```bash
lms server start
lms load text-embedding-bge-m3
```

O `lms daemon` (ver `lms daemon --help`) mantém o servidor vivo sem o app aberto
— recomendado. O identificador exato do modelo sai de `lms ls`.

**Chave de API:** LM Studio não exige chave. Se quiser exigir (Settings → Server),
defina uma e use-a em `HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY` (seção 4.2).

### 3.3 Verificação

```bash
curl -s http://localhost:1234/v1/models | head -c 400
curl -s http://localhost:1234/v1/embeddings -H 'Content-Type: application/json' -d '{
  "model": "text-embedding-bge-m3",
  "input": "responda só: OK"
}' | head -c 200
```

Esperado: o modelo na lista; um vetor de 1024 números em `data[0].embedding`.

## 4. Hindsight (memória semântica, sem Docker)

Daemon local com PostgreSQL embutido (pg0), só `127.0.0.1:8888`.

### 4.1 Instalação (uv — nunca pip)

```bash
uv tool install hindsight-embed
# prova imediata, sem instalar nada: uvx hindsight-embed@latest --help
```

### 4.2 Configuração — embeddings bge-m3 e sem LLM

`./brain memory setup` põe os bancos em `chunks`, sem consolidação nem observações: o Hindsight
não chama LLM. O que importa é o modelo de **embeddings** — aponte-o para o `bge-m3` do LM Studio
(o padrão embutido é só de inglês; `guides/memory.md`):

```bash
export HINDSIGHT_API_EMBEDDINGS_PROVIDER=openai
export HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL=http://localhost:1234/v1
export HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL=text-embedding-bge-m3
export HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY=lm-studio   # placeholder; o LM Studio ignora
export HINDSIGHT_API_RERANKER_PROVIDER=rrf                 # sem reranker neural
export HINDSIGHT_API_SKIP_LLM_VERIFICATION=true            # não carrega nenhum LLM ao subir
hindsight-embed configure
```

> O servidor ainda aceita configuração de LLM (`HINDSIGHT_API_LLM_*`), mas nada a usa; só
> preencha se reativar `concise` (extração por LLM) em `guides/memory.md`. Confira o que foi
> aceito em `~/.hindsight/embed` e nos logs do daemon.

Se aparecerem erros de MPS/XPC no macOS, os arquivos de config aceitam
`HINDSIGHT_API_EMBEDDINGS_LOCAL_FORCE_CPU=1` (só vale para embeddings locais).

### 4.3 Subir e verificar

```bash
hindsight-embed daemon status    # o primeiro comando sobe o daemon sozinho
sleep 5
curl -s http://127.0.0.1:8888/health     # esperado: database connected
tail -n 50 ~/.hindsight/daemon.log       # providers devem aparecer verificados
```

O daemon não desliga sozinho. Reinício de máquina: ele volta no primeiro uso,
ou crie um LaunchAgent que rode `hindsight-embed daemon status` no login.

### 4.4 Prova em português

```bash
hindsight-embed memory retain brain-mem "Decidimos congelar a compra do forno até o orçamento, na reunião com a Marina-demo"
sleep 90    # a extração é assíncrona
hindsight-embed memory recall brain-mem "o que foi decidido sobre o forno?"
```

Esperado: a resposta cita o fato. Se o recall em pt-BR vier fraco, confira se os
embeddings estão apontando para o `bge-m3` do LM Studio (seção 4.2).

## 5. Ligar a memória no brain

`config/brain.toml`:

```toml
[memory]
engine = "hindsight"
url = "http://localhost:8888"
```

```bash
./brain memory setup
./brain memory sync           # primeira carga: alguns minutos
./brain memory recall "quem decidiu congelar a compra do forno?"
./brain doctor --online       # deve ficar verde incluindo o servidor de memória
```

O noturno chama `sync` sozinho. Após `/dump` pesado, um `./brain memory sync`
manual mantém o índice fresco no mesmo dia.

## 6. Noturno

```bash
./brain schedule install --time 05:00
./brain schedule status
```

**Atenção:** Mac dormindo às 05:00 → o cron é pulado em silêncio (o macOS não
recupera jobs perdidos). O ritual mais confiável é manual: `./brain nightly`
logo ao abrir a máquina de manhã. Use os dois.

## 7. Claude Code

Os comandos (`/brief`, `/todo`, `/dump`, `/focus`…) já estão em
`.claude/commands/` — dentro da pasta do repo, estão disponíveis como slash
commands nativos. Primeira sessão: `/init`.

O MCP somente-leitura (`./brain mcp`) pode ser registrado no Claude Code para
perguntas de outras sessões:

```bash
claude mcp add segundo-cerebro -- ~/brain/brain mcp
```

## 8. Checklist final

```bash
python -m unittest tests.test_brain | tail -3   # OK
./brain doctor --online                          # verde, memória incluída
./brain render --open                            # painel abre
./brain memory recall "qualquer coisa"           # responde (mesmo que vazio)
```

## Problemas comuns

| Sintoma | Provável causa | Saída |
|---|---|---|
| `brain requer Python 3.11+` | PATH sem mise | seção 2, `mise doctor` |
| embeddings: `localhost:1234 não respondeu` | LM Studio parado ou sem o `bge-m3` | `lms server start` e `lms load text-embedding-bge-m3` |
| daemon não sobe | porta 8888 ocupada | `lsof -i :8888`, mate o processo ou mude de porta |
| recall fraco em pt-BR | embeddings embutidos (só inglês) | `bge-m3` no LM Studio (seção 4.2) |
| cron não rodou | Mac dormia | `./brain nightly` manual (seção 6) |

## Depois (não é hoje)

- **Google OAuth** (foco no calendário + backup no Drive): `guides/google-oauth.md`.
- **Fontes Slack/Gmail/Calendar**: conectores MCP no agente + `config/watch.toml`
  — `guides/manual.md` §Update.
