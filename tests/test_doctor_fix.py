"""Testes de `brain doctor --fix` (dry-run, apply, isolamento, gate safety) e métricas de frescor (#57)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, doctor, index, render, serve, util  # noqa: E402
from brainlib.core import Brain  # noqa: E402


def _inst(tmp: Path, *, memory_engine: str = "none") -> config.Instance:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "reports").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "logs").mkdir(parents=True, exist_ok=True)
    today_iso = util.today().isoformat()
    horizon_iso = (util.today() + timedelta(days=30)).isoformat()
    due_iso = (util.today() + timedelta(days=7)).isoformat()
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Marina Demo"\n\n'
        f'[memory]\nengine = "{memory_engine}"\n\n'
        '[outbound]\nallow = ["colega-demo", "#time"]\n\n'
        '[publish]\ndestinations = ["slack:#time"]\n',
        encoding="utf-8",
    )
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Meta de teste\n- status: ativo\n"
        f"- horizonte: {horizon_iso}\n- por quê: validar frescor ({today_iso})\n\n"
        "### PROJ-1 — Projeto de teste\n- status: ativo\n- dono: eu\n"
        f"- [ ] PROJ-1.1 Entregável 1 · prazo: {due_iso} · peso: 2\n",
        encoding="utf-8",
    )
    return config.load(tmp)


def _brain(tmp: Path, *, memory_engine: str = "none") -> Brain:
    b = Brain(_inst(tmp, memory_engine=memory_engine))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Marina Demo", "aliases": ["Eu"], "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "colega-demo", "by": "owner",
                  "data": {"name": "Colega Demo", "aliases": ["Colega"], "email": "colega@example.com"}})
    return b


def _run_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "BRAIN_HOME": str(root)}
    return subprocess.run([sys.executable, str(ROOT / "brain"), *args], env=env,
                          capture_output=True, text=True)


class DoctorFixDryRunAndApplyTests(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.b = _brain(self.td)

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_fix_dry_run_default_is_deterministic_and_non_destructive(self):
        # Cria pidfile órfão (PID improbável, além de testar CLI), FTS ausente e views ausentes
        pid_file = serve.live_url_file(self.b.inst)
        pid_file.write_text(json.dumps({"url": "http://127.0.0.1:8787/#t=abc", "port": 8787, "pid": 99999999}),
                            encoding="utf-8")
        db_file = index.db_path(self.b.inst)
        db_file.unlink(missing_ok=True)
        rs_file = self.b.inst.fresh / ".render-state.json"

        # Via funções puras: determinístico
        p1 = doctor.plan_fix(self.b, pid_alive=lambda _p: False)
        p2 = doctor.plan_fix(self.b, pid_alive=lambda _p: False)
        d1 = doctor.format_fix_diff(p1)
        d2 = doctor.format_fix_diff(p2)
        self.assertEqual(d1, d2)
        self.assertEqual(p1["mode"], "dry-run")
        self.assertEqual([a["kind"] for a in p1["actions"]], ["orphan_bridge_pid", "fts_stale", "views_stale"])

        # Via CLI: `doctor --fix` (default dry-run) e `doctor --fix --dry-run` geram saída byte-a-byte idêntica
        r1 = _run_cli(self.td, "doctor", "--fix")
        r2 = _run_cli(self.td, "doctor", "--fix", "--dry-run")
        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertEqual(r1.stdout, r2.stdout)
        self.assertIn("+ [orphan_bridge_pid]", r1.stdout)
        self.assertIn("+ [fts_stale]", r1.stdout)
        self.assertIn("+ [views_stale]", r1.stdout)

        # Nada foi alterado no disco
        self.assertTrue(pid_file.exists())
        self.assertFalse(db_file.exists())
        self.assertFalse(rs_file.exists())
        self.assertFalse((self.b.inst.logs / "doctor-fix.log").exists())

        # --dry-run e --apply juntos retornam code=4
        r_bad = _run_cli(self.td, "doctor", "--fix", "--dry-run", "--apply")
        self.assertEqual(r_bad.returncode, 4)

    def test_apply_removes_orphan_preserves_live_pid_rebuilds_fts_and_renders(self):
        pid_file = serve.live_url_file(self.b.inst)
        pid_file.write_text(json.dumps({"url": "http://127.0.0.1:8787/#t=abc", "port": 8787, "pid": 424242}),
                            encoding="utf-8")
        db_file = index.db_path(self.b.inst)
        db_file.unlink(missing_ok=True)

        # Processo vivo: pidfile preservado
        plan_live = doctor.plan_fix(self.b, pid_alive=lambda _p: True)
        self.assertNotIn("orphan_bridge_pid", [a["kind"] for a in plan_live["actions"]])
        res_live = doctor.apply_fix(self.b, plan_live)
        self.assertTrue(pid_file.exists())
        self.assertEqual([a["kind"] for a in res_live["actions"]], ["fts_stale", "views_stale"])
        self.assertTrue(all(a["status"] == "applied" for a in res_live["actions"]))

        # Agora deixa FTS velho (mtime anterior ao ledger), views velhas (mtime anterior) e pid órfão
        old_ts = util.now().timestamp() - 3600
        os.utime(db_file, (old_ts, old_ts))
        rs_file = self.b.inst.fresh / ".render-state.json"
        rs_data = util.read_json(rs_file, {})
        rs_data["rendered_at"] = (util.now() - timedelta(hours=30)).isoformat(timespec="seconds")
        util.write_json(rs_file, rs_data)
        os.utime(rs_file, (old_ts, old_ts))

        plan_orphan = doctor.plan_fix(self.b, pid_alive=lambda _p: False)
        self.assertEqual([a["kind"] for a in plan_orphan["actions"]],
                         ["orphan_bridge_pid", "fts_stale", "views_stale"])

        res_apply = doctor.apply_fix(self.b, plan_orphan)
        self.assertEqual(res_apply["mode"], "apply")
        self.assertTrue(all(a["status"] == "applied" for a in res_apply["actions"]))
        self.assertFalse(pid_file.exists())
        self.assertTrue(db_file.exists())
        self.assertTrue(index.status(self.b)["ok"])
        self.assertTrue((self.b.inst.fresh / "home.md").exists())

        # Log estruturado gravado em vault/logs/doctor-fix.log
        log_file = self.b.inst.logs / "doctor-fix.log"
        self.assertTrue(log_file.exists())
        lines = [json.loads(ln) for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[-1]["applied"], 3)
        self.assertEqual(lines[-1]["failed"], 0)

        # CLI `--fix --apply` com tudo em dia não falha
        r_ok = _run_cli(self.td, "doctor", "--fix", "--apply")
        self.assertEqual(r_ok.returncode, 0, r_ok.stderr)

    def test_memory_failure_is_isolated_from_fts_and_views(self):
        td_mem = Path(tempfile.mkdtemp())
        try:
            b_mem = _brain(td_mem, memory_engine="hindsight")
            index.db_path(b_mem.inst).unlink(missing_ok=True)
            plan = doctor.plan_fix(b_mem, pid_alive=lambda _p: True)
            self.assertEqual([a["kind"] for a in plan["actions"]],
                             ["fts_stale", "views_stale", "memory_unsynced"])

            def _boom(_brain):
                raise RuntimeError("Hindsight inacessível no teste")

            res = doctor.apply_fix(b_mem, plan, handlers={"memory_unsynced": _boom})
            by_kind = {a["kind"]: a for a in res["actions"]}
            self.assertEqual(by_kind["fts_stale"]["status"], "applied")
            self.assertEqual(by_kind["views_stale"]["status"], "applied")
            self.assertEqual(by_kind["memory_unsynced"]["status"], "failed")
            self.assertIn("Hindsight inacessível", by_kind["memory_unsynced"]["error"])
            self.assertTrue(index.status(b_mem)["ok"])
            self.assertTrue((b_mem.inst.fresh / "home.md").exists())

            log_file = b_mem.inst.logs / "doctor-fix.log"
            entry = json.loads(log_file.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(entry["applied"], 2)
            self.assertEqual(entry["failed"], 1)
        finally:
            shutil.rmtree(td_mem, ignore_errors=True)

    def test_gate_safety_never_puts_gated_items_in_actions(self):
        # Cria rascunho no outbox, proposta aberta, pergunta ASK aberta, plano de foco proposto e publicação pedida
        self.b.record_one({
            "type": "message.drafted", "by": "agent", "prov": "observado", "source": "RAW/nota.md",
            "data": {"to": "colega-demo", "channel": "slack", "text": "oi"},
        })
        self.b.record_one({
            "type": "proposal.opened", "by": "agent", "prov": "observado", "source": "RAW/nota.md",
            "data": {"kind": "outro", "summary": "Proposta aberta"},
        })
        self.b.record_one({
            "type": "question.asked", "by": "agent", "prov": "observado", "source": "RAW/nota.md",
            "data": {"text": "Qual o prazo?", "kind": "confirmacao", "options": ["Hoje", "Amanhã"]},
        })
        self.b.record_one({
            "type": "focus.planned", "by": "system",
            "data": {"plan_file": "FRESH/focus.md", "sha": util.sha("focus"), "blocks": [], "horizon_days": 7},
        })
        report_file = self.b.inst.reports / "share" / "status.md"
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text("# Status\n", encoding="utf-8")
        self.b.record_one({
            "type": "share.requested", "by": "owner",
            "data": {"report": "reports/share/status.md", "destination": "slack:#time",
                     "content_sha": util.sha("# Status\n")},
        })

        plan = doctor.plan_fix(self.b, pid_alive=lambda _p: True)
        action_kinds = {a["kind"] for a in plan["actions"]}
        self.assertTrue(action_kinds.issubset(set(doctor.AUTO_FIXABLE)))

        titles = {s["title"]: s for s in plan["suggestions"]}
        for expected in ("mensagens", "propostas", "perguntas", "foco", "publicação"):
            self.assertIn(expected, titles, f"faltou sugestão para {expected}")
            self.assertTrue(titles[expected]["gate"])
            self.assertTrue(titles[expected]["command"].startswith("./brain "))

        diff = doctor.format_fix_diff(plan)
        self.assertIn("! [mensagens] ./brain outbox list", diff)
        self.assertIn("! [propostas] ./brain proposal list", diff)
        self.assertIn("! [perguntas] ./brain ask list --open", diff)
        self.assertIn("! [foco] ./brain focus show", diff)
        self.assertIn("! [publicação] ./brain publish list", diff)

    def test_doctor_without_fix_remains_compatible(self):
        r = _run_cli(self.td, "doctor", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertIsInstance(data, list)
        self.assertTrue(any(item["title"] == "ledger" for item in data))


class FreshnessMetricsTests(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.b = _brain(self.td, memory_engine="hindsight")

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_freshness_calculations_and_view_model(self):
        base_now = util.now()

        # Sem dump, sem render, sem memory-state, inbox vazia (ignorando .keep.md e dotfile)
        (self.b.inst.inbox / ".keep.md").write_text("", encoding="utf-8")
        (self.b.inst.inbox / ".DS_Store").write_text("", encoding="utf-8")
        f0 = doctor.freshness(self.b, now=base_now)
        self.assertIsNone(f0["last_dump_at"])
        self.assertIsNone(f0["last_dump_age_h"])
        self.assertIsNone(f0["last_render_at"])
        self.assertIsNone(f0["last_render_age_h"])
        self.assertIsNone(f0["last_memory_sync_at"])
        self.assertIsNone(f0["last_memory_sync_age_h"])
        self.assertEqual(f0["inbox_backlog"], 0)
        self.assertIsNone(f0["inbox_oldest_age_h"])
        self.assertFalse(f0["stale"]["dump"])
        self.assertTrue(f0["stale"]["render"])
        self.assertTrue(f0["stale"]["memory_sync"])
        self.assertFalse(f0["stale"]["inbox"])
        self.assertEqual(f0["thresholds"], doctor.FRESHNESS_THRESHOLDS)

        # Simula artifact.added há 60h, render há 10h, memory-state há 30h, 2 itens na inbox (mais antigo 50h)
        dump_dt = base_now - timedelta(hours=60)
        ev = self.b.record_one({
            "type": "artifact.added", "id": "PROCESSED/nota.md", "by": "agent",
            "prov": "observado", "source": "RAW/nota.md",
            "data": {"kind": "nota", "title": "Nota", "raw": "RAW/nota.md"},
        })
        # Ajusta ts do artifact.added para 60h atrás no ledger
        lines = self.b.ledger_path.read_text(encoding="utf-8").splitlines()
        patched = []
        for ln in lines:
            row = json.loads(ln)
            if row.get("seq") == ev["seq"]:
                row["ts"] = dump_dt.isoformat(timespec="seconds")
            patched.append(json.dumps(row, ensure_ascii=False))
        self.b.ledger_path.write_text("\n".join(patched) + "\n", encoding="utf-8")
        self.b.reload()

        render_dt = base_now - timedelta(hours=10)
        util.write_json(self.b.inst.fresh / ".render-state.json", {
            "rendered_at": render_dt.isoformat(timespec="seconds"),
            "todo": {},
            "records": {},
        })

        mem_state = self.b.inst.root / ".memory-state.json"
        mem_state.write_text("{}", encoding="utf-8")
        mem_ts = (base_now - timedelta(hours=30)).timestamp()
        os.utime(mem_state, (mem_ts, mem_ts))

        item_old = self.b.inst.inbox / "antigo.md"
        item_new = self.b.inst.inbox / "novo.md"
        item_old.write_text("antigo", encoding="utf-8")
        item_new.write_text("novo", encoding="utf-8")
        old_mtime = (base_now - timedelta(hours=50)).timestamp()
        new_mtime = (base_now - timedelta(hours=2)).timestamp()
        os.utime(item_old, (old_mtime, old_mtime))
        os.utime(item_new, (new_mtime, new_mtime))

        f1 = doctor.freshness(self.b, now=base_now)
        self.assertAlmostEqual(f1["last_dump_age_h"], 60.0, places=1)
        self.assertAlmostEqual(f1["last_render_age_h"], 10.0, places=1)
        self.assertAlmostEqual(f1["last_memory_sync_age_h"], 30.0, places=1)
        self.assertEqual(f1["inbox_backlog"], 2)
        self.assertAlmostEqual(f1["inbox_oldest_age_h"], 50.0, places=1)
        self.assertEqual(f1["stale"], {"dump": True, "render": False, "memory_sync": True, "inbox": True})

        # Verifica m["freshness"] em render.view_model(brain)
        vm = render.view_model(self.b)
        self.assertIn("freshness", vm)
        self.assertEqual(vm["freshness"]["inbox_backlog"], 2)
        self.assertEqual(vm["freshness"]["thresholds"], doctor.FRESHNESS_THRESHOLDS)


if __name__ == "__main__":
    unittest.main()
