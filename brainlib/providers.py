"""Provedores da memória — LLM · embeddings · reranker.

Escolha do dono, gravada em três lugares coerentes:
  • config/.env  — o segredo e a "wire" (HINDSIGHT_API_*) que o compose lê (nunca volta em output);
  • [memory]     — a ESCOLHA (provedor/modelo) para status, painel e doctor: llm_provider,
                   embeddings_provider, reranker_provider… nunca chave;
  • compose      — sobe com --env-file config/.env; a base interpola ${VAR:-default}.

Curadoria: poucos provedores testáveis por slot + `custom` via base_url compatível.
`jina-mlx` fica fora do menu — benchmark 2026-11-07 reprovou no gate de latência (§4.2 do
plano da memória). Reranker de nuvem e embeddings de nuvem mandam texto do vault para fora:
o wizard diz isso na tela e o doctor narra enquanto ativos.
"""
from __future__ import annotations

import json
import subprocess
import time

from . import config, util

SLOTS = ("llm", "embeddings", "reranker", "decision")

# Rótulo curto de cada slot — fonte ÚNICA para TUI (store) e CLI (icons): lista que espelha
# registro na mão vive do drift (o slot decisão enterrou o painel de provedores da TUI).
SLOT_LABELS = {"llm": "LLM (extração/consolidação/mental models)", "embeddings": "Embeddings",
               "reranker": "Reranker", "decision": "Decisão (System-1, opcional — corta ~40% das chamadas do LLM)"}

# LLM por operação (cenário B do plano da memória): barato no alto volume, maior na síntese.
LLM_OPS = (("retain", "RETAIN_LLM_MODEL"), ("consolidation", "CONSOLIDATION_LLM_MODEL"),
           ("mental_models", "MENTAL_MODEL_REFRESH_LLM_MODEL"), ("reflect", "REFLECT_LLM_MODEL"),
           ("default", "LLM_MODEL"))
# Rótulo de cada operação — a tela Memória do painel lê daqui (nada de lista à mão no JS). `default` é o campo
# Modelo: vale para toda operação sem modelo próprio.
LLM_OP_LABELS = {"retain": "retain — extração de fatos", "consolidation": "consolidação",
                 "mental_models": "mental models", "reflect": "reflect", "default": "padrão — demais operações"}

_EMB = "HINDSIGHT_API_EMBEDDINGS_"
_RER = "HINDSIGHT_API_RERANKER_"
_SUB_NOTE = "Custo incluído no plano, sujeito ao limite de taxa da assinatura."

LOCAL_LLM_BLOCKED = frozenset({"lmstudio", "ollama", "llama.cpp", "local"})

# Fluxos de autenticação que o Brain consegue DIRIGIR (provedores de assinatura do slot LLM):
#   claude-token → CLI `claude` na máquina: `claude setup-token` gera o token de longo prazo
#                  (caminho "server-held token" documentado do Hindsight) que o Brain grava
#                  no config/.env — sobrevive a recreate do container.
#   xai-device   → device-code DENTRO do container (sem callback de navegador): o login
#                  escreve ~/.hindsight/xai_oauth.json no volume hindsight-auth e o servidor
#                  renova o token sozinho a cada uso.
# Vazio = fluxo manual nesta instalação: o setup_hint e o auth_command carregam o caminho exato.
AUTH_FLOWS = {"claude-code": "claude-token", "xai-oauth": "xai-device"}

DOCKER_AUTH_SUFFIX = {
    "guided": "",
    "manual": "login manual no servidor",
    "unavailable": "indisponível no Docker",
}


def derive_label(entry: dict) -> str:
    """Deriva o rótulo exibido no menu a partir de `docker_auth` e `weak_default` (sem cópia manual)."""
    base = entry.get("base_label") or entry.get("label", "")
    parts: list[str] = []
    da = entry.get("docker_auth", "")
    if da and DOCKER_AUTH_SUFFIX.get(da):
        parts.append(DOCKER_AUTH_SUFFIX[da])
    if entry.get("weak_default"):
        parts.append("modelo padrão fraco para memória")
    if not parts:
        return base
    suffix = " · ".join(parts)
    return f"{base} — {suffix}" if suffix not in base else base

# Modelo default de cada provedor no SERVIDOR PINADO (Hindsight 1.3.0-slim, digest do services/compose.yaml) —
# sondado ao vivo da imagem (a tabela mora em hindsight_api.config.PROVIDER_DEFAULT_MODELS). O que o registro do
# Brain cura TEM PRECEDÊNCIA sobre esta tabela (é gravado explícito no .env) e, nos provedores de laboratório
# (Claude, GPT, Grok, Gemini), acompanha o mais novo da mesma linha (models_catalog).
SERVER_DEFAULT_MODELS = {
    "openai": "gpt-5-nano",
    "anthropic": "claude-haiku-5-5",
    "gemini": "gemini-3.8-flash",
    "zai": "glm-5.3-flash",
    "fireworks": "accounts/fireworks/models/deepseek-v4-flash",
    "openrouter": "qwen/qwen3.5-9b",
    "litellm": "gpt-5-nano",
    "openai-codex": "gpt-5.6-luna",
    "chatgpt": "gpt-6-luna",
    "claude-code": "claude-sonnet-5-5",
    "cursor": "auto",
    "github-copilot": "gpt-5.6-terra",
    "nous": "deepseek/deepseek-v4-flash",
    "xai-oauth": "grok-4.5",
}


def default_model(provider: str) -> str:
    """SEMENTE do modelo que o Brain aplica quando o dono deixa o campo em branco: a cura do registro
    (model/models.default) vence; senão, o default do servidor pinado; senão, vazio. O efetivo é o mais novo da
    linha da semente (`seed_models` + `models_catalog.resolve`)."""
    p = PROVIDERS["llm"].get(provider) or {}
    if p.get("model"):
        return p["model"]
    if p.get("models"):
        return p["models"].get("default", "")
    return SERVER_DEFAULT_MODELS.get(provider, "")


def seed_models(provider: str) -> dict[str, str]:
    """Sementes por operação do provedor: o cenário do registro (`models`) ou só o `default`."""
    p = PROVIDERS["llm"].get(provider) or {}
    if p.get("models"):
        return dict(p["models"])
    d = default_model(provider)
    return {"default": d} if d else {}

# key_env: onde a chave mora no .env (para o doctor conferir presença, nunca valor).
PROVIDERS: dict[str, dict[str, dict]] = {
    "llm": {
        # ── Assinatura com login guiado (sem chave de API) ───────────────────
        "claude-code": {
            "label": "Claude Code (assinatura Claude Pro/Max)",
            "family": "subscription",
            "docker_auth": "guided",
            "auth_command": "brain memory auth claude-code",
            "key_env": "",
            "cost_mode": "subscription",
            "rate_limit_note": _SUB_NOTE,
            # Régua do dono (2026-11-19): Haiku 5.5 em TODAS as operações, esforço high —
            # leaderboard da Hindsight: haiku-5.5+decide é a melhor qualidade acessível
            # (88.5 all-ops; 14/14 idiomas no retain) e a 5.5 derrubou o preço em ~90%.
            "models": {"retain": "claude-haiku-5-5", "consolidation": "claude-haiku-5-5",
                       "mental_models": "claude-haiku-5-5", "reflect": "claude-haiku-5-5",
                       "default": "claude-haiku-5-5"},
            "effort": "high",
            "setup_hint": "Autentique pelo botão Autenticar (painel) ou `brain memory auth claude-code`: "
                          "o token de longo prazo do `claude setup-token` vai para o config/.env.",
        },
        "xai-oauth": {
            "label": "xAI / SuperGrok (sign-in)",
            "family": "subscription",
            "docker_auth": "guided",
            "auth_command": "brain memory auth xai-oauth",
            "key_env": "",
            "cost_mode": "subscription",
            "rate_limit_note": _SUB_NOTE,
            "models": {"default": "grok-4.7"},     # mesmo preço do 4.6 ($2/$6) — sem razão pra ficar no 4.5
            "setup_hint": "Autentique pelo botão Autenticar (painel) ou `brain memory auth xai-oauth`: "
                          "código de dispositivo que você aprova no navegador; o token renova sozinho.",
        },
        # ── Chave de API ─────────────────────────────────────────────────────
        "anthropic": {"label": "Anthropic", "family": "key", "cost_mode": "api_key", "recommended": True,
                      # Régua do dono (2026-11-19): Haiku 5.5 em TODAS as operações (o antigo cenário B
                      # com Sonnet nos mental models foi superado — haiku-5.5 tem a melhor qualidade
                      # acessível na leaderboard e $0.10/$0.50 até 100k de prompt), esforço high.
                      "models": {"retain": "claude-haiku-5-5", "consolidation": "claude-haiku-5-5",
                                 "mental_models": "claude-haiku-5-5", "reflect": "claude-haiku-5-5",
                                 "default": "claude-haiku-5-5"},
                      "effort": "high",
                      "key_env": "HINDSIGHT_API_LLM_API_KEY"},
        "openai": {"label": "OpenAI", "family": "key", "cost_mode": "api_key",
                   "model": "gpt-6-luna",        # #2 geral ($11/1k c/ decide; retain 95.8 @ $0.43)
                   "key_env": "HINDSIGHT_API_LLM_API_KEY"},
        "fireworks": {"label": "Fireworks — DeepSeek v4.1-Flash", "family": "key", "cost_mode": "api_key", "recommended": True,
                      "model": "accounts/fireworks/models/deepseek-v4p1-flash",
                      "base_url": "https://api.fireworks.ai/inference/v1", "wire": "openai",
                      "key_env": "HINDSIGHT_API_LLM_API_KEY"},
        "zai": {"label": "Z.ai (GLM, plano coding)", "family": "key", "cost_mode": "api_key",
                "model": "glm-5.3-flash",        # #1 valor da leaderboard ($9.33/1k; consolid. e reflect #1)
                "base_url": "https://api.z.ai/api/coding/paas/v4",
                "wire": "openai", "key_env": "HINDSIGHT_API_LLM_API_KEY"},
        "gemini": {"label": "Google Gemini (chave do AI Studio)", "family": "key", "cost_mode": "api_key",
                   "model": "gemini-3.1-flash-lite",   # valor do Google: $0.25/$1.50 — 3.8-flash custa
                   # 3-6× mais e é MAIS FRACA no retain (84.0 vs 88.3): qualidade sobe só no all-ops caro
                   "key_env": "HINDSIGHT_API_LLM_API_KEY"},
        "minimax": {"label": "MiniMax — M3.1-Flash (campeão de extração)", "family": "key", "cost_mode": "api_key",
                    "model": "MiniMax-M3.1-Flash",    # retain 96.4 (qualidade 98.8) @ $0.81/1k; $0.15/$0.60
                    "key_env": "HINDSIGHT_API_LLM_API_KEY"},
        "custom": {"label": "Outro (OpenAI-compatível)", "family": "key", "cost_mode": "api_key",
                   "wire": "openai", "key_env": "HINDSIGHT_API_LLM_API_KEY"},
        # ── Assinatura com login manual ou indisponível no Docker ────────────
        "chatgpt": {
            "label": "ChatGPT (sign-in / assinatura Plus/Pro)",
            "family": "subscription",
            "docker_auth": "manual",
            "auth_command": "docker exec -it hindsight hindsight-admin chatgpt login",
            "key_env": "",
            "cost_mode": "subscription",
            "rate_limit_note": _SUB_NOTE,
            "models": {"default": "gpt-6-luna"},   # #2 geral na leaderboard ($11/1k c/ decide; retain 95.8)
            "setup_hint": "Login por navegador no servidor de memória (hindsight-admin chatgpt login) — "
                          "nesta instalação Docker é manual; prefira claude-code ou uma chave de API.",
        },
        "nous": {
            "label": "Nous Portal (assinatura)",
            "family": "subscription",
            "docker_auth": "manual",
            "auth_command": "docker exec -it hindsight hermes portal",
            "key_env": "",
            "cost_mode": "subscription",
            "rate_limit_note": _SUB_NOTE,
            "setup_hint": "Exige o login do Hermes (hermes portal) no servidor de memória — nesta instalação "
                          "Docker é manual; prefira claude-code ou uma chave de API.",
        },
        "github-copilot": {
            "label": "GitHub Copilot (assinatura)",
            "family": "subscription",
            "docker_auth": "manual",
            "weak_default": True,
            "auth_command": "docker exec -it hindsight hindsight-admin copilot login",
            "key_env": "",
            "cost_mode": "subscription",
            "rate_limit_note": _SUB_NOTE,
            "setup_hint": "Exige login manual do Copilot no servidor de memória — prefira um provedor com login "
                          "guiado (claude-code, xai-oauth) ou uma chave de API. (A variável COPILOT_GITHUB_TOKEN/"
                          "GH_TOKEN existe, mas não é o caminho recomendado; além disso, o modelo padrão "
                          "gpt-5.6-terra é o mais fraco da leaderboard: 73 pontos, $332/1k.)",
        },
        "cursor": {
            "label": "Cursor (assinatura)",
            "family": "subscription",
            "docker_auth": "unavailable",
            "auth_command": "",
            "key_env": "",
            "cost_mode": "subscription",
            "rate_limit_note": _SUB_NOTE,
            "models": {"default": "auto"},
            "setup_hint": "Exige o cursor-agent logado no servidor de memória — não disponível na instalação "
                          "Docker do Brain; prefira claude-code ou uma chave de API.",
        },
    },
    "embeddings": {
        "local": {"label": "Local — LM Studio bge-m3 (zero egress)", "recommended": True, "local": True,
                  "model": "text-embedding-bge-m3", "base_url": "http://host.docker.internal:1234/v1",
                  "key_env": ""},
        "fireworks": {"label": "Fireworks — Qwen3-Embedding-8B", "recommended_cloud": True,
                      "model": "fireworks/qwen3-embedding-8b", "dimensions": 1536,
                      "base_url": "https://api.fireworks.ai/inference/v1", "wire": "openai",
                      "key_env": _EMB + "OPENAI_API_KEY"},
        "openai": {"label": "OpenAI", "model": "text-embedding-3-small", "wire": "openai",
                   "key_env": _EMB + "OPENAI_API_KEY"},
        "cohere": {"label": "Cohere", "model": "embed-multilingual-v3.0", "wire": "cohere",
                   "key_env": _EMB + "COHERE_API_KEY"},
        "custom": {"label": "Outro (OpenAI-compatível)", "wire": "openai", "key_env": _EMB + "OPENAI_API_KEY"},
    },
    "reranker": {
        "off": {"label": "Desligado — fusão RRF (recomendado; veredito 2026-11-07)", "recommended": True},
        "fireworks": {"label": "Fireworks — Qwen3-Reranker-8B", "recommended_cloud": True,
                      "model": "fireworks_ai/fireworks/qwen3-reranker-8b", "wire": "litellm-sdk",
                      "base_url": "https://api.fireworks.ai/inference/v1", "candidates": 50,
                      "key_env": _RER + "LITELLM_SDK_API_KEY"},
        "cohere": {"label": "Cohere", "model": "rerank-v3.5", "wire": "cohere", "key_env": _RER + "COHERE_API_KEY"},
        "zeroentropy": {"label": "ZeroEntropy", "model": "zerank-2", "wire": "zeroentropy",
                        "key_env": _RER + "ZEROENTROPY_API_KEY"},
        "openrouter": {"label": "OpenRouter", "model": "cohere/rerank-v3.5", "wire": "openrouter",
                       "key_env": _RER + "OPENROUTER_API_KEY"},
        "custom": {"label": "Outro (endpoint compatível com Cohere /rerank — Jina, Voyage, BGE próprio…)",
                   "wire": "cohere", "key_env": _RER + "COHERE_API_KEY"},
    },
    # Decisão (opcional, só vale no full): o juiz rápido System-1 de 0,8B do próprio
    # Hindsight — responde julgamentos tipados (muda/novo/repete, ajuda?, é suficiente?)
    # e corta ~40% das chamadas do LLM SUBINDO a qualidade (leaderboard: haiku-5.5
    # $35→$21/1k casos, 85.5→88.1). Sem ele tudo funciona como sempre — quem pula paga
    # só os tokens do próprio LLM. Off explícito = "none" no servidor pinado.
    # Nuvem (Hindsight 1.3.0: DECISION_MODEL_PROVIDERS = none·hindsight·typesafe·cloudflare·openai): cada provedor
    # guarda a SUA chave (`key_env`) e o Brain copia a do provedor ativo para a variável que o servidor lê
    # (DECISION_WIRE_KEY) — trocar de provedor nunca entrega a chave de um ao outro. A do Hindsight mora na própria
    # variável do servidor (instâncias antigas) e vai para HINDSIGHT_API_DECISION_CLOUD_API_KEY quando sai de cena.
    "decision": {
        "off": {"label": "Desligado — só os tokens do próprio LLM (padrão)", "recommended": True},
        "hindsight": {"label": "Hindsight — hs-decide-1-flash · US$ 0,02/1M de entrada (corta ~40% das chamadas do LLM)",
                      "model": "hs-decide-1-flash", "recommended_cloud": True, "wire": "hindsight", "recall": True,
                      "note": "Trechos pequenos de memória vão à nuvem de inferência do Hindsight para julgamento "
                              "(hsk_ key em inference.hindsight.vectorize.io — por uso, sem assinatura).",
                      "key_env": "HINDSIGHT_API_DECISION_MODEL_API_KEY"},
        "openai": {"label": "OpenAI — Decisions API (gpt-6-luna)",
                   "model": "gpt-6-luna", "wire": "openai", "recall": True,
                   "note": "Trechos pequenos de memória vão à Decisions API da OpenAI (api.openai.com) para julgamento "
                           "— chave da OpenAI, cobrança por uso. Com o LLM na OpenAI, a mesma chave serve.",
                   "key_env": "BRAIN_DECISION_OPENAI_API_KEY", "shares_llm_key": "openai"},
        "typesafe": {"label": "Typesafe — jev-latest (System One)",
                     "model": "jev-latest", "wire": "typesafe", "recall": True,
                     "note": "Trechos pequenos de memória vão à API da Typesafe (api.typesafe.ai) para julgamento — "
                             "chave da Typesafe, cobrança por uso.",
                     "key_env": "BRAIN_DECISION_TYPESAFE_API_KEY"},
        "local": {"label": "Local — hs-decide-1-flash (/v1/systemone, zero egress)",
                  "local": True, "managed": True, "wire": "hindsight", "model": "hs-decide-1-flash",
                  "base_url": "http://host.docker.internal:8000", "max_concurrent": 1,
                  "note": "O Brain instala e liga o servidor (MLX no Apple Silicon, vLLM no Linux com GPU). "
                          "LM Studio e Ollama não servem este protocolo. Nada sai da máquina.",
                  "key_env": "BRAIN_DECISION_LOCAL_API_KEY"},
    },
}

for _pid, _entry in PROVIDERS["llm"].items():
    _entry.setdefault("base_label", _entry["label"])
    _entry["label"] = derive_label(_entry)


def menu_providers(slot: str, *, include_custom: bool = True, include_unavailable: bool = False,
                   mode: str = "embed") -> list[tuple[str, dict]]:
    """Lista ordenada de provedores de um slot para wizard e painel: guiados e chave de API
    primeiro; manual e indisponível por último. `cursor` (unavailable) fica fora do cardápio
    padrão (continua aceito pela CLI). Embeddings `local` entra nos dois modos (a exigência de nuvem
    do `full` vale só para o LLM); no `full` ele vai para o fim da lista — o recomendado de lá
    continua sendo o de nuvem, `local` é escolha, não padrão."""
    tbl = PROVIDERS.get(slot, {})
    items: list[tuple[str, dict]] = []
    for pid, info in tbl.items():
        if not include_custom and pid == "custom":
            continue
        if not include_unavailable and info.get("docker_auth") == "unavailable":
            continue
        items.append((pid, info))
    emb_full = slot == "embeddings" and mode == "full"
    items.sort(key=lambda kv: (
        1 if kv[1].get("docker_auth") in ("manual", "unavailable") else 0,
        1 if kv[1].get("docker_auth") == "unavailable" else 0,
        1 if emb_full and kv[1].get("local") else 0,
    ))
    return items


CLOUD_FLAGS = {"embeddings": "cloud_embeddings", "reranker": "cloud_reranker", "decision": "cloud_decision"}


def _parse_recall(val) -> bool | None:
    if val is None or val == "":
        return None
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    if s in ("on", "true", "1", "sim", "yes"):
        return True
    if s in ("off", "false", "0", "nao", "não", "no", "none"):
        return False
    raise util.BrainError(f"--recall aceita on|off — veio {val!r}", code=4)


def _validate_key(provider: str, p: dict, key: str | None) -> None:
    """Chave vazia (`""`) vale como não informada: nada a gravar e nenhum erro — o wizard
    (`setup._providers_step`) repassa `""` quando a chave já está no `.env` e não pergunta de novo."""
    if key is None or (isinstance(key, str) and not key.strip()):
        return
    env_var = p.get("key_env", "")
    if not env_var:
        raise util.BrainError(
            f"provedor '{provider}' não usa variável de ambiente para chave — remova a flag de chave",
            code=4,
        )
    if not isinstance(key, str):
        raise util.BrainError(
            f"valor inválido para a variável de ambiente {env_var} — nada gravado no .env",
            code=4,
        )


def _guard_env_updates(env_updates: dict) -> None:
    for k, v in env_updates.items():
        if not isinstance(k, str) or not k.strip():
            raise util.BrainError("nome de variável de ambiente vazio — nada gravado no .env", code=4)
        if v is None or (isinstance(v, str) and v.strip() == ""):
            raise util.BrainError(f"valor vazio para a variável de ambiente {k} — nada gravado no .env", code=4)


def _clean(value):
    """Texto vazio ou só espaços = `""` (não informado) — a regra da chave, em todo campo de texto."""
    return value.strip() if isinstance(value, str) else value


def _clean_models(models: dict | None) -> dict | None:
    """`_clean` em cada modelo por operação; o que fica vazio sai do dicionário."""
    if not models:
        return None
    kept = {op: _clean(m) for op, m in models.items()}
    kept = {op: m for op, m in kept.items() if m is not None and m != ""}
    return kept or None


DECISION_WIRE_KEY = "HINDSIGHT_API_DECISION_MODEL_API_KEY"     # a chave que o servidor lê para o decisor ativo
DECISION_CLOUD = ("hindsight", "openai", "typesafe")


def _op_env(envk: str, suffix: str) -> str:
    """`RETAIN_LLM_MODEL` → `HINDSIGHT_API_RETAIN_LLM_<suffix>` (só o `_MODEL` final: MENTAL_MODEL_REFRESH… fica)."""
    return "HINDSIGHT_API_" + envk[: -len("_MODEL")] + "_" + suffix


EFFORT_ENV = {op: _op_env(envk, "REASONING_EFFORT") for op, envk in LLM_OPS}
BODY_ENV = {op: _op_env(envk, "EXTRA_BODY") for op, envk in LLM_OPS}
# a chave do extra body que é do Brain em cada lane — o resto do JSON (temperatura, top_p…) é do dono e fica
_BODY_KEY = {"anthropic": ("output_config", "effort"), "gemini": ("thinking_config", "thinking_level")}


def efforts_of(spec: str) -> dict[str, str]:
    """`llm_effort` gravado → {operação: nível} (um nível solto é o `default`), tolerante como `models_of`."""
    spec = (spec or "").strip()
    if not spec:
        return {}
    if "=" not in spec:
        return {"default": spec.lower()}
    ops = dict(LLM_OPS)
    out: dict[str, str] = {}
    for part in spec.split(","):
        op, sep, lv = part.partition("=")
        if sep and op.strip() in ops and lv.strip():
            out[op.strip()] = lv.strip().lower()
    return out


def _fmt_spec(d: dict) -> str:
    if not d:
        return ""
    if set(d) == {"default"}:
        return d["default"]
    return ",".join(f"{op}={d[op]}" for op, _ in LLM_OPS if d.get(op))


def effort_plan(provider: str, op_models: dict, effort: str = "", efforts: dict | None = None,
                cat: dict | None = None) -> tuple[dict[str, str], list[str]]:
    """Nível efetivo por operação (\"\" = o padrão do modelo, nada vai ao servidor) e avisos. Explícito inválido
    para o modelo = erro; o padrão do Brain (registro: Claude `high`) só vale onde o modelo o aceita — senão, o
    padrão do próprio modelo. Operação com modelo próprio herda o nível do padrão quando o modelo dela o aceita."""
    from . import models_catalog as mc
    p = PROVIDERS["llm"].get(provider) or {}
    effort = (effort or "").strip().lower()
    efforts = {op: str(v).strip().lower() for op, v in (efforts or {}).items() if str(v or "").strip()}
    bad = [op for op in efforts if op not in dict(LLM_OPS)]
    if bad:
        raise util.BrainError(f"--efforts aceita {','.join(op for op, _ in LLM_OPS)} — veio {bad[0]!r}", code=4)
    if not mc.lane(provider):
        if effort or efforts:
            raise util.BrainError(f"o provedor {provider!r} não tem esforço ajustável pelo Brain "
                                  f"(o modelo recomendado não expõe o parâmetro)", code=4)
        return {}, []
    warns: list[str] = []
    dflt_model = op_models.get("default") or ""
    base = effort or p.get("effort", "")
    plan: dict[str, str] = {}
    for op, _ in LLM_OPS:
        m = op_models.get(op) or dflt_model
        e = mc.efforts(provider, m, mc.entry(cat, m))
        asked = efforts.get(op) or (effort if op == "default" else "")
        if asked:
            w = mc.check_effort(provider, m, asked, mc.entry(cat, m))
            if w:
                warns.append(w)
            plan[op] = asked
        elif base and base in e["levels"]:
            plan[op] = base
        elif base and op != "default" and plan.get("default") and e["levels"]:
            plan[op] = e["default"]              # o modelo desta operação não aceita o nível do padrão
        else:
            plan[op] = ""
    return plan, warns


def _merge_body(raw: str, lane: str, level: str) -> str:
    """Extra body com o nível do Brain (ou sem ele) preservando o resto do JSON do dono; \"\" = nada sobra."""
    try:
        body = json.loads(raw) if raw and raw.strip() else {}
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    for ln, (outer, inner) in _BODY_KEY.items():
        sub = body.get(outer)
        if isinstance(sub, dict):
            sub = {k: v for k, v in sub.items() if k != inner}
            if sub:
                body[outer] = sub
            else:
                body.pop(outer, None)
    if level and lane in _BODY_KEY:
        outer, inner = _BODY_KEY[lane]
        body.setdefault(outer, {})[inner] = level.upper() if lane == "gemini" else level
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")) if body else ""


def effort_env(provider: str, plan: dict[str, str], cur_env: dict | None = None) -> tuple[dict, list[str]]:
    """Variáveis do esforço no lane do provedor (`models_catalog` docstring): global = o do padrão; operação só
    quando difere (o servidor herda o global). Devolve (gravar, apagar) cobrindo as 10 variáveis do Brain."""
    from . import models_catalog as mc
    cur_env = cur_env or {}
    lane = mc.lane(provider)
    g = plan.get("default", "")
    upd: dict[str, str] = {}
    for op, _ in LLM_OPS:
        lv = plan.get(op, "")
        if op != "default" and lv == g:
            lv = ""
        elif op != "default" and not lv and g:
            raise util.BrainError(
                f"o modelo de {LLM_OP_LABELS.get(op, op)} não aceita esforço e herdaria {g!r} do padrão — "
                "deixe o esforço do padrão vazio (padrão do modelo) ou troque o modelo da operação", code=4)
        if lane in ("reasoning", "chat") and lv:
            upd[EFFORT_ENV[op]] = lv
        body = _merge_body(cur_env.get(BODY_ENV[op], ""), lane, lv if lane in _BODY_KEY else "")
        if body:
            upd[BODY_ENV[op]] = body
    unset = [k for k in (*EFFORT_ENV.values(), *BODY_ENV.values()) if k not in upd]
    return upd, unset


def decision_key_ready(provider: str, env: dict, mem: dict) -> bool:
    """O provedor de decisão tem chave para ligar agora? (presença, nunca valor)"""
    from . import decider
    p = PROVIDERS["decision"].get(provider) or {}
    if provider in ("off",) or p.get("managed"):
        return True
    if provider == "hindsight":
        wire = env.get(DECISION_WIRE_KEY, "")
        local = env.get(decider.LOCAL_KEY_ENV, "")
        return bool(env.get(decider.CLOUD_STASH_ENV) or (wire and wire != local
                    and (mem.get("decision_provider") or "off") in ("hindsight", "off")))
    if env.get(p.get("key_env", "")):
        return True
    return bool(p.get("shares_llm_key") and mem.get("llm_provider") == p["shares_llm_key"]
                and env.get("HINDSIGHT_API_LLM_API_KEY"))


def _emb_env(p: dict, model: str, base_url: str, dimensions: int, key: str | None) -> dict:
    env: dict[str, str] = {}
    wire = p.get("wire", "openai")
    env[_EMB + "PROVIDER"] = wire
    pref = _EMB + ("OPENAI_" if wire == "openai" else wire.upper() + "_")
    if model:                                # não informado = a variável nem entra (nada vazio chega ao .env)
        env[pref + "MODEL"] = model
    url = base_url or p.get("base_url", "")
    if wire == "openai" and url:
        env[pref + "BASE_URL"] = url
    dimensions = dimensions or p.get("dimensions", 0)
    if dimensions:
        env[pref + "DIMENSIONS"] = str(dimensions)
    kenv = p.get("key_env")
    if key and kenv:
        env[kenv] = key
    return env


def _rer_env(p: dict, model: str, base_url: str, candidates: int, key: str | None) -> dict:
    if p is PROVIDERS["reranker"]["off"]:
        return {_RER + "PROVIDER": "rrf"}
    env = {_RER + "PROVIDER": p["wire"]}
    pref = _RER + p["wire"].upper().replace("-", "_") + "_"
    if model:                                # `custom` sem --model gravava antes da guarda de .env vazio
        env[pref + "MODEL"] = model
    url = base_url or p.get("base_url", "")
    if p["wire"] == "litellm-sdk" and url:
        env[_RER + "LITELLM_SDK_API_BASE"] = url
    elif base_url:
        env[pref + "BASE_URL"] = base_url
    candidates = candidates or p.get("candidates", 0)
    if candidates:
        env[_RER + "MAX_CANDIDATES"] = str(candidates)
    kenv = p.get("key_env")
    if key and kenv:
        env[kenv] = key
    return env


def slot_env(slot: str, provider: str, *, model: str = "", models: dict | None = None,
             base_url: str = "", dimensions: int = 0, candidates: int = 0, key: str | None = None,
             recall: bool | str | None = None, effort: str = "", efforts: dict | None = None,
             cur_env: dict | None = None, cat: dict | None = None) -> dict:
    """Env do .env para a escolha (sem tocar disco). Valores vazios caem fora — segredo nunca ecoa. No LLM, o
    esforço vai pelo lane do provedor (`effort_env`); as variáveis de esforço a APAGAR o `set_slot` calcula."""
    p = PROVIDERS[slot][provider]
    _validate_key(provider, p, key)
    rec = _parse_recall(recall)
    if rec is not None and slot != "decision":
        raise util.BrainError("--recall só vale no slot decision", code=4)
    if (effort or efforts) and slot != "llm":
        raise util.BrainError("--effort/--efforts só valem no slot llm", code=4)
    if isinstance(key, str):
        key = key.strip() or None            # vazia ou só espaços = não informada, em todo slot (nada vazio chega ao .env)
    model, base_url, models = _clean(model), _clean(base_url), _clean_models(models)   # mesma regra nos demais textos
    if slot == "llm":
        sub = p.get("family") == "subscription"
        env = {"HINDSIGHT_API_LLM_PROVIDER": p.get("wire", provider) if sub
               else ("openai" if p.get("wire") == "openai" else provider)}
        url = base_url or p.get("base_url", "")
        if not sub and p.get("wire") == "openai" and url:
            env["HINDSIGHT_API_LLM_BASE_URL"] = url
        ops = models or {}
        op_models: dict[str, str] = {}
        for op, envk in LLM_OPS:
            m = ops.get(op) or (model if op == "default" else "")
            if m:
                env[f"HINDSIGHT_API_{envk}"] = m
                op_models[op] = m
        if not sub and key and p.get("key_env"):
            env[p["key_env"]] = key
        plan, _w = effort_plan(provider, op_models, effort, efforts, cat)
        env.update(effort_env(provider, plan, cur_env)[0])
        return env
    if slot == "embeddings":
        return _emb_env(p, model or p.get("model", ""), base_url, dimensions, key)
    if slot == "decision":
        rec_on = bool(rec)
        if rec_on and not p.get("recall"):
            raise util.BrainError(
                "decisor no recall (--recall on) só é suportado com um provedor de nuvem "
                f"({', '.join(DECISION_CLOUD)}) — não no decisor local nem desligado",
                code=4,
            )
        if rec_on and (not candidates or int(candidates) <= 0):
            raise util.BrainError(
                "ligar o decisor no recall (--recall on) exige um teto explícito de candidatos (--candidates N)",
                code=4,
            )
        # off explícito = "none" (valor de fábrica do servidor pinado) — trocar de lane limpa o estado. O recall é
        # SEMPRE dito: no 1.3.0 um decisor openai/typesafe global vale também no recall quando a variável falta
        env = {
            "HINDSIGHT_API_DECISION_MODEL_PROVIDER": "none" if provider == "off" else p.get("wire", "hindsight"),
            "HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER": p.get("wire", "hindsight") if rec_on else "none",
        }
        if provider == "off":
            return env
        if model or p.get("model"):
            env["HINDSIGHT_API_DECISION_MODEL_MODEL"] = model or p["model"]
        if provider == "local":
            url = base_url or p.get("base_url", "")
            if url:
                env["HINDSIGHT_API_DECISION_MODEL_BASE_URL"] = url
            env["HINDSIGHT_API_DECISION_MODEL_MAX_CONCURRENT"] = str(p.get("max_concurrent", 1))
            if key:
                env["BRAIN_DECISION_LOCAL_API_KEY"] = key
                env[DECISION_WIRE_KEY] = key
        elif key and p.get("key_env"):
            env[p["key_env"]] = key
            env[DECISION_WIRE_KEY] = key             # o servidor lê a do provedor ativo
        if rec_on and candidates:
            env["HINDSIGHT_API_RERANKER_MAX_CANDIDATES"] = str(int(candidates))
        return env
    return _rer_env(p, model or p.get("model", ""), base_url, candidates, key)


REBUILD_COST_NOTE = ("no modo full o rebuild reenvia o vault inteiro ao LLM e paga a extração de novo "
                     "(`brain memory cost` mede)")


def embeddings_change_pending(brain, provider: str, model: str = "", dimensions: int | None = None) -> bool:
    """Escolher `provider`/`model` (e a dimensão de saída, quando o chamador a diz — a efetiva: a pedida ou a do
    provedor; 0 = a do modelo) nos embeddings muda os vetores de um banco já sincronizado? Quem chama avisa ANTES
    de gravar (o `rebuild` é o que re-deriva tudo do vault)."""
    mem = brain.inst.cfg["memory"]
    prev_provider, prev_model = mem.get("embeddings_provider", ""), mem.get("embeddings_model", "")
    prev_dims = str(mem.get("embeddings_dimensions") or "0").strip()
    dims_changed = dimensions is not None and int(dimensions or 0) != (int(prev_dims) if prev_dims.isdigit() else 0)
    return (mem.get("engine") == "hindsight"
            and (prev_provider != provider or bool(prev_model and model and prev_model != model) or dims_changed)
            and (brain.inst.root / ".memory-state.json").exists())


def rebuild_warning(brain, full: bool | None = None) -> str:
    """Texto do aviso de troca de embeddings: vetores incompatíveis → `rebuild`; no full, o custo.
    `full` = o modo de destino quando o chamador está trocando de modo junto (wizard); None = o modo atual."""
    from .memory import mode as _mem_mode                      # lazy: evita ciclo em tempo de import
    msg = "embeddings mudam: vetores antigos ficam incompatíveis — `brain memory rebuild` re-deriva tudo do vault"
    if _mem_mode(brain.inst.cfg["memory"]) == "full" if full is None else full:
        msg += f"; {REBUILD_COST_NOTE}"
    return msg


def resolve_llm_models(brain, provider: str, model: str = "", models: dict | None = None
                       ) -> tuple[dict[str, str], list[str]]:
    """Mapa por operação que vai ao servidor + operações FIXADAS pelo dono. Modelo dito (o `default` ou o de uma
    operação) é fixo; `auto` (ou vazio) = segue o mais novo da linha da semente do registro. Com o Modelo dito,
    operação sem modelo próprio herda ele (não a semente) — é o que o campo Modelo sempre quis dizer."""
    from . import models_catalog as mc
    explicit = {op: m for op, m in (_clean_models(models) or {}).items() if m.lower() != "auto"}
    m0 = _clean(model) or ""
    if m0 and m0.lower() != "auto":
        explicit.setdefault("default", m0)
    if explicit.get("default"):
        return dict(explicit), sorted(explicit)
    seeds = seed_models(provider)
    final = {op: mc.resolve(brain, provider, s) for op, s in seeds.items() if op not in explicit}
    final.update(explicit)
    return final, sorted(explicit)


def pinned_ops(brain) -> list[str]:
    """Operações do LLM que o dono fixou (as outras seguem o mais novo). Instância anterior ao acompanhamento
    (`llm_follow_v` = 0): fixa é a operação cujo modelo gravado não é a semente do registro nem um mais novo da
    mesma linha — quem nunca mexeu no padrão passa a acompanhar."""
    from . import models_catalog as mc
    mem = brain.inst.cfg["memory"]
    if int(mem.get("llm_follow_v") or 0) >= 1:
        return [x for x in str(mem.get("llm_pinned") or "").split(",") if x]
    seeds = seed_models(mem.get("llm_provider", ""))
    out = []
    for op, m in models_of(mem.get("llm_models", "")).items():
        s = seeds.get(op) or seeds.get("default", "")
        ps, pm = mc.parse(s), mc.parse(m)
        follows = m == s or bool(ps and pm and ps["line"] == pm["line"] and pm["version"] >= ps["version"])
        if not follows:
            out.append(op)
    return sorted(out)


def _decision_keys(brain, provider: str, p: dict, key: str | None, mem: dict, cur_env: dict,
                   env_updates: dict, unset_env: list) -> None:
    """A variável que o servidor lê (DECISION_WIRE_KEY) sempre com a chave do provedor ATIVO:
      • a do Hindsight que sai de cena vai para o cofre (CLOUD_STASH_ENV) e volta quando ele volta;
      • OpenAI/Typesafe guardam a sua em variável própria; ao sair, a variável do servidor volta à do cofre;
      • ligar um de nuvem sem chave alguma é recusado antes de gravar."""
    from . import decider
    prev = mem.get("decision_provider") or "off"
    wire = cur_env.get(DECISION_WIRE_KEY, "")
    stash = cur_env.get(decider.CLOUD_STASH_ENV, "")
    local_key = cur_env.get(decider.LOCAL_KEY_ENV, "")
    k = (key or "").strip()
    if prev == "hindsight" and provider != "hindsight" and wire and wire != local_key and wire != stash:
        env_updates[decider.CLOUD_STASH_ENV] = wire
        stash = wire
    if prev in ("openai", "typesafe") and provider != prev and DECISION_WIRE_KEY not in env_updates:
        own = cur_env.get(PROVIDERS["decision"][prev].get("key_env", ""), "")
        if wire and (wire == own or not own):
            if stash and provider in ("off", "hindsight"):
                env_updates[DECISION_WIRE_KEY] = stash
            else:
                unset_env.append(DECISION_WIRE_KEY)
    if provider == "hindsight" and not k:
        if prev != "hindsight" and stash and DECISION_WIRE_KEY not in env_updates:
            env_updates[DECISION_WIRE_KEY] = stash
        if not (env_updates.get(DECISION_WIRE_KEY) or (prev in ("hindsight", "off") and wire and wire != local_key)):
            raise util.BrainError("cole a chave do Hindsight (hsk_…) para ligar a Decisão na nuvem — --key", code=4)
    if provider in ("openai", "typesafe"):
        own = k or cur_env.get(p.get("key_env", ""), "")
        if not own and p.get("shares_llm_key") and mem.get("llm_provider") == p["shares_llm_key"]:
            own = cur_env.get("HINDSIGHT_API_LLM_API_KEY", "")         # mesma conta da OpenAI no LLM
        if not own:
            raise util.BrainError(f"cole a chave de {p['label'].split(' — ')[0]} para ligar a Decisão — --key", code=4)
        env_updates[DECISION_WIRE_KEY] = own
        unset_env[:] = [x for x in unset_env if x != DECISION_WIRE_KEY]


def set_slot(brain, slot: str, provider: str, *, model: str = "", models: dict | None = None,
             base_url: str = "", dimensions: int = 0, candidates: int = 0, key: str | None = None,
             recall: bool | str | None = None, effort: str = "", efforts: dict | None = None) -> dict:
    """Grava a escolha: .env (wire + chave) + [memory] (provedor/modelo/flags). Devolve o resumo."""
    if slot not in SLOTS:
        raise util.BrainError(f"slot inválido: {slot!r} — use {', '.join(SLOTS)}", code=4)
    if slot == "llm" and provider in LOCAL_LLM_BLOCKED:
        raise util.BrainError(
            f"LLM local ({provider!r}) não é suportado no slot LLM — use um provedor por assinatura ou chave de API "
            "(embeddings locais valem nos modos embed e full — o LLM é que não pode ser local)",
            code=4,
        )
    if provider not in PROVIDERS[slot]:
        raise util.BrainError(f"provedor inválido para {slot}: {provider!r} — "
                              f"{', '.join(PROVIDERS[slot])}", code=4)
    p = PROVIDERS[slot][provider]
    model, base_url, models = _clean(model), _clean(base_url), _clean_models(models)   # mesma regra da chave
    is_sub = slot == "llm" and p.get("family") == "subscription"
    pinned: list[str] = []
    if slot == "llm":
        # vazio = a semente do registro (SERVER_DEFAULT_MODELS quando o registro não cura) resolvida para o mais
        # novo da linha — gravado EXPLÍCITO no .env: o que aplicou é o que o stack mostra
        models, pinned = resolve_llm_models(brain, provider, model, models)
        model = ""
        if not models and not is_sub:
            raise util.BrainError("provedor custom precisa de --model (ou --models por operação)", code=4)
    if slot == "embeddings" and provider in ("custom",) and not (model and (base_url or p.get("base_url"))):
        raise util.BrainError("embeddings custom exige --model e --base-url", code=4)

    mem = brain.inst.cfg["memory"]
    rebuild = slot == "embeddings" and embeddings_change_pending(brain, provider, model or p.get("model", ""),
                                                                 int(dimensions or p.get("dimensions", 0) or 0))
    cur_env = config.load_env(brain.inst)
    effort_explicit = {**({"default": effort.strip().lower()} if (effort or "").strip() else {}),
                       **{op: str(v).strip().lower() for op, v in (efforts or {}).items() if str(v or "").strip()}}
    warnings: list[str] = []
    cat = None
    if slot == "llm":
        from . import models_catalog as mc
        cat = (mc.load_cache(brain).get("providers") or {}).get(provider)
        warnings = effort_plan(provider, models or {}, effort, efforts, cat)[1]
    env_updates = slot_env(slot, provider, model=model, models=models, base_url=base_url,
                           dimensions=dimensions, candidates=candidates, key=key, recall=recall,
                           effort=effort, efforts=efforts, cur_env=cur_env, cat=cat)
    unset_env: list[str] = []
    if slot == "llm":
        unset_env.extend(k for k in effort_env(provider, effort_plan(provider, models or {}, effort, efforts, cat)[0],
                                               cur_env)[1] if k in cur_env)
    if slot == "decision" and provider == "local" and not base_url:
        from . import decider
        try:
            prepared = decider.prepare(brain, key=key or None)
        except util.BrainError:
            if mem.get("decision_provider") == "local":
                set_slot(brain, "decision", "off")
            raise
        base_url = prepared["container_url"]
        key = prepared["local_key"]
        env_updates["HINDSIGHT_API_DECISION_MODEL_BASE_URL"] = base_url
        env_updates["HINDSIGHT_API_DECISION_MODEL_MODEL"] = p.get("model") or "hs-decide-1-flash"
        env_updates["BRAIN_DECISION_LOCAL_API_KEY"] = key
        env_updates["HINDSIGHT_API_DECISION_MODEL_API_KEY"] = key
    if slot == "decision" and provider == "local":
        from . import decider
        prev = cur_env.get("HINDSIGHT_API_DECISION_MODEL_API_KEY", "")
        local_key = env_updates.get("BRAIN_DECISION_LOCAL_API_KEY") or key or ""
        if prev and prev != local_key:
            env_updates[decider.CLOUD_STASH_ENV] = prev
    if slot == "decision" and provider != "local" and mem.get("decision_provider") == "local":
        from . import decider
        decider.stop_service(brain.inst, remove=True)
        stash = cur_env.get(decider.CLOUD_STASH_ENV, "")
        local_key = cur_env.get(decider.LOCAL_KEY_ENV, "")
        wire = cur_env.get(DECISION_WIRE_KEY, "")
        if provider == "off" and wire and wire == local_key:
            if stash:
                env_updates[DECISION_WIRE_KEY] = stash
            else:
                unset_env.append(DECISION_WIRE_KEY)
        elif provider == "hindsight" and not key and stash and DECISION_WIRE_KEY not in env_updates:
            env_updates[DECISION_WIRE_KEY] = stash
    if slot == "decision":
        _decision_keys(brain, provider, p, key, mem, cur_env, env_updates, unset_env)
    # #159: sem esforço dito, não sobrescreve um .env existente que já tem HINDSIGHT_API_LLM_REASONING_EFFORT=max
    if (slot == "llm" and not effort_explicit
            and cur_env.get("HINDSIGHT_API_LLM_REASONING_EFFORT", "").strip().lower() == "max"):
        env_updates.pop("HINDSIGHT_API_LLM_REASONING_EFFORT", None)
        unset_env = [k for k in unset_env if k != "HINDSIGHT_API_LLM_REASONING_EFFORT"]
    if slot == "llm":
        # a escolha nova regrava a tabela por operação INTEIRA: modelo de operação que ela não define sai do .env —
        # senão o retain seguia com o modelo do provedor anterior (claude-haiku no OpenAI) e falhava no servidor.
        # O `default` (LLM_MODEL) fica: sem ele o compose do full interpola um placeholder local.
        unset_env.extend(f"HINDSIGHT_API_{envk}" for op, envk in LLM_OPS
                         if op != "default" and f"HINDSIGHT_API_{envk}" not in env_updates)
    # o mesmo vale para a dimensão dos embeddings e o teto do reranker: não dito e sem padrão no provedor = o do
    # servidor. O de antes ficava: Fireworks → local seguia pedindo 1536 dimensões ao bge-m3 (1024), e Fireworks →
    # Cohere seguia com o teto 50 do Fireworks
    if slot == "embeddings":
        unset_env.extend(k for k in cur_env
                         if k.startswith(_EMB) and k.endswith("_DIMENSIONS") and k not in env_updates)
    if slot == "reranker" and _RER + "MAX_CANDIDATES" not in env_updates and not mem.get("decision_recall"):
        unset_env.append(_RER + "MAX_CANDIDATES")   # com o recall do decisor ligado, a variável é do recall
    _guard_env_updates(env_updates)
    rec_on = False
    if slot == "decision":
        rec_on = bool(_parse_recall(recall)) and bool(p.get("recall"))
        if provider != "local":
            unset_env.extend([
                "HINDSIGHT_API_DECISION_MODEL_BASE_URL",
                "HINDSIGHT_API_DECISION_MODEL_MAX_CONCURRENT",
            ])
        if not rec_on and mem.get("decision_recall"):
            saved = str(mem.get("decision_recall_saved_reranker_cap") or "")
            if saved:
                env_updates["HINDSIGHT_API_RERANKER_MAX_CANDIDATES"] = saved
            else:
                unset_env.append("HINDSIGHT_API_RERANKER_MAX_CANDIDATES")
            unset_env.append("HINDSIGHT_API_RECALL_DECISION_MODEL_MAX_CANDIDATES")
        elif not rec_on:
            unset_env.append("HINDSIGHT_API_RECALL_DECISION_MODEL_MAX_CANDIDATES")
    from .setup import set_env                     # lazy: setup importa memory em tempo de execução
    changed_env = set_env(brain.inst, env_updates, unset=unset_env)

    cfg_updates: dict = {f"{slot}_provider": provider}
    if slot == "llm":
        cfg_updates["llm_models"] = _fmt_spec(models or {})
        cfg_updates["llm_pinned"] = ",".join(pinned)          # o resto segue o mais novo da linha
        cfg_updates["llm_follow_v"] = 1
        cfg_updates["llm_effort"] = _fmt_spec(effort_explicit)
    elif slot == "decision":
        cfg_updates["decision_model"] = (model or p.get("model", "")) if provider != "off" else ""
        cfg_updates["decision_base_url"] = (base_url or p.get("base_url", "")) if provider == "local" else ""
        cfg_updates["decision_recall"] = rec_on
        cfg_updates["decision_max_candidates"] = int(candidates) if (rec_on and candidates) else 0
        if rec_on and not mem.get("decision_recall"):
            cfg_updates["decision_recall_saved_reranker_cap"] = cur_env.get(
                "HINDSIGHT_API_RERANKER_MAX_CANDIDATES", "")
        elif not rec_on:
            cfg_updates["decision_recall_saved_reranker_cap"] = ""
    else:
        if model or p.get("model"):
            cfg_updates[f"{slot}_model"] = model or p.get("model", "")
        if base_url or (provider not in ("local",) and p.get("base_url")):
            cfg_updates[f"{slot}_base_url"] = base_url or p.get("base_url", "")
        if slot == "embeddings":                   # 0 = a do modelo (o servidor não manda `dimensions`)
            cfg_updates["embeddings_dimensions"] = int(dimensions or p.get("dimensions", 0) or 0)
        if slot == "reranker":                     # 0 = o padrão do servidor
            cfg_updates["reranker_max_candidates"] = int(candidates or p.get("candidates", 0) or 0)
    flag = CLOUD_FLAGS.get(slot)
    if flag:
        cfg_updates[flag] = provider not in ("local", "off")
    changed_cfg = config.set_keys(brain.inst, "memory", cfg_updates)
    from .core import Brain                       # recarga completa (lição do _apply_mode)
    brain.inst = config.load(brain.inst.root)
    brain.reload()
    # CLI (`memory providers set`) não passa pelo wizard: sem este sinal, o `setup --only memoria`
    # que a saída indica vê o contêiner saudável e não recria — o config já diz local, o processo não.
    if (slot == "embeddings" and mem.get("engine") == "hindsight"
            and (mem.get("embeddings_provider") != provider or changed_env)):
        from .setup import _recreate_mark
        _recreate_mark(brain).write_text("embeddings\n", encoding="utf-8")

    return {
        "slot": slot,
        "provider": provider,
        "label": p["label"],
        "family": p.get("family", ""),
        "docker_auth": p.get("docker_auth", ""),
        "auth_command": p.get("auth_command", ""),
        "setup_hint": p.get("setup_hint", ""),
        "rate_limit_note": p.get("rate_limit_note", ""),
        "cloud": bool(flag and cfg_updates.get(flag)) or (slot == "llm"),
        "recall": rec_on,
        "env": sorted(changed_env),
        "cfg": sorted(changed_cfg),
        "rebuild_needed": rebuild,
        "models": dict(models or {}) if slot == "llm" else {},
        "warnings": warnings,
    }


def _recreate_and_verify(brain, say) -> tuple[bool, str]:
    """Recria o servidor com o .env atual e confere o LLM (health/llm). (ok, motivo)."""
    from . import memory, setup
    mem = brain.inst.cfg["memory"]
    env_file = brain.inst.env_file if brain.inst.env_file.exists() else None
    ui = setup._SayOnly(say)
    if not setup.docker_available():
        return False, "Docker/OrbStack fora do ar"
    if not setup.compose_up(memory.mode(mem), ui, env_file=env_file) or not setup.wait_hindsight(mem["url"], 120):
        return False, "o servidor de memória não voltou"
    try:
        memory.client(brain).health_llm(mem["bank"])
    except util.BrainError as e:
        if "disabled" in str(e).lower() or "ENABLE_BANK_LLM_HEALTH" in str(e):
            return True, ""                  # sonda desligada no servidor: sem como verificar, não se desfaz por isso
        return False, f"health/llm falhou: {str(e)[:160]}"
    return True, ""


def follow_latest(brain, *, http=None, now: float | None = None, force: bool = False, dry_run: bool = False,
                  recreate=None, say=print) -> dict:
    """Checagem diária: operações do LLM que seguem o padrão passam ao mais novo da linha (Haiku 5.5 → 5.6).
    Lê o catálogo (rede), regrava o slot com as fixas intactas, recria o servidor e confere o LLM; falhou =
    volta ao modelo de antes e recria de novo. Cada movimento (ou tentativa) fica no cache para o aviso do painel.
    Esforço dito pelo dono que o modelo novo não aceita cai no padrão do modelo (e o aviso diz)."""
    from . import memory, models_catalog as mc
    now = time.time() if now is None else now
    mem = brain.inst.cfg["memory"]
    provider = mem.get("llm_provider", "")
    out: dict = {"provider": provider, "moves": [], "applied": False, "reason": ""}
    if memory.mode(mem) != "full" or provider not in mc.VENDOR:
        out["reason"] = "sem LLM de laboratório no modo full — nada a acompanhar"
        return out
    data = mc.load_cache(brain)
    if not force and now - float(data.get("follow_at") or 0) < mc.TTL_S:
        out["reason"] = "conferido há menos de 24 h"
        return out
    cat = mc.catalog(brain, provider, refresh=True, http=http, now=now)
    data = mc.load_cache(brain)
    data["follow_at"] = now
    mc._save_cache(brain, data)
    if cat.get("error") and not cat.get("models"):
        out["reason"] = f"catálogo indisponível ({cat['error']})"
        return out
    cur = models_of(mem.get("llm_models", ""))
    pinned = pinned_ops(brain)
    explicit = {op: cur[op] for op in pinned if cur.get(op)}
    want, _ = resolve_llm_models(brain, provider, models=explicit)
    out["moves"] = [{"op": op, "from": cur.get(op, ""), "to": m} for op, m in want.items() if cur.get(op) != m]
    if not out["moves"] or dry_run:
        out["reason"] = "já no mais novo" if not out["moves"] else "simulação"
        return out
    eff = efforts_of(mem.get("llm_effort", ""))
    snap_env = config.load_env(brain.inst)
    snap_cfg = {k: mem.get(k) for k in ("llm_models", "llm_pinned", "llm_follow_v", "llm_effort")}
    note = ""
    try:
        set_slot(brain, "llm", provider, models=explicit, effort=eff.get("default", ""),
                 efforts={k: v for k, v in eff.items() if k != "default"})
    except util.BrainError:
        set_slot(brain, "llm", provider, models=explicit)        # esforço dito não cabe no modelo novo
        note = "o esforço que você fixou não existe no modelo novo — voltou ao padrão do modelo"
    ok, why = (recreate or _recreate_and_verify)(brain, say)
    if not ok:
        from .setup import set_env
        keys = {k for k in config.load_env(brain.inst) if k.startswith("HINDSIGHT_API_")}
        set_env(brain.inst, {k: v for k, v in snap_env.items() if k in keys or k.startswith("HINDSIGHT_API_")},
                unset=[k for k in keys if k not in snap_env])
        config.set_keys(brain.inst, "memory", snap_cfg)
        brain.inst = config.load(brain.inst.root)
        brain.reload()
        (recreate or _recreate_and_verify)(brain, say)
        note = f"não aplicou ({why}) — voltou ao modelo de antes"
    out.update(applied=ok, reason=note or "aplicado")
    mc.record_move(brain, {"at": now, "provider": provider, "moves": out["moves"], "ok": ok, "note": note})
    return out


def env_migration_pending(mem: dict) -> bool:
    """O config/.env do LLM ainda está no formato de antes da 2.62 (sem `llm_follow_v`)?"""
    return mem.get("llm_provider", "") in PROVIDERS["llm"] and int(mem.get("llm_follow_v") or 0) < 1


def migrate_env(brain) -> list[str]:
    """Reescreve o slot LLM no formato da 2.62, mantendo a escolha do dono: modelos fixados continuam fixos, o resto
    passa a seguir o mais novo da linha, e o esforço vai pelo caminho que o lane aplica (na API Anthropic,
    REASONING_EFFORT — ignorado pelo servidor — vira `output_config.effort` no extra body). Chave não muda.
    Devolve as variáveis do .env que mudaram."""
    mem = brain.inst.cfg["memory"]
    if not env_migration_pending(mem):
        return []
    cur = models_of(mem.get("llm_models", ""))
    explicit = {op: cur[op] for op in pinned_ops(brain) if cur.get(op)}
    eff = efforts_of(mem.get("llm_effort", ""))
    res = set_slot(brain, "llm", mem["llm_provider"], models=explicit or None, effort=eff.get("default", ""),
                   efforts={k: v for k, v in eff.items() if k != "default"} or None)
    return list(res["env"])


def models_of(spec: str) -> dict[str, str]:
    """`llm_models` gravado → {operação: modelo}, tolerante (só para mostrar/preencher; quem valida é o
    `_parse_models`): um modelo solto é o `default`; pedaço fora das operações conhecidas é ignorado."""
    spec = (spec or "").strip()
    if not spec:
        return {}
    if "=" not in spec:
        return {"default": spec}
    ops = dict(LLM_OPS)
    out: dict[str, str] = {}
    for part in spec.split(","):
        op, sep, m = part.partition("=")
        if sep and op.strip() in ops and m.strip():
            out[op.strip()] = m.strip()
    return out


def _llm_effort_view(brain, provider: str, env: dict) -> dict:
    """Esforço e acompanhamento do LLM para a tela/CLI: nível efetivo por operação (o que está no .env), o que o
    dono fixou, os níveis de cada modelo em uso e da lista do catálogo, e quem segue o mais novo."""
    from . import models_catalog as mc
    mem = brain.inst.cfg["memory"]
    ops = models_of(mem.get("llm_models", ""))
    dflt = ops.get("default") or next(iter(ops.values()), "") if ops else ""
    lane = mc.lane(provider)
    cat = (mc.load_cache(brain).get("providers") or {}).get(provider) or {}
    level: dict[str, str] = {}
    for op, _ in LLM_OPS:
        raw = ""
        if lane in ("reasoning", "chat"):
            raw = env.get(EFFORT_ENV[op], "")
        elif lane in _BODY_KEY:
            outer, inner = _BODY_KEY[lane]
            try:
                raw = str(((json.loads(env.get(BODY_ENV[op]) or "{}") or {}).get(outer) or {}).get(inner) or "")
            except (ValueError, AttributeError):
                raw = ""
        level[op] = raw.lower()
    g = level.get("default", "")
    effective = {op: (level[op] or g) for op, _ in LLM_OPS}
    in_use = {op: ops.get(op) or dflt for op, _ in LLM_OPS}
    models = sorted({m for m in in_use.values() if m} | {m["id"] for m in cat.get("models") or []})
    pinned = pinned_ops(brain)
    seeds = seed_models(provider)
    follow = {op: {"seed": s, "latest": mc.newest(s, cat.get("models") or [])}
              for op, s in seeds.items() if op not in pinned}
    return {
        "effort_lane": lane,
        "effort": g,
        "efforts": effective,
        "effort_explicit": efforts_of(mem.get("llm_effort", "")),
        "effort_default": (PROVIDERS["llm"].get(provider) or {}).get("effort", ""),
        "levels": {m: mc.efforts(provider, m, mc.entry(cat, m)) for m in models},
        "pinned": pinned,
        "follow": follow,
        "catalog": {"source": cat.get("source", ""), "at": cat.get("at", 0), "error": cat.get("error", ""),
                    "models": [m["id"] for m in cat.get("models") or []]},
        "moves": mc.moves(brain)[:3],
    }


def stack(brain) -> dict:
    """O stack atual, para status/TUI/painel/doctor. Chaves: só presença, nunca valor."""
    mem = brain.inst.cfg["memory"]
    env = config.load_env(brain.inst)
    out: dict = {}
    for slot in SLOTS:
        provider = mem.get(f"{slot}_provider", "") or ("off" if slot in ("reranker", "decision") else
                                                       "local" if slot == "embeddings" else "")
        p = PROVIDERS[slot].get(provider) or {}
        if slot == "llm":
            models = mem.get("llm_models", "")
            detail = models if models else (p.get("models") and "recomendados (cenário B)") or (p.get("model") or "")
        else:
            detail = mem.get(f"{slot}_model", "") or p.get("model", "") or ("—" if provider == "off" else "")
        kenv = p.get("key_env", "")
        entry = {
            "provider": provider,
            "label": p.get("label", provider),
            "model": detail,
            "cloud": (slot != "llm" and provider not in ("local", "off"))
                     or (slot == "llm" and bool(provider) and provider not in LOCAL_LLM_BLOCKED),
            "key_env": kenv,
            "key_present": bool(kenv and env.get(kenv)),
            "local": bool(p.get("local")) or (slot == "llm" and provider in LOCAL_LLM_BLOCKED),
            "managed": bool(p.get("managed")),       # chave nasce no Brain (decisor local): nunca se cola
        }
        if slot == "llm":
            entry.update({
                "family": p.get("family", ""),
                "docker_auth": p.get("docker_auth", ""),
                "auth_command": p.get("auth_command", ""),
                "cost_mode": p.get("cost_mode", ""),
                "legacy_local": provider in LOCAL_LLM_BLOCKED,
                "key_required": bool(p and p.get("key_env")),
                "setup_hint": p.get("setup_hint", ""),
                "rate_limit_note": p.get("rate_limit_note", ""),
                # o que a tela Memória preenche para editar: modelo de cada operação e o endpoint (só na wire openai)
                "ops": models_of(mem.get("llm_models", "")),
                "base_url": env.get("HINDSIGHT_API_LLM_BASE_URL", "") if p.get("wire") == "openai" else "",
            })
            entry.update(_llm_effort_view(brain, provider, env))
        elif slot in ("embeddings", "reranker"):
            entry["base_url"] = mem.get(f"{slot}_base_url", "") if provider == "custom" else ""
            if slot == "embeddings":
                dims = str(mem.get("embeddings_dimensions") or "0").strip()
                entry["dimensions"] = int(dims) if dims.isdigit() else 0
            if slot == "reranker":
                cands = str(mem.get("reranker_max_candidates") or "0").strip()
                entry["candidates"] = int(cands) if provider != "off" and cands.isdigit() else 0
                entry["inert"] = bool(mem.get("decision_recall")
                                      or env.get("HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER") == "hindsight")
        elif slot == "decision":
            rec_on = (bool(mem.get("decision_recall"))
                      or env.get("HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER") == "hindsight")
            rec_cands = int(mem.get("decision_max_candidates")
                            or env.get("HINDSIGHT_API_RERANKER_MAX_CANDIDATES") or 0)
            base_u = (env.get("HINDSIGHT_API_DECISION_MODEL_BASE_URL")
                      or mem.get("decision_base_url", "")
                      or (p.get("base_url", "") if provider == "local" else ""))
            entry.update({
                "recall": rec_on if p.get("recall") else False,
                "candidates": rec_cands if (p.get("recall") and rec_on) else 0,
                "base_url": base_u if provider == "local" else "",
                # chave de cada provedor de nuvem (presença): a tela troca de provedor sem pedir a que já existe
                "keys": {k: decision_key_ready(k, env, mem) for k in DECISION_CLOUD},
                "key_present": decision_key_ready(provider, env, mem) if provider in DECISION_CLOUD else
                               entry["key_present"],
            })
        out[slot] = entry
    return out


_AUTH_CACHE: dict = {"at": 0.0, "probed": False, "value": None}


def reset_auth_cache() -> None:
    """Zera o cache da sonda de container (para isolamento em testes)."""
    _AUTH_CACHE.update(at=0.0, probed=False, value=None)


def _container_store(run=None) -> bool | None:
    """O store de credencial existe no servidor de memória? True/False; None = sem como ver
    (Docker fora ou container ausente). Resultado guardado 60 s (o painel consulta a cada passo)."""
    now = time.time()
    if not _AUTH_CACHE["probed"] or now - _AUTH_CACHE["at"] > 60:
        try:
            res = (run or subprocess.run)(
                ["docker", "exec", "hindsight", "sh", "-c", "test -f $HOME/.hindsight/xai_oauth.json"],
                capture_output=True, text=True, timeout=10, check=False)
            _AUTH_CACHE.update(
                at=now,
                probed=True,
                value=(res.returncode == 0) if hasattr(res, "returncode") else bool(res),
            )
        except Exception:                                          # noqa: BLE001 — docker ausente/lento
            _AUTH_CACHE.update(at=now, probed=True, value=None)
    return _AUTH_CACHE["value"]


def auth_state(brain, run=None) -> dict[str, str]:
    """Estado da credencial do provedor de LLM por assinatura (o access token o servidor
    renova sozinho; o que morre e pede dono é o login/token raiz — é isso que se vigia).
    `state`: ok (pronta) · pending (falta autenticar — `fix` carrega o comando) ·
             unknown (não deu para verificar agora) · manual (sem verificação automática) ·
             unavailable (indisponível no Docker) · na (o slot não é assinatura)."""
    provider = brain.inst.cfg["memory"].get("llm_provider", "")
    p = PROVIDERS["llm"].get(provider) or {}
    out: dict = {"provider": provider, "family": p.get("family", ""), "flow": AUTH_FLOWS.get(provider, ""),
                 "docker_auth": p.get("docker_auth", ""), "auth_command": p.get("auth_command", ""),
                 "state": "na", "note": "", "fix": ""}
    if p.get("family") != "subscription":
        return out
    if provider == "claude-code":
        env = config.load_env(brain.inst)
        if env.get("HINDSIGHT_API_LLM_API_KEY"):
            out.update(state="ok", note="token de longo prazo no config/.env")
        else:
            out.update(state="pending", fix="brain memory auth claude-code",
                       note="sem token no config/.env (gere com `claude setup-token`)")
        return out
    if provider == "xai-oauth":
        found = _container_store(run)
        if found is None:
            out.update(state="unknown", note="servidor de memória fora do ar — verifica ao subir")
        elif found:
            out.update(state="ok", note="login ativo no servidor de memória (renova sozinho)")
        else:
            out.update(state="pending", fix="brain memory auth xai-oauth",
                       note="sem login no servidor de memória")
        return out
    out.update(state="manual", note=p.get("setup_hint", ""), fix=p.get("auth_command", ""))
    return out


def _fmt_models(s: str) -> str:
    return s.replace(",", " · ") if s else ""


def _lms_state() -> str:
    """`up` · `installed` · `missing` — estado do LM Studio na máquina (probe de :1234)."""
    from . import setup                                        # lazy: setup importa providers
    return setup.lmstudio_state()


def cli(args, brain) -> None:
    if getattr(args, "pcmd", "") == "set":
        if args.slot == "embeddings" and args.provider in PROVIDERS["embeddings"] and embeddings_change_pending(
                brain, args.provider, args.model or PROVIDERS["embeddings"][args.provider].get("model", ""),
                int(args.dimensions or PROVIDERS["embeddings"][args.provider].get("dimensions", 0) or 0)):
            print(f"  ⚠ {rebuild_warning(brain)}")                 # antes de gravar: quem desiste ainda pode
        res = set_slot(brain, args.slot, args.provider, model=args.model or "",
                       models=_parse_models(args.models) if args.models else None,
                       base_url=args.base_url or "", dimensions=args.dimensions or 0,
                       candidates=args.candidates or 0, key=args.key,
                       recall=getattr(args, "recall", None), effort=getattr(args, "effort", None) or "",
                       efforts=_parse_efforts(args.efforts) if getattr(args, "efforts", None) else None)
        print(f"✓ {res['slot']} → {res['label']}")
        if res.get("models"):
            print(f"  modelos: {_fmt_models(_fmt_spec(res['models']))}")
        for w in res.get("warnings") or []:
            print(f"  ⚠ {w}")
        if res["env"]:
            print(f"  .env: {', '.join(res['env'])} (valor não impresso)")
        if res["cfg"]:
            print(f"  [memory]: {', '.join(res['cfg'])}")
        if res.get("family") == "subscription":
            if res.get("setup_hint"):
                print(f"  setup: {res['setup_hint']}")
            if res.get("auth_command") and res.get("docker_auth") == "manual":
                print(f"  comando: {res['auth_command']}")
            if res.get("rate_limit_note"):
                print(f"  limite: {res['rate_limit_note']}")
        from .memory import mode as _mem_mode
        _is_full = _mem_mode(brain.inst.cfg["memory"]) == "full"
        _full = " -f services/compose.full.yaml" if _is_full else ""
        _recreate = f"docker compose -f services/compose.yaml{_full} --env-file config/.env up -d"
        if res["cloud"]:
            print("  ⚠ egress: texto do vault vai para a API do provedor — recreate do container aplica "
                  f"({_recreate})")
        elif res["slot"] == "embeddings" and res["provider"] == "local":
            _egress = ("embeddings local — os vetores não saem da máquina; o LLM continua na nuvem (o texto do "
                       "vault vai a ele no full)" if _is_full else "embeddings local — nada sai da máquina")
            print(f"  {_egress}")
            _state = _lms_state()
            if _state == "up":
                print("  ✓ LM Studio respondendo em :1234")
            else:
                print(f"  ⚠ LM Studio {'instalado com o servidor desligado' if _state == 'installed' else 'ausente'} — "
                      "`brain setup --only memoria` sobe e configura o bge-m3 antes de recriar o contêiner "
                      "(sem ele o contêiner morre no boot)")
            print(f"  próximo passo: {_recreate}")
        if res["rebuild_needed"]:
            print("  → depois de recriar o contêiner: `brain memory rebuild`"
                  + (f" — {REBUILD_COST_NOTE}" if _is_full else ""))
        return
    if getattr(args, "pcmd", "") == "catalog":
        _cli_catalog(args, brain)
        return
    st = stack(brain)
    if getattr(args, "json", False):
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return
    icons = dict(SLOT_LABELS)
    for slot in SLOTS:
        s = st[slot]
        if slot == "llm" and s.get("family") == "subscription":
            key = " · assinatura (sem chave de API)"
        else:
            key = " · chave ok" if s["key_present"] else (" · sem chave" if s["key_env"] else "")
        cloud = " · ☁ egress" if s["cloud"] else (" · local" if s["local"] else "")
        name = s["label"] or "—"
        print(f"{icons[slot]}: {name}{cloud}{key}")
        if s["model"] and s["model"] != "—":
            print(f"  modelo: {_fmt_models(s['model'])}")
        if slot == "decision" and s.get("recall"):
            print(f"  recall: ligado (top-{s.get('candidates') or '?'} candidatos · sem fallback para RRF)")
        if slot == "decision" and s.get("base_url"):
            print(f"  base_url: {s['base_url']}")
        if slot == "reranker" and s.get("inert"):
            print("  nota: inerte enquanto o decisor estiver ligado no recall (.env preservado)")
        if slot == "llm" and s.get("effort_lane"):
            eff = s.get("efforts") or {}
            shown = " · ".join(f"{op}={eff[op]}" for op, _ in LLM_OPS if op != "default" and eff.get(op)
                               and eff[op] != eff.get("default"))
            print(f"  esforço: {eff.get('default') or 'padrão do modelo'}" + (f" · {shown}" if shown else ""))
        if slot == "llm" and s.get("provider"):
            fol = [op for op in (s.get("follow") or {})]
            if fol:
                print(f"  acompanha o mais novo da linha: {', '.join(fol)}"
                      + (f" · fixos: {', '.join(s['pinned'])}" if s.get("pinned") else ""))
        if slot == "llm" and s.get("rate_limit_note"):
            print(f"  nota: {s['rate_limit_note']}")
    print("\nProvedores LLM disponíveis (modo full):")
    print("  Assinatura (sem chave de API):")
    for pid, p in PROVIDERS["llm"].items():
        if p.get("family") == "subscription":
            print(f"    {pid:<16} {p['label']}")
    print("  Chave de API:")
    for pid, p in PROVIDERS["llm"].items():
        if p.get("family") == "key":
            print(f"    {pid:<16} {p['label']}")


def _parse_efforts(spec: str) -> dict:
    """`retain=low,reflect=high` → dict (ops válidas; o nível o `effort_plan` confere contra o modelo)."""
    out: dict = {}
    for part in spec.split(","):
        op, sep, lv = part.partition("=")
        op = op.strip()
        if not sep or op not in dict(LLM_OPS) or not lv.strip():
            raise util.BrainError(f"--efforts aceita {','.join(op for op, _ in LLM_OPS)}=<nível> — veio {part!r}",
                                  code=4)
        out[op] = lv.strip().lower()
    return out


def _cli_catalog(args, brain) -> None:
    """`brain memory providers catalog` — lista viva, o mais novo de cada linha e os níveis de esforço."""
    from . import models_catalog as mc
    provider = getattr(args, "provider", None) or brain.inst.cfg["memory"].get("llm_provider", "")
    if provider not in PROVIDERS["llm"]:
        raise util.BrainError("escolha o provedor: --provider anthropic|claude-code|openai|chatgpt|xai-oauth|gemini",
                              code=4)
    if getattr(args, "follow", False):
        res = follow_latest(brain, force=True, dry_run=getattr(args, "dry_run", False))
        if getattr(args, "json", False):
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return
        for m in res["moves"]:
            print(f"  {m['op']}: {m['from'] or '—'} → {m['to']}")
        print(f"{'✓' if res['applied'] else '•'} {res['reason']}")
        return
    cat = mc.catalog(brain, provider, refresh=getattr(args, "refresh", False))
    seeds = seed_models(provider)
    rows = [{"id": m["id"], "line": m["line"], "efforts": mc.efforts(provider, m["id"], m)}
            for m in cat.get("models") or []]
    if getattr(args, "json", False):
        print(json.dumps({"provider": provider, "source": cat.get("source"), "at": cat.get("at"),
                          "error": cat.get("error", ""), "lane": mc.lane(provider),
                          "defaults": {op: mc.newest(s, cat.get("models") or []) for op, s in seeds.items()},
                          "models": rows}, ensure_ascii=False, indent=2))
        return
    if not mc.VENDOR.get(provider):
        print(f"{provider}: sem lista viva (só os modelos do registro) · esforço: "
              + ("ajustável" if mc.lane(provider) else "não ajustável pelo Brain"))
        return
    src = {"openrouter": "catálogo público do OpenRouter", "anthropic": "API da Anthropic", "openai": "API da OpenAI",
           "google": "API do Gemini"}.get(cat.get("source", ""), cat.get("source") or "—")
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(cat["at"])) if cat.get("at") else "—"
    print(f"{provider} · fonte: {src} · lida em {when}" + (f" · ⚠ {cat['error']}" if cat.get("error") else ""))
    for op, s in seeds.items():
        print(f"  padrão {op}: {s} → {mc.newest(s, cat.get('models') or [])} (o mais novo da linha)")
    for r in rows:
        e = r["efforts"]
        lv = ", ".join(e["levels"]) if e["levels"] else ("sem esforço" if e["known"] else "não consta")
        print(f"  {r['id']:<26} {r['line']:<18} {lv}" + (f" · padrão {e['default']}" if e["default"] else "")
              + (" · herdado" if e["inferred"] else "") + (" · API" if e["source"] == "api" else ""))


def _parse_models(spec: str) -> dict:
    """`retain=m1,consolidation=m2` → dict (ops válidas do LLM_OPS)."""
    out: dict = {}
    for part in spec.split(","):
        op, sep, m = part.partition("=")
        op = op.strip()
        if not sep or op not in dict(LLM_OPS) or not m.strip():
            raise util.BrainError(f"--models aceita {','.join(op for op, _ in LLM_OPS)} — veio {part!r}", code=4)
        out[op] = m.strip()
    return out
