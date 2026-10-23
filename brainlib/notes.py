"""Notas avulsas: o dono escreve, o arquivo cai na inbox (a porta única) e o /dump arquiva depois.

Nome: `<VÍNCULO>-AAAA-MM-DD-note.md` (`TASK-0146-…`, `GOAL-1-…`, `PROJ-2-…`, `PROJ-2.1-…`; os nomes antigos `A-0146-…`, `G1-…`, `P2-…` ainda são lidos); sem vínculo, `note-…`.
Mesmo dia e mesmo alvo ganham sufixo: `…-note-2.md`. O arquivo carrega um frontmatter com o vínculo e a
hora (AAAA-MM-DD HH:mm), então o TUI mostra a nota no detalhe do alvo sem depender do /dump — na inbox
ou, depois de arquivada, em `RAW/<ano>/<mês>/` (conteúdo imutável: o cérebro só lê).
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import ids, util

LINK_RE = ids.LINK_ID
# o nome aceita também os prefixos antigos (nota ainda não migrada): o vínculo é sempre devolvido no formato novo
NAME_RE = re.compile(rf"^(?P<link>{ids.LINK_SRC}|{ids.LEGACY_LINK_SRC}|note)"
                     r"-(?P<day>\d{4}-\d{2}-\d{2})-note(?:-(?P<n>\d+))?\.md$")
KINDS = {"TASK": "ação", "GOAL": "goal", "PROJ": "projeto"}
MAX_CHARS = 200_000


@dataclass
class Note:
    path: str              # relativo ao vault
    link: str              # "" = avulsa
    created: str           # AAAA-MM-DD HH:mm
    text: str
    archived: bool         # já em RAW/<ano>/<mês>/ (a inbox ainda espera o /dump)
    edited: str = ""       # AAAA-MM-DD HH:mm da última edição, se houve

    @property
    def kind(self) -> str:
        return kind_of(self.link)

    @property
    def title(self) -> str:
        first = next((ln.strip() for ln in self.text.splitlines() if ln.strip()), "")
        return first[:80] or Path(self.path).name


def kind_of(link: str) -> str:
    """'ação' | 'goal' | 'projeto' | 'entregável' | '' (avulsa)."""
    if not link:
        return ""
    link = ids.normalize(link)
    if link.startswith("PROJ-") and "." in link:
        return "entregável"
    return KINDS.get(link.split("-")[0], "")


def normalize_link(value: str) -> str:
    """'a-146' → 'TASK-0146'; 'p2.1' → 'PROJ-2.1'; 'g1' → 'GOAL-1'. Vazio continua vazio; formato inválido devolve o texto em maiúsculas."""
    v = (value or "").strip().upper()
    m = re.fullmatch(r"(?:A|TASK)-?(\d{1,})", v)
    if m:
        return f"TASK-{int(m.group(1)):04d}"
    return ids.normalize(v)


def check_link(brain, link: str) -> str:
    """Mensagem de erro ('' = ok): o vínculo precisa existir na ação ou na árvore do PLANNING."""
    if not link:
        return ""
    if not LINK_RE.match(link):
        return f"vínculo inválido: {link!r} (use TASK-####, GOAL-#, PROJ-# ou PROJ-#.#)"
    if link.startswith("TASK-"):
        return "" if link in brain.state.actions else f"{link}: ação não encontrada"
    return "" if brain.plan.has(link) else f"{link}: não existe em PLANNING/goals.md"


def _taken(inst) -> set[str]:
    names = {p.name for p in inst.inbox.glob("*-note*.md")} if inst.inbox.exists() else set()
    raw = inst.vault / "RAW"
    if raw.exists():
        names |= {p.name for p in raw.glob("*/*/**/*-note*.md")}
    return names


def filename(inst, link: str, day: str) -> str:
    taken, base = _taken(inst), f"{link or 'note'}-{day}-note"
    name, n = f"{base}.md", 2
    while name in taken:
        name, n = f"{base}-{n}.md", n + 1
    return name


def create(brain, text: str, link: str = "") -> Path:
    if os.environ.get("BRAIN_NIGHTLY") == "1":
        raise util.BrainError("note add: proibido no noturno — nota é do dono, que precisa estar presente", code=4)
    text = (text or "").strip("\n")
    if not text.strip():
        raise util.BrainError("a nota está vazia", code=3)
    if len(text) > MAX_CHARS:
        raise util.BrainError(f"nota grande demais ({len(text)} caracteres; o limite é {MAX_CHARS})", code=3)
    link = normalize_link(link)
    err = check_link(brain, link)
    if err:
        raise util.BrainError(err, code=3)
    inst, now = brain.inst, util.now()
    head = ["---", "tipo: nota"]
    if link:
        head += [f"vinculo: {link}", f"vinculo-tipo: {kind_of(link)}"]
    head += [f"criada: {now.strftime('%Y-%m-%d %H:%M')}", "---", ""]
    inst.inbox.mkdir(parents=True, exist_ok=True)
    # 'x' não sobrescreve nunca: se outro processo pegou o nome no meio, tenta o próximo sufixo
    for _ in range(20):
        path = inst.inbox / filename(inst, link, now.strftime("%Y-%m-%d"))
        try:
            with open(path, "x", encoding="utf-8") as fh:
                fh.write("\n".join(head) + text + "\n")
            return path
        except FileExistsError:
            continue
    raise util.BrainError("não consegui um nome livre para a nota", code=5)


def editable_today(inst, link: str) -> Note | None:
    """A nota de hoje, ainda na inbox, para esse vínculo (a mais recente). Arquivada no RAW é imutável: não conta."""
    if not link:
        return None
    today = util.today().isoformat()
    return next((n for n in scan(inst) if n.link == link and not n.archived and n.created[:10] == today), None)


def update(brain, rel: str, text: str) -> Path:
    """Reescreve o texto de uma nota que ainda está na inbox; o vínculo e a hora de criação ficam, `editada:` marca a edição."""
    if os.environ.get("BRAIN_NIGHTLY") == "1":
        raise util.BrainError("note edit: proibido no noturno — nota é do dono, que precisa estar presente", code=4)
    text = (text or "").strip("\n")
    if not text.strip():
        raise util.BrainError("a nota está vazia", code=3)
    if len(text) > MAX_CHARS:
        raise util.BrainError(f"nota grande demais ({len(text)} caracteres; o limite é {MAX_CHARS})", code=3)
    inst = brain.inst
    path = (inst.vault / rel).resolve()
    if path.parent != inst.inbox.resolve() or not NAME_RE.match(path.name) or not path.is_file():
        raise util.BrainError(f"{rel}: não é uma nota da inbox (só nota ainda não arquivada pode ser editada)", code=3)
    raw = path.read_text(encoding="utf-8")
    end = raw.find("\n---", 4) if raw.startswith("---\n") else -1
    head = raw[4:end].splitlines() if end != -1 else ["tipo: nota"]
    head = [ln for ln in head if not ln.startswith("editada:")] + [f"editada: {util.now().strftime('%Y-%m-%d %H:%M')}"]
    util.atomic_write(path, "\n".join(["---", *head, "---", ""]) + text + "\n")
    return path


def _parse(path: Path, vault: Path) -> Note | None:
    m = NAME_RE.match(path.name)
    if not m:
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta: dict[str, str] = {}
    body = raw
    if raw.startswith("---\n"):
        end = raw.find("\n---", 4)
        if end != -1:
            for ln in raw[4:end].splitlines():
                k, sep, v = ln.partition(":")
                if sep:
                    meta[k.strip()] = v.strip()
            body = raw[end + 4:].lstrip("\n")
    link = ids.normalize((meta.get("vinculo") or ("" if m["link"] == "note" else m["link"])).upper())
    if link and not LINK_RE.match(link):
        link = ""
    created = meta.get("criada") or ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", created):
        created = datetime.fromtimestamp(path.stat().st_mtime, util.tz()).strftime("%Y-%m-%d %H:%M")
    rel = util.relpath(path, vault)
    # arquivada = fora de RAW/inbox/ (olhar só o caminho relativo: uma pasta "inbox" acima do vault não conta)
    archived = Path(rel).parts[:2] != ("RAW", "inbox")
    return Note(rel, link, created, body.strip("\n"), archived, meta.get("editada", ""))


def scan(inst) -> list[Note]:
    """Todas as notas (inbox + RAW), da mais nova para a mais antiga."""
    found: list[Path] = []
    if inst.inbox.exists():
        found += sorted(inst.inbox.glob("*-note*.md"))
    raw = inst.vault / "RAW"
    if raw.exists():
        found += sorted(raw.glob("*/*/**/*-note*.md"))
    out = [n for n in (_parse(p, inst.vault) for p in found) if n]
    out.sort(key=lambda n: (n.created, n.path), reverse=True)
    return out


def cli(args, brain) -> None:
    if args.ncmd == "add":
        text = args.text if args.text is not None else sys.stdin.read()
        path = create(brain, text, args.link or "")
        rel = brain.inst.rel(path)
        if args.json:
            print(json.dumps({"path": rel}, ensure_ascii=False))
        else:
            print(f"✓ nota → {rel} (rode /dump para arquivar)")
        return
    if args.ncmd == "edit":
        text = args.text if args.text is not None else sys.stdin.read()
        rel = brain.inst.rel(update(brain, args.path, text))
        print(json.dumps({"path": rel}, ensure_ascii=False) if args.json else f"✓ nota editada → {rel}")
        return
    link = normalize_link(args.link or "")
    rows = [n for n in scan(brain.inst) if not link or n.link == link]
    if args.json:
        print(json.dumps([n.__dict__ for n in rows], ensure_ascii=False, indent=2))
    else:
        print("\n".join(f"{n.created} · {n.link or 'avulsa':<7} · {n.title} · {n.path}" for n in rows) or "(nenhuma)")
