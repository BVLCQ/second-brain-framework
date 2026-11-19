"""Testes do backfill `brain seed folder` e da extensão `captured_at` no snapshot."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, seed, snapshot, util
from brainlib.core import Brain


def _make_brain(tmp: Path) -> Brain:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    for sub in ("PLANNING", "PROFILE", "RAW/inbox", "PROCESSED", "FRESH", "reports"):
        (tmp / "vault" / sub).mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n', encoding="utf-8"
    )
    (tmp / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    b = Brain(config.load(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    return b


def _make_docx(path: Path, paragraphs: list[str]) -> None:
    xml_paras = "".join(
        f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs
    )
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{xml_paras}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", doc_xml)


def _set_mtime(path: Path, dt: datetime) -> float:
    ts = dt.timestamp()
    os.utime(path, (ts, ts))
    return path.stat().st_mtime


class SeedFolderTests(unittest.TestCase):
    def test_import_all_supported_formats_preserves_date_prefix_and_mtime(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            b = _make_brain(tmp / "inst")
            src = tmp / "historico"
            (src / "sub").mkdir(parents=True)

            base_dt = datetime.now(util.tz()).replace(microsecond=0)
            dt_md = base_dt - timedelta(days=400)
            dt_txt = base_dt - timedelta(days=300)
            dt_docx = base_dt - timedelta(days=200)
            dt_pdf = base_dt - timedelta(days=100)

            p_md = src / "ata.md"
            p_md.write_text("# Reunião antiga\nDecisão registrada.\n", encoding="utf-8")
            mt_md = _set_mtime(p_md, dt_md)

            p_txt = src / "anotacao.txt"
            p_txt.write_bytes("Anotação em latin-1: ação concluída.\n".encode("latin-1"))
            mt_txt = _set_mtime(p_txt, dt_txt)

            p_docx = src / "sub" / "proposta.docx"
            _make_docx(p_docx, ["Primeiro parágrafo", "Segundo parágrafo"])
            mt_docx = _set_mtime(p_docx, dt_docx)

            p_pdf = src / "relatorio.pdf"
            p_pdf.write_bytes(b"%PDF-1.4 fake")
            mt_pdf = _set_mtime(p_pdf, dt_pdf)

            # Arquivo fora das extensões suportadas deve ser ignorado
            (src / "planilha.csv").write_text("a,b\n1,2\n", encoding="utf-8")

            seen_progress: list[tuple[int, int, str]] = []
            res = seed.seed_folder(
                b,
                src,
                kind="documento",
                pdf_extractor=lambda p: f"Texto extraído de {p.name}",
                progress_cb=lambda done, total, rel: seen_progress.append((done, total, rel)),
            )

            self.assertEqual(res["total_found"], 4)
            self.assertEqual(res["imported"], 4)
            self.assertEqual(res["skipped_unchanged"], 0)
            self.assertEqual(res["remaining"], 0)
            self.assertEqual(res["errors"], [])
            self.assertEqual([p[0] for p in seen_progress], [1, 2, 3, 4])
            self.assertEqual([p[1] for p in seen_progress], [4, 4, 4, 4])

            expected = {
                "ata.md": (dt_md.strftime("%Y-%m-%d"), mt_md, "# Reunião antiga"),
                "anotacao.txt": (dt_txt.strftime("%Y-%m-%d"), mt_txt, "ação concluída"),
                "sub/proposta.docx": (dt_docx.strftime("%Y-%m-%d"), mt_docx, "Primeiro parágrafo\n\nSegundo parágrafo"),
                "relatorio.pdf": (dt_pdf.strftime("%Y-%m-%d"), mt_pdf, "Texto extraído de relatorio.pdf"),
            }
            by_src = {f["src"]: f for f in res["files"]}
            self.assertEqual(set(by_src), set(expected))

            for rel_src, (date_prefix, orig_mtime, snippet) in expected.items():
                snap_path = b.inst.vault / by_src[rel_src]["snapshot"]
                self.assertTrue(snap_path.is_file())
                self.assertTrue(snap_path.name.startswith(f"{date_prefix}-"), snap_path.name)
                self.assertAlmostEqual(snap_path.stat().st_mtime, orig_mtime, places=2)
                body = snap_path.read_text(encoding="utf-8")
                self.assertIn(f"_pull: seed-folder · kind=documento · origem={rel_src}", body)
                self.assertIn(snippet, body)

            state = util.read_json(b.inst.state_file, {})
            key = f"seed-folder:{util.slugify(src.resolve().name, 32)}"
            for rel_src in expected:
                slot = state[f"snapshot:{key}#{rel_src}"]
                self.assertIn("captured_at", slot)
                self.assertIn("at", slot)

    def test_idempotency_by_hash_skips_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            b = _make_brain(tmp / "inst")
            src = tmp / "docs"
            src.mkdir()
            for i in range(3):
                p = src / f"doc-{i}.md"
                p.write_text(f"Conteúdo {i}\n", encoding="utf-8")
                _set_mtime(p, datetime.now(util.tz()) - timedelta(days=30 + i))

            r1 = seed.seed_folder(b, src)
            self.assertEqual(r1["imported"], 3)
            inbox_before = sorted(p.name for p in b.inst.inbox.glob("*"))

            r2 = seed.seed_folder(b, src)
            self.assertEqual(r2["imported"], 0)
            self.assertEqual(r2["skipped_unchanged"], 3)
            self.assertEqual(r2["remaining"], 0)
            inbox_after = sorted(p.name for p in b.inst.inbox.glob("*"))
            self.assertEqual(inbox_before, inbox_after)

    def test_batch_limit_and_resumption(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            b = _make_brain(tmp / "inst")
            src = tmp / "lote"
            src.mkdir()
            base_dt = datetime.now(util.tz()) - timedelta(days=60)
            for i in range(5):
                p = src / f"item-{i}.md"
                p.write_text(f"Nota número {i}\n", encoding="utf-8")
                _set_mtime(p, base_dt + timedelta(days=i))

            r1 = seed.seed_folder(b, src, limit=2)
            self.assertEqual((r1["imported"], r1["remaining"], r1["skipped_unchanged"]), (2, 3, 0))

            r2 = seed.seed_folder(b, src, limit=2)
            self.assertEqual((r2["imported"], r2["remaining"], r2["skipped_unchanged"]), (2, 1, 2))

            r3 = seed.seed_folder(b, src, limit=2)
            self.assertEqual((r3["imported"], r3["remaining"], r3["skipped_unchanged"]), (1, 0, 4))

            r4 = seed.seed_folder(b, src, limit=2)
            self.assertEqual((r4["imported"], r4["remaining"], r4["skipped_unchanged"]), (0, 0, 5))
            self.assertEqual(len(list(b.inst.inbox.glob("*.md"))), 5)

    def test_refuses_vault_self_ingestion(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            b = _make_brain(tmp / "inst")
            for bad in (b.inst.vault, b.inst.inbox, b.inst.vault / "RAW", b.inst.root):
                with self.assertRaises(util.BrainError) as ctx:
                    seed.seed_folder(b, bad)
                self.assertEqual(ctx.exception.code, 4)

    def test_resilience_errors_and_hidden_files(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            b = _make_brain(tmp / "inst")
            src = tmp / "misto"
            (src / ".git").mkdir(parents=True)
            (src / ".git" / "config.md").write_text("ignorar\n", encoding="utf-8")
            (src / ".DS_Store").write_bytes(b"\x00\x01")
            (src / ".hidden.md").write_text("oculto\n", encoding="utf-8")

            base_dt = datetime.now(util.tz()) - timedelta(days=10)

            bad_docx = src / "corrompido.docx"
            bad_docx.write_bytes(b"nao e um zip")
            _set_mtime(bad_docx, base_dt)

            empty_pdf = src / "escaneado.pdf"
            empty_pdf.write_bytes(b"%PDF-1.4")
            _set_mtime(empty_pdf, base_dt + timedelta(hours=1))

            valid_md = src / "valido.md"
            valid_md.write_text("Conteúdo aproveitável\n", encoding="utf-8")
            _set_mtime(valid_md, base_dt + timedelta(hours=2))

            res = seed.seed_folder(b, src, pdf_extractor=lambda _p: "=== PÁGINA 1 ===\n   \n")
            self.assertEqual(res["total_found"], 3)
            self.assertEqual(res["imported"], 1)
            self.assertEqual(len(res["errors"]), 2)
            err_paths = {e["path"]: e["error"] for e in res["errors"]}
            self.assertIn("corrompido.docx", err_paths)
            self.assertIn("escaneado.pdf", err_paths)
            self.assertEqual(err_paths["escaneado.pdf"], "PDF sem texto extraível")
            self.assertEqual([f["src"] for f in res["files"]], ["valido.md"])

    def test_cli_seed_folder_json_and_text_output(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            inst_dir = tmp / "inst"
            _make_brain(inst_dir)
            src = tmp / "origem"
            src.mkdir()
            base_dt = datetime.now(util.tz()) - timedelta(days=15)
            for i in range(3):
                p = src / f"nota-{i}.txt"
                p.write_text(f"Texto da nota {i}\n", encoding="utf-8")
                _set_mtime(p, base_dt + timedelta(days=i))

            env = {**os.environ, "BRAIN_HOME": str(inst_dir)}
            r1 = subprocess.run(
                [sys.executable, str(ROOT / "brain"), "seed", "folder", str(src), "--limit", "2", "--kind", "nota", "--json"],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(r1.returncode, 0, r1.stderr)
            data = json.loads(r1.stdout)
            self.assertEqual(data["kind"], "nota")
            self.assertEqual(data["limit"], 2)
            self.assertEqual(data["total_found"], 3)
            self.assertEqual(data["imported"], 2)
            self.assertEqual(data["remaining"], 1)

            r2 = subprocess.run(
                [sys.executable, str(ROOT / "brain"), "seed", "folder", str(src), "--limit", "2", "--kind", "nota"],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertIn("importado: nota-2.txt", r2.stdout)
            self.assertIn("/dump", r2.stdout)

            r3 = subprocess.run(
                [sys.executable, str(ROOT / "brain"), "seed", "folder", str(src), "--limit", "2", "--kind", "nota"],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(r3.returncode, 0, r3.stderr)
            self.assertEqual(r3.stdout.strip(), "✓ pasta já sincronizada (nada novo)")

    def test_snapshot_captured_at_collision_and_iso_str(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            b = _make_brain(tmp / "inst")
            dt = (datetime.now(util.tz()) - timedelta(days=50)).replace(microsecond=0)
            r1 = snapshot.take(b, "seed-folder:x", "conteudo A\n", item="a.md", name="mesmo", captured_at=dt.isoformat())
            r2 = snapshot.take(b, "seed-folder:x", "conteudo B\n", item="b.md", name="mesmo", captured_at=dt)
            self.assertTrue(r1["changed"] and r2["changed"])
            prefix = dt.strftime("%Y-%m-%d")
            self.assertTrue(r1["path"].name.startswith(f"{prefix}-"))
            self.assertTrue(r2["path"].name.startswith(f"{prefix}-"))
            self.assertTrue(r2["path"].stem.endswith("-2"))


if __name__ == "__main__":
    unittest.main()
