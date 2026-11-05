# Plano — Hindsight como provedor de memória dos harnesses (e serviço único)

Executor: agente de código da instância. Regime dos outros planos: testes verdes
(`python3 -m unittest discover -s tests`), um commit local por etapa, nada do dono no
repo, `./brain upstream scan` antes de propor push. Este plano executa junto as
decisões 8–11 do `guides/plans/memory-setups.md` (banco único `brain`, Hindsight
1.2.0, colisão de nome/porta, serviço que também serve os harnesses).

## 0. Topologia alvo

Um serviço Hindsight por máquina; dois bancos, separados **por construção**:

```
Hindsight 1.2.0 (compose do repo OU servidor já existente adotado — decisão 10)
├── brain    ← o cérebro: derivado do vault (embed e full), rebuild apaga/recria
└── hermes   ← os agentes (Claude Code · Cursor · Codex · Hermes): memória de
               conversa/git dos harnesses — NUNCA tocada por `memory rebuild`,
               nunca vira fato do vault
```

- `brain` é o banco único dos dois modos (decisão 8 do plano da memória).
- `hermes` é o nome padrão do banco dos agentes (configurável). No pacote oficial
  dos coding agents, `bankId` fixo substitui o padrão por-repo `coding-agent::<repo>`;
  a provenância volta pelas tags/metadata de retain (abaixo).

## 1. Problema

1. O cérebro tem servidor Hindsight e o consome, mas **nunca atuou como provedor de
   memória** para os agentes de código do dono: o hook de recall não está registrado
   em lugar nenhum, Cursor/Codex não têm nada, e o Hermes foi cablado à mão fora do
   wizard. O wizard não pergunta quais harnesses a máquina usa.
2. O compose fixa 0.10.3 — versão que **contém** a regressão upstream #5738 (fixada
   na 1.1.0) e não tem nada do que o plano da memória depende (1.2.0).
3. Máquina que já roda outro Hindsight no :8888 (ex.: o serviço pessoal do dono):
   dois compose projects reivindicando `container_name: hindsight` — o do cérebro
   nunca sobe. Precisa de regra (decisão 10: adotar ou sobrepor portas).
4. Usuários existentes (0.10.x, dois bancos `brain-raw`/`brain-mem`) precisam de um
   caminho de atualização documentado e sem sustos até o alvo deste plano.

## 2. Princípios

1. **Um serviço por máquina.** Onde já houver Hindsight sadio, ele é **adotado**
   (`[memory].url` aponta pra ele); o banco `brain` nasce lá. Nunca dois containers
   brigando pelo mesmo nome/porta.
2. **Bancos separados por nome, não por disciplina.** `memory rebuild` só toca o que
   o `[memory]` nomeia; o banco dos agentes fica fora. Memória de conversa de agente
   não é fato do vault e não polui o `/ask`.
3. **Encanamento é do upstream.** Claude Code/Cursor/Codex são cablados pelo
   instalador oficial (`@vectorize-io/hindsight-coding-agents`) apontado ao nosso
   servidor — não reescrito por nós. Nosso hook segue registrado, em modo
   ledger-only (`BRAIN_RECALL_ROUTE=ledger`): oficial = memória semântica, nosso =
   fatos exatos do ledger, zero duplicação.
4. **Provenância no banco compartilhado.** Banco único de agente recebe
   `retainTags: ["project:{gitProject}", "harness:{harness}"]` e
   `retainMetadata: {repo: "{gitProject}"}` — todo documento carrega de onde veio;
   recall pode filtrar por projeto. Quem quiser o padrão por-repo do upstream
   (`coding-agent::<repo>`), basta remover o `bankId` do `~/.hindsight/coding-agent.json`.
5. **Verificar é perguntar.** Cada harness cablado termina com um **recall ping**
   contra o servidor (pergunta fixa, resposta qualquer); doctor avisa se o banco de
   um harness selecionado sumiu.
6. **Consentimento que não dá para automatizar fica na receita.** Plugin do Hermes
   exige clique de aprovação interativo: o wizard escreve o que pode, imprime o
   comando único que falta e verifica o resultado.

## 3. O que existe hoje (inventário verificado)

| Peça | Estado |
|---|---|
| Wizard passo 11 (Memória) | Configura o consumo PRÓPRIO do cérebro (`none/embed/full`, `[memory]`, bancos, compose). Zero noção de harness. |
| `services/hooks/recall_context.py` | Hook read-only (UserPromptSubmit) + rota ledger-only; nada o instala; `~/.claude/settings.json` pode nem existir. |
| Cursor / Codex | Nada no repo. |
| Hermes | Cablado à mão (`~/.hermes/hindsight/config.json`, `local_external → :8888`); wizard não sabe. |
| Instalador oficial | `npx @vectorize-io/hindsight-coding-agents install <harness> --server self-hosted --api-url <url>` — 3 hooks + MCP + skill companion; config única em `~/.hindsight/coding-agent.json` (camadas: defaults → env → arquivo). |
| Versão do servidor | `GET /version` → `{"api_version": …}` (existe desde antes da 1.2.0 — verificado ao vivo). |

## 4. Design

### 4.1 Wizard — sub-passo "Harnesses" no passo Memória

Só oferecido com `engine != "none"` (o servidor precisa existir; se `none`, oferecer
`embed` antes ou pular). Multi-seleção com detecção por PATH:
`Claude Code · Cursor CLI · Codex · Hermes`. Escolhas gravadas em `[memory]`:
`harness_bank = "hermes"` (padrão; perguntado só se o dono mudar) e
`harnesses = [...]` (o que foi cablado — doctor vigia esses).

### 4.2 Claude Code / Cursor CLI / Codex — instalador oficial

```
npx @vectorize-io/hindsight-coding-agents install <claude-code|cursor-cli|codex> \
    --server self-hosted --api-url <[memory].url>
```

Depois o wizard garante o `~/.hindsight/coding-agent.json` do dono (merge, sem
sobrescrever chaves estranhas):

```jsonc
{
  "serverMode": "self-hosted",
  "apiUrl": "<[memory].url>",
  "bankId": "hermes",                          // decisão: banco único de agente
  "retainTags": ["project:{gitProject}", "harness:{harness}"],
  "retainMetadata": { "repo": "{gitProject}" }
}
```

Nosso `recall_context.py` segue registrado ao lado (ledger-only). Verificação:
recall ping no banco `hermes`.

### 4.3 Hermes — config escrita pelo wizard + receita TTY

1. Escrever `~/.hermes/hindsight/config.json`: `local_external` → `[memory].url`,
   banco `hermes`.
2. `hermes config set memory.provider hindsight` (se o CLI do Hermes estiver no PATH).
3. Plugin (consentimento interativo — não automatizável): detectar a ausência e
   imprimir a linha única para o dono rodar; não falhar por isso.
4. Verificação: recall ping.

### 4.4 Fresnness no doctor/setup

`doctor` (e o passo Memória do wizard) comparam `GET /version` do servidor contra o
`releases/latest` do upstream (GitHub), com cache ≤1×/dia em
`FRESH/.update-check.json` — mesmo padrão do update-check do framework. Aviso é
informação ("atualização disponível: X → Y"), nunca bloqueio. Quem fixa a versão é o
compose por digest; o procedimento de bump (export → troca de digest → `up -d` →
re-audit R5) mora no `guides/memory.md`.

### 4.5 Guardrails do doctor

- Banco `hermes` (ou o `harness_bank` configurado) sumiu do servidor → ⚠.
- Harness listado em `harnesses` sem sinal de encanamento (ex.: `~/.claude/settings.json`
  sem hooks) → ⚠ informativo.
- Servidor antigo (fresnness) → ⚠ com o caminho de atualização.

### 4.6 Migração de usuários existentes (0.10.x → este plano)

Público: quem já roda o cérebro com Hindsight 0.10.x e bancos `brain-raw`/`brain-mem`.

1. **Atualizar o servidor** — export/backup dos bancos (`hindsight-admin export-bank`
   por banco; no embed é seguro até sem export), trocar o digest do compose para
   1.2.0, `up -d` (migração Alembic automática, forward-only; rollback = restaurar
   export ou rebuild), re-audit R5 das chaves de config.
2. **Consolidar os bancos do cérebro** — `[memory] bank = "brain"` (decisão 8) +
   `brain memory rebuild` (apaga `brain-raw`/`brain-mem` legados, cria `brain`,
   reenvia o vault; no embed custo US$ 0; no full re-paga extração — export antes).
3. **Escolher o setup** — `brain setup --only memoria`: embed (chunks, US$ 0) ou
   full (LLM com a chave do dono no `.env`). Trocar depois é a mesma porta
   (decisão 1 do plano da memória).
4. **Harnesses (opcional)** — `brain setup --only memoria` de novo, sub-passo
   Harnesses.

Tudo isso vira seção do `guides/memory.md` + entrada de CHANGELOG (o `brain update`
mostra o caminho).

## 5. Fases

### Fase 1 — Serviço único, versão e colisão

Compose fixa `1.2.0-slim` **por digest**; portas passam a aceitar override por env
(`HINDSIGHT_API_PORT`/`HINDSIGHT_UI_PORT`, default 8888/9999) para a máquina com
outro Hindsight; `guides/memory.md` ganha a regra adotar-ou-sobrepor (decisão 10) e
o procedimento de bump. Smoke ao vivo do container 1.2.0 novo: `/version`,
chaves do `NO_LLM_CONFIG`/`FULL_CONFIG` aceitas em banco rabisco (criado e apagado),
recall de resposta vazia. **Pronto quando:** smoke verde e suite verde.
**Rollback:** digest anterior de volta (bancos derivados se reconstroem).

### Fase 2 — Banco único `brain` (decisão 8)

`[memory] bank = "brain"` nos dois modos; `mem_bank`/`raw_bank` viram legados (lidos
por 1 versão, doctor avisa); `documents()`, `_banks()`, `setup()`, `rebuild()`
(recusa lixo: apaga os três nomes), `memory setup --mode`, CLI `recall`, wizard e
`config/brain.toml.example` acompanham; estado `.memory-state.json` migrou junto
(rebuild resolve). **Pronto quando:** suite verde + smoke em banco rabisco.
**Rollback:** config de volta aos nomes antigos + rebuild.

### Fase 3 — Fresnness

`doctor`/setup: `/version` vs `releases/latest` com cache diário (mesmo arquivo e
padrão do update-check). **Pronto quando:** teste com cache falso dos dois lados
(desatualizado/na versão) verde.

### Fase 4 — Harnesses

CLI `brain memory harness install <agent>…` + `verify` + sub-passo do wizard;
escreve `[memory] harnesses`/`harness_bank`; installer oficial para os três CLIs;
config do Hermes + receita TTY; recall ping; guardrails do doctor. Superfícies: CLI,
TUI (form do passo Memória), painel (formDialog do setup). **Pronto quando:** suite
verde + smoke do installer contra banco rabisco no servidor local (onde houver
node/npm). **Rollback:** `harness uninstall` remove encanamento; `[memory] harnesses = []`.

### Fase 5 — Migração, docs e release

`guides/memory.md` (topologia nova, bump de versão, migração §4.6), tabela do passo
11 do `setup-wizard.md`, AGENTS.md (linha do registro de egresso já cobre o full;
harnesses não mandam texto do vault a lugar nenhum), CHANGELOG + bump de versão
(ritual). **Pronto quando:** scan limpo, CHANGELOG humano.

## 6. Riscos

| Risco | Mitigação |
|---|---|
| Installer oficial muda flags/comportamento | Versão pinada no comando que o wizard imprime/executa (`npx @vectorize-io/hindsight-coding-agents@<v>`), `harness verify` é o detetor; falha degrada para receita impressa, não quebra o setup. |
| Banco único de agente mistura projetos | Tags/metadata de provenância por retain; recall filtra por `project:`; quem preferir por-repo remove o `bankId` (padrão upstream volta). |
| `npx` precisa de node/rede | Detecção por PATH antes de oferecer; sem node → receita impressa para depois. |
| Nome `hermes` num repo público | Nome é de software, não do dono; default configurável no wizard. |
| Servidor antigo sem `/version` | Trata como "versão desconhecida" (⚠ informativo), nunca erro. |
| Dois serviços na mesma máquina | Regra adotar-ou-sobrepor na Fase 1; doctor acusa `container_name` em conflito quando puder ver. |

## Decisões do dono (registradas 2026-11-05 — não re-litigar)

1. **Topologia: 1 serviço, 2 bancos** — `brain` (vault) + `hermes` (agentes), o
   último chamado "Hermes" por decisão do dono. Instâncias com `brain-raw`/`brain-mem`
   migram: um sai, o outro vira `brain` (decisão 8 do plano da memória).
2. **Todos os quatro harnesses** — Claude Code, Cursor, Codex e Hermes (sessão de
   2026-11-05), cablados pelo **instalador oficial** em modo self-hosted apontado ao
   nosso servidor; nosso hook segue em modo ledger-only.
3. **Banco de agente compartilhado** com proveniência por tags/metadata (não
   por-repo como o padrão upstream); reversível removendo o `bankId`.
4. **Hermes: wizard escreve a config** (config.json + memory.provider) e imprime a
   linha de consentimento do plugin; verificação por recall ping.
5. **Fresnness no doctor** (informação, nunca bloqueio) + procedimento de bump
   documentado; versão do servidor continua fixada por digest no compose.
6. **Migração de usuários existentes é parte da entrega** (§4.6), nas duas escolhas
   (embed/full), documentada em `guides/memory.md` e no CHANGELOG.
