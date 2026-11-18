"""Testes de `watch.toml` (`enabled`, `slack-dm`, `exclude`, `source_status`) e agrupamento no TUI Fontes."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import cli, config, demo as demo_mod, forms, oppdrive, rawsort, render, share, snapshot, state, util, watch  # noqa: E402
from brainlib.core import Brain  # noqa: E402
from brainlib.tui import rows, store  # noqa: E402

try:
    import textual  # noqa: F401
    HAVE_TEXTUAL = True
except ImportError:
    HAVE_TEXTUAL = False


def _inst(tmp: Path) -> config.Instance:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "reports").mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n'
        '[oppdrive]\nenabled = true\nroot = "1RootOppDriveFolder"\n',
        encoding="utf-8",
    )
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n"
        "- por quê: teste\n\n### PROJ-1 — Projeto\n- status: ativo\n- dono: eu\n"
        "- [ ] PROJ-1.1 Um entregável · prazo: 2026-10-20 · peso: 2\n",
        encoding="utf-8",
    )
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "marina-demo", "by": "owner",
                  "data": {"name": "Marina-demo", "aliases": ["Marina"], "email": "marina-demo@x.com"}})
    return b


def _run_cli(root: Path, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, {"BRAIN_HOME": str(root)}):
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(list(argv))
    return rc, out.getvalue(), err.getvalue()


class WatchEnabledAndStatusTest(unittest.TestCase):
    NOW = "2026-10-19T10:00:00-03:00"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.brain = _brain(self.root)
        self.inst = self.brain.inst
        self.old_now = os.environ.get("BRAIN_NOW")
        os.environ["BRAIN_NOW"] = self.NOW
        self.addCleanup(self._restore_now)

    def _restore_now(self):
        if self.old_now is None:
            os.environ.pop("BRAIN_NOW", None)
        else:
            os.environ["BRAIN_NOW"] = self.old_now

    def test_1_missing_enabled_defaults_to_true_everywhere(self):
        doc_id = "1AbCdEfGhIjKlMnOpQrStUv"
        watch.add(self.inst, "slack-dados", {"kind": "slack", "window": "1d", "channel": "#dados"})
        watch.add(self.inst, "playbook-1", {"kind": "drive-doc", "doc": doc_id})
        srcs = watch.list_sources(self.inst)
        self.assertTrue(all(watch.is_enabled(s) for s in srcs))
        self.assertEqual(watch.since(self.brain, "slack-dados")["window"], "1d")
        self.assertEqual(watch.docs(self.brain)["ids"], [doc_id])
        rendered = {s["key"]: s for s in render._sources(self.brain)}
        self.assertTrue(rendered["slack-dados"]["enabled"])
        self.assertTrue(rendered["playbook-1"]["enabled"])

    def test_2_disable_and_reenable_source_preserves_comments_and_skips_since_and_docs(self):
        doc_a = "1AaaaaaaaaaaaaaaaaaaaAa"
        doc_b = "1BbbbbbbbbbbbbbbbbbbbBb"
        watch.path(self.inst).write_text(
            "# cabeçalho\n\n"
            "[[source]]\nkey = \"slack-dados\"\nkind = \"slack\"\nwindow = \"1d\"  # manter\n\n"
            "[[source]]\nkey = \"doc-a\"\nkind = \"drive-doc\"\ndoc = \"" + doc_a + "\"\n\n"
            "[[source]]\nkey = \"doc-b\"\nkind = \"drive-doc\"\ndoc = \"" + doc_b + "\"\n",
            encoding="utf-8",
        )
        rc, _, err = _run_cli(self.root, "watch", "edit", "slack-dados", "--set", "enabled=false")
        self.assertEqual(rc, 0, err)
        raw_toml = watch.path(self.inst).read_text(encoding="utf-8")
        self.assertIn("enabled = false", raw_toml)
        self.assertNotIn('enabled = "false"', raw_toml)
        self.assertIn("# cabeçalho", raw_toml)
        self.assertIn('window = "1d"  # manter', raw_toml)

        rc, _, err = _run_cli(self.root, "watch", "edit", "doc-a", "--set", "enabled=false")
        self.assertEqual(rc, 0, err)

        with self.assertRaises(util.BrainError) as ctx:
            watch.since(self.brain, "slack-dados")
        self.assertEqual(ctx.exception.code, 3)
        self.assertIn("desligada", str(ctx.exception))

        d = watch.docs(self.brain)
        self.assertEqual(d["ids"], [doc_b])

        # list text & --json
        rc, out, _ = _run_cli(self.root, "watch", "list")
        self.assertEqual(rc, 0)
        self.assertIn("desligada", out)
        rc, jout, _ = _run_cli(self.root, "watch", "list", "--json")
        self.assertEqual(rc, 0)
        by_key = {s["key"]: s for s in json.loads(jout)}
        self.assertFalse(by_key["slack-dados"]["enabled"])
        self.assertTrue(by_key["doc-b"]["enabled"])

        # comentário inline em `enabled = true  # obs` sobrevive ao editar para false e vice-versa
        watch.path(self.inst).write_text(
            "[[source]]\nkey = \"slack-dados\"\nkind = \"slack\"\nenabled = false  # pausada no feriado\n",
            encoding="utf-8",
        )
        rc, _, err = _run_cli(self.root, "watch", "edit", "slack-dados", "--set", "enabled=true")
        self.assertEqual(rc, 0, err)
        txt = watch.path(self.inst).read_text(encoding="utf-8")
        self.assertIn("enabled = true  # pausada no feriado", txt)
        self.assertEqual(watch.since(self.brain, "slack-dados")["window"], "1d")

        # strings defensivas e valor inválido
        self.assertFalse(watch.is_enabled({"enabled": "nao"}))
        self.assertFalse(watch.is_enabled({"enabled": "0"}))
        self.assertTrue(watch.is_enabled({"enabled": "sim"}))
        with self.assertRaises(util.BrainError) as bad:
            watch.edit(self.inst, "slack-dados", {"enabled": "talvez"})
        self.assertEqual(bad.exception.code, 4)

    def test_3_source_status_buckets_and_reasons(self):
        now = util.parse_dt(self.NOW)
        # desabilitada: mesmo com falhas ou nunca puxada, problem=False e sort_bucket=2
        st_dis = watch.source_status({"key": "s1", "kind": "slack", "enabled": False},
                                     state.Connector("s1", consecutive_failures=3))
        self.assertEqual(st_dis, {"enabled": False, "problem": False, "problem_reason": "desligada", "sort_bucket": 2})

        # falhas seguidas
        st_fail = watch.source_status({"key": "s2", "kind": "slack"},
                                      state.Connector("s2", last_ok=self.NOW, consecutive_failures=2), now=now)
        self.assertEqual(st_fail, {"enabled": True, "problem": True, "problem_reason": "2 falha(s)", "sort_bucket": 0})

        # nunca puxada
        st_never = watch.source_status({"key": "s3", "kind": "gmail"}, None, now=now)
        self.assertEqual(st_never, {"enabled": True, "problem": True, "problem_reason": "nunca puxada", "sort_bucket": 0})

        # atrasada (window 1d -> corte max(36h, 30h) = 36h)
        stale_dt = (now - timedelta(hours=37)).isoformat(timespec="seconds")
        st_stale = watch.source_status({"key": "s4", "kind": "slack", "window": "1d"},
                                       state.Connector("s4", last_ok=stale_dt), now=now)
        self.assertEqual(st_stale, {"enabled": True, "problem": True, "problem_reason": "atrasada", "sort_bucket": 0})

        # dentro da tolerância (31h <= 36h) -> ok
        ok_dt = (now - timedelta(hours=31)).isoformat(timespec="seconds")
        st_ok = watch.source_status({"key": "s5", "kind": "slack", "window": "1d"},
                                    state.Connector("s5", last_ok=ok_dt), now=now)
        self.assertEqual(st_ok, {"enabled": True, "problem": False, "problem_reason": "", "sort_bucket": 1})

        # NO_WINDOW (drive-doc / github) não fica atrasada por janela
        old_dt = (now - timedelta(days=30)).isoformat(timespec="seconds")
        st_doc = watch.source_status({"key": "d1", "kind": "drive-doc"},
                                     state.Connector("d1", last_ok=old_dt), now=now)
        self.assertEqual(st_doc, {"enabled": True, "problem": False, "problem_reason": "", "sort_bucket": 1})

        # render._sources inclui in_watch=False com defaults sadios
        watch.add(self.inst, "s-ok", {"kind": "slack", "window": "1d"})
        self.brain.record_one({"type": "connector.pulled", "id": "s-ok", "by": "system",
                               "data": {"changed": False}})
        self.brain.record_one({"type": "connector.pulled", "id": "avulsa-1", "by": "system",
                               "data": {"changed": False}})
        by_key = {s["key"]: s for s in render._sources(self.brain)}
        self.assertEqual((by_key["s-ok"]["enabled"], by_key["s-ok"]["problem"]), (True, False))
        self.assertEqual((by_key["avulsa-1"]["in_watch"], by_key["avulsa-1"]["enabled"], by_key["avulsa-1"]["problem"]),
                         (False, True, False))


class SlackDmAndPrivacyTest(unittest.TestCase):
    NOW = "2026-10-19T10:00:00-03:00"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.brain = _brain(self.root)
        self.inst = self.brain.inst
        self.old_now = os.environ.get("BRAIN_NOW")
        os.environ["BRAIN_NOW"] = self.NOW
        self.addCleanup(self._restore_now)

    def _restore_now(self):
        if self.old_now is None:
            os.environ.pop("BRAIN_NOW", None)
        else:
            os.environ["BRAIN_NOW"] = self.old_now

    def test_4_slack_dm_kind_exclude_roundtrip_and_forms(self):
        self.assertIn("slack-dm", [k for k, _ in watch.KINDS])
        self.assertNotIn("slack-dm", watch.NO_WINDOW)

        rc, _, err = _run_cli(self.root, "watch", "add", "slack-dms", "--kind", "slack-dm",
                              "--set", "exclude=U111, @fulano ")
        self.assertEqual(rc, 0, err)
        raw_toml = watch.path(self.inst).read_text(encoding="utf-8")
        self.assertIn('exclude = ["U111", "@fulano"]', raw_toml)

        srcs = watch.list_sources(self.inst)
        self.assertEqual(srcs[0]["kind"], "slack-dm")
        self.assertEqual(srcs[0]["exclude"], ["U111", "@fulano"])
        self.assertEqual(watch.since(self.brain, "slack-dms")["window"], "1d")

        # forms.build para watch.add / watch.edit com slack-dm e enabled
        add_cmd = forms.build("watch.add", {"key": "dm2", "kind": "slack-dm", "exclude": "U1, U2", "window": "1d"}, {}, {})[0]
        self.assertIn("--set", add_cmd)
        self.assertIn("exclude=U1, U2", add_cmd)

        edit_cmd = forms.build("watch.edit", {"key": "slack-dms", "kind": "slack-dm", "exclude": "", "enabled": "false"},
                               {"key0": "slack-dms", "item": {**srcs[0], "enabled": True}}, {})[0]
        self.assertIn("--unset", edit_cmd)
        self.assertIn("exclude", edit_cmd)
        self.assertIn("enabled=false", edit_cmd)

        rc, _, err = _run_cli(self.root, "watch", "edit", "slack-dms", "--unset", "exclude")
        self.assertEqual(rc, 0, err)
        self.assertNotIn("exclude", watch.list_sources(self.inst)[0])

    def test_5_slack_dm_snapshot_archives_to_slack_and_never_leaks_to_oppdrive_or_share(self):
        secret_dm = "SEGREDO_DM_CONFIDENCIAL_XYZ"
        res = snapshot.take(self.brain, "slack-dms", f"# DM Marina\n\n{secret_dm}\n",
                            item="D012345", name="marina", prefix="slack")
        self.assertTrue(res["changed"])
        moved = rawsort.archive(self.inst)
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0]["type"], "slack")
        self.assertTrue(moved[0]["to"].startswith("RAW/2026/10/slack/"))

        # oppdrive nunca aceita RAW/.../slack/ nem lista como upload
        self.brain.record_one({"type": "area.added", "id": "ops", "by": "owner", "data": {"name": "Ops"}})
        self.brain.record_one({"type": "artifact.added", "id": "ART-0001", "by": "agent", "prov": "observado",
                               "source": moved[0]["to"],
                               "data": {"raw": moved[0]["to"], "kind": "conector", "title": "DM Marina",
                                        "summary": "DM com marina", "projects": [], "people": ["marina-demo"],
                                        "links": []}})
        opp_id = self.brain.record_one({"type": "opportunity.added", "by": "agent", "prov": "observado",
                                        "source": "ART-0001",
                                        "data": {"title": "Melhoria", "area": "ops"}})["id"]
        b2 = Brain(self.inst)
        opp_obj = b2.state.opportunities[opp_id]
        sf = oppdrive.source_files(b2, opp_obj)
        self.assertEqual(sf["upload"], [])
        self.assertEqual(len(sf["mention"]), 1)
        rc, _, err = _run_cli(self.root, "oppdrive", "record", opp_id, "--folder", "1FolderOppId00",
                              "--parent", "1RootOppDriveFolder")
        self.assertEqual(rc, 0, err)
        rc, _, err = _run_cli(self.root, "oppdrive", "record", opp_id, "--sources-folder", "1FontesFolder0",
                              "--parent", "1FolderOppId00")
        self.assertEqual(rc, 0, err)
        rc, _, err = _run_cli(self.root, "oppdrive", "record", opp_id, "--source-file", "1DriveFileId00",
                              "--raw", moved[0]["to"], "--parent", "1FontesFolder0")
        self.assertEqual(rc, 4)
        self.assertIn("só sobe documento", err)

        # share nunca vaza o corpo do snapshot bruto da DM
        out_path = share.export(b2, "opportunity", opp_id, fmt="md")
        exported = out_path.read_text(encoding="utf-8")
        self.assertNotIn(secret_dm, exported)


class TuiSourcesGroupingAndToggleTest(unittest.IsolatedAsyncioTestCase):
    NOW = "2026-10-19T10:00:00-03:00"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "inst"
        with contextlib.redirect_stdout(io.StringIO()):
            demo_mod.cli(argparse.Namespace(dir=str(self.root), open=False))
        self.inst = config.load(self.root)
        self.old_now = os.environ.get("BRAIN_NOW")
        os.environ["BRAIN_NOW"] = self.NOW
        self.addCleanup(self._restore_now)

        # Fontes em 3 tipos: gmail (1 falha + 1 ok antiga + 1 ok recente + 1 desligada), gcal (ok), slack (atrasada)
        watch.add(self.inst, "gmail-ok-recente", {"kind": "gmail", "window": "1d"})
        watch.add(self.inst, "gmail-ok-antiga", {"kind": "gmail", "window": "7d"})
        watch.add(self.inst, "gmail-falha", {"kind": "gmail", "window": "1d"})
        watch.add(self.inst, "gmail-off", {"kind": "gmail", "window": "1d", "enabled": False})
        watch.add(self.inst, "gcal-ok", {"kind": "gcal", "window": "7d"})
        watch.add(self.inst, "slack-atrasada", {"kind": "slack", "window": "1d"})

        b = Brain(self.inst)
        def rec_at(ts: str, ev: dict) -> None:
            with mock.patch.dict(os.environ, {"BRAIN_NOW": ts}):
                b.record_one(ev)

        rec_at("2026-10-19T09:00:00-03:00", {"type": "connector.pulled", "id": "gmail-ok-recente", "by": "system",
                                              "data": {"changed": False}})
        rec_at("2026-10-18T09:00:00-03:00", {"type": "connector.pulled", "id": "gmail-ok-antiga", "by": "system",
                                              "data": {"changed": False}})
        rec_at("2026-10-19T08:00:00-03:00", {"type": "connector.pulled", "id": "gmail-falha", "by": "system",
                                              "data": {"changed": False}})
        rec_at("2026-10-19T09:30:00-03:00", {"type": "connector.failed", "id": "gmail-falha", "by": "system",
                                              "data": {"error": "timeout"}})
        rec_at("2026-10-19T07:00:00-03:00", {"type": "connector.pulled", "id": "gcal-ok", "by": "system",
                                              "data": {"changed": False}})
        rec_at("2026-10-17T08:00:00-03:00", {"type": "connector.pulled", "id": "slack-atrasada", "by": "system",
                                              "data": {"changed": False}})

    def _restore_now(self):
        if self.old_now is None:
            os.environ.pop("BRAIN_NOW", None)
        else:
            os.environ["BRAIN_NOW"] = self.old_now

    def test_6_store_grouping_sorting_and_disabled_row_rendering(self):
        st = store.Store(self.inst)
        desc_items = st.items(0, 1, 1, sort=0)
        ids_desc = [i.id for i in desc_items]
        # Grupos com problema primeiro (gmail, slack — alfabético), depois gcal (saudável)
        self.assertEqual(ids_desc, [
            "sgrp:gmail",
            "src:gmail-falha",
            "src:gmail-ok-recente",
            "src:gmail-ok-antiga",
            "src:gmail-off",
            "sgrp:slack",
            "src:slack-atrasada",
            "sgrp:gcal",
            "src:gcal-ok",
        ])

        # Alternando para asc (o): problemas continuam no topo; saudáveis invertem (antiga antes de recente); desligada por último
        asc_items = st.items(0, 1, 1, sort=1)
        ids_asc = [i.id for i in asc_items]
        self.assertEqual(ids_asc, [
            "sgrp:gmail",
            "src:gmail-falha",
            "src:gmail-ok-antiga",
            "src:gmail-ok-recente",
            "src:gmail-off",
            "sgrp:slack",
            "src:slack-atrasada",
            "sgrp:gcal",
            "src:gcal-ok",
        ])

        # Linha desligada renderiza em dim com [desligada]
        off_item = next(i for i in desc_items if i.id == "src:gmail-off")
        rendered_off = rows.row(st, off_item, 80)
        self.assertIn("[desligada]", rendered_off.plain)
        self.assertTrue(any("dim" in str(sp.style) for sp in rendered_off.spans))

        # Cabeçalho mostra label do tipo, contagem e indicador de problema
        hdr = next(i for i in desc_items if i.id == "sgrp:gmail")
        rendered_hdr = rows.row(st, hdr, 80)
        self.assertIn("gmail · e-mails (4)", rendered_hdr.plain)
        self.assertIn("⚠ 1", rendered_hdr.plain)

    @unittest.skipUnless(HAVE_TEXTUAL, "textual não instalado (./brain tui --setup)")
    async def test_6_tui_skips_headers_sorts_and_toggles_enabled(self):
        from brainlib.tui.app import BrainApp
        app = BrainApp(self.inst)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("1", "]")
            self.assertEqual((app.p, app.tab[1]), (1, 1))
            # Seleção inicial pula sgrp:gmail e cai em src:gmail-falha
            self.assertEqual(app.cur().id, "src:gmail-falha")

            # Mover para baixo pula sgrp:slack ao sair do grupo gmail
            await pilot.press("j", "j", "j")
            self.assertEqual(app.cur().id, "src:gmail-off")
            await pilot.press("j")
            self.assertEqual(app.cur().id, "src:slack-atrasada")
            await pilot.press("k")
            self.assertEqual(app.cur().id, "src:gmail-off")
            await pilot.press("home")
            self.assertEqual(app.cur().id, "src:gmail-falha")

            # jump_source continua funcionando com cabeçalhos na lista
            app.jump_source("gcal-ok")
            self.assertEqual(app.cur().id, "src:gcal-ok")

            # `o` alterna ordenação asc/desc mantendo problemas no topo
            await pilot.press("o")
            self.assertEqual(app.source_sort, 1)
            self.assertEqual([i.id for i in app.items(1)][:5], [
                "sgrp:gmail", "src:gmail-falha", "src:gmail-ok-antiga", "src:gmail-ok-recente", "src:gmail-off",
            ])
            await pilot.press("o")
            self.assertEqual(app.source_sort, 0)

            # `x` desliga a fonte selecionada e mantém ela selecionada após recarregar
            app.jump_source("gcal-ok")
            await pilot.press("x")
            for _ in range(80):
                await pilot.pause(0.1)
                if not app.busy and not app._lock.locked():
                    break
            gcal = next(s for s in watch.list_sources(self.inst) if s["key"] == "gcal-ok")
            self.assertFalse(watch.is_enabled(gcal))
            self.assertEqual(app.cur().id, "src:gcal-ok")

            # `x` liga de novo
            await pilot.press("x")
            for _ in range(80):
                await pilot.pause(0.1)
                if not app.busy and not app._lock.locked():
                    break
            gcal = next(s for s in watch.list_sources(self.inst) if s["key"] == "gcal-ok")
            self.assertTrue(watch.is_enabled(gcal))


if __name__ == "__main__":
    unittest.main()
