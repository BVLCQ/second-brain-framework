"""Ícone clicável do painel: `brain app install` cria um app de dois cliques que faz `brain render --open`.

macOS → `~/Applications/Segundo Cérebro.app` (aparece no Launchpad/Spotlight e arrasta para o Dock);
Linux → entrada `.desktop` no menu de aplicativos. O ícone é desenhado aqui mesmo (PNG em Python puro, `.icns`
montado à mão): sem dependência, sem binário no repo.

Escreve só no diretório de destino (nada no vault, nada no ledger, nada na rede) e só apaga o que ele próprio criou
— o marcador vive no Info.plist / `.desktop`. O launcher guarda o caminho da instância (`BRAIN_HOME`) e do
framework; se você mover a pasta, reinstale.
"""
from __future__ import annotations

import functools
import math
import os
import plistlib
import shlex
import shutil
import struct
import sys
import zlib
from pathlib import Path

from . import __version__, util

MARK = "segundo-cerebro-launcher"                 # marcador: só mexemos no que carrega isto
BUNDLE_ID = "app.segundo-cerebro.painel"
DEFAULT_NAME = "Segundo Cérebro"
SUPPORTED = ("darwin", "linux")


# ── ícone: PNG + ICNS em Python puro ─────────────────────────────────────────
def _sd_round_rect(px: float, py: float, cx: float, cy: float, hw: float, hh: float, r: float) -> float:
    qx, qy = abs(px - cx) - (hw - r), abs(py - cy) - (hh - r)
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r


def _cover(d: float) -> float:
    """Cobertura de pixel (anti-alias de 1px) a partir da distância com sinal."""
    return min(1.0, max(0.0, 0.5 - d))


@functools.lru_cache(maxsize=8)
def render_png(size: int) -> bytes:
    """O ícone: placa arredondada em degradê índigo com a grade 2×2 de um painel (o primeiro bloco em destaque)."""
    top, bottom = (91, 141, 239), (59, 42, 158)
    c = size / 2
    half = size * 0.45                            # a placa ocupa 90% — margem de respiro do macOS
    body_r = half * 0.46
    pad = half * 0.34                             # miolo onde mora a grade
    gap = half * 0.12
    tile = (2 * (half - pad) - gap) / 2
    t_r = tile * 0.26
    centers = [(c - (tile + gap) / 2, c - (tile + gap) / 2, 1.0), (c + (tile + gap) / 2, c - (tile + gap) / 2, 0.55),
               (c - (tile + gap) / 2, c + (tile + gap) / 2, 0.55), (c + (tile + gap) / 2, c + (tile + gap) / 2, 0.55)]
    raw = bytearray()
    for y in range(size):
        raw.append(0)                             # filtro "nenhum" por linha
        py = y + 0.5
        k = min(1.0, max(0.0, (py - (c - half)) / (2 * half)))
        base = tuple(top[i] + (bottom[i] - top[i]) * k for i in range(3))
        for x in range(size):
            px = x + 0.5
            a = _cover(_sd_round_rect(px, py, c, c, half, half, body_r))
            if a <= 0.0:
                raw += b"\x00\x00\x00\x00"
                continue
            rgb = base
            for tx, ty, op in centers:
                w = _cover(_sd_round_rect(px, py, tx, ty, tile / 2, tile / 2, t_r)) * op
                if w > 0.0:
                    rgb = tuple(rgb[i] + (255 - rgb[i]) * w for i in range(3))
            raw += bytes((round(rgb[0]), round(rgb[1]), round(rgb[2]), round(a * 255)))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


ICNS_TYPES = ((b"ic07", 128), (b"ic08", 256), (b"ic09", 512))      # PNG embutido; 512 cobre o Dock em tela retina


def build_icns(pngs: dict[int, bytes] | None = None) -> bytes:
    pngs = pngs or {size: render_png(size) for _t, size in ICNS_TYPES}
    body = b"".join(t + struct.pack(">I", 8 + len(pngs[size])) + pngs[size] for t, size in ICNS_TYPES)
    return b"icns" + struct.pack(">I", 8 + len(body)) + body


# ── o script que roda no clique ──────────────────────────────────────────────
def launcher_script(root: Path, framework: Path, logs: Path, python: str, *, platform: str,
                    extra_env: dict[str, str] | None = None) -> str:
    q = shlex.quote
    env_lines = "".join(f"export {k}={q(v)}\n" for k, v in (extra_env or {}).items())
    if platform == "darwin":
        notify = ('osascript - "$LOG" >/dev/null 2>&1 <<\'OSA\'\n'
                  'on run argv\n'
                  '  display dialog "Não consegui abrir o painel do Segundo Cérebro." & return & return & '
                  '"Detalhes em:" & return & (item 1 of argv) buttons {"OK"} default button "OK" with icon caution\n'
                  'end run\n'
                  'OSA\n')
    else:
        notify = ('command -v notify-send >/dev/null 2>&1 && '
                  'notify-send "Segundo Cérebro" "Não consegui abrir o painel. Detalhes em: $LOG"\n')
    return (
        "#!/bin/sh\n"
        f"# {MARK} — gerado por `brain app install`; não edite (reinstale para atualizar).\n"
        '# Clique duplo = `brain render --open`: regenera as views e abre o painel (sobe a ponte se preciso).\n'
        'export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"\n'
        'export LANG="${LANG:-en_US.UTF-8}" PYTHONIOENCODING=utf-8\n'
        f"export BRAIN_HOME={q(str(root))}\n"
        f"{env_lines}"
        f"LOG={q(str(logs / 'app.log'))}\n"
        f"PY={q(python)}\n"
        '[ -x "$PY" ] || PY=python3\n'
        'mkdir -p "$(dirname "$LOG")"\n'
        f'{{ cd "$BRAIN_HOME" && "$PY" {q(str(framework / "brain"))} render --open; }} >"$LOG" 2>&1 && exit 0\n'
        f"{notify}"
        "exit 1\n")


# ── instalação ───────────────────────────────────────────────────────────────
def _platform() -> str:
    if sys.platform not in SUPPORTED:
        raise util.BrainError("o ícone do painel existe só para macOS e Linux — nos demais, use `brain render --open`")
    return sys.platform


def default_dest(platform: str | None = None) -> Path:
    if (platform or _platform()) == "darwin":
        return Path.home() / "Applications"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"


def _safe_name(name: str) -> str:
    n = name.strip()
    if not n or any(ch in n for ch in "/\\:\0\n") or n.startswith("."):
        raise util.BrainError(f"nome inválido para o app: {name!r}")
    return n


def _target(dest: Path, name: str, platform: str) -> Path:
    return dest / (f"{name}.app" if platform == "darwin" else f"{name.lower().replace(' ', '-')}.desktop")


def owner_of(target: Path) -> str | None:
    """Se `target` é um launcher nosso, devolve a instância (BRAIN_HOME) para a qual aponta ('' se desconhecida);
    senão None — e quem chama não toca no que não é nosso."""
    try:
        if target.is_dir():
            info = plistlib.loads((target / "Contents" / "Info.plist").read_bytes())
            return str(info.get("SegundoCerebroHome") or "") if info.get("CFBundleIdentifier") == BUNDLE_ID else None
        if target.is_file():
            text = target.read_text(encoding="utf-8")
            if f"X-{MARK}=true" not in text:
                return None
            home = next((ln.split("=", 1)[1] for ln in text.splitlines() if ln.startswith("X-SegundoCerebroHome=")), "")
            return home
    except (OSError, plistlib.InvalidFileException, UnicodeDecodeError, KeyError):
        return None
    return None


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _swap(tmp: Path, target: Path) -> None:
    _remove(target)
    tmp.rename(target)


def install(inst, dest: Path | None = None, name: str = DEFAULT_NAME, *, framework: Path | None = None,
            python: str | None = None, platform: str | None = None) -> Path:
    """Cria (ou recria) o launcher e devolve o caminho. Recusa sobrescrever algo que não foi feito por nós."""
    platform = platform or _platform()
    name = _safe_name(name)
    if framework is None:
        from .tui.bridge import FRAMEWORK
        framework = FRAMEWORK
    dest = Path(dest).expanduser() if dest else default_dest(platform)
    dest.mkdir(parents=True, exist_ok=True)
    target = _target(dest, name, platform)
    if (target.exists() or target.is_symlink()) and owner_of(target) is None:
        raise util.BrainError(f"{target} já existe e não é um launcher do Segundo Cérebro — escolha outro --name ou --dest")
    extra = {k: os.environ[k] for k in ("BRAIN_VAULT", "BRAIN_CONFIG") if os.environ.get(k)}
    script = launcher_script(inst.root, framework, inst.logs, python or sys.executable, platform=platform,
                             extra_env=extra)
    tmp = dest / f".{target.name}.tmp"
    _remove(tmp)
    pngs = {size: render_png(size) for _t, size in ICNS_TYPES}
    if platform == "darwin":
        macos, res = tmp / "Contents" / "MacOS", tmp / "Contents" / "Resources"
        macos.mkdir(parents=True)
        res.mkdir(parents=True)
        (macos / "launcher").write_text(script, encoding="utf-8")
        (macos / "launcher").chmod(0o755)
        (res / "AppIcon.icns").write_bytes(build_icns(pngs))
        (tmp / "Contents" / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleName": name, "CFBundleDisplayName": name, "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleExecutable": "launcher", "CFBundleIconFile": "AppIcon", "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": __version__, "CFBundleVersion": __version__,
            "LSMinimumSystemVersion": "11.0", "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.productivity",
            "SegundoCerebroHome": str(inst.root),
        }))
        _swap(tmp, target)
        target.touch()                                  # o Finder renova o cache do ícone
    else:
        assets = dest.parent / "segundo-cerebro"
        assets.mkdir(parents=True, exist_ok=True)
        (assets / "launcher.sh").write_text(script, encoding="utf-8")
        (assets / "launcher.sh").chmod(0o755)
        (assets / "icon.png").write_bytes(pngs[256])
        exec_path = str(assets / "launcher.sh").replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
        tmp.write_text(
            "[Desktop Entry]\nType=Application\nVersion=1.0\n"
            f"Name={name}\nComment=Abre o painel do Segundo Cérebro\n"
            f'Exec="{exec_path}"\nIcon={assets / "icon.png"}\nTerminal=false\n'
            f"Categories=Office;\nX-{MARK}=true\nX-SegundoCerebroHome={inst.root}\n", encoding="utf-8")
        tmp.chmod(0o755)
        _swap(tmp, target)
    return target


def uninstall(dest: Path | None = None, name: str = DEFAULT_NAME, *, platform: str | None = None) -> Path | None:
    """Remove o launcher (só se for nosso). Devolve o caminho removido, ou None se não havia."""
    platform = platform or _platform()
    target = _target(Path(dest).expanduser() if dest else default_dest(platform), _safe_name(name), platform)
    if not (target.exists() or target.is_symlink()):
        return None
    if owner_of(target) is None:
        raise util.BrainError(f"{target} não é um launcher do Segundo Cérebro — não vou apagar")
    _remove(target)
    if platform != "darwin":
        assets = target.parent.parent / "segundo-cerebro"
        for f in ("launcher.sh", "icon.png"):
            (assets / f).unlink(missing_ok=True)
        try:
            assets.rmdir()
        except OSError:
            pass
    return target


def is_installed(root: Path, dest: Path | None = None, name: str = DEFAULT_NAME) -> bool:
    """O launcher existe e aponta para ESTA instância?"""
    try:
        platform = _platform()
    except util.BrainError:
        return False
    owner = owner_of(_target(Path(dest).expanduser() if dest else default_dest(platform), name, platform))
    return owner is not None and Path(owner or "/nonexistent").resolve() == Path(root).resolve()


# ── CLI ──────────────────────────────────────────────────────────────────────
def cli(args) -> None:
    from . import config
    dest = Path(args.dest) if args.dest else None
    if args.acmd == "install":
        inst = config.load()
        target = install(inst, dest, args.name)
        print(f"✓ ícone criado: {target}")
        print(f"  aponta para: {inst.root}")
        if sys.platform == "darwin":
            print("  abra pelo Launchpad/Spotlight ('" + args.name + "') ou arraste para o Dock; mudou a pasta do Brain? reinstale.")
        else:
            print("  procure pelo nome no menu de aplicativos; mudou a pasta do Brain? reinstale.")
        print(f"  log da última abertura: {inst.logs / 'app.log'}")
    else:
        removed = uninstall(dest, args.name)
        print(f"✓ ícone removido: {removed}" if removed else "nenhum ícone instalado nesse destino")
