"""Render: colhe edições do dono → view model → Markdown + painel HTML. Sem LLM, em segundos."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from . import doctor, model, render_md, util
from . import harvest as harvest_mod

ASSET = Path(__file__).resolve().parent / "assets" / "dashboard.html"
MANAGED_DIRS = ("projects", "people", "records/actions", "records/decisions")


def _notes(fresh: Path) -> list[dict]:
    """Narrativas do agente (FRESH/notes/*.md: brief, semana) entram no painel como estão."""
    out = []
    for p in sorted((fresh / "notes").glob("*.md")) if (fresh / "notes").exists() else []:
        text = p.read_text(encoding="utf-8")
        out.append({"name": p.stem, "text": text[:20000]})
    return out


def render_html(m: dict) -> str:
    data = json.dumps(m, ensure_ascii=False, default=str)
    data = data.replace("</", "<\\/").replace("<!--", "<\\!--")
    return ASSET.read_text(encoding="utf-8").replace("__DATA__", data, 1)


def _cleanup(fresh: Path, keep: set[Path]) -> list[str]:
    removed = []
    for sub in MANAGED_DIRS:
        d = fresh / sub
        if not d.exists():
            continue
        for p in d.glob("*.md"):
            if p not in keep:
                p.unlink()
                removed.append(str(p.relative_to(fresh)))
    return removed


def render_all(brain, do_harvest: bool = True) -> dict:
    harvested = harvest_mod.run(brain) if do_harvest else []
    m = model.build(brain)
    m["health"] = doctor.checks(brain)
    m["notes"] = _notes(brain.inst.fresh)
    pages = render_md.Pages(brain.inst, m)
    pages.home()
    todo_checks = pages.todo()
    pages.goals_page()
    pages.project_pages()
    pages.decisions_page()
    pages.wins_page()
    pages.people_pages()
    pages.timeline_page()
    pages.map_page()
    pages.focus_page()
    pages.outbox_page()
    record_status = pages.records()
    pages.health_page(m["health"])
    dashboard = brain.inst.fresh / "dashboard" / "index.html"
    pages.files[dashboard] = render_html(m)
    written = sum(util.atomic_write(path, text) for path, text in pages.files.items())
    removed = _cleanup(brain.inst.fresh, set(pages.files))
    harvest_mod.save_state(brain.inst.fresh, todo_checks, record_status)
    return {"harvested": [f"{e['type']} {e.get('id', '')}" for e in harvested], "written": written,
            "total": len(pages.files), "removed": removed, "dashboard": str(dashboard),
            "warnings": [c for c in m["health"] if c["level"] != "ok"]}


def summary(report: dict) -> str:
    lines = [f"✓ views regeneradas: {report['total']} arquivos ({report['written']} mudaram)"
             + (f" · {len(report['removed'])} obsoletos removidos" if report["removed"] else "")]
    if report["harvested"]:
        lines.append("  colhido das suas edições: " + ", ".join(report["harvested"]))
    lines.append(f"  painel: {report['dashboard']}")
    for w in report["warnings"][:6]:
        lines.append(f"  {'✗' if w['level'] == 'error' else '⚠'} {w['title']}: {w['detail']}")
    return "\n".join(lines)


def open_dashboard(brain) -> None:
    path = brain.inst.fresh / "dashboard" / "index.html"
    opener = shutil.which("xdg-open") or shutil.which("open")
    if opener:
        subprocess.run([opener, str(path)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print(f"abra no navegador: file://{path}")
