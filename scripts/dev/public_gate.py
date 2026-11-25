#!/usr/bin/env python3
"""Portão de dados do repositório público — o que entra no repo passa pela varredura do brain.

O repositório é público e é a origem: cada pull request acrescenta commits a ele. O hook pre-push
já varre na máquina de quem sobe (`brain upstream scan`); o CI repete a varredura de forma
independente, antes de rodar a suíte — a mesma varredura do brain (caminho da máquina, segredo,
workspace do Slack, dado pessoal da instância) mais uma lista privada de termos (nome de empresa,
de rede interna, o que o mantenedor nunca quiser ver lá), que mora num segredo do repositório
(Actions) e nunca vai ao código.

    public_gate.py gate --base <ref|sha> [--root <repo>] --denylist <arquivo>

Varre `<base>..HEAD` do repositório `--root` (padrão: a pasta de onde se chama — nunca a do script,
que chamado de outro checkout varria o lugar errado e dá "limpo"), commit a commit. A lista
privada é um termo por linha (ou separado por vírgula); linha que começa com `#` é comentário. No
CI o `--root` é um worktree do PR: os scripts e a configuração da varredura vêm do checkout da
main — o PR nunca diz quais são os termos.

Arquivo compactado ou documento (zip, gzip, 7z, RAR, PDF, Office) que o alcance cria é achado por si,
mesmo sem termo nenhum: o portão não lê o que está comprimido dentro. Imagem e vídeo não são
bloqueados — são revisão de quem mantém.

Códigos de saída: 0 limpo · 4 achado (o valor achado nunca é ecoado: só arquivo, linha e regra) ·
1 erro — inclusive lista privada ausente, vazia, toda em comentário ou com termo curto demais:
sem os termos pedidos o portão não atesta nada.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from brainlib import config, upstream, util  # noqa: E402

KIND = "lista privada"                 # nome da regra nos achados
MIN_TERM = upstream.MIN_TERM           # mesmo piso do `brain upstream scan`: evita termo curto que casa tudo
CLEAN, FOUND, ERROR = 0, 4, 1


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
    genéricas — a lista privada é o que cobre o dado de empresa nesse ponto. Devolve o original.
    """
    original = upstream._leak_terms

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



OPAQUE_RULE = "anexo fechado (compactado ou documento: o portão não lê o que há dentro)"
# Anexo cujo conteúdo a varredura não abre. O dado pode estar lá dentro, comprimido ou codificado, e a
# busca de texto passa direto: por isso o arquivo em si é o achado, pelo nome ou pela assinatura dos
# primeiros bytes. Imagem e vídeo ficam de fora — o repositório os usa (ícones e auditoria de interface)
# — e, desenhado, o dado não é legível para o portão de jeito nenhum: é revisão de quem mantém.
OPAQUE_SUFFIXES = (".zip", ".gz", ".tgz", ".tar", ".bz2", ".xz", ".7z", ".rar", ".pdf", ".doc", ".docx",
                   ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp")
OPAQUE_MAGIC = (b"\x1f\x8b", b"PK\x03\x04", b"7z\xbc\xaf\x27\x1c", b"Rar!\x1a\x07", b"\xfd7zXZ\x00",
                b"BZh", b"%PDF-", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")


def _git_bytes(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
    r = subprocess.run(["git", "-C", str(root), "-c", "core.quotepath=false", *args],
                       input=stdin, capture_output=True)
    if r.returncode != 0:
        raise subprocess.CalledProcessError(r.returncode, r.args, r.stdout, r.stderr)
    return r.stdout


def _blob_heads(root: Path, shas: list[str], size: int = 8) -> dict[str, bytes]:
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
        proc.kill()
        proc.wait()
    return heads


def opaque_attachments(root: Path, base: str | None) -> list[dict]:
    """Anexos do alcance que a varredura não abre: compactado ou documento, pelo nome ou pela assinatura.

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
    heads = _blob_heads(root, list(blobs))
    return [{"file": path, "line": 1, "rule": OPAQUE_RULE, "hint": f"blob {sha[:12]}"}
            for sha, path in blobs.items()
            if path.lower().endswith(OPAQUE_SUFFIXES) or heads.get(sha, b"").startswith(OPAQUE_MAGIC)]


def main(argv: list[str] | None = None, trusted: Path | None = None) -> int:
    """`trusted` é o checkout de onde vêm a configuração da varredura (padrão: o deste script)."""
    p = argparse.ArgumentParser(description="portão de dados do repositório público")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate", help="varre <base>..HEAD; código 4 se achar algo")
    g.add_argument("--base", required=True, help="ref ou sha do último commit já público")
    g.add_argument("--root", default=".", help="repositório a varrer (padrão: a pasta de onde se chama)")
    g.add_argument("--denylist", required=True, help="arquivo com a lista privada de termos (um por linha)")
    a = p.parse_args(argv)
    try:
        deny = load_denylist(Path(a.denylist))
        restore = install_denylist(deny)
        try:
            findings = scan_range(Path(a.root), a.base, trusted=trusted)
            findings += opaque_attachments(Path(a.root), a.base)
        finally:
            upstream._leak_terms = restore
        if findings:
            print(f"✗ portão de dados: {len(findings)} achado(s) em {a.base}..HEAD")
            upstream._print_findings(findings)
            return FOUND
        print(f"✓ portão de dados limpo em {a.base}..HEAD")
        return CLEAN
    except (RuntimeError, subprocess.CalledProcessError, util.BrainError) as e:
        # a mensagem destas exceções não carrega valor achado: só a classe do erro de git
        detail = e.stderr.strip()[-200:] if isinstance(e, subprocess.CalledProcessError) else str(e)
        print(f"✗ portão de dados: {detail}")
        return ERROR


if __name__ == "__main__":
    sys.exit(main())
