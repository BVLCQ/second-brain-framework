"""Render: colhe edições do dono → view model → Markdown + painel HTML. Sem LLM, em segundos."""
from __future__ import annotations

import json
import shutil
import webbrowser  # noqa: F401 — os testes interceptam render.webbrowser.open
import subprocess
from pathlib import Path

from . import doctor, forms, model, render_md, render_portfolio, schema, util, watch
from . import harvest as harvest_mod

ASSET = Path(__file__).resolve().parent / "assets" / "dashboard.html"
PORTFOLIO_ASSET = ASSET.with_name("portfolio.html")
ONBOARDING_ASSET = ASSET.with_name("onboarding.html")
PANELS = {"execucao": "index.html", "portfolio": "portfolio.html"}   # brain render --open [execucao|portfolio]
MANAGED_DIRS = ("projects", "people", "records/actions", "records/decisions",
                "records/processes", "records/opportunities")


def _notes(fresh: Path) -> list[dict]:
    """Narrativas do agente (FRESH/notes/*.md: brief, semana) entram no painel com metadados opcionais."""
    from . import notes
    out = []
    for p in sorted((fresh / "notes").glob("*.md")) if (fresh / "notes").exists() else []:
        parsed = notes.parse_note(p)
        out.append({
            **parsed,
            "body": parsed["body"][:20000],
            "text": parsed["text"][:20000],
        })
    return out


def render_html(m: dict, asset: Path = ASSET) -> str:
    # `<`, `>` e `&` só aparecem dentro de strings JSON: \u003c etc. é JSON válido e não deixa o texto fechar o
    # <script> nem abrir comentário. (`<\!--` NÃO é escape JSON válido — derrubava o JSON.parse do painel inteiro.)
    data = json.dumps(m, ensure_ascii=False, default=str)
    data = (data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    return asset.read_text(encoding="utf-8").replace("__DATA__", data, 1)


def render_shell_html(asset: Path = ASSET) -> str:
    """Shell HTML sem dados do vault para a ponte (`./brain serve`): o cliente hidrata via /api/data|/api/portfolio."""
    return asset.read_text(encoding="utf-8").replace("__DATA__", "{}", 1)


def _cleanup(fresh: Path, keep: set[Path]) -> list[str]:
    removed = []
    notes_dir = (fresh / "notes").resolve()
    for sub in MANAGED_DIRS:
        d = fresh / sub
        if not d.exists() or d.resolve() == notes_dir:
            continue
        for p in d.glob("*.md"):
            if p.resolve().parent == notes_dir:
                continue
            if p not in keep:
                p.unlink()
                removed.append(str(p.relative_to(fresh)))
    return removed


def _sources(brain) -> list[dict]:
    """Fontes do watch.toml + o que o ledger sabe de cada pull (a mesma conta da aba Fontes do TUI); pulls avulsos
    (/connect) aparecem fora do watch."""
    try:
        listed = watch.list_sources(brain.inst)
    except util.BrainError:
        listed = []
    conns, out, seen = brain.state.connectors, [], set()
    for s in listed:
        c = conns.get(s.get("key", ""))
        seen.add(s.get("key"))
        st = watch.source_status(s, c)
        out.append({**s, "in_watch": True, "last_ok": c.last_ok if c else "", "last_error": c.last_error if c else "",
                    "failures": c.consecutive_failures if c else 0, "pulls": c.pulls if c else 0,
                    "last_changed": c.last_changed if c else "",
                    "enabled": st["enabled"], "problem": st["problem"], "problem_reason": st["problem_reason"]})
    for k, c in conns.items():
        if k not in seen:
            out.append({"key": k, "kind": "", "in_watch": False, "last_ok": c.last_ok, "last_error": c.last_error,
                        "failures": c.consecutive_failures, "pulls": c.pulls, "last_changed": c.last_changed,
                        "enabled": True, "problem": False, "problem_reason": ""})
    return out


def view_model(brain) -> dict:
    """O view model completo (o que o render injeta no painel e o serve devolve em /api/data):
    modelo + checagens de saúde + notas do agente — mesmas chaves nos dois caminhos."""
    m = model.build(brain)
    from . import onboard
    m["onboarding"] = {"needed": onboard.needed(brain)}          # F8: primeira vez abre o wizard na própria página
    m["health"] = [{**c, "fix": doctor.fix_for(c)} for c in doctor.checks(brain)]
    from . import services as _services
    m["services"] = _services.read_status(brain.inst)
    m["freshness"] = doctor.freshness(brain)
    m["sources"] = _sources(brain)
    m["source_kinds"] = [list(k) for k in watch.KINDS]
    m["doc_kinds"] = sorted(schema.DOC_KINDS)
    m["forms"] = forms.export()                                 # formulários: a MESMA especificação da TUI
    m["form_static"] = forms.static(brain)
    m["notes"] = _notes(brain.inst.fresh)
    from . import notes as _notes_mod
    m["daily_brief"] = _notes_mod.daily_brief(brain.inst.fresh)
    from . import review
    m["review"] = review.summary(brain)
    from . import upstream as _up                              # versão + aviso de atualização (cache, sem rede)
    from . import __version__ as _ver
    c = _up.read_check_cache(brain.inst)
    m["update"] = {"version": _ver, "behind": c.get("behind"), "ahead": c.get("ahead"),
                   "remote_version": c.get("remote_version"), "checked_at": c.get("checked_at"),
                   "news": c.get("news", []), "lines": _up.commit_lines(c.get("incoming") or []), "checked": bool(c),
                   "stale": _up.check_is_stale(c), "error": bool(c.get("error")),
                   "cli_cmd": "./brain update"}
    return m


_UNSET = object()


def render_all(brain, do_harvest: bool = True, window=_UNSET) -> dict:
    if window is _UNSET:
        window = harvest_mod.consume_agent_window(brain.inst) if do_harvest else None
    elif window is not None:
        (brain.inst.logs / harvest_mod.HARVEST_GUARD_FILE).unlink(missing_ok=True)
    notices: list[dict] = []
    brain.sweep_proposals()        # propostas que o dono já resolveu por fora do painel
    harvested = harvest_mod.run(brain, notices, window=window) if do_harvest else []
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
    try:
        from . import index as _idx
        _idx.update(brain)               # Fase 1: views e índice saem juntos (best-effort)
    except Exception:                    # noqa: BLE001 — índice é acelerador, não verdade
        pass
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
        from .serve import live_panel_url, stop_stale
        if stop_stale(brain.inst):                         # ponte de uma versão anterior: troca pela atual
            print("↻ a ponte do painel era de uma versão anterior — reiniciando")
        live = live_panel_url(brain.inst)
    except Exception:                                      # noqa: BLE001 — abrir o painel nunca falha por isso
        live = None
    if live:
        return live
    import os, subprocess, sys, time
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
            from .serve import live_panel_url as _lpu
            url = _lpu(brain.inst)
            if url:
                return url
        except Exception:                                  # noqa: BLE001
            pass
        time.sleep(0.15)
    print("⚠ a ponte não respondeu a tempo — abrindo o retrato (log: logs/serve.log)")
    return None


def open_onboarding(brain) -> bool:
    """Abre o onboarding no navegador (precisa da ponte: é ela que grava). False se a ponte não subiu.
    F8: o wizard é um modo do painel — o hash `onboarding` entra no modo sem trocar de página."""
    live = ensure_bridge(brain, wait_s=15.0)                # primeira subida pode ser lenta (máquina recém-instalada)
    if not live:
        return False
    base, _, frag = live.partition("#")
    tok = frag.split("=", 1)[1] if frag.startswith("t=") else ""
    hash_ = "onboarding" + ("&t=" + tok if tok else "")     # extra.js lê t= no hash ([#&]t=…)
    print("✓ abrindo a configuração guiada do Brain")
    util.open_url(base.rstrip("/") + "/#" + hash_)
    return True


def open_dashboard(brain, panel: str = "execucao", spawn: bool = True) -> None:
    from . import services as _services
    _services.kick(brain.inst, reason="open")
    # painel VIVO sempre que possível: executa comandos e o reload é sempre fresco
    try:
        from .serve import live_panel_url, stop_stale
        restarted = bool(spawn and stop_stale(brain.inst))
        if restarted:
            print("↻ a ponte do painel era de uma versão anterior — reiniciando")
        already = None if restarted else live_panel_url(brain.inst)
        live = already or (ensure_bridge(brain) if spawn else None)
        focus_only, keep_route = bool(already), not already
    except Exception:                                      # noqa: BLE001
        live, focus_only, keep_route = None, False, False
    if live:
        print(f"✓ ponte CLI no ar — abrindo o painel vivo ({live.split('#')[0]})")
        import sys
        focused = sys.platform == "darwin" and util.focus_open_tab(
            live, focus_only=focus_only, keep_route=keep_route and not focus_only)
        if not focused:
            util.open_url(live)
        return
    path = brain.inst.fresh / "dashboard" / PANELS[panel]
    # via util.open_url (→ webbrowser.open): um só ponto de abertura, que os testes conseguem interceptar
    if util.open_url(path.as_uri()):
        print("retrato file:// — ./brain serve liga os comandos (e o --open passa a abrir o vivo)")
    else:
        print(f"abra no navegador: file://{path}\n(retrato — ./brain serve liga os comandos)")
