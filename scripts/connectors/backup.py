#!/usr/bin/env python3
"""Backup do vault — zip → upload para pasta do Google Drive (OAuth).

Uso:
  python3 scripts/connectors/backup.py            # backup agora (noturno: semanal)
  python3 scripts/connectors/backup.py --status   # último backup + saúde

Requer no config/.env (além de GOOGLE_CLIENT_ID/SECRET — o MESMO OAuth do
google_auth.py, com o escopo adicional drive.file — ver guides/backup.md):
  GOOGLE_BACKUP_FOLDER_ID=<id da pasta do Drive>   (URL da pasta: .../folders/<id>)

O que faz:
  1. zipa vault/ inteiro → /tmp/brain-backup-<AAAAMMDD-HHMM>.zip (segredos e
     estado operacional moram em config/.env e config/.state.json — FORA do
     vault, fora do zip por construção; nunca precisaram ser "excluídos")
  2. multipart upload para a pasta configurada (nome: brain-backup-<ts>.zip)
  3. retenção: mantém os 8 mais recentes NA PASTA DO DRIVE, apaga os antigos
     (apaga SOMENTE arquivos cujo nome casa brain-backup-*.zip criados por nós)

Exceção constitucional documentada: este é o ÚNICO fluxo com escopo de escrita
(drive.file — só cria/apaga os próprios backups na pasta configurada; NÃO lê
nem toca em mais nada do Drive). O LLM nunca roda este fluxo por conta própria:
o /backup (noturno semanal ou comando do dono) é o único gatilho.
"""
from __future__ import annotations

import os
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3"
NAME_PREFIX = "brain-backup-"
KEEP = 8


def folder_id() -> str:
    fid = os.environ.get("GOOGLE_BACKUP_FOLDER_ID", "").strip()
    if not fid:
        common.die("GOOGLE_BACKUP_FOLDER_ID ausente no config/.env — crie/pegue a URL "
                   "da pasta no Drive (…/folders/<id>) — ver guides/backup.md")
    return fid


def api(path: str, token: str, data: bytes | None = None, method: str = "GET",
        ctype: str = "application/json"):
    req = urllib.request.Request(f"{API}{path}", data=data, method=method,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read().decode()
        return common.json.loads(body) if body else {}


def make_zip() -> Path:
    vault = common.INSTANCE_ROOT / "vault"
    if not vault.is_dir():
        common.die("vault/ não encontrado — backup roda numa instância instalada")
    stamp = time.strftime("%Y%m%d-%H%M")
    zpath = Path(f"/tmp/{NAME_PREFIX}{stamp}.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(vault.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(vault.parent))
    return zpath


def upload(zpath: Path, token: str, fid: str) -> str:
    meta = common.json.dumps({"name": zpath.name,
                              "parents": [fid]}).encode()
    boundary = "sbkb" + str(int(time.time()))
    body = (b"--" + boundary.encode() + b"\r\n"
            b"Content-Type: application/json; charset=UTF-8\r\n\r\n" + meta + b"\r\n"
            b"--" + boundary.encode() + b"\r\n"
            b"Content-Type: application/zip\r\n\r\n" +
            zpath.read_bytes() +
            b"\r\n--" + boundary.encode() + b"--\r\n")
    req = urllib.request.Request(
        f"{UPLOAD}/files?uploadType=multipart",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": f"multipart/related; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return common.json.loads(r.read().decode())["id"]


def prune(fid: str, token: str) -> int:
    q = urllib.parse.quote(f"'{fid}' in parents and trashed = false and name contains '{NAME_PREFIX}'")
    req = urllib.request.Request(f"{API}/files?q={q}&pageSize=50&orderBy=createdTime desc"
                                 f"&fields=files(id,name,createdTime)",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        files = common.json.loads(r.read().decode()).get("files", [])
    removed = 0
    for f in files[KEEP:]:
        api(f"/files/{f['id']}", token, method="DELETE")
        removed += 1
    return removed


def status(fid: str, token: str) -> None:
    q = urllib.parse.quote(f"'{fid}' in parents and trashed = false and name contains '{NAME_PREFIX}'")
    req = urllib.request.Request(f"{API}/files?q={q}&pageSize=10&orderBy=createdTime desc"
                                 f"&fields=files(name,createdTime)",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        files = common.json.loads(r.read().decode()).get("files", [])
    if not files:
        print("backup: NENHUM backup na pasta — rode /backup")
        return
    latest = files[0]
    print(f"backup: último = {latest['name']} ({latest['createdTime'][:10]}); "
          f"total na pasta: {len(files)}")


def main() -> None:
    common.load_env()
    fid = folder_id()          # gate de config ANTES do token (morte educada)
    token = common.google_access_token()
    if "--status" in sys.argv:
        status(fid, token)
        return
    zpath = make_zip()
    size_kb = zpath.stat().st_size // 1024
    file_id = upload(zpath, token, fid)
    removed = prune(fid, token)
    zpath.unlink(missing_ok=True)
    print(f"✓ backup: {zpath.name} ({size_kb} KB) → pasta Drive {fid}")
    if removed:
        print(f"  retenção: {removed} backup(s) antigo(s) removido(s) (mantém {KEEP})")


if __name__ == "__main__":
    main()
