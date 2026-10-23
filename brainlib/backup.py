"""Porta do backup — zip do vault → pasta do Google Drive (escopo drive.file) ou pasta local.

Escrita estreita: só cria/apaga os próprios `brain-backup-*.zip` na pasta configurada.
Arquivos maiores que [backup].max_file_mb (vídeos, zips baixados) ficam FORA do zip e
entram num MANIFESTO (caminho, tamanho, sha256) dentro do próprio zip — você sabe
exatamente o que não está no backup. Segredos (config/.env) moram fora do vault.
Upload resumível em pedaços: o zip nunca é carregado inteiro na memória.
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from . import config, util
from .gcal import access_token

API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable"
PREFIX = "brain-backup-"
CHUNK = 8 * 2**20


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(2**20), b""):
            h.update(block)
    return h.hexdigest()


def make_zip(brain, dest_dir: Path) -> tuple[Path, list[dict]]:
    inst = brain.inst
    limit = inst.cfg["backup"]["max_file_mb"] * 2**20
    stamp = util.now().strftime("%Y%m%d-%H%M")
    zpath = dest_dir / f"{PREFIX}{stamp}.zip"
    skipped: list[dict] = []
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        vault_real = inst.vault.resolve()
        for f in sorted(inst.vault.rglob("*")):
            if not f.is_file() or f.name.endswith(".lock"):
                continue
            if f.is_symlink() and vault_real not in f.resolve().parents:
                continue        # link para fora do vault (~/.ssh, config/.env…) nunca vai para o Drive
            rel = f.relative_to(inst.vault.parent)
            if f.stat().st_size > limit:
                skipped.append({"path": str(rel), "bytes": f.stat().st_size, "sha256": _sha256(f)})
                continue
            z.write(f, rel)
        z.writestr("vault/BACKUP-MANIFEST.json", json.dumps(
            {"created": util.iso_now(), "max_file_mb": inst.cfg["backup"]["max_file_mb"], "skipped": skipped},
            ensure_ascii=False, indent=2))
    return zpath, skipped


def _drive(token: str, method: str, url: str, body: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Authorization": f"Bearer {token}", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        if e.code == 308:
            return 308, e.headers, b""
        raise util.BrainError(f"Drive {method} → {e.code}: {e.read().decode(errors='replace')[:300]}", code=2) from e


def upload(zpath: Path, token: str, folder: str) -> str:
    size = zpath.stat().st_size
    meta = json.dumps({"name": zpath.name, "parents": [folder]}).encode()
    _, headers, _ = _drive(token, "POST", UPLOAD, meta, {"Content-Type": "application/json; charset=UTF-8",
                                                        "X-Upload-Content-Type": "application/zip",
                                                        "X-Upload-Content-Length": str(size)})
    session = headers["Location"]
    sent = 0
    with open(zpath, "rb") as fh:
        while sent < size:
            chunk = fh.read(CHUNK)
            end = sent + len(chunk) - 1
            status, _, body = _drive(token, "PUT", session, chunk, {"Content-Length": str(len(chunk)),
                                                                    "Content-Range": f"bytes {sent}-{end}/{size}"})
            sent = end + 1
    return json.loads(body.decode() or "{}").get("id", "")


FOLDER_RE = re.compile(r"^[A-Za-z0-9_-]{5,}$")
NAME_RE = re.compile(rf"^{re.escape(PREFIX)}\d{{8}}-\d{{4}}(?:-\d+)?\.zip$")   # só o que make_zip gera


def _ours(name: str) -> bool:
    """Arquivo que esta porta criou: `brain-backup-AAAAMMDD-HHMM.zip`. `name contains` do Drive pega também
    `meu-brain-backup-notas.docx` — nada fora deste padrão é listado como backup, nem apagado."""
    return bool(NAME_RE.match(name or ""))


def _folder(env_value: str) -> str:
    folder = (env_value or "").strip()
    if folder and not FOLDER_RE.match(folder):
        # o ID entra na query do Drive entre aspas: aspas/espaços mudariam a busca (e o que a rotação apaga)
        raise util.BrainError("GOOGLE_BACKUP_FOLDER_ID inválido (esperado só o ID da pasta: letras, números, - e _)",
                              code=3)
    return folder


def _list(token: str, folder: str) -> list[dict]:
    q = urllib.parse.quote(f"'{_folder(folder)}' in parents and trashed = false and name contains '{PREFIX}'")
    _, _, body = _drive(token, "GET", f"{API}/files?q={q}&pageSize=100&orderBy="
                                      f"{urllib.parse.quote('createdTime desc')}&fields=files(id,name,createdTime,size)")
    return [f for f in json.loads(body.decode()).get("files", []) if _ours(f.get("name", ""))]


def run(brain, local: str | None = None) -> str:
    keep = max(int(brain.inst.cfg["backup"]["keep"]), 1)     # keep = 0 apagaria o backup que acabou de ser feito
    if local:
        dest = Path(local).expanduser()
        dest.mkdir(parents=True, exist_ok=True)
        zpath, skipped = make_zip(brain, dest)
        old = sorted((p for p in dest.glob(f"{PREFIX}*.zip") if _ours(p.name) and p.is_file() and not p.is_symlink()),
                     reverse=True)[keep:]
        for p in old:
            p.unlink()
        return (f"{zpath} ({zpath.stat().st_size // 2**20} MB) · {len(skipped)} arquivos grandes no manifesto"
                + (f" · {len(old)} antigos removidos" if old else ""))
    folder = _folder(config.load_env(brain.inst).get("GOOGLE_BACKUP_FOLDER_ID", ""))
    if not folder:
        raise util.BrainError("GOOGLE_BACKUP_FOLDER_ID ausente no config/.env (guides/backup.md) — "
                              "ou use `brain backup --local <pasta>`", code=3)
    token = access_token(brain.inst)
    with tempfile.TemporaryDirectory() as tmp:
        zpath, skipped = make_zip(brain, Path(tmp))
        mb = zpath.stat().st_size // 2**20
        new_id = upload(zpath, token, folder)
    if not new_id:
        # sem confirmação do Drive de que o novo backup existe, nenhum antigo é apagado
        raise util.BrainError("Drive não confirmou o upload (sem id) — nenhum backup antigo foi removido", code=2)
    files = _list(token, folder)
    for f in files[keep:]:
        if _ours(f.get("name", "")) and f.get("id") != new_id:
            _drive(token, "DELETE", f"{API}/files/{urllib.parse.quote(f['id'], safe='')}")
    return f"{zpath.name} ({mb} MB) → Drive · {len(skipped)} arquivos grandes no manifesto"


def cli(args, brain) -> None:
    if args.status:
        if args.local:
            files = sorted((p for p in Path(args.local).expanduser().glob(f"{PREFIX}*.zip") if _ours(p.name)),
                           reverse=True)
            print(f"último: {files[0].name} · total {len(files)}" if files else "nenhum backup local")
            return
        folder = _folder(config.load_env(brain.inst).get("GOOGLE_BACKUP_FOLDER_ID", ""))
        if not folder:
            raise util.BrainError("GOOGLE_BACKUP_FOLDER_ID ausente no config/.env", code=3)
        files = _list(access_token(brain.inst), folder)
        print(f"último: {files[0]['name']} ({files[0]['createdTime'][:10]}) · total {len(files)}" if files
              else "NENHUM backup na pasta — rode `brain backup`")
        return
    print("✓ backup: " + run(brain, args.local))
