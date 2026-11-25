#!/usr/bin/env python3
"""Portão de dados do repositório público — o que entra no repo passa pela varredura do brain.

O repositório é público e é a origem: cada pull request acrescenta commits a ele. O hook pre-push
já varre na máquina de quem sobe (`brain upstream scan`); o CI repete a varredura de forma
independente, antes de rodar a suíte — a mesma varredura do brain (caminho da máquina, segredo,
workspace do Slack, dado pessoal da instância) mais uma lista privada de termos (nome de empresa,
de rede interna, o que o mantenedor nunca quiser ver lá), que mora num segredo do repositório
(Actions) e nunca vai ao código.

    public_gate.py gate --base <ref|sha> [--root <repo>] --denylist <arquivo> [--detalhes]
    public_gate.py status --sha <sha> --rc <código do gate> [--run <url>]

`gate` varre `<base>..HEAD` do repositório `--root` (padrão: a pasta de onde se chama — nunca a do
script, que chamado de outro checkout varria o lugar errado e dá "limpo"), commit a commit. A lista
privada é um termo por linha (ou separado por vírgula); linha que começa com `#` é comentário. No CI
o `--root` é um worktree do PR: os scripts e a configuração da varredura vêm do checkout da main —
o PR nunca diz quais são os termos.

O log do CI é público e qualquer pessoa abre PR de fork: o portão não pode virar oráculo da lista
privada. No CI, achado da lista privada sai sem arquivo, sem linha e sem contagem — um bit por
execução ("ao menos um termo aparece no alcance"). Com `--detalhes` (fora do CI, na máquina de
quem mantém) sai onde. O valor achado nunca é ecoado, em nenhum modo.

Arquivo que a varredura não abre por dentro — compactado, documento, banco de dados, e-mail,
imagem de disco, binário (zip, gzip, 7z, RAR, PDF, Office, SQLite, Parquet, PST, ISO, JAR…) — que o
alcance cria é achado por si, mesmo sem termo nenhum. Imagem e vídeo não são bloqueados: o
repositório os usa, e são revisão de quem mantém.

`status` publica o resultado do portão como status de commit de contexto `data-gate (status)` na
ponta do PR, que é o que o branch protection exige. O check run do job não serve para isso: um fork
consegue emitir um check com o mesmo nome na ponta do próprio PR (a chave é só o texto); status de
commit exige token de escrita, que PR de fork não tem.

Códigos de saída do `gate`: 0 limpo · 4 achado · 1 erro — inclusive lista privada ausente, vazia,
toda em comentário ou com termo curto demais: sem os termos pedidos o portão não atesta nada.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from brainlib import config, upstream, util  # noqa: E402

KIND = "lista privada"                 # nome da regra nos achados
PRIVATE_RULE = upstream.term_rule(KIND)   # como a regra aparece nos achados (`f["rule"]`)
MIN_TERM = upstream.MIN_TERM           # mesmo piso do `brain upstream scan`: evita termo curto que casa tudo
CLEAN, FOUND, ERROR = 0, 4, 1
LISTED = 25                            # achados de regra pública listados por execução (os demais só são contados)


def parse_denylist(text: str) -> list[str]:
    """Uma linha ou vírgula por termo; sem repetição, na ordem de chegada.

    Linha que começa com `#` é comentário, inteiro (comentário no meio de um termo não existe: vira
    parte dele). Termo curto demais não entra — e não é pulado em silêncio: é erro, porque a lista
    deixaria de cobrir o que o mantenedor pediu sem que ninguém visse.
    """
    out: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for raw in line.split(","):
            term = raw.strip()
            if not term:
                continue
            if len(term) < MIN_TERM:
                raise RuntimeError(f"lista privada com termo curto demais (menos de {MIN_TERM} caracteres)")
            if term.casefold() not in {t.casefold() for t in out}:
                out.append(term)
    return out


def load_denylist(path: Path) -> list[str]:
    """Lê a lista privada do arquivo. Ilegível ou sem nenhum termo válido é erro: o portão não passa."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as e:
        raise RuntimeError(f"lista privada ilegível: {type(e).__name__}") from e
    terms = parse_denylist(text)
    if not terms:
        raise RuntimeError("lista privada vazia: sem termos o portão não atesta nada")
    return terms


def install_denylist(terms: list[str]):
    """Acrescenta os termos privados aos termos pessoais da instância, na varredura do brain.

    A varredura lê os termos por `_leak_terms`; sem instância configurada (o CI) sobram só as regras
    genéricas — a lista privada é o que cobre o dado de empresa nesse ponto. Casa como substring,
    sem fronteira de palavra: nome de empresa colado noutro (`<termo>_prod`, `<termo>VPN`) é dado
    igual. Devolve o original.
    """
    original = upstream._leak_terms
    upstream.PLAIN_KINDS.add(KIND)

    def with_denylist(inst: config.Instance) -> list[tuple[str, str]]:
        return original(inst) + [(t, KIND) for t in terms]

    upstream._leak_terms = with_denylist
    return original


def scan_range(root: Path, base: str | None, trusted: Path | None = None) -> list[dict]:
    """Varre os commits de `<base>..HEAD` (ou todo o histórico, sem `base`) como o hook pre-push faria.

    A configuração — os termos da instância — vem de `trusted`, o checkout de onde este script saiu
    (padrão). `root` só diz qual repositório varrer: o PR fornece os commits, não as regras.
    """
    src = config.load(trusted or ROOT)
    inst = config.Instance(root=Path(root), vault=src.vault, config_dir=src.config_dir, cfg=src.cfg)
    revsets = [[f"{base}..HEAD"] if base else ["HEAD"]]
    return upstream.scan(inst, None, committed=True, revsets=revsets)


OPAQUE_RULE = "anexo fechado (a varredura não lê o que há dentro)"
# Anexo cujo conteúdo a varredura não abre: compactado, documento, banco, e-mail, imagem de disco,
# binário. O dado pode estar lá dentro, comprimido ou num formato fechado, e a busca de texto passa
# direto: por isso o arquivo em si é o achado, pelo nome ou pela assinatura dos primeiros bytes.
# Imagem e vídeo ficam de fora — o repositório os usa (ícones e auditoria de interface) — e, desenhado,
# o dado não é legível para o portão de jeito nenhum: é revisão de quem mantém.
OPAQUE_SUFFIXES = (
    ".zip", ".gz", ".tgz", ".taz", ".tar", ".bz2", ".tbz2", ".xz", ".txz", ".zst", ".tzst", ".lz4", ".lz", ".lzma",
    ".lzo", ".br", ".zlib", ".z", ".tbz", ".7z", ".rar", ".cab", ".cpio", ".wim",                   # compactado
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".xlsb", ".ppt", ".pptx", ".odt", ".ods", ".odp",
    ".odg", ".rtf", ".epub", ".mobi", ".djvu", ".chm", ".one",                                 # documento
    ".db", ".sqlite", ".sqlite3", ".db3", ".s3db", ".mdb", ".accdb", ".accde", ".db-wal", ".sqlite-wal",
    ".db-shm", ".sqlite-shm", ".parquet", ".feather", ".arrow", ".avro", ".orc", ".h5", ".hdf5", ".hdf",
    ".nc", ".npz", ".npy", ".pkl", ".pickle", ".joblib", ".pt", ".pth", ".ckpt", ".safetensors",  # dados
    ".eml", ".emlx", ".msg", ".pst", ".ost",                                                   # e-mail
    ".iso", ".dmg", ".img", ".vhd", ".vhdx", ".vmdk", ".vdi", ".qcow", ".qcow2",               # imagem de disco
    ".jar", ".war", ".ear", ".whl", ".egg", ".apk", ".ipa", ".deb", ".rpm", ".msi", ".exe", ".dll",
    ".so", ".dylib", ".class", ".pyc", ".pyz", ".node", ".wasm", ".a", ".o", ".lib", ".bin",   # binário
)
OPAQUE_MAGIC = (
    b"\x1f\x8b", b"\x1f\x9d", b"PK\x03\x04", b"PK\x05\x06", b"7z\xbc\xaf\x27\x1c", b"Rar!\x1a\x07",
    b"\xfd7zXZ\x00", b"\x28\xb5\x2f\xfd", b"\x04\x22\x4d\x18", b"BZh", b"MSCF", b"070701", b"!<arch>\n",
    b"%PDF-", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"{\\rtf",
    b"SQLite format 3\x00", b"PAR1", b"ORC", b"Obj\x01", b"ARROW1", b"\x89HDF\r\n\x1a\n",
    b"\x7fELF", b"\x00asm", b"\xca\xfe\xba\xbe",
)


def _git_bytes(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
    r = subprocess.run(["git", "-C", str(root), "-c", "core.quotepath=false", *args],
                       input=stdin, capture_output=True)
    if r.returncode != 0:
        raise subprocess.CalledProcessError(r.returncode, r.args, r.stdout, r.stderr)
    return r.stdout


def _blob_heads(root: Path, shas: list[str], size: int = 32) -> dict[str, bytes]:
    """Primeiros bytes de cada blob, sem carregar o conteúdo inteiro."""
    heads: dict[str, bytes] = {}
    proc = subprocess.Popen(["git", "-C", str(root), "cat-file", "--batch"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    assert proc.stdin and proc.stdout
    try:
        for sha in shas:
            proc.stdin.write(f"{sha}\n".encode("ascii"))
            proc.stdin.flush()
            parts = proc.stdout.readline().split()
            if len(parts) < 3 or parts[1] != b"blob":
                continue                                   # objeto que não é blob ou que não existe
            length = int(parts[2])
            head = proc.stdout.read(min(size, length))
            left = length - len(head) + 1                  # resto do conteúdo e a linha em branco que fecha
            while left > 0:
                chunk = proc.stdout.read(min(left, 1 << 20))
                if not chunk:
                    raise RuntimeError("git cat-file terminou antes da hora")
                left -= len(chunk)
            heads[parts[0].decode("ascii")] = head
    finally:
        proc.stdin.close()
        proc.stdout.close()
        proc.kill()
        proc.wait()
    return heads


def _zlib_header(head: bytes) -> bool:
    """Dois bytes de cabeçalho zlib (RFC 1950): método deflate e checksum fechando."""
    return (len(head) >= 2 and head[0] & 0x0F == 8 and head[0] >> 4 <= 7
            and ((head[0] << 8) | head[1]) % 31 == 0)


def _is_text(data: bytes) -> bool:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return all(ch.isprintable() or ch in "\t\n\r" for ch in text)


def _zlib_stream(head: bytes) -> bool:
    """Fluxo zlib de verdade: depois do cabeçalho vem o que não é texto. zlib não tem assinatura fixa — é o
    compactado comum que sobra sem uma —, e o dado comprimido com ele entrava como binário comum, que a
    busca lê em bytes e não entende. O teste de texto afasta o arquivo de texto que começa com os dois
    bytes certos por acaso (1 em cada 31 dos que começam com `x`, `h`, `(`…)."""
    return _zlib_header(head) and not _is_text(head[2:])


def opaque_attachments(root: Path, base: str | None) -> list[dict]:
    """Anexos do alcance que a varredura não abre: compactado, documento, banco, binário — pelo nome ou
    pela assinatura.

    Olha todo blob que `<base>..HEAD` cria — inclusive num commit que outro commit do mesmo PR apagou,
    porque o conteúdo continua no histórico que o PR leva. O achado é o arquivo, nunca um valor.
    """
    revs = [f"{base}..HEAD"] if base else ["HEAD"]
    paths: dict[str, str] = {}
    listing = _git_bytes(root, "rev-list", "--objects", *revs, "--")
    for line in listing.decode("utf-8", "replace").splitlines():
        sha, _, path = line.partition(" ")
        if path:
            paths.setdefault(sha, path)
    if not paths:
        return []
    names = "".join(f"{sha} {path}\n" for sha, path in paths.items()).encode("utf-8")
    listed = _git_bytes(root, "cat-file", "--batch-check=%(objectname) %(objecttype) %(rest)", stdin=names)
    blobs: dict[str, str] = {}
    for line in listed.decode("utf-8", "replace").splitlines():
        fields = line.split(" ", 2)
        if len(fields) == 3 and fields[1] == "blob":
            blobs[fields[0]] = fields[2]
    heads = _blob_heads(root, list(blobs), size=32)   # 32 bytes: a assinatura mais longa (SQLite) tem 16
    # zlib só se reconhece com mais bytes depois do cabeçalho: leitura maior só dos candidatos
    wide = _blob_heads(root, [sha for sha in blobs if _zlib_header(heads.get(sha, b""))], size=4096)
    return [{"file": path, "line": 1, "rule": OPAQUE_RULE, "hint": f"blob {sha[:12]}"}
            for sha, path in blobs.items()
            if path.lower().endswith(OPAQUE_SUFFIXES) or heads.get(sha, b"").startswith(OPAQUE_MAGIC)
            or _zlib_stream(wide.get(sha, b""))]


def _lists_private_term(terms: list[str], text: str) -> bool:
    return any(upstream._term_regex(t, KIND).search(text) for t in terms)


def _mask(text: str, terms: list[str]) -> str:
    """Tira da mensagem qualquer termo da lista privada que tenha entrado nela (nome de arquivo que o git
    repete no erro, por exemplo)."""
    for t in terms:
        text = upstream._term_regex(t, KIND).sub("•••", text)
    return text


def report(findings: list[dict], base: str, terms: list[str], details: bool) -> None:
    """Diz o que achou. Fora do CI (`details`), tudo. No CI, achado da lista privada sai sem arquivo, sem
    linha e sem contagem: o log é público, e quem abre PR de fork testaria candidato a termo contra ele.
    Caminho de arquivo é dado igual — nome de pasta da empresa, por exemplo."""
    print(f"✗ portão de dados: achado em {base}..HEAD")
    if details:
        for f in findings:
            print(upstream._show(upstream._format_finding(f)))
        return
    private = [f for f in findings if f["rule"] == PRIVATE_RULE]
    others = [f for f in findings if f["rule"] != PRIVATE_RULE]
    if private:
        print("  ✗ lista privada: ao menos um termo aparece no alcance — sem arquivo nem linha (o log do CI é")
        print("    público; quem mantém vê onde com --detalhes, na própria máquina)")
    shown = 0
    for f in others:
        text = upstream._format_finding(f)
        if _lists_private_term(terms, text):
            text = "  ✗ — (caminho omitido: traz termo da lista privada) — " + _mask(f["rule"], terms)
        print(upstream._show(text))
        shown += 1
        if shown == LISTED:
            break
    if len(others) > shown:
        print("  … outros achados omitidos")


STATUS_CONTEXT = "data-gate (status)"
STATUS_TEXT = {
    CLEAN: ("success", "limpo: nada do alcance bate nas regras"),
    FOUND: ("failure", "achado: o portão de dados bloqueou esta ponta (onde, só no checkout de quem mantém)"),
}


def post_status(sha: str, rc: int, run: str | None, api: str, repo: str, token: str) -> tuple[str, int]:
    """Status de commit na ponta do PR, a partir do código de saída do `gate`. Qualquer código que não
    seja 0 ou 4 (inclusive job que não chegou a rodar o gate) vira `error`: o portão não atesta nada."""
    state, text = STATUS_TEXT.get(rc, ("error", "erro: o portão não rodou até o fim — não atesta nada desta ponta"))
    body = {"state": state, "context": STATUS_CONTEXT, "description": text[:255]}
    if run:
        body["target_url"] = run
    req = urllib.request.Request(
        f"{api}/repos/{repo}/statuses/{sha}", data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json",
                 "User-Agent": "brain-public-gate"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return state, resp.status


SHA_RE = re.compile(r"[0-9a-f]{40}")
REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def main_status(a) -> int:
    sha = (a.sha or "").strip().lower()
    try:
        rc = int(a.rc)
    except ValueError:
        rc = -1
    token = os.environ.get("GITHUB_TOKEN", "")
    api, repo = os.environ.get("GITHUB_API_URL", ""), os.environ.get("GITHUB_REPOSITORY", "")
    if not SHA_RE.fullmatch(sha) or not REPO_RE.fullmatch(repo) or not api.startswith("https://") or not token:
        print("✗ status: sha da ponta ausente ou malformado, ou sem token e contexto do Actions — nada publicado")
        return ERROR
    try:
        state, _ = post_status(sha, rc, a.run, api, repo, token)
    except urllib.error.HTTPError as e:
        print(f"✗ status: a API respondeu HTTP {e.code}")
        return ERROR
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"✗ status: {type(e).__name__}")
        return ERROR
    print(f"✓ status `{STATUS_CONTEXT}`: {state}")
    return CLEAN


def main(argv: list[str] | None = None, trusted: Path | None = None) -> int:
    """`trusted` é o checkout de onde vêm a configuração da varredura (padrão: o deste script)."""
    p = argparse.ArgumentParser(description="portão de dados do repositório público")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate", help="varre <base>..HEAD; código 4 se achar algo")
    g.add_argument("--base", required=True, help="ref ou sha do último commit já público")
    g.add_argument("--root", default=".", help="repositório a varrer (padrão: a pasta de onde se chama)")
    g.add_argument("--denylist", required=True, help="arquivo com a lista privada de termos (um por linha)")
    g.add_argument("--detalhes", action="store_true",
                   help="lista também onde bateu a lista privada — só fora do CI: o log do CI é público")
    s = sub.add_parser("status", help=f"publica o resultado do gate como status de commit `{STATUS_CONTEXT}`")
    s.add_argument("--sha", required=True, help="sha da ponta do PR")
    s.add_argument("--rc", required=True, help="código de saída do gate (0, 4 ou qualquer outro)")
    s.add_argument("--run", default=None, help="URL do run, para o link do status")
    a = p.parse_args(argv)
    if a.cmd == "status":
        return main_status(a)
    deny: list[str] = []
    try:
        deny = load_denylist(Path(a.denylist))
        restore = install_denylist(deny)
        try:
            findings = scan_range(Path(a.root), a.base, trusted=trusted)
            findings += opaque_attachments(Path(a.root), a.base)
        finally:
            upstream._leak_terms = restore
            upstream.PLAIN_KINDS.discard(KIND)
        if findings:
            report(findings, a.base, deny, a.detalhes)
            return FOUND
        print(f"✓ portão de dados limpo em {a.base}..HEAD")
        return CLEAN
    except (RuntimeError, subprocess.CalledProcessError, util.BrainError) as e:
        # a mensagem destas exceções não carrega valor achado: só a classe do erro de git. Ainda assim,
        # qualquer termo da lista que tenha entrado nela sai antes de imprimir.
        detail = e.stderr.strip()[-200:] if isinstance(e, subprocess.CalledProcessError) else str(e)
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", "replace")
        print(f"✗ portão de dados: {_mask(str(detail), deny)}")
        return ERROR


if __name__ == "__main__":
    sys.exit(main())
