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

# Modelo default de cada provedor no SERVIDOR PINADO (digest do services/compose.yaml) —
# sondado ao vivo da imagem (a tabela mora em hindsight_api.config.PROVIDER_DEFAULT_MODELS).
# O docs upstream anda na frente (gpt-5-nano · claude-haiku-5-5 · gemini-3.8-flash ·
# glm-5.3-flash…): vazio no Brain = o default do servidor que você roda; o campo Modelo
# aceita qualquer um dos novos. O que o registro do Brain cura (anthropic cenário B,
# fireworks deepseek-v4p1) TEM PRECEDÊNCIA sobre esta tabela (é gravado explícito no .env).
SERVER_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5",
    "gemini": "gemini-3.5-flash",
    "zai": "glm-4.5-flash",
    "fireworks": "accounts/fireworks/models/llama-v3p1-8b-instruct",
    "openrouter": "qwen/qwen3.5-9b",
    "litellm": "gpt-4o-mini",
    "openai-codex": "gpt-5.6-luna",
    "chatgpt": "gpt-6-luna",
    "claude-code": "claude-sonnet-4-5-20250929",
    "cursor": "auto",
    "github-copilot": "gpt-5.6-terra",
    "nous": "deepseek/deepseek-v4-flash",
    "xai-oauth": "grok-4.5",
}


def default_model(provider: str) -> str:
    """Modelo que o Brain aplica quando o dono deixa o campo em branco: a cura do registro
    (model/models.default) vence; senão, o default do servidor pinado; senão, vazio."""
    p = PROVIDERS["llm"].get(provider) or {}
    if p.get("model"):
        return p["model"]
    if p.get("models"):
        return p["models"].get("default", "")
    return SERVER_DEFAULT_MODELS.get(provider, "")

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
    "decision": {
        "off": {"label": "Desligado — só os tokens do próprio LLM (padrão)", "recommended": True},
        "hindsight": {"label": "Hindsight — hs-decide-1-flash · US$ 0,02/1M de entrada (corta ~40% das chamadas do LLM)",
                      "model": "hs-decide-1-flash", "recommended_cloud": True, "wire": "hindsight",
                      "note": "Trechos pequenos de memória vão à nuvem de inferência do Hindsight para julgamento "
                              "(hsk_ key em inference.hindsight.vectorize.io — por uso, sem assinatura).",
                      "key_env": "HINDSIGHT_API_DECISION_MODEL_API_KEY"},
        "local": {"label": "Local — hs-decide-1-flash (/v1/systemone, zero egress)",
                  "local": True, "wire": "hindsight", "model": "hs-decide-1-flash",
                  "base_url": "http://host.docker.internal:8000", "max_concurrent": 1,
                  "note": "Servidor local /v1/systemone (MLX, vLLM ou transformers — LM Studio e Ollama não servem "
                          "este protocolo). Nada sai da máquina.",
                  "key_env": "HINDSIGHT_API_DECISION_MODEL_API_KEY"},
    },
}

for _pid, _entry in PROVIDERS["llm"].items():
    _entry.setdefault("base_label", _entry["label"])
    _entry["label"] = derive_label(_entry)


def menu_providers(slot: str, *, include_custom: bool = True, include_unavailable: bool = False,
                   mode: str = "embed") -> list[tuple[str, dict]]:
    """Lista ordenada de provedores de um slot para wizard e painel: guiados e chave de API
    primeiro; manual e indisponível por último. `cursor` (unavailable) fica fora do cardápio
    padrão (continua aceito pela CLI)."""
    tbl = PROVIDERS.get(slot, {})
    items: list[tuple[str, dict]] = []
    for pid, info in tbl.items():
        if not include_custom and pid == "custom":
            continue
        if not include_unavailable and info.get("docker_auth") == "unavailable":
            continue
        if slot == "embeddings" and mode == "full" and (
            pid == "local" or info.get("local") or info.get("family") == "local"
        ):
            continue
        items.append((pid, info))
    items.sort(key=lambda kv: (
        1 if kv[1].get("docker_auth") in ("manual", "unavailable") else 0,
        1 if kv[1].get("docker_auth") == "unavailable" else 0,
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
             recall: bool | str | None = None) -> dict:
    """Env do .env para a escolha (sem tocar disco). Valores vazios caem fora — segredo nunca ecoa."""
    p = PROVIDERS[slot][provider]
    _validate_key(provider, p, key)
    rec = _parse_recall(recall)
    if rec is not None and slot != "decision":
        raise util.BrainError("--recall só vale no slot decision", code=4)
    if isinstance(key, str):
        key = key.strip() or None            # vazia ou só espaços = não informada, em todo slot (nada vazio chega ao .env)
    model, base_url, models = _clean(model), _clean(base_url), _clean_models(models)   # mesma regra nos demais textos
    if slot == "llm":
        if p.get("family") == "subscription":
            env = {"HINDSIGHT_API_LLM_PROVIDER": p.get("wire", provider)}
            ops = models or {}
            for op, envk in LLM_OPS:
                m = ops.get(op) or (model if op == "default" else "")
                if m:
                    env[f"HINDSIGHT_API_{envk}"] = m
            if p.get("effort"):
                env["HINDSIGHT_API_LLM_REASONING_EFFORT"] = p["effort"]
            return env
        env = {"HINDSIGHT_API_LLM_PROVIDER": "openai" if p.get("wire") == "openai" else provider}
        url = base_url or p.get("base_url", "")
        if p.get("wire") == "openai" and url:
            env["HINDSIGHT_API_LLM_BASE_URL"] = url
        ops = models or {}
        for op, envk in LLM_OPS:
            m = ops.get(op) or (model if op == "default" else "")
            if m:
                env[f"HINDSIGHT_API_{envk}"] = m
        if key and p.get("key_env"):
            env[p["key_env"]] = key
        if p.get("effort"):
            env["HINDSIGHT_API_LLM_REASONING_EFFORT"] = p["effort"]
        return env
    if slot == "embeddings":
        return _emb_env(p, model or p.get("model", ""), base_url, dimensions, key)
    if slot == "decision":
        rec_on = bool(rec)
        if rec_on and provider != "hindsight":
            raise util.BrainError(
                "decisor no recall (--recall on) só é suportado com o provedor hindsight "
                "(não disponível no decisor local ou desligado)",
                code=4,
            )
        if rec_on and (not candidates or int(candidates) <= 0):
            raise util.BrainError(
                "ligar o decisor no recall (--recall on) exige um teto explícito de candidatos (--candidates N)",
                code=4,
            )
        # off explícito = "none" (valor de fábrica do servidor pinado) — trocar de lane limpa o estado
        env = {
            "HINDSIGHT_API_DECISION_MODEL_PROVIDER": "none" if provider == "off" else p.get("wire", "hindsight"),
            "HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER": "hindsight" if rec_on else "none",
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
        if rec_on and candidates:
            env["HINDSIGHT_API_RERANKER_MAX_CANDIDATES"] = str(int(candidates))
        if key and p.get("key_env"):
            env[p["key_env"]] = key
        return env
    return _rer_env(p, model or p.get("model", ""), base_url, candidates, key)


def set_slot(brain, slot: str, provider: str, *, model: str = "", models: dict | None = None,
             base_url: str = "", dimensions: int = 0, candidates: int = 0, key: str | None = None,
             recall: bool | str | None = None) -> dict:
    """Grava a escolha: .env (wire + chave) + [memory] (provedor/modelo/flags). Devolve o resumo."""
    if slot not in SLOTS:
        raise util.BrainError(f"slot inválido: {slot!r} — use {', '.join(SLOTS)}", code=4)
    if slot == "llm" and provider in LOCAL_LLM_BLOCKED:
        raise util.BrainError(
            f"LLM local ({provider!r}) não é suportado no slot LLM — use um provedor por assinatura ou chave de API "
            "(embeddings locais continuam no modo embed)",
            code=4,
        )
    if provider not in PROVIDERS[slot]:
        raise util.BrainError(f"provedor inválido para {slot}: {provider!r} — "
                              f"{', '.join(PROVIDERS[slot])}", code=4)
    p = PROVIDERS[slot][provider]
    model, base_url, models = _clean(model), _clean(base_url), _clean_models(models)   # mesma regra da chave
    is_sub = slot == "llm" and p.get("family") == "subscription"
    if slot == "embeddings" and provider == "local":
        from .memory import mode as _mem_mode                   # lazy: evita ciclo em tempo de import
        if _mem_mode(brain.inst.cfg["memory"]) == "full":
            raise util.BrainError("no modo full os embeddings são de nuvem — fireworks (qwen3-embedding-8b) "
                                  "ou openai; o bge-m3 local é do modo embed (guides/memory.md)", code=4)
    if slot == "llm" and not is_sub and not (models or model) and not p.get("models"):
        # vazio = recomendado do provedor (tabela do servidor pinado em SERVER_DEFAULT_MODELS) —
        # gravado EXPLÍCITO no .env: o que aplicou é o que o stack mostra
        model = default_model(provider)
        if not model:
            raise util.BrainError("provedor custom precisa de --model (ou --models por operação)", code=4)
    if slot == "embeddings" and provider in ("custom",) and not (model and (base_url or p.get("base_url"))):
        raise util.BrainError("embeddings custom exige --model e --base-url", code=4)

    mem = brain.inst.cfg["memory"]
    prev = {"provider": mem.get(f"{slot}_provider", ""), "model": mem.get(f"{slot}_model", "")}
    if slot == "llm" and not (models or model) and p.get("models"):
        models = dict(p["models"])              # recomendados por operação (cenário B) como default
    env_updates = slot_env(slot, provider, model=model, models=models, base_url=base_url,
                           dimensions=dimensions, candidates=candidates, key=key, recall=recall)
    cur_env = config.load_env(brain.inst)
    # #159: não sobrescreve um .env existente que já tem HINDSIGHT_API_LLM_REASONING_EFFORT=max
    if slot == "llm" and cur_env.get("HINDSIGHT_API_LLM_REASONING_EFFORT", "").strip().lower() == "max":
        env_updates.pop("HINDSIGHT_API_LLM_REASONING_EFFORT", None)
    _guard_env_updates(env_updates)
    unset_env: list[str] = []
    rec_on = False
    if slot == "decision":
        rec_on = bool(_parse_recall(recall)) and provider == "hindsight"
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
        if models:
            cfg_updates["llm_models"] = ",".join(f"{op}={m}" for op, m in models.items() if m)
        elif model:
            cfg_updates["llm_models"] = model
        elif not is_sub:
            cfg_updates["llm_models"] = ""
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
        if slot == "embeddings" and (dimensions or p.get("dimensions")):
            cfg_updates["embeddings_dimensions"] = dimensions or p.get("dimensions", 0)
        if slot == "reranker" and (candidates or p.get("candidates")):
            cfg_updates["reranker_max_candidates"] = candidates or p.get("candidates", 0)
    flag = CLOUD_FLAGS.get(slot)
    if flag:
        cfg_updates[flag] = provider not in ("local", "off")
    changed_cfg = config.set_keys(brain.inst, "memory", cfg_updates)
    from .core import Brain                       # recarga completa (lição do _apply_mode)
    brain.inst = config.load(brain.inst.root)
    brain.reload()

    rebuild = (slot == "embeddings"
               and mem.get("engine") == "hindsight"
               and (prev["provider"] != provider or (prev["model"] and prev["model"] != (model or p.get("model", ""))))
               and (brain.inst.root / ".memory-state.json").exists())
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
            })
        elif slot == "decision":
            rec_on = (bool(mem.get("decision_recall"))
                      or env.get("HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER") == "hindsight")
            rec_cands = int(mem.get("decision_max_candidates")
                            or env.get("HINDSIGHT_API_RERANKER_MAX_CANDIDATES") or 0)
            base_u = (env.get("HINDSIGHT_API_DECISION_MODEL_BASE_URL")
                      or mem.get("decision_base_url", "")
                      or (p.get("base_url", "") if provider == "local" else ""))
            entry.update({
                "recall": rec_on if provider == "hindsight" else False,
                "candidates": rec_cands if (provider == "hindsight" and rec_on) else 0,
                "base_url": base_u if provider == "local" else "",
            })
        elif slot == "reranker":
            entry["inert"] = bool(mem.get("decision_recall")
                                  or env.get("HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER") == "hindsight")
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


def cli(args, brain) -> None:
    if getattr(args, "pcmd", "") == "set":
        res = set_slot(brain, args.slot, args.provider, model=args.model or "",
                       models=_parse_models(args.models) if args.models else None,
                       base_url=args.base_url or "", dimensions=args.dimensions or 0,
                       candidates=args.candidates or 0, key=args.key,
                       recall=getattr(args, "recall", None))
        print(f"✓ {res['slot']} → {res['label']}")
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
        if res["cloud"]:
            from .memory import mode as _mem_mode
            _full = " -f services/compose.full.yaml" if _mem_mode(brain.inst.cfg["memory"]) == "full" else ""
            print("  ⚠ egress: texto do vault vai para a API do provedor — recreate do container aplica "
                  f"(docker compose -f services/compose.yaml{_full} --env-file config/.env up -d)")
        if res["rebuild_needed"]:
            print("  ⚠ embeddings mudaram: vetores antigos são incompatíveis — `brain memory rebuild` "
                  "re-deriva tudo do vault")
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
