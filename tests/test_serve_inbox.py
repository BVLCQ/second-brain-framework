"""Testes da Issue #28: arrastar arquivo ou pasta para a inbox via ponte `./brain serve` (`POST /api/inbox`)."""
from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import serve  # noqa: E402
from test_brain import _inst  # noqa: E402


def _multipart_body(
    *,
    filename: str | None = "nota.txt",
    file_bytes: bytes = b"conteudo",
    mode: str | None = None,
    source_path: str | None = None,
    include_file: bool = True,
    boundary: str = "----BrainInboxTestBoundary7d9",
) -> tuple[str, bytes]:
    chunks: list[bytes] = []
    if mode is not None:
        chunks.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="mode"\r\n\r\n'
            f"{mode}\r\n".encode("utf-8")
        )
    if source_path is not None:
        chunks.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="source_path"\r\n\r\n'
            f"{source_path}\r\n".encode("utf-8")
        )
    if include_file:
        fn_attr = f'; filename="{filename}"' if filename is not None else ""
        chunks.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"{fn_attr}\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n".encode("utf-8")
            + file_bytes
            + b"\r\n"
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return f"multipart/form-data; boundary={boundary}", b"".join(chunks)


class ServeInboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.base = Path(cls.td.name)
        cls.inst = _inst(cls.base / "inst")
        cls.token = "tok-inbox-28"
        serve._Handler.state = serve._State(cls.inst, cls.token)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve._Handler)
        cls.httpd.daemon_threads = True
        cls.port = cls.httpd.server_address[1]
        serve._Handler.state.port = cls.port
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.td.cleanup()

    def setUp(self):
        # limpa inbox entre testes para previsibilidade das colisões
        for p in list(self.inst.inbox.glob("*")):
            if p.is_file() or p.is_symlink():
                p.unlink()

    def _post_raw(
        self,
        body: bytes,
        content_type: str,
        *,
        token: str | None = None,
        host: str | None = None,
        origin: str | None = None,
    ) -> tuple[int, dict]:
        url = f"http://127.0.0.1:{self.port}/api/inbox"
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", content_type)
        if token is not None:
            req.add_header("X-Brain-Token", token)
        req.add_header("Host", host if host is not None else f"127.0.0.1:{self.port}")
        if origin is not None:
            req.add_header("Origin", origin)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    # ── 1. segurança: token, Host, Origin ────────────────────────────────
    def test_auth_host_and_origin_guards(self):
        ct, body = _multipart_body(filename="seg.txt", file_bytes=b"oi", mode="copy")

        code, _ = self._post_raw(body, ct, token=None)
        self.assertEqual(code, 401)

        code, _ = self._post_raw(body, ct, token="errado")
        self.assertEqual(code, 401)

        code, data = self._post_raw(body, ct, token=self.token, host="atacante.invalid")
        self.assertEqual(code, 403)
        self.assertIn("127.0.0.1", data["error"])

        for evil_origin in ("http://atacante.invalid", "http://127.0.0.1.atacante.invalid", "null"):
            code, _ = self._post_raw(body, ct, token=self.token, origin=evil_origin)
            self.assertEqual(code, 403, evil_origin)

        # Origin exato do painel vivo é aceito
        code, data = self._post_raw(
            body, ct, token=self.token, origin=f"http://127.0.0.1:{self.port}"
        )
        self.assertEqual(code, 200)
        self.assertTrue(data["ok"])

    # ── 2. copy cria na inbox e mantém original ──────────────────────────
    def test_copy_creates_file_in_inbox_and_keeps_original(self):
        src = self.base / "origem.bin"
        payload = b"\x00\x01\xffrelatorio\r\n\xfe"
        src.write_bytes(payload)

        ct, body = _multipart_body(
            filename="relatório.bin",
            file_bytes=payload,
            mode="copy",
            source_path=str(src),
        )
        code, data = self._post_raw(body, ct, token=self.token)
        self.assertEqual(code, 200)
        self.assertEqual(
            data,
            {
                "ok": True,
                "name": "relatório.bin",
                "original": "relatório.bin",
                "moved": False,
                "moved_from": None,
                "fallback_copy": False,
                "candidates": [],
                "search": False,
                "search_complete": True,
            },
        )
        saved = self.inst.inbox / "relatório.bin"
        self.assertTrue(saved.is_file())
        self.assertEqual(saved.read_bytes(), payload)
        self.assertTrue(src.exists())

    def test_default_mode_is_copy(self):
        ct, body = _multipart_body(filename="padrao.md", file_bytes=b"# oi\n", mode=None)
        code, data = self._post_raw(body, ct, token=self.token)
        self.assertEqual(code, 200)
        self.assertFalse(data["moved"])
        self.assertFalse(data["fallback_copy"])
        self.assertEqual((self.inst.inbox / "padrao.md").read_bytes(), b"# oi\n")

    # ── 3. colisão recebe sufixo -2, -3 (rawsort.py) ─────────────────────
    def test_repeated_filename_gets_collision_suffixes(self):
        names = []
        for idx in range(3):
            ct, body = _multipart_body(
                filename="ata.md",
                file_bytes=f"versao {idx}".encode("utf-8"),
                mode="copy",
            )
            code, data = self._post_raw(body, ct, token=self.token)
            self.assertEqual(code, 200)
            names.append(data["name"])
        self.assertEqual(names, ["ata.md", "ata-2.md", "ata-3.md"])
        self.assertEqual((self.inst.inbox / "ata.md").read_bytes(), b"versao 0")
        self.assertEqual((self.inst.inbox / "ata-2.md").read_bytes(), b"versao 1")
        self.assertEqual((self.inst.inbox / "ata-3.md").read_bytes(), b"versao 2")

    # ── 4. path traversal, nomes inválidos, Content-Length, oversized ────
    def test_invalid_filenames_rejected_with_400_and_nothing_written(self):
        bad_names = [
            "../fora.txt",
            "../../etc/passwd",
            "sub/arquivo.txt",
            r"sub\arquivo.txt",
            ".",
            "..",
            ".keep.md",
            "",
            "   ",
            "nulo\x00.txt",
            "ctrl\n.txt",
        ]
        for bad in bad_names:
            with self.subTest(filename=bad):
                ct, body = _multipart_body(filename=bad, file_bytes=b"x", mode="copy")
                code, data = self._post_raw(body, ct, token=self.token)
                self.assertEqual(code, 400)
                self.assertFalse(data["ok"])
                self.assertEqual(
                    data["error"],
                    "nome de arquivo inválido — só caminhos dentro da inbox são aceitos",
                )
        self.assertFalse((self.inst.vault / "fora.txt").exists())
        self.assertEqual(list(self.inst.inbox.glob("*")), [])

    def test_missing_content_length_and_chunked_rejected_with_411(self):
        for headers in (
            {"Content-Type": "multipart/form-data; boundary=x"},
            {"Content-Type": "multipart/form-data; boundary=x", "Transfer-Encoding": "chunked"},
        ):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            conn.putrequest("POST", "/api/inbox")
            conn.putheader("Host", f"127.0.0.1:{self.port}")
            conn.putheader("X-Brain-Token", self.token)
            for k, v in headers.items():
                conn.putheader(k, v)
            conn.endheaders()
            resp = conn.getresponse()
            self.assertEqual(resp.status, 411)
            conn.close()

    def test_negative_and_oversized_content_length_rejected(self):
        for cl, expected in (("-1", 400), ("abc", 400), (str(serve.INBOX_UPLOAD_MAX + 1), 413)):
            with self.subTest(cl=cl):
                conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
                conn.putrequest("POST", "/api/inbox")
                conn.putheader("Host", f"127.0.0.1:{self.port}")
                conn.putheader("X-Brain-Token", self.token)
                conn.putheader("Content-Type", "multipart/form-data; boundary=x")
                conn.putheader("Content-Length", cl)
                conn.endheaders()
                resp = conn.getresponse()
                self.assertEqual(resp.status, expected)
                conn.close()

    # ── 5. move dentro de HOME fora do vault vs fallback seguro ──────────
    def test_move_deletes_only_regular_file_inside_home_outside_vault(self):
        fake_home = self.base / "home_dono"
        downloads = fake_home / "Downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        outside_home = self.base / "fora_home"
        outside_home.mkdir(parents=True, exist_ok=True)

        with mock.patch("brainlib.serve.Path.home", return_value=fake_home):
            # Caso válido: dentro de HOME e fora de inst.root / inst.vault
            ok_src = downloads / "reuniao.txt"
            ok_src.write_text("pauta", encoding="utf-8")
            ct, body = _multipart_body(
                filename="reuniao.txt",
                file_bytes=b"pauta",
                mode="move",
                source_path=str(ok_src),
            )
            code, data = self._post_raw(body, ct, token=self.token)
            self.assertEqual(code, 200)
            self.assertTrue(data["moved"])
            self.assertFalse(data["fallback_copy"])
            self.assertFalse(ok_src.exists())
            self.assertEqual((self.inst.inbox / "reuniao.txt").read_bytes(), b"pauta")

            # Caso 2: sem source_path (como navegador padrão) -> fallback_copy
            ct, body = _multipart_body(filename="navegador.txt", file_bytes=b"nav", mode="move")
            code, data = self._post_raw(body, ct, token=self.token)
            self.assertEqual(code, 200)
            self.assertFalse(data["moved"])
            self.assertTrue(data["fallback_copy"])
            self.assertTrue((self.inst.inbox / "navegador.txt").exists())

            # Caso 3: arquivo dentro de inst.vault -> NÃO apaga original
            in_vault = self.inst.vault / "PROFILE" / "guardado.md"
            in_vault.parent.mkdir(parents=True, exist_ok=True)
            in_vault.write_text("importante", encoding="utf-8")
            ct, body = _multipart_body(
                filename="guardado.md",
                file_bytes=b"importante",
                mode="move",
                source_path=str(in_vault),
            )
            code, data = self._post_raw(body, ct, token=self.token)
            self.assertEqual(code, 200)
            self.assertFalse(data["moved"])
            self.assertTrue(data["fallback_copy"])
            self.assertTrue(in_vault.exists())

            # Caso 4: arquivo dentro de inst.root (config) -> NÃO apaga original
            in_root = self.inst.root / "config" / "brain.toml"
            ct, body = _multipart_body(
                filename="copia.toml",
                file_bytes=in_root.read_bytes(),
                mode="move",
                source_path=str(in_root),
            )
            code, data = self._post_raw(body, ct, token=self.token)
            self.assertEqual(code, 200)
            self.assertFalse(data["moved"])
            self.assertTrue(data["fallback_copy"])
            self.assertTrue(in_root.exists())

            # Caso 5: arquivo fora de HOME -> NÃO apaga original
            ext_file = outside_home / "externo.txt"
            ext_file.write_text("externo", encoding="utf-8")
            ct, body = _multipart_body(
                filename="externo.txt",
                file_bytes=b"externo",
                mode="move",
                source_path=str(ext_file),
            )
            code, data = self._post_raw(body, ct, token=self.token)
            self.assertEqual(code, 200)
            self.assertFalse(data["moved"])
            self.assertTrue(data["fallback_copy"])
            self.assertTrue(ext_file.exists())

            # Caso 6: symlink dentro de HOME -> NÃO apaga symlink nem alvo
            real_target = downloads / "alvo.txt"
            real_target.write_text("alvo", encoding="utf-8")
            sym = downloads / "atalho.txt"
            sym.symlink_to(real_target)
            ct, body = _multipart_body(
                filename="atalho.txt",
                file_bytes=b"alvo",
                mode="move",
                source_path=str(sym),
            )
            code, data = self._post_raw(body, ct, token=self.token)
            self.assertEqual(code, 200)
            self.assertFalse(data["moved"])
            self.assertTrue(data["fallback_copy"])
            self.assertTrue(sym.is_symlink())
            self.assertTrue(real_target.exists())

            # Caso 7: source_path ausente -> copia e retorna fallback_copy
            ct, body = _multipart_body(
                filename="fantasma.txt",
                file_bytes=b"abc",
                mode="move",
                source_path=str(downloads / "nao-existe.txt"),
            )
            code, data = self._post_raw(body, ct, token=self.token)
            self.assertEqual(code, 200)
            self.assertFalse(data["moved"])
            self.assertTrue(data["fallback_copy"])
            self.assertTrue((self.inst.inbox / "fantasma.txt").exists())

    # ── 6. BRAIN_NIGHTLY=1 retorna 403 ───────────────────────────────────
    def test_nightly_env_rejects_with_403(self):
        ct, body = _multipart_body(filename="noturno.txt", file_bytes=b"noite", mode="copy")
        with mock.patch.dict(os.environ, {"BRAIN_NIGHTLY": "1"}):
            code, data = self._post_raw(body, ct, token=self.token)
        self.assertEqual(code, 403)
        self.assertFalse(data["ok"])
        self.assertFalse((self.inst.inbox / "noturno.txt").exists())


class ServeInboxMoveSearchTests(unittest.TestCase):
    """Mover por busca: a ponte acha o original no disco (índice ou varredura) e apaga
    só sob conteúdo idêntico; duplicata vira escolha do dono (`/api/inbox/remove`)."""
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.base = Path(cls.td.name)
        cls.inst = _inst(cls.base / "inst")
        cls.token = "tok-move-find"
        serve._Handler.state = serve._State(cls.inst, cls.token)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve._Handler)
        cls.httpd.daemon_threads = True
        cls.port = cls.httpd.server_address[1]
        serve._Handler.state.port = cls.port
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.td.cleanup()

    def setUp(self):
        for p in list(self.inst.inbox.glob("*")):
            if p.is_file() or p.is_symlink():
                p.unlink()
        self.home = self.base / "home_dono"
        for d in ("Downloads", "Desktop"):
            (self.home / d).mkdir(parents=True, exist_ok=True)
        self.cfg_path = self.inst.root / "config" / "brain.toml"
        self.cfg_orig = self.cfg_path.read_text(encoding="utf-8")

    def tearDown(self):
        self.cfg_path.write_text(self.cfg_orig, encoding="utf-8")

    def _set_cfg(self, section: str):
        self.cfg_path.write_text(self.cfg_orig + section, encoding="utf-8")

    def _post(self, filename: str, file_bytes: bytes, *, mode: str = "move") -> tuple[int, dict]:
        ct, body = _multipart_body(filename=filename, file_bytes=file_bytes, mode=mode)
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/inbox", data=body, method="POST")
        req.add_header("Content-Type", ct)
        req.add_header("X-Brain-Token", self.token)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _remove(self, payload: dict, *, token: str | None = None, nightly: bool = False) -> tuple[int, dict]:
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/inbox/remove",
                                     data=json.dumps(payload).encode("utf-8"), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Brain-Token", token if token is not None else self.token)
        env = {"BRAIN_NIGHTLY": "1"} if nightly else {}
        try:
            with mock.patch.dict(os.environ, env):
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_unique_match_is_deleted_after_copy(self):
        src = self.home / "Downloads" / "contrato.pdf"
        src.write_bytes(b"pdf de verdade")
        with mock.patch("brainlib.serve.Path.home", return_value=self.home), \
             mock.patch("brainlib.serve._mdfind_candidates", return_value=[]):
            code, data = self._post("contrato.pdf", b"pdf de verdade")
        self.assertEqual(code, 200)
        self.assertTrue(data["moved"], data)
        self.assertTrue(data["moved_from"].endswith("contrato.pdf"))
        self.assertFalse(data["fallback_copy"])
        self.assertFalse(src.exists())                                   # original sumiu…
        self.assertTrue((self.inst.inbox / "contrato.pdf").exists())     # …a cópia ficou

    def test_match_via_system_index(self):
        src = self.home / "Downloads" / "pela-index.txt"
        src.write_bytes(b"index")
        with mock.patch("brainlib.serve.Path.home", return_value=self.home), \
             mock.patch("brainlib.serve._mdfind_candidates", return_value=[str(src)]):
            code, data = self._post("pela-index.txt", b"index")
        self.assertEqual(code, 200)
        self.assertTrue(data["moved"])
        self.assertFalse(src.exists())

    def test_duplicates_are_not_deleted_but_reported(self):
        a = self.home / "Downloads" / "orcamento.xlsx"
        b = self.home / "Desktop" / "orcamento.xlsx"
        a.write_bytes(b"planilha")
        b.write_bytes(b"planilha")
        with mock.patch("brainlib.serve.Path.home", return_value=self.home), \
             mock.patch("brainlib.serve._mdfind_candidates", return_value=[]):
            code, data = self._post("orcamento.xlsx", b"planilha")
        self.assertEqual(code, 200)
        self.assertFalse(data["moved"])
        self.assertTrue(data["fallback_copy"])
        self.assertEqual(len(data["candidates"]), 2)
        self.assertEqual({c["path"] for c in data["candidates"]}, {str(a.resolve()), str(b.resolve())})
        self.assertTrue(a.exists() and b.exists())                       # nada apagado sozinho

    def test_same_name_different_content_is_not_the_original(self):
        src = self.home / "Downloads" / "leitura.md"
        src.write_bytes(b"outro conteudo")
        with mock.patch("brainlib.serve.Path.home", return_value=self.home), \
             mock.patch("brainlib.serve._mdfind_candidates", return_value=[str(src)]):
            code, data = self._post("leitura.md", b"conteudo caiu")
        self.assertEqual(code, 200)
        self.assertFalse(data["moved"])
        self.assertEqual(data["candidates"], [])
        self.assertTrue(src.exists())

    def test_symlink_candidate_is_ignored(self):
        alvo = self.home / "Downloads" / "alvo.txt"
        alvo.write_bytes(b"alvo")
        sym = self.home / "Desktop" / "atalho.txt"
        sym.symlink_to(alvo)
        with mock.patch("brainlib.serve.Path.home", return_value=self.home), \
             mock.patch("brainlib.serve._mdfind_candidates", return_value=[str(sym), str(alvo)]):
            code, data = self._post("alvo.txt", b"alvo")
        self.assertEqual(code, 200)
        self.assertTrue(data["moved"])                                   # só o regular conta
        self.assertTrue(alvo.exists() is False)
        self.assertTrue(sym.is_symlink())                                # symlink intacto

    def test_search_disabled_reports_no_search(self):
        self._set_cfg("\n[serve]\nmove_search = false\n")
        src = self.home / "Downloads" / "desligado.txt"
        src.write_bytes(b"x")
        with mock.patch("brainlib.serve.Path.home", return_value=self.home), \
             mock.patch("brainlib.serve._mdfind_candidates", return_value=[str(src)]) as mdf:
            code, data = self._post("desligado.txt", b"x")
        self.assertEqual(code, 200)
        self.assertFalse(data["moved"])
        self.assertFalse(data["search"])
        self.assertTrue(src.exists())
        mdf.assert_not_called()

    def test_custom_roots_are_walked(self):
        proj = self.home / "Projetos" / "cliente"
        proj.mkdir(parents=True)
        src = proj / "briefing.txt"
        src.write_bytes(b"brief")
        self._set_cfg('\n[serve]\nmove_search = ["Projetos"]\n')
        with mock.patch("brainlib.serve.Path.home", return_value=self.home), \
             mock.patch("brainlib.serve._mdfind_candidates", return_value=[]):
            code, data = self._post("briefing.txt", b"brief")
        self.assertEqual(code, 200)
        self.assertTrue(data["moved"], data)
        self.assertFalse(src.exists())

    def test_remove_endpoint_deletes_chosen_and_refuses_the_rest(self):
        a = self.home / "Downloads" / "dup.txt"
        b = self.home / "Desktop" / "dup.txt"
        c = self.home / "Desktop" / "fora.txt"
        a.write_bytes(b"dup")
        b.write_bytes(b"dup")
        c.write_bytes(b"outra coisa")
        with mock.patch("brainlib.serve.Path.home", return_value=self.home), \
             mock.patch("brainlib.serve._mdfind_candidates", return_value=[]):
            code, data = self._post("dup.txt", b"dup")
        inbox_name = data["name"]                                       # cópia com sufixo se preciso
        self.assertEqual(code, 200)

        # escolha do dono: apagar a e b; caminho fora do home e conteúdo adulterado recusam
        tampered = self.home / "Downloads" / "adulterado.txt"
        tampered.write_bytes(b"dup")
        with mock.patch("brainlib.serve.Path.home", return_value=self.home):
            code, r = self._remove({"inbox_name": inbox_name,
                                    "paths": [str(a), str(b), str(c), "/etc/hosts"]})
        self.assertEqual(code, 200)
        self.assertEqual(set(r["removed"]), {str(a.resolve()), str(b.resolve())})
        self.assertEqual(len(r["refused"]), 2)                           # c: conteúdo; /etc/hosts: fora
        self.assertFalse(a.exists() or b.exists())
        self.assertTrue(c.exists())

        # conteúdo mudou depois da escolha → recusa na hora
        d = self.home / "Desktop" / "mudou.txt"
        d.write_bytes(b"v1")
        with mock.patch("brainlib.serve.Path.home", return_value=self.home), \
             mock.patch("brainlib.serve._mdfind_candidates", return_value=[]):
            _, data2 = self._post("mudou.txt", b"v1")
        d.write_bytes(b"v2")                                             # o disco andou
        with mock.patch("brainlib.serve.Path.home", return_value=self.home):
            code, r = self._remove({"inbox_name": data2["name"], "paths": [str(d)]})
        self.assertEqual(code, 200)
        self.assertEqual(r["removed"], [])
        self.assertTrue(d.exists())

    def test_remove_endpoint_guards(self):
        # sem token
        code, _ = self._remove({"inbox_name": "x.txt", "paths": ["/tmp/x.txt"]}, token="errado")
        self.assertEqual(code, 401)
        # noturno
        code, r = self._remove({"inbox_name": "x.txt", "paths": ["/tmp/x.txt"]}, nightly=True)
        self.assertEqual(code, 403)
        self.assertIn("noturno", r["error"])
        # inbox_name inválido (caminho) e cópia inexistente
        code, _ = self._remove({"inbox_name": "../secreto.txt", "paths": ["/tmp/x.txt"]})
        self.assertEqual(code, 400)
        code, _ = self._remove({"inbox_name": "nao-existe.txt", "paths": ["/tmp/x.txt"]})
        self.assertEqual(code, 404)
        # paths vazio/estouro
        code, _ = self._remove({"inbox_name": "x.txt", "paths": []})
        self.assertEqual(code, 400)
        code, _ = self._remove({"inbox_name": "x.txt", "paths": [str(i) for i in range(21)]})
        self.assertEqual(code, 400)


class PanelDragDropAssetsTests(unittest.TestCase):
    def test_assets_rebuilt_with_inbox_drag_and_drop_overlay(self):
        extra = (ROOT / "brainlib/assets/src/extra.js").read_text(encoding="utf-8")
        css = (ROOT / "brainlib/assets/src/dashboard.css").read_text(encoding="utf-8")
        self.assertIn("/api/inbox", extra)
        self.assertIn('data-drop-mode="move"', extra)
        self.assertIn('data-drop-mode="copy"', extra)
        self.assertIn("Mover arquivo para a inbox", extra)
        self.assertIn("Copiar arquivo para a inbox", extra)
        self.assertIn("webkitGetAsEntry", extra)
        self.assertIn(".DS_Store", extra)
        self.assertIn(".keep.md", extra)
        self.assertIn("Ponte CLI inativa — rode ./brain serve para arrastar arquivos para o painel, ou salve direto em vault/RAW/inbox/.", extra)
        # mover de verdade: busca no disco (byte a byte) + escolha de duplicatas + pastas concedidas
        self.assertIn("showDirectoryPicker", extra)
        self.assertIn("queryPermission", extra)
        self.assertIn("requestPermission", extra)
        self.assertIn("removeEntry", extra)
        self.assertIn("g.size !== file.size || g.lastModified !== file.lastModified", extra)  # nunca apaga por nome puro
        self.assertIn("/api/inbox/remove", extra)
        self.assertIn("Achei cópias idênticas", extra)
        self.assertIn("Manter todas", extra)
        self.assertIn("+ Adicionar pasta", extra)                # pastas concedidas: várias, gerenciáveis
        self.assertIn("inbox-origins", extra)                    # lista persistida (migra da chave única)
        self.assertIn("inboxOriginAsked", extra)                 # a oferta é 1× por sessão
        self.assertIn("inbox-origin-hint", extra)                # a zona Mover anuncia o estado antes do drop
        self.assertIn("cópias idênticas no disco", extra)
        self.assertIn(".inbox-drop-ov", css)
        self.assertIn(".pal-foot", css)
        self.assertIn(".duprow", css)

        for name in ("dashboard.html", "portfolio.html"):
            html = (ROOT / "brainlib/assets" / name).read_text(encoding="utf-8")
            self.assertIn("/api/inbox", html, name)
            self.assertIn('data-drop-mode="move"', html, name)
            self.assertIn(".inbox-drop-ov", html, name)


if __name__ == "__main__":
    unittest.main()
