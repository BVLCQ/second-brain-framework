"""Instância ↔ framework: `brain update` traz melhorias; `brain upstream scan` guarda o caminho de volta.

A instância é um clone do repo do framework; o vault e a config pessoal são ignorados pelo git.
Tudo que não é do dono (brainlib/, commands/, guides/, template/, tests/, services/…) é framework
e volta ao repo com git puro (add/commit/push). O que o `.gitignore` não cobre é dado pessoal
DENTRO de arquivo do framework, e o repo é público: a varredura (nome, e-mail, pessoas do ledger,
caminhos da máquina, tokens) roda num hook pre-push e no `doctor`. Rede de segurança, não revisão.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import shutil
import subprocess
import sys
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

_HOME_RE = re.compile(r"(/Users|/home)/([A-Za-z0-9._-]+)/")
_SECRET_RES = [
    ("token do Slack", re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("token do GitHub", re.compile(r"(?:ghp_|gho_|ghs_|github_pat_)[A-Za-z0-9_]{20,}")),
    ("chave AWS", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("chave de API do Google", re.compile(r"AIza[0-9A-Za-z_-]{30,}")),
    ("chave sk-", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("chave privada", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("segredo do Google", re.compile(r"GOOGLE_(?:CLIENT_SECRET|REFRESH_TOKEN)\s*=\s*[^\s#]{8,}")),
]
_SLACK_WS_RE = re.compile(r"\b([a-z0-9-]+)\.slack\.com/(?:archives|team|files|docs)\b", re.I)
SLACK_PLACEHOLDERS = {"seu-workspace", "workspace", "example", "acme", "empresa", "team"}


# ── git ─────────────────────────────────────────────────────────────────────
GIT_TIMEOUT_S = 600


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    # sem terminal para pedir senha (noturno, hook): credencial ausente falha em vez de travar para sempre
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, errors="replace",
                           env=env, timeout=GIT_TIMEOUT_S)
    except FileNotFoundError as e:
        raise util.BrainError("git não encontrado no PATH") from e
    except subprocess.TimeoutExpired as e:
        raise util.BrainError(f"git {' '.join(args[:2])} não respondeu em {GIT_TIMEOUT_S}s", 4) from e
    if check and r.returncode != 0:
        raise util.BrainError(f"git {' '.join(args[:2])} falhou: {(r.stderr or r.stdout).strip()}", 4)
    return r


def _lines(r: subprocess.CompletedProcess) -> list[str]:
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def _prepare(inst: config.Instance, remote: str | None, branch: str | None, fetch: bool = True,
             require_ref: bool = True) -> tuple[str, str, str | None]:
    """Valida o repo e devolve (remote, branch, ref). Faz fetch; sem rede, ref pode ser None se não for exigida."""
    root = inst.root
    if not (root / ".git").exists():
        raise util.BrainError("esta instância não é um clone git do framework — nada a sincronizar", 1)
    remote = remote or "origin"
    if remote not in _git(root, "remote").stdout.split():
        raise util.BrainError(f"remote '{remote}' não existe (git remote -v)", 3)
    if not branch:
        branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if branch == "HEAD":
            raise util.BrainError("HEAD solto (detached): entre num branch antes de sincronizar", 1)
    private = [f for f in _lines(_git(root, "ls-files")) if f in PRIVATE_FILES or f.startswith(PRIVATE_PREFIXES)]
    if private:
        raise util.BrainError("arquivos do dono estão rastreados pelo git (nunca devem): "
                              + ", ".join(private[:5]) + " — `git rm --cached` neles antes de continuar", 4)
    if fetch:
        # refspec explícito: clones feitos com `git remote add` não têm remote.origin.fetch, e aí o
        # fetch simples só atualizaria FETCH_HEAD (origin/<branch> ficaria velho e ahead/behind mentiria)
        r = _git(root, "fetch", remote, f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}", check=False)
        if r.returncode != 0:
            raise util.BrainError(f"fetch de {remote}/{branch} falhou: {(r.stderr or r.stdout).strip()}", 4)
    ref = f"{remote}/{branch}"
    if _git(root, "rev-parse", "--verify", "--quiet", ref, check=False).returncode != 0:
        if require_ref:
            raise util.BrainError(f"{ref} não existe — o branch ainda não foi publicado?", 3)
        return remote, branch, None
    return remote, branch, ref


def _ahead_behind(root: Path, ref: str) -> tuple[int, int]:
    a, b = _git(root, "rev-list", "--left-right", "--count", f"HEAD...{ref}").stdout.split()
    return int(a), int(b)


def _pending_files(root: Path, ref: str) -> tuple[list[str], list[str]]:
    """(rastreados que diferem do remoto, novos não rastreados e não ignorados)."""
    tracked = _lines(_git(root, "diff", "--name-only", ref))
    untracked = _lines(_git(root, "ls-files", "--others", "--exclude-standard"))
    return tracked, untracked


def _version(root: Path) -> str:
    try:
        m = re.search(r'__version__\s*=\s*"([^"]+)"', (root / "brainlib" / "__init__.py").read_text(encoding="utf-8"))
    except OSError:
        return "?"
    return m.group(1) if m else "?"


# ── semeadura (compartilhada com `brain init`) ──────────────────────────────
def seed_template(inst: config.Instance) -> list[str]:
    """Copia de template/ para o vault o que ainda não existe. Nunca sobrescreve."""
    tpl = inst.root / "template"
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
           remote: str | None = None, branch: str | None = None) -> dict:
    root = inst.root
    remote, branch, ref = _prepare(inst, remote, branch)
    ahead, behind = _ahead_behind(root, ref)
    tracked, untracked = _pending_files(root, ref)
    res: dict = {"remote": remote, "branch": branch, "ahead": ahead, "behind": behind, "checked_only": check,
                 "version_before": _version(root), "incoming": [], "areas": {}, "seeded": [],
                 "template_diverged": [], "local_pending": len(tracked) + len(untracked)}
    if behind:
        res["incoming"] = [ln for ln in _lines(_git(root, "log", "--format=%h %s", f"HEAD..{ref}"))]
        files = _lines(_git(root, "diff", "--name-only", f"HEAD...{ref}"))
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
        mode = ["--rebase"] if ahead else ["--ff-only"]
        r = _git(root, "pull", *mode, "--autostash", remote, branch, check=False)
        if r.returncode != 0:
            raise util.BrainError("pull falhou — nada do vault foi tocado; edições locais ficam no `git stash list` "
                                  f"se o autostash não reaplicou:\n{(r.stderr or r.stdout).strip()}", 4)
        res["updated"] = True
        res["version_after"] = _version(root)
        incoming_tpl = [f for f in res.get("incoming_files", []) if f.startswith("template/")]
        res["seeded"] = seed_template(inst)
        res["template_diverged"] = [f"vault/{f[len('template/'):]}" for f in incoming_tpl
                                    if (inst.vault / f[len("template/"):]).exists()
                                    and (inst.vault / f[len("template/"):]).read_bytes() != (root / f).read_bytes()]
        try:
            d = subprocess.run([sys.executable, str(root / "brain"), "doctor"], cwd=root, capture_output=True,
                               text=True, timeout=GIT_TIMEOUT_S)
            doc_out, doc_ok = d.stdout + d.stderr, d.returncode == 0
        except subprocess.TimeoutExpired:
            doc_out, doc_ok = f"doctor não respondeu em {GIT_TIMEOUT_S}s", False
        res["hook"] = hook(inst, "install")
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
        for ln in res["incoming"][:15]:
            print(f"  · {ln}")
        if len(res["incoming"]) > 15:
            print(f"  … e mais {len(res['incoming']) - 15}")
        print("  arquivos por área: " + " · ".join(f"{k} {v}" for k, v in sorted(res["areas"].items())))
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
    add("dono", cfg["owner"]["id"])
    add("dono", cfg["owner"]["name"])
    for x in cfg.get("outbound", {}).get("allow", []):
        add("destinatário", str(x).lstrip("#@"))
    for x in cfg.get("publish", {}).get("destinations", []):
        add("destino", str(x).split(":", 1)[-1].lstrip("#@"))
    emails: list[str] = []
    try:
        from .core import Brain
        for p in Brain(inst).state.people.values():
            for n in p.names():
                add("pessoa", n)
            if p.email:
                emails.append(p.email)
    except Exception:  # ledger ausente/corrompido: segue com o que a config deu
        pass
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


def _scan_line(text: str, term_res: list[tuple[str, re.Pattern]], home: str) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    plain = _DEMO_TOKEN_RE.sub(" ", text)          # o sufixo -demo marca dado fictício: não é vazamento do ledger
    for kind, rx in term_res:
        if rx.search(plain):
            hits.append((f"dado pessoal ({kind})", rx.pattern))
    for m in _HOME_RE.finditer(text):
        who = m.group(2).lower()
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


MAX_BLOB_BYTES = 50 * 2**20          # binário maior que isto não é varrido (o framework não carrega blobs assim)
_PRINTABLE_RUN = re.compile(rb"[\x20-\x7e\t\x80-\xff]{6,}")   # como o `strings`: só trechos legíveis de um binário
_C_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def _unquote(path: str) -> str:
    """Caminho como o git imprime: `"b/caf\\303\\251.md"` (aspas C, octal UTF-8) → `b/café.md`."""
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
        out += c.encode("utf-8")
        i += 1
    return out.decode("utf-8", errors="replace")


def _strip_side(path: str, side: str) -> str:
    path = _unquote(path.strip())
    return path[2:] if path.startswith(f"{side}/") else ("" if path == "/dev/null" else path)


def _binary_lines(data: bytes) -> list[str]:
    return [m.group(0).decode("utf-8", errors="replace") for m in _PRINTABLE_RUN.finditer(data)]


def _blob(root: Path, sha: str, path: str) -> bytes | None:
    """Conteúdo de `path` no commit `sha` (ou da working tree, sem sha) — para varrer binários."""
    try:
        if not sha:
            p = root / path
            return p.read_bytes() if p.is_file() and p.stat().st_size <= MAX_BLOB_BYTES else None
        size = subprocess.run(["git", "-C", str(root), "cat-file", "-s", f"{sha}:{path}"],
                              capture_output=True, text=True, timeout=60)
        if size.returncode != 0 or int(size.stdout.strip() or 0) > MAX_BLOB_BYTES:
            return None
        r = subprocess.run(["git", "-C", str(root), "cat-file", "blob", f"{sha}:{path}"], capture_output=True, timeout=120)
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

    for ln in text.splitlines():
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


def scan(inst: config.Instance, ref: str | None, committed: bool = False,
         revsets: list[list[str]] | None = None) -> list[dict]:
    """Procura dado pessoal/segredo no que subiria: linhas adicionadas, nomes de arquivo, binários,
    arquivos novos e mensagens de commit.

    committed=True olha só commits (o que um push envia); False inclui working tree e arquivos novos.
    `revsets` (só com committed): os conjuntos de commits que o push envia, um por ref atualizada
    (ex.: [["<sha local>", "^<sha remoto>"]]) — é o que o hook pre-push recebe do git.
    """
    root = inst.root
    term_res = [(kind, re.compile(r"(?<![\w])" + re.escape(t) + r"(?![\w])", re.I)) for t, kind in _leak_terms(inst)]
    home = str(Path.home())
    findings: list[dict] = []
    seen: set[tuple[str, int, str]] = set()

    def check(file: str, line: int, text: str) -> None:
        for rule, _ in _scan_line(text, term_res, home):
            if (file, line, rule) not in seen:
                seen.add((file, line, rule))
                findings.append({"file": file, "line": line, "rule": rule, "text": text.strip()[:110]})

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
            diff = _git(root, *q, "log", "-p", "-U0", "--no-color", "--cc", "--reverse", "--format=%x01%H", *revs)
            _scan_diff(root, diff.stdout, check)
            for f in _lines(_git(root, *q, "log", "--name-only", "--format=", *revs)):
                if _private_path(f):
                    key = (f, 0, "arquivo do dono no histórico")
                    if key not in seen:
                        seen.add(key)
                        findings.append({"file": f, "line": 0, "rule": key[2],
                                         "text": "vault/ e config pessoal nunca vão ao repo (git rm --cached + reescrever o commit)"})
    else:
        _scan_diff(root, _git(root, *q, "diff", "-U0", "--no-color", ref or EMPTY_TREE).stdout, check)
    for f in ([] if committed else _lines(_git(root, *q, "ls-files", "--others", "--exclude-standard"))):
        p = root / f
        check(f, 0, f)
        try:
            if not p.is_file() or p.stat().st_size > MAX_BLOB_BYTES:
                continue
            raw = p.read_bytes()
        except OSError:
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
            if "noreply@" not in text:
                check("(mensagem de commit)", n, text)
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


def pre_push_scan(inst: config.Instance, remote: str, stdin_text: str) -> dict:
    """O que o hook pre-push roda: varre exatamente os commits que este push envia (qualquer branch,
    tag, HEAD solto ou ref nova), sem depender do branch atual."""
    revsets = push_revsets(inst, remote, stdin_text)
    tracked = [f for f in _lines(_git(inst.root, "ls-files")) if _private_path(f)]
    findings = [{"file": f, "line": 0, "rule": "arquivo do dono rastreado pelo git",
                 "text": "git rm --cached antes de enviar"} for f in tracked]
    findings += scan(inst, None, committed=True, revsets=revsets) if revsets else []
    return {"remote": remote, "branch": "(pre-push)", "ref": None, "ahead": 0, "behind": 0, "changed": [], "new": [],
            "local_scripts": [], "committed_only": True, "revsets": revsets, "findings": findings}


def _local_scripts(root: Path) -> list[str]:
    d = root / "scripts" / "local"
    return sorted(str(p.relative_to(root)) for p in d.rglob("*") if p.is_file()) if d.exists() else []


def _ref_offline(inst: config.Instance, remote: str | None, branch: str | None) -> tuple[str, str, str | None]:
    """Como `_prepare`, mas sem rede: usa a referência remota que já existe localmente (ou None)."""
    remote, branch, ref = _prepare(inst, remote, branch, fetch=False, require_ref=False)
    return remote, branch, ref


def upstream_scan(inst: config.Instance, remote: str | None = None, branch: str | None = None,
                  committed: bool = False, fetch: bool = False) -> dict:
    if fetch:
        remote, branch, ref = _prepare(inst, remote, branch)
    else:
        remote, branch, ref = _ref_offline(inst, remote, branch)
    ahead, behind = _ahead_behind(inst.root, ref) if ref else (0, 0)
    tracked, untracked = _pending_files(inst.root, ref) if ref else ([], [])
    return {"remote": remote, "branch": branch, "ref": ref, "ahead": ahead, "behind": behind,
            "changed": tracked, "new": untracked, "local_scripts": _local_scripts(inst.root),
            "committed_only": committed, "findings": scan(inst, ref, committed=committed)}


def _print_findings(findings: list[dict]) -> None:
    for f in findings[:25]:
        print(f"  ✗ {f['file']}:{f['line']} — {f['rule']}: {f['text']}")
    if len(findings) > 25:
        print(f"  … e mais {len(findings) - 25}")


def _print_scan(st: dict) -> None:
    if "revsets" in st:
        print(f"pre-push → {st['remote']}: {len(st['revsets'])} ref(s) com commits a varrer")
    else:
        ref = st["ref"] or f"{st['remote']}/{st['branch']} (ainda sem referência local)"
        print(f"{ref}: {st['ahead']} commit(s) à frente · {st['behind']} atrás (sem rede; `--fetch` atualiza)")
    if not st["committed_only"] and (st["changed"] or st["new"]):
        print(f"não enviados: {len(st['changed'])} alterado(s) · {len(st['new'])} novo(s)")
        for f in st["changed"][:30]:
            print(f"  M {f}")
        for f in st["new"][:30]:
            print(f"  ? {f}")
    if st["local_scripts"]:
        print("inovação local (scripts/local/ — ignorada pelo git; gradue movendo para scripts/ ou brainlib/):")
        for f in st["local_scripts"][:10]:
            print(f"  · {f}")
    if st["findings"]:
        print(f"✗ {len(st['findings'])} achado(s) de dado pessoal/segredo — não envie ao repo público até limpar:")
        _print_findings(st["findings"])
    elif st["ahead"] or st["changed"] or st["new"]:
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


def _hook_path(root: Path) -> Path:
    rel = _git(root, "rev-parse", "--git-path", "hooks/pre-push").stdout.strip()
    return (root / rel) if not os.path.isabs(rel) else Path(rel)


def hook_state(inst: config.Instance) -> str:
    """'instalado' | 'ausente' | 'de-outro' (já existe um pre-push que não é nosso) | 'sem-git'."""
    if not (inst.root / ".git").exists():
        return "sem-git"
    path = _hook_path(inst.root)
    if not path.exists():
        return "ausente"
    return "instalado" if HOOK_MARK in path.read_text(encoding="utf-8", errors="replace") else "de-outro"


def hook(inst: config.Instance, action: str) -> str:
    state = hook_state(inst)
    if state == "sem-git":
        return state
    path = _hook_path(inst.root)
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
    state = hook_state(inst)
    if state == "ausente":
        out.append({"level": "warn", "title": "hook pre-push", "detail": "não instalado — `brain upstream hook install`"})
    elif state == "de-outro":
        out.append({"level": "warn", "title": "hook pre-push",
                    "detail": "já existe um pre-push que não é do brain; a varredura não roda no push"})
    return out


# ── entrada do CLI ──────────────────────────────────────────────────────────
def cli_update(args, _b) -> None:
    res = update(config.load(), check=args.check, rebase=args.rebase, remote=args.remote, branch=args.branch)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
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
    if args.committed and pre_push is not None:          # chamado pelo hook: refs do push no stdin
        st = pre_push_scan(inst, args.remote or pre_push or "origin", sys.stdin.read())
    else:
        st = upstream_scan(inst, args.remote, args.branch, committed=args.committed, fetch=args.fetch)
    if args.json:
        print(json.dumps(st, ensure_ascii=False, indent=2))
    else:
        _print_scan(st)
    if st["findings"]:
        raise SystemExit(util.BrainError("", 4).code)
