# setup.md — instalação completa do Segundo Cérebro em máquina nova

> **Para o agente (Claude Code):** este documento é executável. Rode cada seção
> na ordem, verifique a saída indicada **antes** de avançar e, se algo falhar,
> pare e resolva antes de continuar — não declare sucesso sem a verificação.
> Tudo no stack padrão (`embed`) é local: nenhuma chave de API externa é necessária.

> **Nota do `install.sh`:** o `install.sh` agora instala sozinho o que as seções
> 0–1 ensinam (git · Homebrew · mise · Python 3.12 · OrbStack/Docker) — silencioso
> e idempotente (plano `guides/plans/install-bootstrap.md`). Estas seções
> continuam valendo como **receita manual**: é o que o script imprime quando
> algo falha.

Alvo: macOS Apple Silicon, usuário com permissão de administrador, Homebrew
disponível (seção 1 cobre se não estiver). A máquina de referência é um
MacBook Pro M4 de 24 GB.

O stack final:

| Peça | O que é | Como verifica |
|---|---|---|
| Python 3.12 (mise) | runtime do `./brain` | `./brain doctor` |
| OrbStack / Docker | runtime de contêiner | `docker info` |
| LM Studio | embeddings multilíngues (`bge-m3`) | `curl -s http://localhost:1234/v1/models` |
| Hindsight (container via docker compose) | memória semântica do vault | `curl -s http://127.0.0.1:8888/health` |
| Noturno (LaunchAgent / launchd no macOS) | rotina noturna por instância | `./brain schedule status` |

---

## 0. Pre-flight

```bash
uname -m          # esperado: arm64
which brew        # se faltar, instalar Homebrew primeiro (abaixo)
df -h /           # ter ≥ 8 GB livres (modelos + imagem do container)
```

Se `brew` faltar:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
# depois siga a instrução final do instalador (eval "$(...brew shellenv)")
```

## 1. Toolchain: mise e git

```bash
brew install mise git
echo 'eval "$(mise activate zsh)"' >> ~/.zprofile   # se ainda não estiver
exec zsh
```

Verificação: `mise --version && git --version` — ambos imprimem versões.
(`uv` só entra se você optar pela alternativa legada sem Docker na seção 4.4.)

## 2. Este repo + smoke test

```bash
git clone <URL-do-repo> ~/brain   # ou a pasta escolhida
cd ~/brain
mise trust                        # autoriza o mise.toml do repo (o `install.sh` já faz isso sozinho)
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
./brain tui             # cockpit de terminal (`?` abre a ajuda do contexto)
```

O núcleo do brain não depende disso. Sem o extra, `./brain tui` explica como instalar.

## 3. LM Studio (embeddings)

No modo `embed` (padrão local), o brain não usa LLM: os bancos do Hindsight guardam
os trechos como estão (`chunks`, sem extração nem consolidação), então o LM Studio
só serve o modelo de **embeddings** — o que torna a busca boa em pt-BR e es (o
embedding embutido do Hindsight é só de inglês; benchmark em `guides/memory.md`).

```bash
brew install --cask lm-studio
open -a "LM Studio"        # abre o app uma vez (exigência do CLI lms)
lms --help >/dev/null      # confirma o CLI
```

### 3.1 Modelo de embeddings

O catálogo padrão do `lms` não resolve mais o apelido por nome, então puxe pela URL
completa (o `lms` registra o modelo como `text-embedding-bge-m3`):

```bash
lms get https://huggingface.co/gpustack/bge-m3-GGUF -y   # 1024 dims · multilíngue · ~635 MB em GGUF
```

### 3.2 Servidor local na porta 1234

```bash
lms server start
lms load text-embedding-bge-m3
```

O `lms daemon` (ver `lms daemon --help`) mantém o servidor vivo sem o app aberto
— recomendado. O identificador exato do modelo sai de `lms ls`.

**Chave de API:** LM Studio não exige chave. Se quiser exigir (Settings → Server),
defina uma e preencha `HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY` em `config/.env`.

### 3.3 Verificação

```bash
curl -s http://localhost:1234/v1/models | head -c 400
curl -s http://localhost:1234/v1/embeddings -H 'Content-Type: application/json' -d '{
  "model": "text-embedding-bge-m3",
  "input": "responda só: OK"
}' | head -c 200
```

Esperado: `text-embedding-bge-m3` na lista; um vetor de 1024 números em `data[0].embedding`.

## 4. Hindsight (memória semântica via container)

### 4.1 Runtime de container (OrbStack / Docker)

No macOS:

```bash
brew install --cask orbstack
open -a OrbStack
```

No Linux ou WSL2, instale e inicie o Docker Engine (`sudo systemctl start docker`).
Confirme antes de avançar:

```bash
docker info
```

### 4.2 Subir o container (modos embed e full)

O arquivo `services/compose.yaml` sobe o container `hindsight` com imagem pinada
por digest SHA-256 em `127.0.0.1:8888` (API) e `127.0.0.1:9999` (UI), alcançando
o LM Studio do host por `host.docker.internal:1234`. No modo `embed`, deixe o LM
Studio no ar com `text-embedding-bge-m3` antes do `up -d`.

**Modo `embed` (padrão local, sem LLM):**

```bash
docker compose -f services/compose.yaml up -d
```

**Modo `full` (extração com LLM na nuvem do dono — requer chaves em `config/.env` e confirmação explícita do dono):**

```bash
docker compose --env-file config/.env -f services/compose.yaml -f services/compose.full.yaml up -d
```

**Caminho guiado:** `./brain setup --only memoria` sobe o runtime, prepara o LM
Studio (no modo `embed` local) e levanta o container sozinho;
no CLI direto (com o container já de pé), use `./brain memory setup --mode embed`
(ou `--mode full --approval "ok"` com as chaves já em `config/.env`).

### 4.3 Verificar saúde

```bash
curl -s http://127.0.0.1:8888/health     # esperado: database connected
docker logs --tail 50 hindsight
```

### 4.4 Alternativa legada (sem Docker): daemon manual

> **Legado:** o código do brain e o watchdog (`services/watchdog.sh`) **não**
> gerenciam o daemon `hindsight-embed`. **Nunca** rode o daemon manual junto
> com o container — ambos disputam a porta `8888`. Use o caminho do container
> (§4.2) sempre que possível.

Se não puder usar OrbStack/Docker, instale via `uv` (`brew install uv`):

```bash
uv tool install hindsight-embed
export HINDSIGHT_API_EMBEDDINGS_PROVIDER=openai
export HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL=http://localhost:1234/v1
export HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL=text-embedding-bge-m3
export HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY=lm-studio   # placeholder; o LM Studio ignora
export HINDSIGHT_API_RERANKER_PROVIDER=rrf
export HINDSIGHT_API_SKIP_LLM_VERIFICATION=true
hindsight-embed configure
hindsight-embed daemon status
curl -s http://127.0.0.1:8888/health     # esperado: database connected
```

## 5. Ligar a memória no brain

Em `config/brain.toml` (o `./brain memory setup` grava isso para você):

```toml
[memory]
engine = "hindsight"
url = "http://localhost:8888"
# No modo full, o setup também grava extract = true e cloud_llm = true
```

Crie o banco, sincronize o vault e valide a busca em português:

```bash
./brain memory setup --mode embed     # ou via ./brain setup --only memoria
./brain memory sync                   # primeira carga: alguns minutos
./brain memory recall "quem decidiu congelar a compra do forno?"
./brain doctor --online               # deve ficar verde incluindo o servidor de memória
```

O noturno chama `sync` sozinho. Após `/dump` pesado, um `./brain memory sync`
manual mantém o índice fresco no mesmo dia.

## 6. Noturno (LaunchAgent por instância)

```bash
./brain schedule install --time 05:00
./brain schedule status
./brain schedule remove               # quando quiser desagendar esta instância
```

No macOS (com `launchctl`), o comando cria um **LaunchAgent (`launchd`) com
rótulo próprio por instância** (`StartCalendarInterval`), rodando dentro da
sessão do usuário e **recuperando automaticamente a execução perdida quando o
Mac acorda**. No Linux (sem `launchctl`), cai para `crontab` por instância.
Para rodar na hora, `./brain nightly` continua disponível manualmente.

## 7. Claude Code

Os comandos (`/brief`, `/todo`, `/dump`, `/focus`…) já estão em
`.claude/commands/` — dentro da pasta do repo, estão disponíveis como slash
commands nativos. Primeira sessão: `/init`.

O MCP somente-leitura (`./brain mcp`) pode ser registrado no Claude Code para
perguntas de outras sessões:

```bash
claude mcp add segundo-cerebro -- ~/brain/brain mcp
```

## 8. Checklist final — feche com o wizard

```bash
python -m unittest tests.test_brain | tail -3   # OK
./brain setup                                    # wizard: identidade, rotina, comando brain,
                                                 # TUI, noturno, memória (embed/full), portas
./brain doctor --online                          # verde, memória incluída
./brain render --open                            # painel abre
./brain memory recall "qualquer coisa"           # responde (mesmo que vazio)
```

O wizard (`guides/setup.md`) é idempotente e deriva o estado de cada passo do
`doctor` — rode-o ao final para o dono responder o que falta (identidade, modo de
memória, portas). Passos mecânicos você pode fechar com `./brain setup --yes
--only framework,comando,tui,noturno` e validar com `./brain doctor`. O passo `framework` confere que o clone
tem a regra de fetch do `origin` (sem ela o `git fetch` não atualiza o `origin/main` e o `update`/`doctor`
mentem) e instala o hook de varredura do push. Modo `full` de memória
(extração com a chave do dono): **sempre** o dono digita o "ok" no terminal dele —
nunca aceite o gate por ele.

## Problemas comuns

| Sintoma | Provável causa | Saída |
|---|---|---|
| `brain requer Python 3.11+` | PATH sem mise | seção 2, `mise doctor` |
| embeddings: `localhost:1234 não respondeu` | LM Studio parado ou sem o `bge-m3` | `lms server start` e `lms load text-embedding-bge-m3` |
| container Hindsight não sobe | OrbStack parado, LM Studio desligado antes do boot ou porta 8888 ocupada | `docker logs --tail 50 hindsight`, confirme `open -a OrbStack` e `lsof -i :8888` |
| recall fraco em pt-BR | embeddings embutidos (só inglês) | `bge-m3` no LM Studio (seção 3) |
| noturno não rodou | LaunchAgent não carregado ou agente deslogado | `./brain schedule status`, veja `vault/logs/cron.log` ou rode `./brain nightly` |

## Depois (não é hoje)

- **Google OAuth** (foco no calendário + backup no Drive): `guides/google-oauth.md`.
- **Fontes Slack/Gmail/Calendar**: conectores MCP no agente + `config/watch.toml`
  — `guides/user-guide.md` §4.
