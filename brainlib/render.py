"""Render: colhe edições do dono → view model → Markdown + painel HTML. Sem LLM, em segundos."""
from __future__ import annotations

import json
import shutil
import webbrowser
import subprocess
from pathlib import Path

from . import doctor, model, render_md, render_portfolio, util
from . import harvest as harvest_mod

ASSET = Path(__file__).resolve().parent / "assets" / "dashboard.html"
PORTFOLIO_ASSET = ASSET.with_name("portfolio.html")
PANELS = {"execucao": "index.html", "portfolio": "portfolio.html"}   # brain render --open [execucao|portfolio]
MANAGED_DIRS = ("projects", "people", "records/actions", "records/decisions",
                "records/processes", "records/opportunities")


def _notes(fresh: Path) -> list[dict]:
    """Narrativas do agente (FRESH/notes/*.md: brief, semana) entram no painel como estão."""
    out = []
    for p in sorted((fresh / "notes").glob("*.md")) if (fresh / "notes").exists() else []:
        text = p.read_text(encoding="utf-8")
        out.append({"name": p.stem, "text": text[:20000]})
    return out


def render_html(m: dict, asset: Path = ASSET) -> str:
    # `<`, `>` e `&` só aparecem dentro de strings JSON: \u003c etc. é JSON válido e não deixa o texto fechar o
    # <script> nem abrir comentário. (`<\!--` NÃO é escape JSON válido — derrubava o JSON.parse do painel inteiro.)
    data = json.dumps(m, ensure_ascii=False, default=str)
    data = (data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    return asset.read_text(encoding="utf-8").replace("__DATA__", data, 1)


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


def view_model(brain) -> dict:
    """O view model completo (o que o render injeta no painel e o serve devolve em /api/data):
    modelo + checagens de saúde + notas do agente — mesmas chaves nos dois caminhos."""
    m = model.build(brain)
    m["health"] = doctor.checks(brain)
    m["notes"] = _notes(brain.inst.fresh)
    return m


def render_all(brain, do_harvest: bool = True) -> dict:
    notices: list[dict] = []
    brain.sweep_proposals()        # propostas que o dono já resolveu por fora do painel
    harvested = harvest_mod.run(brain, notices) if do_harvest else []
    m = view_model(brain)
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
    record_status.update(render_portfolio.render(pages))
    pages.health_page(m["health"])
    dashboard = brain.inst.fresh / "dashboard" / "index.html"
    pages.files[dashboard] = render_html(m)
    pf_html = dashboard.with_name(PANELS["portfolio"])
    pages.files[pf_html] = render_html(render_portfolio.html_payload(m), PORTFOLIO_ASSET)
    written = sum(util.atomic_write(path, text) for path, text in pages.files.items())
    removed = _cleanup(brain.inst.fresh, set(pages.files))
    harvest_mod.save_state(brain.inst.fresh, todo_checks, record_status)
    return {"harvested": [f"{e['type']} {e.get('id', '')}" for e in harvested], "written": written,
            "total": len(pages.files), "removed": removed, "dashboard": str(dashboard),
            "portfolio": str(pf_html),
            "warnings": notices + [c for c in m["health"] if c["level"] != "ok"]}


def summary(report: dict) -> str:
    lines = [f"✓ views regeneradas: {report['total']} arquivos ({report['written']} mudaram)"
             + (f" · {len(report['removed'])} obsoletos removidos" if report["removed"] else "")]
    if report["harvested"]:
        lines.append("  colhido das suas edições: " + ", ".join(report["harvested"]))
    lines.append(f"  painel: {report['dashboard']}")
    lines.append(f"  mapa de oportunidades: {report['portfolio']}")
    for w in report["warnings"][:6]:
        lines.append(f"  {'✗' if w['level'] == 'error' else '⚠'} {w['title']}: {w['detail']}")
    return "\n".join(lines)


def ensure_bridge(brain, port: int = 8787, wait_s: float = 3.0) -> str | None:
    """Ponte no ar? devolve a URL viva. Não está? SOBE uma (daemon destacado) e espera.
    É o `./brain serve` de sempre, só não fazendo o dono lembrar dele."""
    try:
        from .serve import live_panel_url
        live = live_panel_url(brain.inst)
    except Exception:                                      # noqa: BLE001 — abrir o painel nunca falha por isso
        live = None
    if live:
        return live
    import os, subprocess, sys, time, socket
    from .tui.bridge import FRAMEWORK                        # o script `brain` mora no FRAMEWORK, não na instância
    log = brain.inst.logs / "serve.log"
    brain.inst.logs.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "BRAIN_HOME": str(brain.inst.root)}
    try:
        with open(log, "ab") as fh:
            subprocess.Popen([sys.executable, str(FRAMEWORK / "brain"), "serve", "--port", str(port)],
                             cwd=str(brain.inst.root), stdout=fh, stderr=fh, env=env,
                             stdin=subprocess.DEVNULL, start_new_session=True)
    except Exception as e:                                 # noqa: BLE001 — sem ponte, segue o retrato
        print(f"⚠ não consegui subir a ponte ({e}) — abrindo o retrato")
        return None
    deadline = time.time() + wait_s
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                from .serve import live_panel_url as _lpu
                url = _lpu(brain.inst)
                if url:
                    return url
        except Exception:                                  # noqa: BLE001
            pass
        time.sleep(0.15)
    print("⚠ a ponte não respondeu a tempo — abrindo o retrato (log: logs/serve.log)")
    return None


def open_dashboard(brain, panel: str = "execucao", spawn: bool = True) -> None:
    # painel VIVO sempre que possível: executa comandos e o reload é sempre fresco
    try:
        from .serve import live_panel_url
        live = live_panel_url(brain.inst)
        if not live and spawn:
            live = ensure_bridge(brain)
    except Exception:                                      # noqa: BLE001
        live = None
    if live:
        print(f"✓ ponte CLI no ar — abrindo o painel vivo ({live.split('#')[0]})")
        webbrowser.open(live)
        return
    path = brain.inst.fresh / "dashboard" / PANELS[panel]
    opener = shutil.which("xdg-open") or shutil.which("open")
    if opener:
        subprocess.run([opener, str(path)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("retrato file:// — ./brain serve liga os comandos (e o --open passa a abrir o vivo)")
    else:
        print(f"abra no navegador: file://{path}\n(retrato — ./brain serve liga os comandos)")
