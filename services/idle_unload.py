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
  BRAIN_RECALL_BANKS       bancos a checar, padrão brain
  BRAIN_IDLE_UNLOAD_OFF=1  desliga (ou ~/.brain-watchdog-off pausa tudo)

Uso: idle_unload.py <arquivo-de-estado> [--dry-run]
"""
import json
import math
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

LMS = os.environ.get("BRAIN_LMS") or str(Path.home() / ".lmstudio/bin/lms")
URL = os.environ.get("BRAIN_HINDSIGHT_URL", "http://127.0.0.1:8888").rstrip("/")
BANKS = [b for b in os.environ.get("BRAIN_RECALL_BANKS", "brain").split(",") if b]
BASE_S = {"llm": float(os.environ.get("BRAIN_IDLE_LLM_MIN", "5")) * 60,
          "embedding": float(os.environ.get("BRAIN_IDLE_EMBED_MIN", "15")) * 60}
MAX_S = float(os.environ.get("BRAIN_IDLE_MAX_MIN", "60")) * 60
REWARM_S = 15 * 60          # recarregado antes disto = descarregamos cedo demais
PRESSURE_LEVEL = 25         # kern.memorystatus_level abaixo disto = pouca memória livre
KEEP = {k.strip() for k in os.environ.get("BRAIN_IDLE_KEEP", "").split(",") if k.strip()}


def log(msg):
    print(time.strftime("%F %T"), "idle:", msg, flush=True)


def _num(val, default, *, min_v=0.0) -> float:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return float(default)
    f = float(val)
    if not math.isfinite(f) or f < min_v:
        return float(default)
    return f


def loaded_models():
    out = subprocess.run([LMS, "ps", "--json"], capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise RuntimeError(f"lms ps falhou: {out.stderr.strip()[:200]}")
    data = json.loads(out.stdout or "[]")
    if not isinstance(data, list):
        raise RuntimeError(f"lms ps --json retornou {type(data).__name__}, esperado list")
    return data


def hindsight_busy():
    """Operações pendentes/em andamento por banco; {} se o Hindsight estiver fora (fora = sem trabalho)."""
    busy = {}
    for bank in BANKS:
        try:
            with urllib.request.urlopen(f"{URL}/v1/default/banks/{bank}/stats", timeout=5) as r:
                raw = r.read()
        except Exception:
            continue
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError(f"payload {type(payload).__name__}")
            ops = payload.get("operations_by_status")
            if ops is None:
                ops = {}
            if not isinstance(ops, dict):
                raise ValueError(f"operations_by_status {type(ops).__name__}")
            pending_raw = ops.get("pending", 0)
            proc_raw = ops.get("processing", 0)
            if isinstance(pending_raw, bool) or isinstance(proc_raw, bool):
                raise ValueError("contagem booleana")
            pending = int(pending_raw)
            processing = int(proc_raw)
            if pending < 0 or processing < 0:
                raise ValueError(f"contagem negativa ({pending}, {processing})")
            n = pending + processing
        except Exception as e:
            log(f"hindsight {bank}: resposta malformada ({e})")
            continue
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


def _sanitize_state(raw_state):
    if not isinstance(raw_state, dict):
        return {}
    clean = {}
    for k, v in raw_state.items():
        if not isinstance(k, str) or not k.strip() or not isinstance(v, dict):
            continue
        entry = {}
        t = _num(v.get("timeout_s"), -1.0, min_v=0.0)
        if t > 0:
            entry["timeout_s"] = t
        lb = _num(v.get("last_busy"), -1.0, min_v=0.0)
        if lb >= 0:
            entry["last_busy"] = lb
        ua = _num(v.get("unloaded_at"), -1.0, min_v=0.0)
        if ua > 0:
            entry["unloaded_at"] = ua
        clean[k] = entry
    return clean


def maybe_stop_decider(hindsight_busy, now, *, dry=False, up=None, stop=None, flag=None):
    """Para o decisor local quando o Hindsight está ocioso, para não segurar memória à toa.

    O watchdog não religa enquanto o arquivo de ociosidade existir. Abrir o Brain apaga o arquivo.
    """
    idle_s = float(os.environ.get("BRAIN_IDLE_DECIDER_MIN", "15")) * 60
    flag = flag or (Path(os.environ.get("BRAIN_DIR", "")) / ".decider" / "idle-stopped" if os.environ.get("BRAIN_DIR") else None)
    if up is None:
        up = _decider_up
    if stop is None:
        stop = _stop_decider
    if hindsight_busy:
        if flag is not None and flag.exists():
            try:
                flag.unlink()
            except OSError:
                pass
        return "ocupado"
    if not up():
        return "fora"
    if dry:
        log("(dry-run) pararia o decisor local — ocioso")
        return "pararia"
    stop()
    if flag is not None:
        try:
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text(str(now), encoding="utf-8")
        except OSError:
            pass
    log(f"decisor local parado — ocioso (limite {idle_s / 60:.0f} min)")
    return "parado"


def _decider_up():
    url = os.environ.get("BRAIN_DECIDER_URL", "http://127.0.0.1:8000/health")
    try:
        with urllib.request.urlopen(url, timeout=2):
            return True
    except Exception:
        return False


def _stop_decider():
    import shutil
    if shutil.which("launchctl"):
        uid = os.getuid()
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/com.segundo-cerebro.decider"],
                       capture_output=True, text=True, timeout=20)
        return
    subprocess.run(["systemctl", "--user", "stop", "segundo-cerebro-decider.service"],
                   capture_output=True, text=True, timeout=20)


def main(argv):
    if os.environ.get("BRAIN_IDLE_UNLOAD_OFF") == "1" or (Path.home() / ".brain-watchdog-off").exists():
        return 0
    if len(argv) < 2:
        return 0
    state_path, dry = Path(argv[1]), "--dry-run" in argv
    now = time.time()
    state_loaded = False
    try:
        parsed = json.loads(state_path.read_text())
        raw_models = parsed.get("models", {}) if isinstance(parsed, dict) else {}
    except Exception:
        raw_models = {}
    state = _sanitize_state(raw_models)
    state_loaded = True

    loaded = None
    try:
        models = loaded_models()
        hs = hindsight_busy()
        level = memory_level()
        pressure = level is not None and level < PRESSURE_LEVEL
        loaded = {
            m["identifier"] for m in models
            if isinstance(m, dict) and isinstance(m.get("identifier"), str) and m["identifier"].strip()
        }

        for m in models:
            try:
                if not isinstance(m, dict):
                    log(f"entrada de modelo inválida ({type(m).__name__}), ignorada")
                    continue
                ident = m.get("identifier")
                if not isinstance(ident, str) or not ident.strip():
                    log("entrada de modelo sem identifier válido, ignorada")
                    continue
                base = BASE_S["embedding" if m.get("type") == "embedding" else "llm"]
                st = state.get(ident)
                if not isinstance(st, dict):
                    st = state[ident] = {}
                # novo (ou entrada truncada/corrompida no estado): conta como recém-usado
                st["timeout_s"] = _num(st.get("timeout_s"), base, min_v=1.0 if base >= 1.0 else 0.0)
                st["last_busy"] = _num(st.get("last_busy"), now, min_v=0.0)

                # voltou depois de descarregado por nós? ajusta o tempo dele
                unloaded_at = _num(st.pop("unloaded_at", None), 0.0, min_v=0.0)
                if unloaded_at > 0:
                    gap = max(0.0, now - unloaded_at)
                    old = st["timeout_s"]
                    st["timeout_s"] = min(old * 2, MAX_S) if gap < REWARM_S else max(old / 2, base)
                    st["last_busy"] = now
                    if st["timeout_s"] != old:
                        log(f"{ident} recarregado {gap / 60:.0f} min após descarregar — ociosidade "
                            f"{old / 60:.0f} → {st['timeout_s'] / 60:.0f} min")

                last_used = _num(m.get("lastUsedTime"), 0.0, min_v=0.0)
                if last_used > 0:
                    st["last_busy"] = max(st["last_busy"], last_used / 1000)
                queued = _num(m.get("queued"), 0.0, min_v=0.0)
                working = m.get("status") not in (None, "idle") or queued > 0
                if working or hs:
                    st["last_busy"] = now

                limit = base / 2 if pressure else st["timeout_s"]
                idle_for = now - st["last_busy"]
                if dry:
                    why = f"ocupado ({m.get('status')}, fila {int(queued)}, hindsight {hs or '-'})" if working or hs \
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
            except Exception as e:
                log(f"erro ao processar modelo: {e}")
                continue

        # esquece quem saiu por outro caminho (TTL do LM Studio, à mão); guarda quem nós descarregamos
        state = {k: v for k, v in state.items() if isinstance(v, dict) and (k in loaded or v.get("unloaded_at"))}
        for k, v in list(state.items()):
            if k not in loaded:
                ua = _num(v.get("unloaded_at"), -1.0, min_v=0.0)
                if ua <= 0 or now - ua > 24 * 3600:
                    del state[k]
        decider_note = maybe_stop_decider(bool(hs), now, dry=dry)
    finally:
        if not dry and state_loaded:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = state_path.with_name(state_path.name + ".tmp")   # troca atômica: morte no meio não trunca o estado
            tmp.write_text(json.dumps({"models": state}, indent=1))
            os.replace(str(tmp), str(state_path))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception as e:
        log(f"erro: {e}")
        sys.exit(1)
