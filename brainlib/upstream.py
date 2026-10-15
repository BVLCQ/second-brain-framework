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
               "yahoo.com", "yahoo.com.br", "proton.me", "protonmail.com", "uol.com.br", "bol.com.br"}
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
def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    except FileNotFoundError as e:
        raise util.BrainError("git não encontrado no PATH") from e
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
        r = _git(root, "fetch", remote, branch, check=False)
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
        d = subprocess.run([sys.executable, str(root / "brain"), "doctor"], cwd=root, capture_output=True, text=True)
        res["hook"] = hook(inst, "install")
        res["doctor"] = [ln for ln in (d.stdout + d.stderr).splitlines() if ln.strip()]
        res["doctor_ok"] = d.returncode == 0
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


def _scan_line(text: str, term_res: list[tuple[str, re.Pattern]], home: str) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for kind, rx in term_res:
        if rx.search(text):
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


def scan(inst: config.Instance, ref: str | None, committed: bool = False) -> list[dict]:
    """Procura dado pessoal/segredo no que subiria: linhas adicionadas, arquivos novos e mensagens de commit.

    committed=True olha só commits (o que um push envia); False inclui working tree e arquivos novos.
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

    # Em modo committed olha commit a commit: o histórico inteiro vai a público, não só o diff líquido
    # (um dado removido num commit posterior continuaria legível no commit anterior).
    if committed:
        diff = _git(root, "log", "-p", "-U0", "--no-color", "--no-merges", "--reverse", "--format=%x01%h",
                    f"{ref}..HEAD" if ref else "HEAD")
    else:
        diff = _git(root, "diff", "-U0", "--no-color", ref or EMPTY_TREE)
    cur, lineno, sha = "", 0, ""
    for ln in diff.stdout.splitlines():
        if ln.startswith("\x01"):
            sha = ln[1:]
        elif ln.startswith("+++ "):
            cur = (ln[6:] if ln.startswith("+++ b/") else "")
            cur = f"{cur} (commit {sha})" if cur and sha else cur
        elif ln.startswith("@@"):
            m = re.search(r"\+(\d+)", ln)
            lineno = int(m.group(1)) if m else 0
        elif ln.startswith("+") and cur:
            check(cur, lineno, ln[1:])
            lineno += 1
    for f in ([] if committed else _lines(_git(root, "ls-files", "--others", "--exclude-standard"))):
        p = root / f
        try:
            if not p.is_file() or p.stat().st_size > MAX_SCAN_BYTES:
                continue
            body = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for n, text in enumerate(body.splitlines(), start=1):
            check(f, n, text)
    rng = f"{ref}..HEAD" if ref else "HEAD"
    for n, text in enumerate(_git(root, "log", "--format=%B", rng).stdout.splitlines(), start=1):
        if "noreply@" not in text:
            check("(mensagem de commit)", n, text)
    return findings


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
HOOK_BODY = f"""#!/bin/sh
{HOOK_MARK} — instalado por `brain update`/`brain init`; `brain upstream hook remove` tira; `git push --no-verify` ignora
root="$(git rev-parse --show-toplevel)" || exit 0
"$root/brain" upstream scan --committed
rc=$?
if [ "$rc" -eq 4 ]; then
  echo "push bloqueado: dado pessoal/segredo nos commits (acima). Limpe e commite de novo." >&2
  exit 1
fi
[ "$rc" -ne 0 ] && echo "aviso: a varredura do brain falhou (código $rc); push liberado." >&2
exit 0
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
    st = upstream_scan(inst, args.remote, args.branch, committed=args.committed, fetch=args.fetch)
    if args.json:
        print(json.dumps(st, ensure_ascii=False, indent=2))
    else:
        _print_scan(st)
    if st["findings"]:
        raise SystemExit(util.BrainError("", 4).code)
