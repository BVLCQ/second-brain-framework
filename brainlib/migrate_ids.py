"""`brain migrate ids` — reescreve o histórico com os prefixos declarativos (A-0146 → ACT-0146, G1 → GOAL-1, P3.2 → PROJ-3.2).

Exceção histórica e única à regra "o ledger só cresce": a instância inteira passa para os nomes novos de uma vez, com
backup antes. Depois dela o código só emite os nomes novos (ids.py); os antigos seguem aceitos na entrada.

Duas etapas, sempre nesta ordem:
  1. plan_migration — monta tudo em memória (mapa, ledger novo, arquivos reescritos, renomeações, relatório). É o dry-run.
  2. apply — backup zip íntegro → valida o ledger novo → escreve arquivos → renomeia → troca o ledger → marcador → render.

Quatro tipos de arquivo de texto, regras diferentes:
  · escritos pelo cérebro (notas, PROCESSED, PLANNING, reports, PROFILE, FRESH/notes, watch.toml): todo ID do mapa, com fronteira de palavra;
  · RAW externo (reuniões, Slack, conectores, documentos): só os IDs longos (`A-0146`); `G#`/`P#` só com --include-external,
    porque "P1" numa transcrição costuma ser outra coisa (prioridade do Jira). O dry-run lista cada ocorrência com contexto;
  · logs/ não são migrados; FRESH/ (menos notes/) é apagado e regenerado.
Só IDs que **existem** (ledger + goals.md) entram no mapa: referência solta a um ID que nunca existiu fica como está.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import ids, notes, planning, schema, util
from .core import LEDGER_REL

MARKER_REL = Path("PROCESSED") / "_ledger" / "MIGRATED-ids"
TEXT_EXT = {".md", ".txt", ".json", ".jsonl", ".csv", ".html", ".htm", ".toml", ".vtt", ".srt", ".yml", ".yaml"}
PATH_KEYS = {"raw", "source", "plan_file", "report", "path", "file"}      # caminhos: só ID longo e nome de nota
SKIP_KEYS = {"seq", "ts", "type", "date", "by", "prov", "actor"}
URL_RE = re.compile(r"^https?://", re.I)
NOTE_LEAD_RE = re.compile(r"(?:(?<=/)|^)(G\d+|P\d+(?:\.\d+)?)(?=-\d{4}-\d{2}-\d{2}-note)")
CONTEXT = 40
SAMPLE_LIMIT = 200


# ── substituição ────────────────────────────────────────────────────────────────────────────────────────
def sub_text(text: str, mapping: dict[str, str], plan_ids: bool = True) -> tuple[str, int]:
    """Troca os IDs antigos que existem no mapa, com fronteira de palavra (`P3.2` antes de `P3`). Devolve (texto, trocas)."""
    n = 0

    def long(m):
        nonlocal n
        new = mapping.get(f"{m.group(1)}-{m.group(2)}")
        if new:
            n += 1
            return new
        return m.group(0)

    def plan(m):
        nonlocal n
        new = mapping.get(m.group(0))
        if new:
            n += 1
            return new
        return m.group(0)

    text = ids.OLD_LONG_RE.sub(long, text)
    if plan_ids:
        text = ids.OLD_PLAN_RE.sub(plan, text)
    return text, n


def sub_path(text: str, mapping: dict[str, str]) -> tuple[str, int]:
    """Caminho/nome de arquivo: ID longo e o vínculo no começo do nome de nota (`P1-2026-10-09-note.md`). Nunca `P#` solto."""
    text, n = sub_text(text, mapping, plan_ids=False)
    k = 0

    def lead(m):
        nonlocal k
        new = mapping.get(m.group(1))
        if new:
            k += 1
            return new
        return m.group(0)

    return NOTE_LEAD_RE.sub(lead, text), n + k


def _walk(v, key: str, mapping: dict, count: list[int]):
    if isinstance(v, str):
        if URL_RE.match(v):
            return v
        out, n = (sub_path if key in PATH_KEYS else sub_text)(v, mapping)
        count[0] += n
        return out
    if isinstance(v, list):
        return [_walk(x, key, mapping, count) for x in v]
    if isinstance(v, dict):
        return {k: _walk(x, k, mapping, count) for k, x in v.items()}
    return v


def rewrite_event(ev: dict, mapping: dict[str, str]) -> tuple[dict, int]:
    """Evento com todos os IDs do mapa trocados (id, referências em `data`, textos livres, caminhos). `seq` e `ts` ficam."""
    count = [0]
    out: dict = {}
    for k, v in ev.items():
        if k in SKIP_KEYS:
            out[k] = v
        elif k == "id" and isinstance(v, str):
            if v in mapping:                              # o mapa só tem IDs que existem; id de artefato (caminho) nunca colide
                out[k] = mapping[v]
                count[0] += 1
            else:
                out[k] = _walk(v, "path", mapping, count)       # id de artefato é caminho
        else:
            out[k] = _walk(v, k, mapping, count)
    return out, count[0]


# ── mapa ────────────────────────────────────────────────────────────────────────────────────────────────
def build_map(events: list[dict], goals_text: str) -> dict[str, str]:
    """{antigo: novo} só do que existe: entidades do ledger e nós do goals.md."""
    mapping: dict[str, str] = {}

    def add(old):
        if isinstance(old, str):
            new = ids.normalize(old)
            if new != old and ids.is_id(new):
                mapping[old] = new

    for ev in events:
        spec = schema.TYPES.get(ev.get("type"), {})
        if spec.get("entity") in schema.ID_ENTITIES:
            add(ev.get("id"))
    for ln in goals_text.splitlines():
        for rx in (planning.GOAL_RE, planning.PROJ_RE):
            m = rx.match(ln)
            if m:
                add(m.group(1))
        m = planning.DELIV_RE.match(ln)
        if m:
            add(m.group(4))
    return mapping


# ── varredura de arquivos ───────────────────────────────────────────────────────────────────────────────
@dataclass
class FileChange:
    rel: str
    zone: str
    old: str
    new: str
    subs: int
    path: Path | None = None


@dataclass
class Migration:
    mapping: dict[str, str]
    events: list[dict]                       # eventos novos (sem o ids.migrated final)
    ledger_subs: int
    goals_old: str
    goals_new: str
    files: list[FileChange] = field(default_factory=list)
    renames: list[tuple[str, str]] = field(default_factory=list)     # relativos ao vault
    ambiguous: list[dict] = field(default_factory=list)              # ocorrências de G#/P# em RAW externo (não migradas)
    ambiguous_total: int = 0
    include_external: bool = False
    hashes: dict[str, int] = field(default_factory=dict)             # quantos hashes recalculados por tipo

    @property
    def zones(self) -> dict[str, dict]:
        z: dict[str, dict] = {"ledger": {"files": 1, "subs": self.ledger_subs}}
        for f in self.files:
            e = z.setdefault(f.zone, {"files": 0, "subs": 0})
            e["files"] += 1
            e["subs"] += f.subs
        return z


def _zone(rel: Path) -> str | None:
    """Zona de um arquivo do vault, ou None se não deve ser migrado."""
    top, parts = rel.parts[0], rel.parts
    if rel.name in (".DS_Store",) or top in ("logs", "FRESH") and not (top == "FRESH" and len(parts) > 1 and parts[1] == "notes"):
        return None
    if top == "PROCESSED":
        return None if len(parts) > 1 and parts[1] == "_ledger" else "PROCESSED"
    if top == "reports":
        return None if len(parts) > 1 and parts[1] == "migration" else "reports"
    if top == "FRESH":
        return "FRESH/notes"
    if top in ("PLANNING", "PROFILE"):
        return top
    if top == "RAW":
        return "RAW notas" if notes.NAME_RE.match(rel.name) else "RAW externo"
    return None


def _read_text(path: Path) -> str | None:
    if path.suffix.lower() not in TEXT_EXT:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def rename_for(name: str, mapping: dict[str, str]) -> str:
    new, _ = sub_path(name, mapping)
    return new


def plan_migration(brain, include_external: bool = False) -> Migration:
    inst = brain.inst
    raw_events = brain.read_events()
    goals_old = inst.planning_file.read_text(encoding="utf-8") if inst.planning_file.exists() else ""
    mapping = build_map(raw_events, goals_old)
    new_events, ledger_subs = [], 0
    for ev in raw_events:
        new, n = rewrite_event(ev, mapping)
        new_events.append(new)
        ledger_subs += n
    mig = Migration(mapping, new_events, ledger_subs, goals_old, "", include_external=include_external)

    vault = inst.vault
    changes: dict[str, FileChange] = {}
    texts: dict[str, str] = {}                       # texto original de cada arquivo lido (para os hashes dos reports)
    for path in sorted(p for p in vault.rglob("*") if p.is_file()):
        rel = path.relative_to(vault)
        zone = _zone(rel)
        if zone is None:
            continue
        new_name = rename_for(rel.name, mapping)
        if new_name != rel.name:
            mig.renames.append((str(rel), str(rel.with_name(new_name))))
        text = _read_text(path)
        if text is None:
            continue
        texts[str(rel)] = text
        external = zone == "RAW externo"
        new, n = sub_text(text, mapping, plan_ids=not external or include_external)
        if external and not include_external:
            for m in ids.OLD_PLAN_RE.finditer(text):
                if m.group(0) in mapping:
                    mig.ambiguous_total += 1
                    if len(mig.ambiguous) < SAMPLE_LIMIT:
                        a, b = max(0, m.start() - CONTEXT), min(len(text), m.end() + CONTEXT)
                        mig.ambiguous.append({"file": str(rel), "token": m.group(0), "would_be": mapping[m.group(0)],
                                              "context": text[a:b].replace("\n", " ")})
        if n:
            changes[str(rel)] = FileChange(str(rel), zone, text, new, n, path)
    wk = inst.config_dir / "watch.toml"
    if wk.exists():
        text = wk.read_text(encoding="utf-8")
        new, n = sub_text(text, mapping)
        if n:
            changes["config/watch.toml"] = FileChange("config/watch.toml", "config", text, new, n, wk)
    mig.files = list(changes.values())
    gl = changes.get("PLANNING/goals.md")
    mig.goals_new = gl.new if gl else goals_old
    _recompute_hashes(mig, raw_events, texts, changes, vault)
    return mig


def _recompute_hashes(mig: Migration, old_events: list[dict], texts: dict, changes: dict, vault: Path) -> None:
    """Hashes que cobrem texto alterado: text_sha (mensagem), content_sha (publicação), sha (plano de foco)."""
    msg_sha: dict[str, tuple[str, str]] = {}           # mensagem → (sha antigo, sha novo)
    focus_sha: dict[str, tuple[str, str]] = {}
    for old, new in zip(old_events, mig.events):
        t = old.get("type")
        if t == "message.drafted":
            a, b = util.sha(old["data"]["text"]), util.sha(new["data"]["text"])
            msg_sha[old["id"]] = (a, b)
        elif t == "focus.planned":
            def body(d):
                return {k: v for k, v in d.items() if k not in ("plan_file", "sha")}
            a, b = util.sha(json.dumps(body(old["data"]), sort_keys=True)), util.sha(json.dumps(body(new["data"]), sort_keys=True))
            if old["data"].get("sha") == a:                  # só mexe se o hash antigo era mesmo o do corpo
                focus_sha[old["id"]] = (old["data"]["sha"], b)
    counts = {"text_sha": 0, "content_sha": 0, "sha": 0}
    for old, new in zip(old_events, mig.events):
        t, od, nd = old.get("type"), old.get("data", {}), new.get("data", {})
        if t in ("message.approved", "message.sent") and old["id"] in msg_sha:
            a, b = msg_sha[old["id"]]
            if od.get("text_sha") == a and a != b:
                nd["text_sha"] = b
                counts["text_sha"] += 1
        elif t in ("share.requested", "share.approved"):
            report = od.get("report")
            if t == "share.approved":                       # a aprovação não repete o caminho: o pedido do mesmo id sabe
                req = next((e for e in old_events if e.get("type") == "share.requested" and e.get("id") == old["id"]), None)
                report = req["data"]["report"] if req else None
            path = vault / report if report else None
            if path and path.is_file() and report in changes and od.get("content_sha") == util.sha(path.read_bytes()):
                nd["content_sha"] = util.sha(changes[report].new.encode("utf-8"))
                counts["content_sha"] += 1
        elif t == "focus.planned" and old["id"] in focus_sha:
            nd["sha"] = focus_sha[old["id"]][1]
            counts["sha"] += 1
        elif t == "focus.approved" and old["id"] in focus_sha and od.get("sha") == focus_sha[old["id"]][0]:
            nd["sha"] = focus_sha[old["id"]][1]
            counts["sha"] += 1
    mig.hashes = {k: v for k, v in counts.items() if v}


# ── relatório ───────────────────────────────────────────────────────────────────────────────────────────
def report_text(mig: Migration, stamp: str, applied: bool, backup: dict | None = None) -> str:
    out = [f"# Migração de IDs — {'aplicada' if applied else 'dry-run'} ({stamp})", "",
           f"- IDs no mapa: **{len(mig.mapping)}** (só os que existem no ledger e no goals.md)",
           f"- RAW externo: {'`G#`/`P#` também migrados (--include-external)' if mig.include_external else 'só IDs longos; `G#`/`P#` listados abaixo e NÃO migrados'}",
           f"- Arquivos renomeados: **{len(mig.renames)}**"]
    if mig.hashes:
        out.append("- Hashes recalculados: " + ", ".join(f"{k} ×{v}" for k, v in mig.hashes.items()))
    if backup:
        out.append(f"- Backup: `{backup['path']}` ({backup['size']} bytes, sha256 `{backup['sha']}`)")
    out += ["", "## Por zona", "", "| Zona | Arquivos | Substituições |", "|---|---|---|"]
    for z, e in mig.zones.items():
        out.append(f"| {z} | {e['files']} | {e['subs']} |")
    out += ["", "## Renomeações", ""] + ([f"- `{a}` → `{b}`" for a, b in mig.renames] or ["_nenhuma_"])
    diff = list(difflib.unified_diff(mig.goals_old.splitlines(), mig.goals_new.splitlines(),
                                     "PLANNING/goals.md (antes)", "PLANNING/goals.md (depois)", lineterm="", n=1))
    out += ["", "## Diff do PLANNING/goals.md (passa pelo gate do dono)", "", "```diff"] + (diff or ["(sem mudança)"]) + ["```"]
    out += ["", f"## Ocorrências ambíguas em RAW externo ({mig.ambiguous_total})", ""]
    if not mig.ambiguous_total:
        out.append("_nenhuma_")
    for a in mig.ambiguous:
        out.append(f"- `{a['file']}` · `{a['token']}` → `{a['would_be']}` · …{a['context']}…")
    if mig.ambiguous_total > len(mig.ambiguous):
        out.append(f"- … e mais {mig.ambiguous_total - len(mig.ambiguous)}")
    out += ["", "## Mapa (amostra)", ""] + [f"- `{a}` → `{b}`" for a, b in list(mig.mapping.items())[:40]]
    return "\n".join(out) + "\n"


# ── backup ──────────────────────────────────────────────────────────────────────────────────────────────
def make_backup(inst) -> dict:
    """Zip completo de vault/ + config/watch.toml FORA do vault (para o próprio backup não ser migrado). Confere antes de seguir."""
    stamp = util.now().strftime("%Y%m%d-%H%M%S")
    path = inst.vault.parent / f"brain-pre-ids-migration-{stamp}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(inst.vault.rglob("*")):
            if p.is_file():
                zf.write(p, Path("vault") / p.relative_to(inst.vault))
        wk = inst.config_dir / "watch.toml"
        if wk.exists():
            zf.write(wk, "config/watch.toml")
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
    if bad:
        path.unlink(missing_ok=True)
        raise util.BrainError(f"backup corrompido ({bad}) — nada foi migrado", code=5)
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"path": str(path), "size": path.stat().st_size, "sha": h}


# ── comando ─────────────────────────────────────────────────────────────────────────────────────────────
def _precheck(brain) -> Path:
    if os.environ.get("BRAIN_NIGHTLY") == "1":
        raise util.BrainError("migrate ids: proibido no noturno — a migração precisa do dono presente", code=4)
    marker = brain.inst.vault / MARKER_REL
    if marker.exists():
        raise util.BrainError(f"esta instância já foi migrada ({marker.relative_to(brain.inst.vault)}) — nada a fazer", code=4)
    return marker


def _write_report(brain, mig: Migration, applied: bool, backup: dict | None) -> Path:
    stamp = util.now().strftime("%Y%m%d-%H%M%S")
    path = brain.inst.reports / "migration" / f"ids-{stamp}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_text(mig, util.now().strftime("%Y-%m-%d %H:%M"), applied, backup), encoding="utf-8")
    return path


def _summary(mig: Migration) -> str:
    lines = [f"mapa: {len(mig.mapping)} IDs · ledger: {mig.ledger_subs} substituições · renomear: {len(mig.renames)} arquivo(s)"]
    for z, e in mig.zones.items():
        lines.append(f"  {z:<14} {e['files']:>4} arquivo(s) · {e['subs']:>5} substituição(ões)")
    lines.append(f"ocorrências ambíguas em RAW externo (G#/P#): {mig.ambiguous_total}"
                 + ("" if not mig.ambiguous_total or mig.include_external else " — não migradas sem --include-external"))
    return "\n".join(lines)


def cli(args, brain) -> None:
    marker = _precheck(brain)
    mig = plan_migration(brain, args.include_external)
    if not mig.mapping:
        print("nada a migrar: a instância já usa os nomes novos (ou ainda não tem IDs)")
        if args.apply:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps({"ts": util.iso_now(), "map": 0}) + "\n", encoding="utf-8")
        return
    if not args.apply:
        rp = _write_report(brain, mig, False, None)
        print("dry-run (nada foi alterado, só o relatório):\n" + _summary(mig))
        print(f"relatório: {brain.inst.rel(rp)}\nPara aplicar: brain migrate ids --apply" + (" --include-external" if mig.include_external else ""))
        return
    apply(brain, mig)


def _stage_and_validate(brain, mig: Migration, backup: dict) -> list[dict]:
    """Ledger novo (+ ids.migrated) validado contra o goals.md novo, ainda em memória. Levanta se não passar."""
    last = mig.events[-1]["seq"] if mig.events else 0
    final = {"seq": last + 1, "ts": util.iso_now(), "type": "ids.migrated", "date": util.today().isoformat(), "by": "system",
             "prov": "sistema", "data": {"map": mig.mapping, "backup_sha": backup["sha"], "backup": Path(backup["path"]).name}}
    events = [*mig.events, final]
    problems = brain.validate_events([json.loads(json.dumps(e)) for e in events], planning.parse(mig.goals_new))
    if problems:
        raise util.BrainError("o ledger migrado não passou na validação — nada foi alterado:\n  " + "\n  ".join(problems[:15]), code=5)
    return events


def apply(brain, mig: Migration) -> None:
    inst = brain.inst
    marker = inst.vault / MARKER_REL
    with brain._lock():
        backup = make_backup(inst)
        print(f"backup: {backup['path']} ({backup['size']} bytes) — íntegro")
        events = _stage_and_validate(brain, mig, backup)
        ledger_new = "".join(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n" for e in events)
        ledger_old = brain.ledger_path.read_text(encoding="utf-8")
        for old, new in mig.renames:                                        # conflito de nome: aborta antes de mexer em qualquer coisa
            if (inst.vault / new).exists():
                raise util.BrainError(f"já existe {new}: não posso renomear {old} — nada foi alterado", code=4)
        done_files: list[FileChange] = []
        done_renames: list[tuple[str, str]] = []
        try:
            for f in mig.files:
                util.atomic_write(f.path, f.new)
                done_files.append(f)
            for old, new in mig.renames:
                os.rename(inst.vault / old, inst.vault / new)
                done_renames.append((old, new))
            tmp = brain.ledger_path.with_suffix(".jsonl.migrating")
            tmp.write_text(ledger_new, encoding="utf-8")
            os.replace(tmp, brain.ledger_path)
            marker.write_text(json.dumps({"ts": util.iso_now(), "map": len(mig.mapping), "backup": backup["path"],
                                          "backup_sha": backup["sha"]}) + "\n", encoding="utf-8")
        except Exception as e:                                              # desfaz o que deu: arquivos, nomes e ledger
            for old, new in reversed(done_renames):
                if (inst.vault / new).exists():
                    os.rename(inst.vault / new, inst.vault / old)
            for f in done_files:
                util.atomic_write(f.path, f.old)
            brain.ledger_path.write_text(ledger_old, encoding="utf-8")
            marker.unlink(missing_ok=True)
            raise util.BrainError(f"a migração falhou ({e}); tudo foi desfeito. Backup em {backup['path']}", code=5) from e
        _clear_fresh(inst)
    brain.reload()
    problems = brain.validate_all()
    rp = _write_report(brain, mig, True, backup)
    print("migrado:\n" + _summary(mig))
    if problems:
        print("⚠ brain validate achou problemas após a migração:\n  " + "\n  ".join(problems[:10]))
    from . import render
    render.render_all(brain, do_harvest=False)
    print(f"✓ views regeneradas · relatório: {brain.inst.rel(rp)}")
    if inst.cfg.get("memory", {}).get("engine") == "hindsight":
        print("→ Hindsight ligado: rode `./brain memory rebuild` (o índice ainda guarda os nomes antigos)")


def _clear_fresh(inst) -> None:
    """FRESH é derivado: apaga tudo e o render refaz — menos `notes/` (narrativas do agente, já migradas no lugar)."""
    fresh = inst.fresh
    if not fresh.exists():
        return
    for child in fresh.iterdir():
        if child.name == "notes":
            continue
        shutil.rmtree(child) if child.is_dir() else child.unlink()
