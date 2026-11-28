"""Instância ↔ framework: `brain update` traz melhorias; `brain upstream scan` guarda o caminho de volta.

A instância é um clone do repo do framework; o vault e a config pessoal são ignorados pelo git.
Tudo que não é do dono (brainlib/, commands/, guides/, template/, tests/, services/…) é framework
e volta ao repo com git puro (add/commit/push). O que o `.gitignore` não cobre é dado pessoal
DENTRO de arquivo do framework, e o repo é público: a varredura (nome, e-mail, pessoas do ledger,
caminhos da máquina, tokens) roda num hook pre-push e no `doctor`. Rede de segurança, não revisão.
"""
from __future__ import annotations

import getpass
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

from . import config, util

# Nunca podem estar rastreados pelo git (zona do dono / segredos da instância).
PRIVATE_FILES = {".env", "config/.env", "config/brain.toml", "config/watch.toml",
                 "config/.state.json", "config/.memory-state.json"}
PRIVATE_PREFIXES = ("vault/",)

PUBLIC_MAIL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "icloud.com",
               "yahoo.com", "yahoo.com.br", "proton.me", "protonmail.com", "uol.com.br", "bol.com.br",
               # RFC 2606: example.com/.org/.net são reservados para documentação — gente de teste no
               # ledger não pode virar termo (barava até o nome config/brain.toml.example)
               "example.com", "example.org", "example.net"}
HOME_PLACEHOLDERS = {"you", "user", "usuario", "seu-usuario", "name", "nome", "voce", "me", "example"}
MIN_TERM = 4
MAX_SCAN_BYTES = 1_000_000
# Tipos de termo que casam como substring pura, sem fronteira de palavra: nome de empresa colado noutro
# (`<termo>_prod`, `<termo>VPN`) é dado igual. O portão público registra aqui a lista privada.
PLAIN_KINDS: set[str] = set()

_HOME_RE = re.compile(r"(/Users|/home)/([A-Za-z0-9._-]+)/")
_SECRET_RES = [
    ("token do Slack", re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("token do GitHub", re.compile(r"(?:ghp_|gho_|ghs_|github_pat_)[A-Za-z0-9_]{20,}")),
    ("chave AWS", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("chave de API do Google", re.compile(r"AIza[0-9A-Za-z_-]{30,}")),
    ("chave sk-", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("chave privada", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # ≥ 24 chars: segredo (35) e refresh token (100+) do Google nunca são curtos; template de código (`={refresh}")`) não é achado.
    ("segredo do Google", re.compile(r"GOOGLE_(?:CLIENT_SECRET|REFRESH_TOKEN)\s*=\s*[^\s#]{24,}")),
]
_SLACK_WS_RE = re.compile(r"\b([a-z0-9-]+)\.slack\.com/(?:archives|team|files|docs)\b", re.I)
SLACK_PLACEHOLDERS = {"seu-workspace", "workspace", "example", "acme", "empresa", "team"}


# ── git ─────────────────────────────────────────────────────────────────────
GIT_TIMEOUT_S = 600


def _git(root: Path, *args: str, check: bool = True, raw: bool = False,
         errors: str = "replace") -> subprocess.CompletedProcess:
    # sem terminal para pedir senha (noturno, hook): credencial ausente falha em vez de travar para sempre
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    # `raw=True`: stdout em bytes, para lista de NOME de arquivo (`_paths`): nome não é texto. `errors` diz o
    # que fazer, na saída em texto, com byte que não é UTF-8 válido. `replace` serve para metadado (ref, remote,
    # mensagem de erro). Diff e log carregam nome de arquivo no cabeçalho e conteúdo: ali o byte tem de voltar
    # inteiro (`surrogateescape`), porque o nome vira rótulo do achado.
    # `encoding` fixado em UTF-8: sem ele o subprocess decodifica com o encoding do locale — `cp1252` num Windows em
    # português — e o nome acentuado do cabeçalho do diff chegava trocado, sem casar com o nome da listagem.
    # A linha de comando sai por `_cmd`: o nome foi LIDO em UTF-8 e tem de voltar em UTF-8, em bytes — como `str`,
    # o Python o codificava no encoding do locale e ele chegava trocado ao git.
    dec = {} if raw else {"text": True, "encoding": "utf-8", "errors": errors}
    try:
        r = subprocess.run(_cmd(root, *args), capture_output=True, env=env,
                           timeout=GIT_TIMEOUT_S, **dec)
    except FileNotFoundError as e:
        raise util.BrainError("git não encontrado no PATH") from e
    except subprocess.TimeoutExpired as e:
        raise util.BrainError(f"git {' '.join(args[:2])} não respondeu em {GIT_TIMEOUT_S}s", 4) from e
    if check and r.returncode != 0:
        err = r.stderr or r.stdout
        if isinstance(err, bytes):                    # leitura em bytes: a mensagem de erro continua sendo texto
            err = err.decode("utf-8", "replace")
        raise util.BrainError(f"git {' '.join(args[:2])} falhou: {_show(err.strip())}", 4)   # texto pode trazer surrogate
    return r


def _lines(r: subprocess.CompletedProcess) -> list[str]:
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def _decode(p: bytes) -> str:
    """Byte de NOME de arquivo → str, lido em UTF-8 com `surrogateescape`: o byte que não é UTF-8 válido fica
    guardado (surrogate) e volta byte a byte quando o nome entra de novo no git (`_arg`) ou no disco (`_fs_path`).
    O par é sempre este, nunca o do sistema: num locale de byte único (`pt_BR.ISO-8859-1`) o par do sistema é
    latin-1 e o nome guardado em UTF-8 vinha trocado; no Windows é UTF-8 com `surrogatepass` (PEP 529), que levanta
    UnicodeDecodeError com esse byte — a varredura caía num clone com histórico de nome assim, em vez de guardar
    o byte e seguir."""
    return p.decode("utf-8", "surrogateescape")


def _paths(r: subprocess.CompletedProcess) -> list[str]:
    """Caminhos de um `git … -z` lido em bytes (`_git(…, raw=True)`): separados por NUL, nunca entre aspas, e
    decodificados como NOME de arquivo (`_decode`), não como texto. Nome de arquivo é a sequência de bytes que o
    sistema de arquivos guarda, e no Linux ela pode não ser UTF-8 válida. Lido como texto, o byte inválido vira
    U+FFFD — o nome de arquivo nenhum: como pathspec não casa com nada, e o arquivo era dado como `já público`,
    saindo do scan sem erro. `_decode` guarda o byte (surrogate), e o nome volta byte a byte quando entra de novo
    no git (`_arg`) ou no disco (`_fs_path`). Sem o -z o git entrega entre aspas e com escapes o nome com acento,
    aspas ou barra invertida; `core.quotePath=false` só tira o caso do acento."""
    return [_decode(p) for p in r.stdout.split(b"\0") if p]


def _arg(a):
    """Argumento da linha de comando do git, na forma em que chega byte a byte. Nome de arquivo é `str` com
    surrogate onde havia byte inválido (`_decode`) e volta em bytes pelo MESMO par da leitura — UTF-8 +
    surrogateescape. Como `str`, o Python o codificava no encoding do locale: num Linux em `pt_BR.ISO-8859-1`
    o acento de `relatório` virava outro byte, e o git não achava o arquivo. O que já é bytes passa inteiro."""
    return a.encode("utf-8", "surrogateescape") if isinstance(a, str) else a


def _cmd(root: Path, *args: str) -> list:
    """Linha de comando do git. Em POSIX vai em bytes: os argumentos por `_arg`; a raiz é caminho do sistema
    operacional (veio do `argv`) e segue o par dele, `os.fsencode`. No Windows a linha de comando é UTF-16 e
    segue em `str` — lá o byte que não é UTF-8 válido não chega ao git (daí `_untrustworthy`)."""
    if os.name == "nt":
        return ["git", "-C", str(root), *args]
    return [b"git", b"-C", os.fsencode(root), *(_arg(a) for a in args)]


def _fs_path(root: Path, name: str) -> bytes | Path:
    """Caminho de DISCO de um nome que saiu do git (`_decode`): em POSIX, bytes pelo par da leitura — como `str`,
    o Python o codificava no encoding do locale, e o arquivo de nome acentuado não era aberto. `Path(bytes)` só
    existe no Python 3.13; bytes cru com `open`/`os.stat` serve de 3.11 a 3.14. No Windows, `Path`."""
    if os.name == "nt":
        return root / name
    return os.path.join(os.fsencode(root), _arg(name))


def _show(name: str) -> str:
    """Nome de arquivo para MOSTRAR: o byte que não é UTF-8 válido (guardado como surrogate) aparece como escape
    (`caf\\udce9.py`) em vez de derrubar o print, porque stdout em UTF-8 recusa surrogate. Só a tela passa por aqui;
    o nome que volta ao git segue intacto."""
    return name.encode("utf-8", "backslashreplace").decode("utf-8")


def _prepare(inst: config.Instance, remote: str | None, branch: str | None, fetch: bool = True,
             require_ref: bool = True, git=None) -> tuple[str, str, str | None]:
    """Valida o repo e devolve (remote, branch, ref). Faz fetch; sem rede, ref pode ser None se não for exigida."""
    git_fn = git or _git
    root = inst.root
    if not (root / ".git").exists():
        raise util.BrainError("esta instância não é um clone git do framework — nada a sincronizar", 1)
    remote = remote or "origin"
    if remote not in git_fn(root, "remote").stdout.split():
        raise util.BrainError(f"remote '{remote}' não existe (git remote -v)", 3)
    if not branch:
        branch = git_fn(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if branch == "HEAD":
            raise util.BrainError("HEAD solto (detached): entre num branch antes de sincronizar", 1)
    private = [f for f in _paths(git_fn(root, "ls-files", "-z", raw=True)) if f in PRIVATE_FILES or f.startswith(PRIVATE_PREFIXES)]
    if private:
        raise util.BrainError("arquivos do dono estão rastreados pelo git (nunca devem): "
                              + ", ".join(_show(p) for p in private[:5])
                              + " — `git rm --cached` neles antes de continuar", 4)
    if fetch:
        # refspec explícito: clones feitos com `git remote add` não têm remote.origin.fetch, e aí o
        # fetch simples só atualizaria FETCH_HEAD (origin/<branch> ficaria velho e ahead/behind mentiria)
        r = git_fn(root, "fetch", remote, f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}", check=False)
        if r.returncode != 0:
            raise util.BrainError(f"fetch de {remote}/{branch} falhou: {(r.stderr or r.stdout).strip()}", 4)
    ref = f"{remote}/{branch}"
    if git_fn(root, "rev-parse", "--verify", "--quiet", ref, check=False).returncode != 0:
        if require_ref:
            raise util.BrainError(f"{ref} não existe — o branch ainda não foi publicado?", 3)
        return remote, branch, None
    return remote, branch, ref


def _ahead_behind(root: Path, ref: str, git=None) -> tuple[int, int]:
    git_fn = git or _git
    a, b = git_fn(root, "rev-list", "--left-right", "--count", f"HEAD...{ref}").stdout.split()
    return int(a), int(b)


def _merge_base(root: Path, ref: str | None, git=None) -> str:
    """O commit em que HEAD e `ref` se separaram ("" se o git não souber dizer)."""
    if not ref:
        return ""
    try:
        r = (git or _git)(root, "merge-base", "HEAD", ref, check=False)
    except util.BrainError:
        return ""
    out = (getattr(r, "stdout", "") or "").strip()
    return out if getattr(r, "returncode", 1) == 0 and re.fullmatch(r"[0-9a-f]{7,64}", out) else ""


def _pending_files(root: Path, ref: str, git=None) -> tuple[list[str], list[str]]:
    """(rastreados que diferem do remoto, novos não rastreados e não ignorados)."""
    git_fn = git or _git
    tracked = _paths(git_fn(root, "diff", "--name-only", "-z", ref, raw=True))
    untracked = _paths(git_fn(root, "ls-files", "-z", "--others", "--exclude-standard", raw=True))
    return tracked, untracked


def _version(root: Path) -> str:
    try:
        m = re.search(r'__version__\s*=\s*"([^"]+)"', (root / "brainlib" / "__init__.py").read_text(encoding="utf-8"))
    except OSError:
        return "?"
    return m.group(1) if m else "?"


# ── novidades (CHANGELOG.md) e verificação de atualização com cache ─────────
CHECK_CACHE = ".update-check.json"       # em FRESH/ (derivado): último resultado da verificação
CHECK_MAX_AGE_H = 2                      # poll do upstream: services/com.segundo-cerebro.updatecheck.plist roda a cada 2h


def _vkey(v: str) -> tuple:
    out = []
    for p in str(v or "").split("."):
        try:
            out.append(int(p))
        except ValueError:
            break                                          # "?" ou sufixo: ordena antes de tudo numérico
    return tuple(out) or (0,)


def _plain(text: str) -> str:
    """Texto do painel é escapado: negrito e crase apareceriam como símbolos soltos."""
    return re.sub(r"\s+", " ", (text or "").replace("**", "").replace("`", "")).strip()


def changelog_entries(text: str) -> list[dict]:
    """CHANGELOG.md → [{v, date, title, resumo, bullets}], do mais novo para o mais antigo.

    `resumo` é a linha `> Resumo: …` logo abaixo do título: uma frase para quem não é técnico.
    """
    out: list[dict] = []
    cur: dict | None = None
    for ln in text.splitlines():
        m = re.match(r"^##\s+(\d[\w.]*)(?:\s*[—–-]\s*(.+))?$", ln.strip())
        if m:
            tail = (m.group(2) or "").strip()
            dt = re.match(r"^(\d{4}-\d{2}-\d{2})$", tail)       # título "AAAA-MM-DD" é data, não assunto
            cur = {"v": m.group(1), "date": tail, "title": "" if dt else tail, "resumo": "", "bullets": []}
            out.append(cur)
            continue
        if cur is None:
            continue
        r = re.match(r"^>\s*resumo:\s*(.+)$", ln.strip(), re.I)
        if r:
            cur["resumo"] = _plain(r.group(1))
            continue
        b = re.match(r"^[-*]\s+(.*)$", ln.strip())      # só o marcador da lista: lstrip("-* ") comia o `**` de abertura
        if b:
            cur["bullets"].append(_plain(b.group(1)))      # negrito e crase apareceriam como símbolos soltos
    return out


def parse_changelog(text: str) -> list[tuple[str, str, list[str]]]:
    """CHANGELOG.md → [(versão, data, [bullets])], do mais novo para o mais antigo."""
    return [(e["v"], e["date"], e["bullets"]) for e in changelog_entries(text)]


def _summary_row(e: dict) -> dict:
    text = e["resumo"] or _plain(e["title"])
    return {"v": e["v"], "text": text[:1].upper() + text[1:]}


def summary_between(text: str, from_v: str, to_v: str | None = None) -> list[dict]:
    """Uma frase por versão em (from_v, to_v], para quem não é técnico. Sem `resumo`, cai no título da seção."""
    lo, hi = _vkey(from_v), (_vkey(to_v) if to_v else (1 << 30,))
    return [_summary_row(e) for e in changelog_entries(text) if lo < _vkey(e["v"]) <= hi and (e["resumo"] or e["title"])]


def entry_for(text: str, version: str) -> dict:
    """Resumo e detalhes de UMA versão (a instalada, quando já está em dia). {} se o changelog não a traz."""
    for e in changelog_entries(text):
        if _vkey(e["v"]) == _vkey(version):
            row = _summary_row(e)
            return {"summary": [row] if row["text"] else [], "news": e["bullets"]}
    return {}


def clip_subject(text: str, limit: int = 140) -> str:
    """Assunto de commit em no máximo `limit` caracteres Unicode. Corta no espaço, senão no limite."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    sp = cut.rfind(" ")
    if sp > 0:
        cut = cut[:sp]
    return cut.rstrip() + "…"


def commit_lines(incoming: list[str], limit: int | None = None) -> list[str]:
    """Uma linha por commit: hash curto fora da conta de 140. `limit` acrescenta 'e mais N'."""
    rows = []
    for raw in incoming or []:
        short, _, subject = str(raw).partition(" ")
        text = clip_subject(subject)
        rows.append(f"{short} {text}".strip() if short else text)
    if limit is not None and len(rows) > limit:
        extra = len(rows) - limit
        rows = rows[:limit] + [f"e mais {extra}"]
    return rows


def news_between(text: str, from_v: str, to_v: str | None = None) -> list[str]:
    """Bullets das versões em (from_v, to_v] — as novidades de quem vinha de from_v."""
    lo, hi = _vkey(from_v), (_vkey(to_v) if to_v else (1 << 30,))
    out: list[str] = []
    for v, _date, bullets in parse_changelog(text):
        if lo < _vkey(v) <= hi:
            out += bullets
    return out


def check_is_stale(cache: dict, max_age_h: float = CHECK_MAX_AGE_H * 2) -> bool:
    """O cache não prova "em dia": vazio, com erro de rede ou mais velho que o dobro do intervalo do poll."""
    from . import util as _u
    if not cache or cache.get("error"):
        return bool(cache)
    try:
        return (_u.now() - _u.parse_dt(cache["checked_at"])).total_seconds() > max_age_h * 3600
    except Exception:                                  # noqa: BLE001 — sem data legível = não dá para afirmar
        return True


def read_check_cache(inst) -> dict:
    """Última verificação (sem rede). {} = nunca verificificado."""
    from . import util as _u
    p = inst.fresh / CHECK_CACHE
    if not p.exists():
        return {}
    try:
        return _u.read_json(p, {})
    except Exception:                                  # noqa: BLE001 — cache corrompido = sem cache
        return {}


def check_update(inst, force: bool = False, git=None) -> dict:
    """Verifica o upstream (git fetch, ≤1× a cada CHECK_MAX_AGE_H a menos que force) e grava o cache em FRESH/.

    Sem rede / sem git: devolve o cache antigo marcado `stale=True` — nunca falha,
    nunca bloqueia (superfícies só LÊEM o cache; a rede fica aqui e no noturno).
    """
    from . import util as _u
    git_fn = git or _git
    local_version = _version(inst.root)                # do DISCO: pós-atualização o módulo importado está velho
    cache = read_check_cache(inst)
    ts = cache.get("checked_at")
    fresh = False
    if ts:
        try:
            fresh = (_u.now() - _u.parse_dt(ts)).total_seconds() < CHECK_MAX_AGE_H * 3600
        except Exception:                              # noqa: BLE001
            fresh = False
    if fresh and not force:
        return cache
    root = inst.root
    out = {"version": local_version, "checked_at": _u.now().isoformat(timespec="seconds")}
    try:
        remote, branch, ref = _prepare(inst, None, None, git=git_fn)
        git_fn(root, "fetch", "--quiet", remote, branch, check=True)
        ahead, behind = _ahead_behind(root, ref, git=git_fn)  # (só-HEAD, só-remote) = (ahead, behind)
        out.update(remote=remote, branch=branch, behind=behind, ahead=ahead,
                   incoming=[ln for ln in _lines(git_fn(root, "log", "--format=%h %s", f"HEAD..{ref}"))],
                   remote_version=_version_at(root, ref, git=git_fn), error="")
        changelog_remote = _file_at(root, ref, "CHANGELOG.md", git=git_fn)
        if changelog_remote and out["remote_version"] != "?":
            out["news"] = news_between(changelog_remote, local_version, out["remote_version"])
            out["summary"] = summary_between(changelog_remote, local_version, out["remote_version"])
        else:
            out["news"], out["summary"] = [], []
    except Exception as e:                              # noqa: BLE001 — offline é estado normal
        out.update(behind=cache.get("behind"), ahead=cache.get("ahead"),
                   incoming=cache.get("incoming", []), remote_version=cache.get("remote_version", "?"),
                   news=cache.get("news", []), summary=cache.get("summary", []), error=str(e)[:200])
    try:
        inst.fresh.mkdir(parents=True, exist_ok=True)
        _u.write_json(inst.fresh / CHECK_CACHE, out)
    except OSError:
        pass
    return out


def _file_at(root: Path, ref: str, path: str, git=None) -> str | None:
    git_fn = git or _git
    try:
        r = git_fn(root, "show", f"{ref}:{path}")
        return r.stdout if r.returncode == 0 else None
    except Exception:                                   # noqa: BLE001
        return None


def _version_at(root: Path, ref: str, git=None) -> str:
    text = _file_at(root, ref, "brainlib/__init__.py", git=git)
    if not text:
        return "?"
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else "?"


FRAMEWORK = Path(__file__).resolve().parents[1]


# ── semeadura (compartilhada com `brain init`) ──────────────────────────────
def seed_template(inst: config.Instance) -> list[str]:
    """Copia de template/ para o vault o que ainda não existe. Nunca sobrescreve."""
    tpl = inst.root / "template"
    if not tpl.is_dir():
        tpl = FRAMEWORK / "template"
    if not tpl.is_dir():
        return []
    created = []
    for src in sorted(tpl.rglob("*")):
        if src.is_dir():
            continue
        dst = inst.vault / src.relative_to(tpl)
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            created.append(inst.rel(dst))
    return created


# ── brain update ────────────────────────────────────────────────────────────
_AREAS = [("brainlib/", "núcleo"), ("commands/", "skills"), ("guides/", "guias"), ("template/", "template"),
          ("config/", "config.example"), ("scripts/", "scripts"), ("tests/", "testes"), ("services/", "serviços")]


def _area(path: str) -> str:
    return next((name for prefix, name in _AREAS if path.startswith(prefix)), "outros")


def update(inst: config.Instance, check: bool = False, rebase: bool = False,
           remote: str | None = None, branch: str | None = None,
           git=None, run=None) -> dict:
    if not check and (util.is_nightly() or util.is_agent()):
        raise util.BrainError(
            "o noturno/agente só pode checar atualizações (`brain update --check`) — não aplica `brain update`",
            code=4,
        )
    git_fn = git or _git
    run_fn = run or subprocess.run
    root = inst.root
    remote, branch, ref = _prepare(inst, remote, branch, git=git_fn)
    ahead, behind = _ahead_behind(root, ref, git=git_fn)
    # Melhoria local = o que mudou desde o ponto em que este clone se separou do remoto. Contra o próprio `ref`, um
    # clone só ATRASADO contava como "alterado" cada arquivo que o remoto mudou (\"48 arquivo(s)\" num clone limpo).
    tracked, untracked = _pending_files(root, _merge_base(root, ref, git=git_fn) or ref, git=git_fn)
    res: dict = {"remote": remote, "branch": branch, "ahead": ahead, "behind": behind, "checked_only": check,
                 "version_before": _version(root), "incoming": [], "areas": {}, "seeded": [],
                 "template_diverged": [], "local_pending": len(tracked) + len(untracked)}
    if behind:
        res["incoming"] = [ln for ln in _lines(git_fn(root, "log", "--format=%h %s", f"HEAD..{ref}"))]
        files = _lines(git_fn(root, "diff", "--name-only", f"HEAD...{ref}"))
        for f in files:
            res["areas"][_area(f)] = res["areas"].get(_area(f), 0) + 1
        res["incoming_files"] = files

    if check or not behind:
        res["updated"] = False
    else:
        if ahead and not rebase:
            raise util.BrainError(
                f"divergiu: {ahead} commit(s) locais ainda não publicados e {behind} novo(s) no upstream. "
                "`brain update --rebase` re-aplica os seus por cima; para conflito, `git rebase --abort` desfaz.", 2)
        expected_sha = git_fn(root, "rev-parse", ref).stdout.strip()
        if not expected_sha:
            raise util.BrainError(f"não foi possível resolver o commit esperado de {ref}", 4)
        mode = ["--rebase"] if ahead else ["--ff-only"]
        r = git_fn(root, "pull", *mode, "--autostash", remote, branch, check=False)
        if r.returncode != 0:
            raise util.BrainError("pull falhou — nada do vault foi tocado; edições locais ficam no `git stash list` "
                                  f"se o autostash não reaplicou:\n{(r.stderr or r.stdout).strip()}", 4)
        actual_head = git_fn(root, "rev-parse", "HEAD").stdout.strip()
        if ahead:
            anc = git_fn(root, "merge-base", "--is-ancestor", expected_sha, "HEAD", check=False)
            if not actual_head or anc.returncode != 0:
                raise util.BrainError(
                    f"HEAD pós-rebase ({actual_head[:12] or '?'}) não contém o commit esperado de {ref} "
                    f"({expected_sha[:12]}) — execução pós-pull (doctor/hook) recusada",
                    4,
                )
        elif actual_head != expected_sha:
            raise util.BrainError(
                f"HEAD pós-pull ({actual_head[:12] or '?'}) difere do commit esperado de {ref} "
                f"({expected_sha[:12]}) — execução pós-pull (doctor/hook) recusada",
                4,
            )
        res["updated"] = True
        res["version_after"] = _version(root)
        try:
            chlog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
            res["news"] = news_between(chlog, res["version_before"], res["version_after"])
        except OSError:
            res["news"] = []
        check_update(inst, force=True, git=git_fn)      # re-basa o cache pós-atualização
        incoming_tpl = [f for f in res.get("incoming_files", []) if f.startswith("template/")]
        res["seeded"] = seed_template(inst)
        res["template_diverged"] = [f"vault/{f[len('template/'):]}" for f in incoming_tpl
                                    if (inst.vault / f[len("template/"):]).exists()
                                    and (inst.vault / f[len("template/"):]).read_bytes() != (root / f).read_bytes()]
        try:
            d = run_fn([sys.executable, str(root / "brain"), "doctor"], cwd=root, capture_output=True,
                       text=True, timeout=GIT_TIMEOUT_S)
            doc_out, doc_ok = d.stdout + d.stderr, d.returncode == 0
        except subprocess.TimeoutExpired:
            doc_out, doc_ok = f"doctor não respondeu em {GIT_TIMEOUT_S}s", False
        res["hook"] = hook(inst, "install", git=git_fn)
        if run is None and not check:
            # o servidor de memória acompanha o código novo (imagem pinada + .env no formato da versão) — em segundo
            # plano: a primeira vez baixa a imagem; o watchdog cobre se este processo cair antes
            try:
                subprocess.Popen([sys.executable, str(root / "brain"), "services", "ensure", "--reason", "update"],
                                 cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                res["server_sync"] = "started"
            except OSError:
                res["server_sync"] = "watchdog"

        res["doctor"] = [ln for ln in doc_out.splitlines() if ln.strip()]
        res["doctor_ok"] = doc_ok
    return res


def _print_update(res: dict) -> None:
    ref = f"{res['remote']}/{res['branch']}"
    if res["behind"] == 0:
        print(f"✓ já está na versão do upstream ({ref}, brain {res['version_before']})")
    else:
        verb = "disponíveis" if res["checked_only"] else "trazidos"
        print(f"{res['behind']} commit(s) {verb} de {ref}:")
        for ln in commit_lines(res.get("incoming") or [], limit=20):      # o diálogo rola; o terminal não
            print(f"  · {ln}")
        print("  arquivos por área: " + " · ".join(f"{k} {v}" for k, v in sorted(res["areas"].items())))
    news = res.get("news") or []
    if news:
        head = "Novidades disponíveis (rode `brain update` para instalar):" if res.get("checked_only") \
            else "Novidades desta atualização:"
        print(f"\n{head}")
        for n in news[:10]:
            print(f"  ✓ {n}")
        if len(news) > 10:
            print(f"  … e mais {len(news) - 10} (CHANGELOG.md)")
    if res.get("updated"):
        va = res.get("version_after", "?")
        print(f"✓ framework atualizado (brain {res['version_before']}" + (f" → {va}" if va != res["version_before"] else "") + ")")
        if res["seeded"]:
            print("  semeado no vault a partir de template/ (novo, nada sobrescrito):\n    " + "\n    ".join(res["seeded"]))
        if res["template_diverged"]:
            print("  ⚠ template mudou em arquivo que já é seu (mantive o seu — peça ao agente o diff):\n    "
                  + "\n    ".join(res["template_diverged"]))
        if res["hook"] == "instalado":
            print("  hook pre-push do brain ativo (varredura de dado pessoal em todo git push)")
        if res.get("server_sync"):
            print("  servidor de memória: conferindo em segundo plano (imagem pinada e config/.env desta versão; "
                  "volta à anterior se não subir) — `brain services status`")
        print("doctor:")
        for ln in res["doctor"]:
            print(f"  {ln}")
    elif res["behind"] and res["checked_only"]:
        print("  (--check: nada foi alterado — rode `brain update` para aplicar)")
    if res["ahead"] or res["local_pending"]:
        print(f"⚠ há melhorias locais ainda não enviadas ao framework "
              f"({res['ahead']} commit(s), {res['local_pending']} arquivo(s) alterado(s)/novo(s)) — `brain upstream scan`")


# ── brain upstream ──────────────────────────────────────────────────────────
def _leak_terms(inst: config.Instance) -> list[tuple[str, str]]:
    """Termos pessoais desta instância que não podem aparecer no repo público."""
    terms: dict[str, str] = {}

    def add(kind: str, value: str) -> None:
        value = (value or "").strip()
        if len(value) >= MIN_TERM:
            terms.setdefault(value.lower(), kind)

    cfg = inst.cfg
    owner = cfg["owner"]
    # Nome ainda igual ao placeholder público dos DEFAULTS não é dado de ninguém: sem config de instância
    # (worktree, clone recém-feito) ele voltava como termo e a varredura acusava toda fixture que o escreve.
    placeholder = config.DEFAULTS["owner"]["name"].strip().casefold()
    if (owner.get("name") or "").strip().casefold() != placeholder:
        add("dono", owner.get("name", ""))
    add("dono", owner.get("id", ""))
    for x in cfg.get("outbound", {}).get("allow", []):
        add("destinatário", str(x).lstrip("#@"))
    for x in cfg.get("publish", {}).get("destinations", []):
        add("destino", str(x).split(":", 1)[-1].lstrip("#@"))
    emails: list[str] = []
    from .core import Brain
    brain = Brain(inst)
    if brain.ledger_path.exists():
        try:
            people = brain.state.people.values()
        except util.BrainError:
            raise
        except (OSError, UnicodeDecodeError, ValueError, TypeError, KeyError) as e:
            raise util.BrainError(f"ledger ilegível ou corrompido: {e}", code=5) from e
        for p in people:
            for n in p.names():
                add("pessoa", n)
            if p.email:
                emails.append(p.email)
    for email in emails:
        add("e-mail", email)
        domain = email.rpartition("@")[2].lower()
        if domain and domain not in PUBLIC_MAIL:
            add("domínio", domain)
            add("empresa", domain.split(".")[0])
    return sorted(terms.items(), key=lambda kv: -len(kv[0]))


def _user() -> str:
    try:
        return getpass.getuser().lower()
    except Exception:
        return ""


_DEMO_TOKEN_RE = re.compile(r"[\w.]+-demo\b", re.IGNORECASE)   # `marina-demo`, `Marina-demo`: nome fictício declarado


def _term_regex(term: str, kind: str) -> re.Pattern:
    """Casa o termo nas formas equivalentes do mesmo texto — a busca recebe as leituras de `_forms`,
    nunca a linha crua. O termo vai para NFC: nome de arquivo vindo do macOS e texto de alguns
    editores vêm decomposto (`e` + acento em vez de `é`) e o mesmo nome não casava. O espaço do termo
    casa qualquer quantidade de espaço: o nome com dois espaços, ou com tabulação, é o mesmo nome."""
    body = r"\s+".join(re.escape(part) for part in unicodedata.normalize("NFC", term).split())
    if kind in PLAIN_KINDS:
        return re.compile(body, re.I)
    return re.compile(r"(?<!\w)" + body + r"(?!\w)", re.I)


def _forms(text: str) -> list[str]:
    """As leituras de uma linha que a busca recebe. ASCII é sempre uma só. Com acento, o texto como veio
    e em NFC — só a NFC funde a letra com o acento que vem depois dela (`Cafe` + acento vira `Café`), e
    o termo sem acento (`Cafe`) deixava de casar o texto decomposto, que antes casava. E, se a linha
    guarda byte que não é UTF-8 (o diff é lido com `surrogateescape`), a mesma linha em CP1252:
    planilha em pt-BR exportada pelo Excel é CP1252, e o `é` de `Soluções` chegava como um surrogate
    que nunca casava o `é` do termo."""
    if text.isascii():
        return [text]
    out = [text]
    nfc = unicodedata.normalize("NFC", text)
    if nfc != text:
        out.append(nfc)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raw = text.encode("utf-8", "surrogateescape").decode("cp1252", "replace")
        out.append(unicodedata.normalize("NFC", raw))
    return out


def term_rule(kind: str) -> str:
    """Nome da regra, nos achados, de um termo pessoal (`kind`) — o portão público casa por ele."""
    return f"dado pessoal ({kind})"


def _scan_line(text: str, term_res: list[tuple[str, re.Pattern]], home: str) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    plain = _DEMO_TOKEN_RE.sub(" ", text)          # o sufixo -demo marca dado fictício: não é vazamento do ledger
    # A isenção vale para o termo do LEDGER, que é quem declara o fictício (`marina-demo`). A lista
    # privada (PLAIN_KINDS) casa com o texto cru: `<empresa>-demo` é host de demonstração de empresa
    # de verdade, e o sufixo apagava o termo antes da busca.
    raw_forms, plain_forms = (_forms(text), _forms(plain)) if term_res else ([], [])
    for kind, rx in term_res:
        if any(rx.search(t) for t in (raw_forms if kind in PLAIN_KINDS else plain_forms)):
            hits.append((term_rule(kind), rx.pattern))
    for m in _HOME_RE.finditer(text):
        who = m.group(2).lower()
        if _DEMO_TOKEN_RE.fullmatch(who):
            continue        # /Users/marina-demo: nome fictício declarado — mesmo critério dos termos do ledger
        # /home/<x> aparece em containers (/home/postgres…): só conta se for o usuário desta máquina
        if who not in HOME_PLACEHOLDERS and (m.group(1) == "/Users" or who == _user()):
            hits.append(("caminho da máquina", m.group(0)))
    if home and home in text:
        hits.append(("caminho da máquina", home))
    if any(m.group(1).lower() not in SLACK_PLACEHOLDERS for m in _SLACK_WS_RE.finditer(text)):
        hits.append(("workspace do Slack", "*.slack.com"))
    for name, rx in _SECRET_RES:
        if rx.search(text):
            hits.append((name, rx.pattern))
    return hits


EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
LITERAL = "--literal-pathspecs"     # caminho de arquivo como pathspec: sem isso, nome com `*` casa vizinhos e um que começa com `:` é mágica


MAX_BLOB_BYTES = 50 * 2**20          # acima disto o arquivo não é varrido: é achado, nunca "limpo" por tamanho
BIG_BLOB_RULE = f"arquivo grande demais para varrer (mais de {MAX_BLOB_BYTES // 2**20} MB)"
UNREADABLE_BLOB_RULE = "arquivo que a varredura não conseguiu ler"
_PRINTABLE_RUN = re.compile(rb"[\x20-\x7e\t\x80-\xff]{%d,}" % MIN_TERM)   # como o `strings`, do tamanho do menor termo: trecho menor que o termo não o contém
_WIDE_SAMPLE = 1 << 16               # amostra que decide se um binário é texto em UTF-16/UTF-32
_PLAIN_CHARS = re.compile(r"[\x20-\x7e\t\n\r]")               # texto comum: distingue a decodificação certa da trocada
_C_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def _unquote(path: str) -> str:
    """Caminho como o git imprime: `"b/caf\\303\\251.md"` (aspas C, octal UTF-8) → `b/café.md`.
    O octal que não forma UTF-8 válido vira surrogate (`_decode`), não U+FFFD: o nome continua servindo de caminho.
    Com `core.quotePath=false` o byte acima de 0x7F vem CRU entre as aspas — no texto, já é surrogate
    (`_decode`) — e volta a ser byte na saída; em octal é a forma do padrão do git."""
    if not (len(path) >= 2 and path[0] == path[-1] == '"'):
        return path
    out, i, s = bytearray(), 0, path[1:-1]
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if re.fullmatch(r"[0-7]{3}", s[i + 1:i + 4]):
                out.append(int(s[i + 1:i + 4], 8))
                i += 4
                continue
            out.append(_C_ESCAPES.get(nxt, ord(nxt)))
            i += 2
            continue
        out += c.encode("utf-8", "surrogateescape")
        i += 1
    return out.decode("utf-8", "surrogateescape")


def _strip_side(path: str, side: str) -> str:
    path = _unquote(path.strip())
    return path[2:] if path.startswith(f"{side}/") else ("" if path == "/dev/null" else path)


def _wide_text(data: bytes) -> str | None:
    """Texto em UTF-16 ou UTF-32 (arquivo "Unicode" do Windows e do Excel, redirecionamento do PowerShell 5):
    entre uma letra e outra vem um byte zero, os trechos legíveis somem e a busca passa direto. Devolve o
    texto decodificado, ou None se não é texto largo.

    Sem BOM, testa as codificações e fica com a que dá mais texto comum (ASCII): onde a decodificação trocada
    põe ideograma, a certa põe letra. Amostra que não decodifica inteira, ou que dá mais de 5% de controle e
    sobra de byte, não é texto."""
    sample = data[:_WIDE_SAMPLE]
    if sample[:4] == b"\xff\xfe\x00\x00":
        candidates = ("utf-32-le",)
    elif sample[:4] == b"\x00\x00\xfe\xff":
        candidates = ("utf-32-be",)
    elif sample[:2] == b"\xff\xfe":
        candidates = ("utf-16-le",)
    elif sample[:2] == b"\xfe\xff":
        candidates = ("utf-16-be",)
    else:
        candidates = ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be")
    best: tuple[int, str] | None = None
    for enc in candidates:
        chunk = sample[:len(sample) - len(sample) % (4 if "32" in enc else 2)]
        try:
            text = chunk.decode(enc).lstrip("\ufeff")
        except UnicodeDecodeError:
            continue
        if not text:
            continue
        odd = sum(1 for ch in text if not ch.isprintable() and ch not in "\t\n\r")
        if odd * 20 > len(text):
            continue
        score = sum(1 for ch in text if _PLAIN_CHARS.match(ch))
        if best is None or score > best[0]:
            best = (score, enc)
    if best is None:
        return None
    return data.decode(best[1], errors="replace").lstrip("\ufeff")


def _decode_piece(piece: bytes) -> str:
    """Um trecho em bytes como texto, em UTF-8 — o byte que não é UTF-8 fica guardado como surrogate
    (`surrogateescape`), como na linha de diff. A leitura em CP1252 (planilha em pt-BR exportada pelo
    Excel) é a de `_forms`, na busca. Duas leituras aqui viravam duas linhas: o mesmo trecho, achado
    duas vezes."""
    return piece.decode("utf-8", "surrogateescape")


def _binary_lines(data: bytes) -> list[str]:
    """Conteúdo de arquivo binário para a busca. Sem byte zero, é texto que o git tratou como binário por
    causa de um `.gitattributes` do próprio alcance (`* -diff`): vai linha a linha, como um diff comum.
    Com byte zero, são os trechos legíveis do tamanho de um termo no mínimo (o que o `strings` mostra,
    sem perder termo de 4 ou 5 caracteres entre dois bytes nulos) e, se é texto em UTF-16/UTF-32, o
    texto decodificado."""
    if b"\0" not in data:
        return _decode_piece(data).splitlines()
    out = [_decode_piece(m.group(0)) for m in _PRINTABLE_RUN.finditer(data)]
    wide = _wide_text(data)
    if wide is not None:
        out += wide.splitlines()
    return out


def _blob_size(root: Path, sha: str, path: str) -> int | None:
    """Tamanho do arquivo no commit (ou na árvore de trabalho, sem `sha`). None quando não dá para saber."""
    try:
        if not sha:
            return os.stat(_fs_path(root, path)).st_size
        return int(_git(root, "cat-file", "-s", f"{sha}:{path}", check=False).stdout.strip())
    except (OSError, ValueError, util.BrainError):
        return None


def _blob_via_stdin(root: Path, sha: str, path: str) -> bytes | None:
    """Blob de um nome que a linha de comando pode não carregar. O pedido vai no stdin, em bytes — no Windows
    o argv é UTF-16 e o byte não chega, e o `cat-file` falhava em silêncio: o binário saía sem acusação."""
    pedido = f"{sha}:{path}".encode("utf-8", "surrogateescape") + b"\n"
    r = subprocess.run(_cmd(root, "cat-file", "--batch"), input=pedido, capture_output=True, timeout=120)
    if r.returncode != 0 or not r.stdout:
        return None
    nl = r.stdout.find(b"\n")
    if nl < 0 or r.stdout[:nl].endswith(b" missing"):
        return None
    try:
        size = int(r.stdout[:nl].rsplit(b" ", 1)[-1])
    except ValueError:
        return None
    if size > MAX_BLOB_BYTES:
        return None
    body = r.stdout[nl + 1:nl + 1 + size]
    return body if len(body) == size else None


def _blob(root: Path, sha: str, path: str) -> bytes | None:
    """Conteúdo de `path` no commit `sha` (ou da working tree, sem sha) — para varrer binários. O nome entra no
    `cat-file` e no disco pelo par da leitura (`_cmd`, `_fs_path`): como `str`, num locale de byte único, o
    binário de nome acentuado era pedido com o nome trocado — e a falha era em silêncio, sem acusação."""
    try:
        if not sha:
            p = _fs_path(root, path)
            if not os.path.isfile(p) or os.stat(p).st_size > MAX_BLOB_BYTES:
                return None
            with open(p, "rb") as fh:
                return fh.read()
        if _untrustworthy(path):
            return _blob_via_stdin(root, sha, path)       # o nome não vai no argv: no Windows ele não chegaria
        size = subprocess.run(_cmd(root, "cat-file", "-s", f"{sha}:{path}"),
                              capture_output=True, text=True, timeout=60)
        if size.returncode != 0 or int(size.stdout.strip() or 0) > MAX_BLOB_BYTES:
            return None
        r = subprocess.run(_cmd(root, "cat-file", "blob", f"{sha}:{path}"), capture_output=True, timeout=120)
        return r.stdout if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _scan_diff(root: Path, text: str, check) -> None:
    """Percorre um `git log -p`/`git diff` (com -U0, inclusive diffs combinados de merge) chamando
    check(arquivo, linha, texto) para cada linha que existe no resultado e não existia antes.

    Máquina de estados: dentro de um hunk, toda linha começada por marcador é conteúdo — uma linha de
    código que começa com `++ b/` não se passa por cabeçalho `+++ b/` e escapa da varredura."""
    cur, lineno, sha, nparents, in_hunk, header_file = "", 0, "", 1, False, ""

    def label(path: str) -> str:
        return f"{path} (commit {sha[:9]})" if path and sha else path

    # `split("\\n")`, não `splitlines()`: `splitlines` corta também em \x0b, \x0c, \x1c, \x85, U+2028…, e o
    # pedaço depois do corte vinha sem marcador de diff — ficava fora da varredura.
    for ln in text.split("\n"):
        if ln.startswith("\x01"):
            sha, cur, in_hunk = ln[1:].strip(), "", False
            continue
        if ln.startswith("diff "):
            in_hunk, cur = False, ""
            m = re.match(r'diff --git (?:"a/.*?"|a/\S*) ("b/.*"|b/.*)$', ln)
            header_file = _strip_side(m.group(1), "b") if m else ""
            if not header_file and (ln.startswith("diff --cc ") or ln.startswith("diff --combined ")):
                header_file = _unquote(ln.split(" ", 2)[2].strip())
            if header_file:
                check(label(header_file), 0, header_file)          # o nome do arquivo também vai a público
            continue
        if not in_hunk:
            if ln.startswith("+++ "):
                cur = _strip_side(ln[4:], "b")
                if cur:
                    check(label(cur), 0, cur)
            elif ln.startswith("rename to ") or ln.startswith("copy to "):
                new = _unquote(ln.split(" to ", 1)[1].strip())
                check(label(new), 0, new)
            elif ln.startswith("Binary files ") and ln.endswith(" differ"):
                target = header_file
                m = re.match(r"Binary files .* and (.*) differ$", ln)
                if m and _strip_side(m.group(1), "b"):
                    target = _strip_side(m.group(1), "b")
                data = _blob(root, sha, target) if target else None
                size = _blob_size(root, sha, target) if target else None
                if data is None and size is not None:      # existe no commit e não foi lido: não varrido não é limpo
                    check(label(target), 0, "", only=BIG_BLOB_RULE if size > MAX_BLOB_BYTES else UNREADABLE_BLOB_RULE)
                for n, piece in enumerate(_binary_lines(data or b""), start=1):
                    check(f"{label(target)} [binário]", n, piece)
            elif ln.startswith("@@"):
                at = len(ln) - len(ln.lstrip("@"))
                nparents = max(at - 1, 1)
                m = re.search(r"\+(\d+)", ln)
                lineno = int(m.group(1)) if m else 0
                in_hunk = True
            continue
        if ln.startswith("@@"):                                     # hunk seguinte do mesmo arquivo
            at = len(ln) - len(ln.lstrip("@"))
            nparents = max(at - 1, 1)
            m = re.search(r"\+(\d+)", ln)
            lineno = int(m.group(1)) if m else 0
            continue
        if ln.startswith("\\"):                                     # "\ No newline at end of file"
            continue
        marks, body = ln[:nparents], ln[nparents:]
        if "-" in marks:
            continue
        if "+" in marks and cur:
            check(label(cur), lineno, body)
        lineno += 1


def _private_path(path: str) -> bool:
    return path in PRIVATE_FILES or path.startswith(PRIVATE_PREFIXES)


IDENTITY_FMT = "%an%x00%ae%x00%cn%x00%ce"      # autor e committer: nome e e-mail, um commit por linha
# Endereço `noreply` em mensagem de commit traz quem commita, não dado do ledger. Do endereço sai só o que
# não é dado: o local inteiro do endereço do GitHub (`<id>+<login>@users.noreply.github.com` — o login é o
# nome de quem commita) ou a palavra `noreply` do local. O domínio fica: `noreply@<empresa>` é dado da empresa.
# Antes a linha inteira era pulada (o dado entrava na mesma linha do trailer) — e o padrão `noreply@` não
# casava o formato do GitHub, que traz o `noreply` no domínio.
_ADDR_RE = re.compile(r"[^\s<>|,;\"']+@[^\s<>|,;\"']+", re.A)
_NOREPLY_WORD_RE = re.compile(r"(^|[.\-_+])no[-_.]?reply(?=$|[.\-_+])", re.I)


def _without_noreply(text: str) -> str:
    def sub(m: re.Match) -> str:
        local, _, domain = m.group(0).rpartition("@")
        if domain.lower() == "users.noreply.github.com":
            return " @" + domain
        return _NOREPLY_WORD_RE.sub(r"\1 ", local) + "@" + domain
    return _ADDR_RE.sub(sub, text)


def _identities(root: Path, *revs: str) -> list[list[str]]:
    """`(autor, e-mail do autor, quem commitou, e-mail de quem commitou)` de cada commit do alcance."""
    rows = _git(root, "log", f"--format={IDENTITY_FMT}", *revs).stdout.split("\n")
    return [row for row in (r.split("\x00") for r in rows) if len(row) == 4]


def _scan_identities(root: Path, revs: list[str], check) -> None:
    """Autor e committer de cada commit do alcance: commit feito com a identidade do trabalho publica o nome
    ou o domínio do empregador — é metadado, não passa pela busca do diff.

    Só entra identidade que o histórico público ainda não mostra (o que as refs remotas têm fora deste
    alcance): a que já está lá é pública por definição, e o próprio dono é termo da instância. Do e-mail novo
    entra o domínio — a parte antes do @ costuma trazer o nome de quem commita. Nome novo entra sempre,
    com e-mail conhecido ou não."""
    shown, invert = ["--remotes"], False
    for r in revs:
        if r == "--not":
            invert = not invert
        elif invert != r.startswith("^"):            # lado que fica de fora do alcance: já é público
            shown.append(r[1:] if r.startswith("^") else r)
        elif ".." in r:
            was, _, tip = r.partition("..")          # `a..b`: a já era público (sob --not, é b)
            shown.append((tip or "HEAD") if invert else (was or "HEAD"))
    public = _identities(root, *shown)
    names = {row[i] for row in public for i in (0, 2)}
    mails = {row[i] for row in public for i in (1, 3)}
    for n, (author, author_mail, by, by_mail) in enumerate(_identities(root, *revs), start=1):
        for who, name, mail in (("autor", author, author_mail), ("committer", by, by_mail)):
            where = f"(identidade do commit {n}: {who})"
            if name not in names:
                check(where, 0, name)
            if mail not in mails:
                check(where, 0, mail.rpartition("@")[2])           # só o domínio do e-mail novo


def scan(inst: config.Instance, ref: str | None, committed: bool = False,
         revsets: list[list[str]] | None = None, keep: list[str] | None = None) -> list[dict]:
    """Procura dado pessoal/segredo no que subiria: linhas adicionadas, nomes de arquivo, binários,
    arquivos novos e mensagens de commit.

    committed=True olha só commits (o que um push envia); False inclui working tree e arquivos novos.
    `revsets`: os conjuntos de commits cujas mensagens entram, um por ref atualizada (ex.:
    [["<sha local>", "^<sha remoto>"]] — é o que o hook pre-push recebe do git); None = `ref..HEAD`.
    `keep` (só sem committed): restringe o diff da árvore de trabalho a esses caminhos; None = todos,
    lista vazia = nada a varrer. Os caminhos entram como pathspec LITERAL: cru, nome que começa com `:` é
    mágica para o git e o diff vinha vazio, em silêncio.
    """
    root = inst.root
    term_res = [(kind, _term_regex(t, kind)) for t, kind in _leak_terms(inst)]
    home = str(Path.home())
    findings: list[dict] = []
    seen: set[tuple[str, int, str]] = set()

    def check(file: str, line: int, text: str, only: str | None = None) -> None:
        for rule, _ in ([(only, "")] if only else _scan_line(text, term_res, home)):
            if (file, line, rule) not in seen:
                seen.add((file, line, rule))
                stripped = text.strip()
                findings.append({
                    "file": file,
                    "line": line,
                    "rule": rule,
                    "fingerprint": util.sha(stripped, 12),
                    "length": len(stripped),
                })

    if revsets is None:
        revsets = [[f"{ref}..HEAD"] if ref else ["HEAD"]]
    q = ("-c", "core.quotePath=false")
    # Em modo committed olha commit a commit: o histórico inteiro vai a público, não só o diff líquido
    # (um dado removido num commit posterior continuaria legível no commit anterior). Merges entram com
    # diff combinado denso (--cc): só o que o merge introduziu além dos pais (resolução de conflito, "evil merge").
    if committed:
        for revs in revsets:
            if not revs:
                continue
            # em bytes, decodificado aqui: o byte que não é UTF-8 volta inteiro (o nome do cabeçalho vira rótulo
            # do achado) e o CR no meio de uma linha não vira `\n` — em modo texto o Python faz a troca, a linha
            # do diff virava duas e a segunda vinha sem marcador, fora da varredura
            diff = _git(root, *q, "log", "-p", "-U0", "--no-color", "--cc", "--reverse", "--format=%x01%H", *revs,
                        raw=True)
            _scan_diff(root, diff.stdout.decode("utf-8", "surrogateescape"), check)
            for f in _paths(_git(root, *q, "log", "--name-only", "-z", "--format=", *revs, raw=True)):
                if _private_path(f):
                    key = (f, 0, "arquivo do dono no histórico")
                    if key not in seen:
                        seen.add(key)
                        findings.append({"file": f, "line": 0, "rule": key[2],
                                         "hint": "vault/ e config pessoal nunca vão ao repo (git rm --cached + reescrever o commit)"})
    else:
        # `keep` deixa de fora o que já é público; lista vazia = nada a varrer na árvore de trabalho
        groups = [()] if keep is None else [("--", *keep[i:i + 400]) for i in range(0, len(keep), 400)]
        for scope in groups:
            _scan_diff(root, _git(root, LITERAL, *q, "diff", "-U0", "--no-color", ref or EMPTY_TREE, *scope,
                                  raw=True).stdout.decode("utf-8", "surrogateescape"), check)   # idem: em bytes
    for f in ([] if committed else _paths(_git(root, *q, "ls-files", "-z", "--others", "--exclude-standard", raw=True))):
        p = _fs_path(root, f)
        check(f, 0, f)
        try:
            size = os.stat(p).st_size if os.path.isfile(p) else None
        except (OSError, ValueError):
            continue
        if size is None:
            continue
        if size > MAX_BLOB_BYTES:
            check(f, 0, "", only=BIG_BLOB_RULE)      # não varrido não é limpo
            continue
        try:
            with open(p, "rb") as fh:
                raw = fh.read()
        except (OSError, ValueError):
            continue
        try:
            body = raw.decode("utf-8") if len(raw) <= MAX_SCAN_BYTES and b"\0" not in raw else None
        except UnicodeDecodeError:
            body = None
        lines = body.splitlines() if body is not None else _binary_lines(raw)
        for n, text in enumerate(lines, start=1):
            check(f if body is not None else f"{f} [binário]", n, text)
    for revs in revsets:
        if not revs:
            continue
        for n, text in enumerate(_git(root, "log", "--format=%B", *revs).stdout.splitlines(), start=1):
            check("(mensagem de commit)", n, _without_noreply(text))   # o noreply traz o login de quem commita; o resto da linha entra
    if committed:
        for revs in revsets:
            if revs:
                _scan_identities(root, revs, check)
    return findings


ZERO_SHA_RE = re.compile(r"^0+$")


def push_revsets(inst: config.Instance, remote: str, stdin_text: str) -> list[list[str]]:
    """Linhas do pre-push (`<ref local> <sha local> <ref remota> <sha remoto>`) → conjuntos de commits enviados.

    Apagar ref remota (sha local zero) não envia nada. Ref nova (sha remoto zero) ou sha remoto que não
    existe aqui: tudo que o remoto ainda não tem segundo as refs locais dele (`--not --remotes=<remote>`);
    se `remote` não é um remote nomeado (push direto para URL), nada é excluído — varre o histórico inteiro.
    """
    root = inst.root
    named = remote in _git(root, "remote").stdout.split()
    out: list[list[str]] = []
    for ln in stdin_text.splitlines():
        parts = ln.split()
        if len(parts) < 4:
            continue
        local_sha, remote_sha = parts[1], parts[3]
        if ZERO_SHA_RE.match(local_sha):
            continue
        known = (not ZERO_SHA_RE.match(remote_sha)
                 and _git(root, "cat-file", "-e", f"{remote_sha}^{{commit}}", check=False).returncode == 0)
        if known:
            out.append([local_sha, f"^{remote_sha}"])
        elif named:
            out.append([local_sha, "--not", f"--remotes={remote}"])
        else:
            out.append([local_sha])
    return out


# Lista privada da máquina de quem mantém (nome de empresa, de rede interna…). Com ela, o hook roda o portão
# de dados inteiro (`scripts/dev/public_gate.py`): os termos da lista somados aos da instância e o anexo fechado.
# Sem o hook, os dois só chegavam no CI — depois do push, com o branch já público.
PRIVATE_DENYLIST_ENV = "BRAIN_PUBLIC_DENYLIST"
PRIVATE_DENYLIST_HOME = Path(".config") / "brain" / "public-denylist"          # relativo à home
GATE_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "dev" / "public_gate.py"


def private_denylist() -> Path | None:
    """A lista privada desta máquina, ou None (sem lista: o push segue só com as regras públicas).

    `$BRAIN_PUBLIC_DENYLIST` manda quando definida: um caminho — que tem de ser lido; se não for, o push
    para — ou vazio, que desliga. Sem a variável, `~/.config/brain/public-denylist`, se existir."""
    env = os.environ.get(PRIVATE_DENYLIST_ENV)
    if env is not None:
        return Path(env.strip()).expanduser() if env.strip() else None
    path = Path.home() / PRIVATE_DENYLIST_HOME
    return path if path.exists() or path.is_symlink() else None


def _public_gate():
    """O portão de dados que vem com este código, como módulo. Ausente com a lista na máquina é erro: o push
    não passa sem ele (fail-closed, como a varredura)."""
    if not GATE_SCRIPT.is_file():
        raise util.BrainError("há lista privada nesta máquina, mas esta árvore não tem o portão "
                              "(scripts/dev/public_gate.py) — atualize o clone, ou rode o push com "
                              f"{PRIVATE_DENYLIST_ENV}= (vazio) para varrer só com as regras públicas", 1)
    spec = importlib.util.spec_from_file_location("brain_public_gate", GATE_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pre_push_scan(inst: config.Instance, remote: str, stdin_text: str, denylist: Path | None = None) -> dict:
    """O que o hook pre-push roda: varre exatamente os commits que este push envia (qualquer branch,
    tag, HEAD solto ou ref nova), sem depender do branch atual.

    `denylist`: a lista privada da máquina (`private_denylist`). Com ela, a varredura é a do portão de dados
    sobre os mesmos commits; lista ilegível, vazia ou com termo curto barra o push (código 1)."""
    revsets = push_revsets(inst, remote, stdin_text)
    tracked = [f for f in _paths(_git(inst.root, "ls-files", "-z", raw=True)) if _private_path(f)]
    findings = [{"file": f, "line": 0, "rule": "arquivo do dono rastreado pelo git",
                 "hint": "git rm --cached antes de enviar"} for f in tracked]
    private = bool(revsets) and denylist is not None
    if private:
        gate = _public_gate()
        try:
            findings += gate.prepush(inst, revsets, denylist)
        except gate.GateError as e:                    # mensagem fixa do portão: nunca traz termo da lista
            raise util.BrainError(f"portão de dados: {e}", 1) from e
    elif revsets:
        findings += scan(inst, None, committed=True, revsets=revsets)
    return {"remote": remote, "branch": "(pre-push)", "ref": None, "ahead": 0, "behind": 0, "changed": [], "new": [],
            "local_scripts": [], "committed_only": True, "revsets": revsets, "private": private, "findings": findings}


def _local_scripts(root: Path) -> list[str]:
    d = root / "scripts" / "local"
    return sorted(str(p.relative_to(root)) for p in d.rglob("*") if p.is_file()) if d.exists() else []


def _ref_offline(inst: config.Instance, remote: str | None, branch: str | None) -> tuple[str, str, str | None]:
    """Como `_prepare`, mas sem rede: usa a referência remota que já existe localmente (ou None)."""
    remote, branch, ref = _prepare(inst, remote, branch, fetch=False, require_ref=False)
    return remote, branch, ref


def _unpushed_range(root: Path, remote: str) -> tuple[int, str, list[list[str]]] | None:
    """Branch ainda sem referência no remoto: o que um push enviaria são os commits só locais — a mesma
    conta do hook (`push_revsets`). Devolve (quantos, base para o diff da árvore de trabalho, conjuntos de
    commits). None quando não dá para saber (push direto para URL). Sem isso a varredura caía no histórico
    inteiro, que já é público, e transformava placeholder de commit antigo em achado.

    A base é o pai do commit só-local mais antigo: cobre o branch linear. Num branch que mergeou outra ref
    do remoto ela é só um candidato — o diff contra ela traz de volta o conteúdo da ref mergeada, que já é
    público; `_public_paths` tira esse conteúdo do diff e da lista de pendentes."""
    if remote not in _git(root, "remote").stdout.split():
        return None
    local = _lines(_git(root, "rev-list", "HEAD", "--not", f"--remotes={remote}"))
    parent = (_git(root, "rev-parse", "--verify", "--quiet", f"{local[-1]}^", check=False).stdout.strip()
              if local else "")
    base = parent or (EMPTY_TREE if local else "HEAD")
    return len(local), base, [["HEAD", "--not", f"--remotes={remote}"]]


def _public_paths(root: Path, remote: str, candidates: list[str]) -> list[str]:
    """Entre os caminhos alterados, os que estão byte-idênticos na ponta de alguma ref do remoto — já são
    públicos. Compara pelo mesmo `git diff` da varredura (árvore de trabalho × ponta), então edição local de
    um arquivo público continua indo ao scan: decide o conteúdo, não o caminho.

    A pergunta vai SEM pathspec — "o que difere da ponta", para a árvore inteira — e o nome nunca entra na linha
    de comando. Com pathspec, o nome era re-codificado no encoding do locale (num de byte único não casava com
    nada) e, no Windows, o byte que não é UTF-8 válido não chega ao git: o diff vazio era lido como "já público"
    e o arquivo saía da varredura, em silêncio."""
    public: set[str] = set()
    todo = list(candidates)
    q = ("-c", "core.quotePath=false")
    for tip in _lines(_git(root, "for-each-ref", "--format=%(objectname)", f"refs/remotes/{remote}")):
        if not todo:
            break
        differing = set(_paths(_git(root, *q, "diff", "--name-only", "-z", tip, raw=True)))
        public.update(p for p in todo if p not in differing)
        todo = [p for p in todo if p in differing]
    return sorted(public)


def _untrustworthy(name: str) -> bool:
    """Nome com byte que não é UTF-8 válido (guardado como surrogate por `_decode`): a linha de comando pode não
    carregá-lo — no Windows ela é UTF-16. Pathspec assim não casa com nada, e o git devolve diff vazio, que
    ninguém distingue de "nada alterado"."""
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return True
    return False


def upstream_scan(inst: config.Instance, remote: str | None = None, branch: str | None = None,
                  committed: bool = False, fetch: bool = False) -> dict:
    if fetch:
        remote, branch, ref = _prepare(inst, remote, branch)
    else:
        remote, branch, ref = _ref_offline(inst, remote, branch)
    unpushed = None
    keep = None
    if ref:
        ahead, behind = _ahead_behind(inst.root, ref)
        tracked, untracked = _pending_files(inst.root, ref)
    else:
        unpushed = _unpushed_range(inst.root, remote)
        if unpushed:
            ahead, behind = unpushed[0], 0
            tracked, untracked = _pending_files(inst.root, unpushed[1])
            public = set(_public_paths(inst.root, remote, tracked))
            tracked = [p for p in tracked if p not in public]      # byte-idêntico ao remoto: já é público
            # Nome que a linha de comando pode não carregar: o pathspec do `keep` não casa com nada e o git
            # devolve diff vazio. Abre mão da restrição — pode acusar arquivo que já é público, nunca deixar
            # um de fora.
            keep = None if any(_untrustworthy(p) for p in tracked) else tracked
        else:
            ahead, behind, tracked, untracked = 0, 0, [], []
    revsets = unpushed[2] if unpushed else None                   # mensagens dos commits só locais, nos dois modos
    base = unpushed[1] if unpushed else ref                  # árvore de trabalho × último commit já no remoto
    return {"remote": remote, "branch": branch, "ref": ref, "ahead": ahead, "behind": behind,
            "changed": tracked, "new": untracked, "local_scripts": _local_scripts(inst.root),
            "committed_only": committed, "unpushed_base": bool(unpushed),
            "findings": scan(inst, base, committed=committed, revsets=revsets, keep=keep)}


def _format_finding(f: dict) -> str:
    """Uma linha por achado: onde e qual regra — nunca o valor achado."""
    if f.get("hint"):
        return f"  ✗ {f['file']}:{f['line']} — {f['rule']}: {f['hint']}"
    if not f.get("length"):
        return f"  ✗ {f['file']}:{f['line']} — {f['rule']}"     # achado do arquivo inteiro: sem linha, não há impressão digital
    return f"  ✗ {f['file']}:{f['line']} — {f['rule']} (sha:{f.get('fingerprint', '')}, {f.get('length', 0)} chars)"


def _print_findings(findings: list[dict]) -> None:
    for f in findings[:25]:
        print(_show(_format_finding(f)))
    if len(findings) > 25:
        print(f"  … e mais {len(findings) - 25}")


def _print_scan(st: dict) -> None:
    if "revsets" in st:
        extra = " · com a lista privada desta máquina e o anexo fechado" if st.get("private") else ""
        print(f"pre-push → {st['remote']}: {len(st['revsets'])} ref(s) com commits a varrer{extra}")
    elif st.get("unpushed_base"):
        print(f"{st['remote']}/{st['branch']} ainda sem referência no {st['remote']} — o que um push enviaria: "
              f"{st['ahead']} commit(s)")
    else:
        ref = st["ref"] or f"{st['remote']}/{st['branch']} (ainda sem referência local)"
        print(f"{ref}: {st['ahead']} commit(s) à frente · {st['behind']} atrás (sem rede; `--fetch` atualiza)")
    if not st["committed_only"] and (st["changed"] or st["new"]):
        print(f"não enviados: {len(st['changed'])} alterado(s) · {len(st['new'])} novo(s)")
        for f in st["changed"][:30]:
            print(f"  M {_show(f)}")
        for f in st["new"][:30]:
            print(f"  ? {_show(f)}")
    if st["local_scripts"]:
        print("inovação local (scripts/local/ — ignorada pelo git; gradue movendo para scripts/ ou brainlib/):")
        for f in st["local_scripts"][:10]:
            print(f"  · {_show(f)}")
    if st["findings"]:
        print(f"✗ {len(st['findings'])} achado(s) de dado pessoal/segredo — não envie ao repo público até limpar:")
        _print_findings(st["findings"])
    elif st["ahead"] or st["changed"] or st["new"] or st.get("revsets"):   # pre-push: varreu os commits do push
        print("✓ varredura limpa (leia o diff mesmo assim: ela é rede de segurança, não revisão)")
    else:
        print("✓ nada pendente — o framework já tem tudo que a instância tem")
    if st["behind"]:
        print(f"⚠ o upstream tem {st['behind']} commit(s) novos — `brain update` antes de enviar")


# ── hook pre-push (git nativo) ──────────────────────────────────────────────
HOOK_MARK = "# brain-upstream-scan"
# O git passa ao pre-push o remoto ($1) e, no stdin, uma linha por ref enviada; a varredura lê as duas
# coisas (BRAIN_PRE_PUSH) e olha exatamente os commits do push — qualquer branch, tag, HEAD solto, ref nova.
# Falha da varredura BLOQUEIA (fail-closed): rede de segurança que some em silêncio não protege nada.
# Exceção: ./brain ausente/não executável (126/127 — árvore sem o CLI) só avisa.
HOOK_BODY = f"""#!/bin/sh
{HOOK_MARK} — instalado por `brain update`/`brain init`; `brain upstream hook remove` tira
root="$(git rev-parse --show-toplevel)" || exit 1
BRAIN_PRE_PUSH="$1" "$root/brain" upstream scan --committed
rc=$?
[ "$rc" -eq 0 ] && exit 0
if [ "$rc" -eq 4 ]; then
  echo "push bloqueado: dado pessoal/segredo nos commits (acima). Limpe e commite de novo." >&2
  exit 1
fi
if [ "$rc" -eq 126 ] || [ "$rc" -eq 127 ]; then
  echo "aviso: ./brain ausente ou não executável nesta árvore — varredura não rodou; push liberado." >&2
  exit 0
fi
echo "push bloqueado: a varredura do brain falhou (código $rc) — corrija o erro acima e tente de novo." >&2
exit 1
"""


def _hook_path(root: Path, git=None) -> Path:
    git_fn = git or _git
    rel = git_fn(root, "rev-parse", "--git-path", "hooks/pre-push").stdout.strip()
    return (root / rel) if not os.path.isabs(rel) else Path(rel)


FETCH_REFSPEC = "+refs/heads/*:refs/remotes/origin/*"


def fetch_refspec_state(inst: config.Instance) -> str:
    """'ok' | 'ausente' | 'sem-origin' | 'sem-git'. Sem `remote.origin.fetch` um `git fetch` comum só atualiza o
    FETCH_HEAD: o `origin/main` local fica velho e ahead/behind (update, doctor, a checagem antes do push) mentem.
    Um `git clone` normal já traz a regra; falta em clones montados à mão (`git init` + config)."""
    if not (inst.root / ".git").exists():
        return "sem-git"
    if "origin" not in _git(inst.root, "remote", check=False).stdout.split():
        return "sem-origin"
    r = _git(inst.root, "config", "--get-all", "remote.origin.fetch", check=False)
    return "ok" if r.stdout.strip() else "ausente"


def ensure_fetch_refspec(inst: config.Instance) -> str:
    """Repara o que `fetch_refspec_state` achou ausente (só acrescenta; regra já existente, inclusive a de um clone
    de um ramo só, nunca é tocada). Devolve o estado: 'ok' | 'corrigido' | 'sem-origin' | 'sem-git'."""
    state = fetch_refspec_state(inst)
    if state != "ausente":
        return state
    _git(inst.root, "config", "--add", "remote.origin.fetch", FETCH_REFSPEC)
    return "corrigido"


def hook_state(inst: config.Instance, git=None) -> str:
    """'instalado' | 'ausente' | 'de-outro' (já existe um pre-push que não é nosso) | 'sem-git'."""
    if not (inst.root / ".git").exists():
        return "sem-git"
    path = _hook_path(inst.root, git=git)
    if not path.exists():
        return "ausente"
    return "instalado" if HOOK_MARK in path.read_text(encoding="utf-8", errors="replace") else "de-outro"


def hook(inst: config.Instance, action: str, git=None) -> str:
    state = hook_state(inst, git=git)
    if state == "sem-git":
        return state
    path = _hook_path(inst.root, git=git)
    if action == "install" and state in ("ausente", "instalado"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(HOOK_BODY, encoding="utf-8")
        path.chmod(0o755)
        return "instalado"
    if action == "remove" and state == "instalado":
        path.unlink()
        return "ausente"
    return state


def doctor_checks(inst: config.Instance) -> list[dict]:
    """Checagens do doctor sobre a sincronia com o framework (sem rede). Vazio fora de um clone git."""
    if not (inst.root / ".git").exists():
        return []
    try:
        st = upstream_scan(inst)
    except util.BrainError as e:
        return [{"level": "warn", "title": "framework", "detail": str(e)}]
    out: list[dict] = []
    pending = st["ahead"] + len(st["changed"]) + len(st["new"])
    if st["findings"]:
        out.append({"level": "warn", "title": "framework",
                    "detail": f"{len(st['findings'])} achado(s) de dado pessoal nas mudanças pendentes — "
                              "`brain upstream scan` (o hook barra o push)"})
    elif pending:
        out.append({"level": "warn", "title": "framework",
                    "detail": f"melhorias locais ainda não enviadas ao repo ({st['ahead']} commit(s), "
                              f"{len(st['changed']) + len(st['new'])} arquivo(s)) — commite e dê push (AGENTS.md)"})
    else:
        out.append({"level": "ok", "title": "framework", "detail": "em dia com o upstream (sem rede)"})
    if fetch_refspec_state(inst) == "ausente":
        out.append({"level": "warn", "title": "git fetch",
                    "detail": "o clone não tem remote.origin.fetch: o origin/<ramo> local fica velho — `brain setup --only framework`"})
    state = hook_state(inst)
    if state == "ausente":
        out.append({"level": "warn", "title": "hook pre-push", "detail": "não instalado — `brain upstream hook install`"})
    elif state == "de-outro":
        out.append({"level": "warn", "title": "hook pre-push",
                    "detail": "já existe um pre-push que não é do brain; a varredura não roda no push"})
    return out


def _print_json(obj) -> None:
    """Saída `--json`: toda string passa por `_show`. Nome de arquivo pode guardar surrogate (byte que não é UTF-8
    válido), a saída vai com `ensure_ascii=False`, e stdout em UTF-8 não imprime surrogate — o comando caía no
    meio do relato em JSON. Na saída o byte aparece como escape, como no relato em texto."""
    print(json.dumps(util.jsonable(obj, _show), ensure_ascii=False, indent=2))


def _follow_models(inst) -> None:
    """Carona no poll de 2 h do `update --check`: no máximo uma vez por dia, as operações do LLM que seguem o padrão
    passam ao mais novo da linha (providers.follow_latest — o dono escolheu acompanhar). Nunca derruba o poll."""
    try:
        from . import providers
        from .core import Brain
        res = providers.follow_latest(Brain(inst), say=lambda *_a, **_k: None)
        if res.get("moves") and res.get("reason") not in ("simulação",):
            print("modelos da memória: " + ", ".join(f"{m['op']} {m['from'] or '—'} → {m['to']}" for m in res["moves"])
                  + f" ({res['reason']})", file=sys.stderr)      # stderr: o `--json` do poll segue JSON puro
    except Exception as e:                                   # noqa: BLE001 — checagem de fundo, nunca quebra o poll
        print(f"modelos da memória: checagem falhou ({type(e).__name__})", file=sys.stderr)


# ── entrada do CLI ──────────────────────────────────────────────────────────
def cli_update(args, _b) -> None:
    inst = config.load()
    if not args.check and not util.is_nightly():
        from . import services as _services
        _services.kick(inst, reason="update")
    checked: dict = {}
    if args.check:                                     # pergunta ao remoto de verdade (é o poll de 2h e o pedido do dono)
        checked = check_update(inst, force=True)
    res = update(inst, check=args.check, rebase=args.rebase, remote=args.remote, branch=args.branch)
    if not args.check:
        from . import perms
        perms.try_sync(config.load(inst.root))   # settings.json novo desceu com o pull: o local acompanha
    if args.check and res.get("behind") and not res.get("news"):
        res["news"] = checked.get("news", [])
    if args.check:
        _follow_models(inst)
    if args.json:
        _print_json(res)
    else:
        _print_update(res)


def cli_upstream(args, _b) -> None:
    inst = config.load()
    if args.ucmd == "hook":
        state = hook(inst, args.action)
        print({"instalado": "✓ hook pre-push instalado (a varredura roda em todo git push)",
               "ausente": "hook pre-push não instalado",
               "de-outro": "⚠ já existe um pre-push que não é do brain — não mexi",
               "sem-git": "esta instância não é um clone git"}[state])
        return
    pre_push = os.environ.get("BRAIN_PRE_PUSH")
    try:
        if args.committed and pre_push is not None:          # chamado pelo hook: refs do push no stdin
            st = pre_push_scan(inst, args.remote or pre_push or "origin", sys.stdin.read(), denylist=private_denylist())
        else:
            st = upstream_scan(inst, args.remote, args.branch, committed=args.committed, fetch=args.fetch)
    except util.BrainError as e:
        # _git usa 4 para falha e para tempo esgotado — o mesmo código do achado. O hook lê 4 como
        # dado pessoal. Aqui, no caminho da varredura, falha do git vira 1; o achado continua 4
        # (SystemExit abaixo). Quem chama _git direto (o update) segue com o 4 de sempre.
        if e.code == 4 and str(e).startswith("git "):
            raise util.BrainError(str(e), 1) from e
        raise
    if args.json:
        _print_json(st)
    else:
        _print_scan(st)
    if st["findings"]:
        raise SystemExit(util.BrainError("", 4).code)
