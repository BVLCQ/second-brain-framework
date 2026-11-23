"""Testes de integridade da migração de IDs: reconferência de hash sob trava e rollback atômico do ledger (#124, #131)."""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import migrate_ids, util  # noqa: E402
from brainlib.core import Brain  # noqa: E402
from test_brain import _brain  # noqa: E402


class MigrateIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.b = _brain(Path(self.td.name))

    def _seed_legacy_instance(self) -> tuple[Brain, Path, Path]:
        self.b.record_one({"type": "action.opened", "by": "owner", "data": {"title": "Revisar entrega", "owner": "eu"}})
        lp = self.b.ledger_path
        lp.write_text(lp.read_text(encoding="utf-8").replace('"TASK-0001"', '"A-0001"'), encoding="utf-8")

        stamp = util.today().isoformat()
        note = self.b.inst.vault / "RAW" / f"{util.today().year:04d}" / f"{util.today().month:02d}" / "notes" / f"A-0001-{stamp}-note.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(
            f"---\ntipo: nota\nvinculo: A-0001\ncriada: {stamp} 10:00\n---\nAcompanhar A-0001.\n",
            encoding="utf-8",
        )

        proc = self.b.inst.vault / "PROCESSED" / f"{util.today().year:04d}" / f"{util.today().month:02d}" / "reuniao.md"
        proc.parent.mkdir(parents=True, exist_ok=True)
        proc.write_text("Ata citando A-0001.\n", encoding="utf-8")

        return Brain(self.b.inst), note, proc

    def test_apply_aborts_if_non_ledger_file_mutated_between_plan_and_apply(self):
        b, note, proc = self._seed_legacy_instance()
        mig = migrate_ids.plan_migration(b)
        self.assertTrue(all(f.old_sha == util.sha(f.old) for f in mig.files))

        ledger_before = b.ledger_path.read_text(encoding="utf-8")
        note_before = note.read_text(encoding="utf-8")
        proc_mutated = proc.read_text(encoding="utf-8") + "Edição recente feita após o dry-run.\n"
        proc.write_text(proc_mutated, encoding="utf-8")

        with self.assertRaises(util.BrainError) as ctx:
            with contextlib.redirect_stdout(io.StringIO()):
                migrate_ids.apply(b, mig)

        self.assertEqual(ctx.exception.code, 5)
        self.assertIn("mudou desde o plano", str(ctx.exception))
        self.assertEqual(b.ledger_path.read_text(encoding="utf-8"), ledger_before)
        self.assertEqual(note.read_text(encoding="utf-8"), note_before)
        self.assertEqual(proc.read_text(encoding="utf-8"), proc_mutated)
        self.assertTrue(note.exists())
        self.assertFalse((b.inst.vault / migrate_ids.MARKER_REL).exists())
        self.assertEqual(list(b.inst.vault.parent.glob("brain-pre-ids-migration-*.zip")), [])

    def test_apply_aborts_if_planned_file_deleted_between_plan_and_apply(self):
        b, note, proc = self._seed_legacy_instance()
        mig = migrate_ids.plan_migration(b)

        ledger_before = b.ledger_path.read_text(encoding="utf-8")
        note_before = note.read_text(encoding="utf-8")
        proc.unlink()

        with self.assertRaises(util.BrainError) as ctx:
            with contextlib.redirect_stdout(io.StringIO()):
                migrate_ids.apply(b, mig)

        self.assertEqual(ctx.exception.code, 5)
        self.assertIn("mudou desde o plano", str(ctx.exception))
        self.assertEqual(b.ledger_path.read_text(encoding="utf-8"), ledger_before)
        self.assertEqual(note.read_text(encoding="utf-8"), note_before)
        self.assertFalse((b.inst.vault / migrate_ids.MARKER_REL).exists())
        self.assertEqual(list(b.inst.vault.parent.glob("brain-pre-ids-migration-*.zip")), [])

    def test_apply_aborts_if_goals_md_mutated_between_plan_and_apply(self):
        b, note, proc = self._seed_legacy_instance()
        mig = migrate_ids.plan_migration(b)
        self.assertNotIn("PLANNING/goals.md", {f.rel for f in mig.files})

        ledger_before = b.ledger_path.read_text(encoding="utf-8")
        goals_mutated = b.inst.planning_file.read_text(encoding="utf-8") + "\n## G2 — Novo objetivo\n"
        b.inst.planning_file.write_text(goals_mutated, encoding="utf-8")

        with self.assertRaises(util.BrainError) as ctx:
            with contextlib.redirect_stdout(io.StringIO()):
                migrate_ids.apply(b, mig)

        self.assertEqual(ctx.exception.code, 5)
        self.assertIn("mudou desde o plano", str(ctx.exception))
        self.assertEqual(b.ledger_path.read_text(encoding="utf-8"), ledger_before)
        self.assertEqual(b.inst.planning_file.read_text(encoding="utf-8"), goals_mutated)
        self.assertEqual(list(b.inst.vault.parent.glob("brain-pre-ids-migration-*.zip")), [])

    def test_rollback_uses_atomic_replace_and_fsync(self):
        b, note, proc = self._seed_legacy_instance()
        mig = migrate_ids.plan_migration(b)

        ledger_before = b.ledger_path.read_text(encoding="utf-8")
        note_before = note.read_text(encoding="utf-8")
        proc_before = proc.read_text(encoding="utf-8")

        marker_path = b.inst.vault / migrate_ids.MARKER_REL
        orig_write_text = Path.write_text
        orig_replace = os.replace
        orig_fsync = os.fsync

        write_text_paths: list[Path] = []
        replace_calls: list[tuple[Path, Path]] = []
        fsync_count = 0

        def wrapped_write_text(self_path: Path, data: str, *args, **kwargs):
            write_text_paths.append(self_path)
            if self_path == marker_path:
                raise OSError("falha simulada ao gravar marcador")
            return orig_write_text(self_path, data, *args, **kwargs)

        def spy_replace(src, dst):
            replace_calls.append((Path(src), Path(dst)))
            return orig_replace(src, dst)

        def spy_fsync(fd):
            nonlocal fsync_count
            fsync_count += 1
            return orig_fsync(fd)

        with mock.patch.object(Path, "write_text", wrapped_write_text), \
             mock.patch("brainlib.migrate_ids.os.replace", side_effect=spy_replace), \
             mock.patch("brainlib.migrate_ids.os.fsync", side_effect=spy_fsync):
            with self.assertRaises(util.BrainError) as ctx:
                with contextlib.redirect_stdout(io.StringIO()):
                    migrate_ids.apply(b, mig)

        self.assertEqual(ctx.exception.code, 5)
        self.assertEqual(b.ledger_path.read_text(encoding="utf-8"), ledger_before)
        self.assertEqual(note.read_text(encoding="utf-8"), note_before)
        self.assertEqual(proc.read_text(encoding="utf-8"), proc_before)
        self.assertFalse(marker_path.exists())
        self.assertFalse(b.ledger_path.with_suffix(".jsonl.migrating").exists())

        # Nenhum Path.write_text direto em events.jsonl (nem no caminho forward nem no rollback)
        self.assertNotIn(b.ledger_path, write_text_paths)

        # Tanto a escrita forward quanto o rollback usaram arquivo .migrating + fsync + os.replace
        ledger_replaces = [(src, dst) for src, dst in replace_calls if dst == b.ledger_path]
        self.assertEqual(len(ledger_replaces), 2)
        for src, dst in ledger_replaces:
            self.assertEqual(src.name, "events.jsonl.migrating")
            self.assertEqual(dst, b.ledger_path)
        self.assertGreaterEqual(fsync_count, 2)

    def test_rollback_keeps_going_and_still_restores_ledger_when_one_undo_step_fails(self):
        # um passo do desfazimento que falha não pode impedir os seguintes — o ledger é o último e o mais importante
        b, note, proc = self._seed_legacy_instance()
        mig = migrate_ids.plan_migration(b)
        self.assertGreaterEqual(len(mig.files), 2)

        ledger_before = b.ledger_path.read_text(encoding="utf-8")
        first = mig.files[0]
        self.assertIsNotNone(first.path)
        marker_path = b.inst.vault / migrate_ids.MARKER_REL
        orig_write_text = Path.write_text
        orig_atomic_write = util.atomic_write

        def failing_marker_write(self_path: Path, data: str, *args, **kwargs):     # derruba o caminho forward no fim
            if self_path == marker_path:
                raise OSError("falha simulada ao gravar marcador")
            return orig_write_text(self_path, data, *args, **kwargs)

        def failing_undo(path: Path, text: str) -> bool:                            # e derruba SÓ um passo do desfazimento
            if Path(path) == Path(first.path) and text == first.old:
                raise OSError("falha simulada ao restaurar um arquivo")
            return orig_atomic_write(path, text)

        with mock.patch.object(Path, "write_text", failing_marker_write), \
             mock.patch.object(migrate_ids.util, "atomic_write", side_effect=failing_undo):
            with self.assertRaises(util.BrainError) as ctx:
                with contextlib.redirect_stdout(io.StringIO()):
                    migrate_ids.apply(b, mig)

        self.assertEqual(ctx.exception.code, 5)
        msg = str(ctx.exception)
        self.assertIn("o desfazimento ficou incompleto", msg)
        self.assertIn(f"restaurar {first.rel}", msg)
        self.assertIn("Restaure pelo backup", msg)
        # o passo que falhou ficou como está; todos os outros foram desfeitos; o ledger voltou
        self.assertEqual(Path(first.path).read_text(encoding="utf-8"), first.new)
        for f in mig.files[1:]:
            self.assertEqual(Path(f.path).read_text(encoding="utf-8"), f.old)
        self.assertEqual(b.ledger_path.read_text(encoding="utf-8"), ledger_before)
        self.assertFalse(marker_path.exists())

    def test_cli_apply_plans_under_lock_and_completes(self):
        b, note, proc = self._seed_legacy_instance()
        events_order: list[str] = []
        orig_lock = Brain._lock
        orig_plan = migrate_ids.plan_migration

        @contextlib.contextmanager
        def spy_lock(self_brain):
            events_order.append("lock_enter")
            with orig_lock(self_brain):
                yield
            events_order.append("lock_exit")

        def spy_plan(self_brain, include_external=False):
            events_order.append("plan")
            return orig_plan(self_brain, include_external)

        with mock.patch.object(Brain, "_lock", spy_lock), \
             mock.patch("brainlib.migrate_ids.plan_migration", side_effect=spy_plan):
            with contextlib.redirect_stdout(io.StringIO()):
                migrate_ids.cli(argparse.Namespace(apply=True, include_external=False), b)

        self.assertEqual(events_order[:3], ["lock_enter", "plan", "lock_exit"])
        self.assertTrue((b.inst.vault / migrate_ids.MARKER_REL).exists())
        self.assertIn("TASK-0001", proc.read_text(encoding="utf-8"))
        self.assertFalse(note.exists())
        self.assertTrue(note.with_name(note.name.replace("A-0001", "TASK-0001")).exists())


if __name__ == "__main__":
    unittest.main()
