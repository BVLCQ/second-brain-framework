#!/usr/bin/env python3
"""Gerencia a memória dos modelos do LM Studio: descarrega quando ociosos, sem ficar recarregando à toa.

Rodado pelo LaunchAgent com.segundo-cerebro.idle a cada minuto.

"Ocupado" = o modelo está gerando/processando ou tem fila no LM Studio, OU há operação
pendente/em processamento nos bancos do Hindsight (retain, consolidação — usam LLM e embeddings).
Ocupado nunca é interrompido. O servidor do LM Studio continua no ar; o modelo descarregado volta
sozinho (JIT) na próxima chamada.

Cada modelo tem seu tempo de ociosidade antes de sair da memória, que se adapta ao uso:
  - base: LLM 5 min, embedding 15 min (o hook de recall usa o embedding a cada prompt do Claude)
  - se o modelo voltar a ser carregado menos de 15 min depois de descarregado (descarregamos
    cedo demais), o tempo dobra, até 60 min
  - se ele ficar fora mais que isso, o tempo cai pela metade, até a base
  - com pouca memória livre (kern.memorystatus_level < 25%), vale metade da base, sem o dobro

Só biblioteca padrão, compatível com o python3 do sistema (3.9).

Ajustes por variável de ambiente (opcionais, no plist):
  BRAIN_IDLE_LLM_MIN       base do LLM em minutos, padrão 5
  BRAIN_IDLE_EMBED_MIN     base do embedding em minutos, padrão 15
  BRAIN_IDLE_MAX_MIN       teto do tempo adaptado, padrão 60
  BRAIN_IDLE_KEEP          identificadores que nunca descarregam, separados por vírgula
  BRAIN_HINDSIGHT_URL      padrão http://127.0.0.1:8888
  BRAIN_RECALL_BANKS       bancos a checar, padrão brain-mem,brain-raw
  BRAIN_IDLE_UNLOAD_OFF=1  desliga (ou ~/.brain-watchdog-off pausa tudo)

Uso: idle_unload.py <arquivo-de-estado> [--dry-run]
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

LMS = os.environ.get("BRAIN_LMS") or str(Path.home() / ".lmstudio/bin/lms")
URL = os.environ.get("BRAIN_HINDSIGHT_URL", "http://127.0.0.1:8888").rstrip("/")
BANKS = [b for b in os.environ.get("BRAIN_RECALL_BANKS", "brain-mem,brain-raw").split(",") if b]
BASE_S = {"llm": float(os.environ.get("BRAIN_IDLE_LLM_MIN", "5")) * 60,
          "embedding": float(os.environ.get("BRAIN_IDLE_EMBED_MIN", "15")) * 60}
MAX_S = float(os.environ.get("BRAIN_IDLE_MAX_MIN", "60")) * 60
REWARM_S = 15 * 60          # recarregado antes disto = descarregamos cedo demais
PRESSURE_LEVEL = 25         # kern.memorystatus_level abaixo disto = pouca memória livre
KEEP = {k.strip() for k in os.environ.get("BRAIN_IDLE_KEEP", "").split(",") if k.strip()}


def log(msg):
    print(time.strftime("%F %T"), "idle:", msg, flush=True)


def loaded_models():
    out = subprocess.run([LMS, "ps", "--json"], capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise RuntimeError(f"lms ps falhou: {out.stderr.strip()[:200]}")
    return json.loads(out.stdout or "[]")


def hindsight_busy():
    """Operações pendentes/em andamento por banco; {} se o Hindsight estiver fora (fora = sem trabalho)."""
    busy = {}
    for bank in BANKS:
        try:
            with urllib.request.urlopen(f"{URL}/v1/default/banks/{bank}/stats", timeout=5) as r:
                ops = json.load(r).get("operations_by_status") or {}
        except Exception:
            continue
        n = int(ops.get("pending", 0)) + int(ops.get("processing", 0))
        if n:
            busy[bank] = n
    return busy


def memory_level():
    """% de memória disponível segundo o kernel (100 = folga total); None se não der para ler."""
    try:
        out = subprocess.run(["/usr/sbin/sysctl", "-n", "kern.memorystatus_level"],
                             capture_output=True, text=True, timeout=5)
        return int(out.stdout.strip())
    except Exception:
        return None


def main(argv):
    if os.environ.get("BRAIN_IDLE_UNLOAD_OFF") == "1" or (Path.home() / ".brain-watchdog-off").exists():
        return 0
    if len(argv) < 2:
        return 0
    state_path, dry = Path(argv[1]), "--dry-run" in argv
    now = time.time()
    try:
        state = json.loads(state_path.read_text()).get("models", {})
    except Exception:
        state = {}
    if not isinstance(state, dict):
        state = {}

    models = loaded_models()
    hs = hindsight_busy()
    level = memory_level()
    pressure = level is not None and level < PRESSURE_LEVEL
    loaded = {m["identifier"] for m in models}

    for m in models:
        ident = m["identifier"]
        base = BASE_S["embedding" if m.get("type") == "embedding" else "llm"]
        st = state.get(ident)
        if not isinstance(st, dict):
            st = state[ident] = {}
        # novo (ou entrada truncada no estado): conta como recém-usado — sem isto um KeyError a cada minuto
        # derrubava a rodada inteira e nenhum modelo voltava a ser descarregado
        st.setdefault("timeout_s", base)
        st.setdefault("last_busy", now)

        # voltou depois de descarregado por nós? ajusta o tempo dele
        if st.get("unloaded_at"):
            gap = now - st.pop("unloaded_at")
            old = st["timeout_s"]
            st["timeout_s"] = min(old * 2, MAX_S) if gap < REWARM_S else max(old / 2, base)
            st["last_busy"] = now
            if st["timeout_s"] != old:
                log(f"{ident} recarregado {gap / 60:.0f} min após descarregar — ociosidade "
                    f"{old / 60:.0f} → {st['timeout_s'] / 60:.0f} min")

        if m.get("lastUsedTime"):
            st["last_busy"] = max(st["last_busy"], m["lastUsedTime"] / 1000)
        working = m.get("status") not in (None, "idle") or int(m.get("queued") or 0) > 0
        if working or hs:
            st["last_busy"] = now

        limit = base / 2 if pressure else st["timeout_s"]
        idle_for = now - st["last_busy"]
        if dry:
            why = f"ocupado ({m.get('status')}, fila {m.get('queued') or 0}, hindsight {hs or '-'})" if working or hs \
                else f"ocioso {idle_for / 60:.1f}/{limit / 60:.0f} min"
            log(f"{ident}: {why}" + (f" · memória livre {level}% (pressão)" if pressure else ""))
        if ident in KEEP or working or hs or idle_for < limit:
            continue
        if dry:
            log(f"(dry-run) descarregaria {ident}")
            continue
        r = subprocess.run([LMS, "unload", ident], capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            st["unloaded_at"] = now
            log(f"descarregado {ident} — ocioso há {idle_for / 60:.0f} min (limite {limit / 60:.0f}"
                + (f", memória livre {level}%)" if pressure else ")"))
        else:
            log(f"falha ao descarregar {ident}: {r.stderr.strip()[:200]}")

    # esquece quem saiu por outro caminho (TTL do LM Studio, à mão); guarda quem nós descarregamos
    state = {k: v for k, v in state.items() if isinstance(v, dict) and (k in loaded or v.get("unloaded_at"))}
    for k, v in list(state.items()):
        if k not in loaded and now - v["unloaded_at"] > 24 * 3600:
            del state[k]

    if not dry:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = state_path.with_name(state_path.name + ".tmp")   # troca atômica: morte no meio não trunca o estado
        tmp.write_text(json.dumps({"models": state}, indent=1))
        os.replace(str(tmp), str(state_path))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception as e:  # nunca derrubar o agendador por causa disto
        log(f"erro: {e}")
        sys.exit(0)
