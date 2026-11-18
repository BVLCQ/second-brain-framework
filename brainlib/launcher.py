"""O app **Brain**: `brain app install` cria um app de dois cliques que faz `brain open` (o onboarding enquanto a
instância não está configurada; depois, o painel).

macOS → `/Applications/Brain.app` (ou `~/Applications` sem permissão; aparece no Launchpad/Spotlight e arrasta para o Dock);
Linux → entrada `.desktop` no menu de aplicativos. Ícone: `assets/icon/brain.svg` (o "Sinapse", traço grosso para ler no
Dock; até 32 px usa a marca simplificada `brain-mark.svg`; a arte detalhada `brain-hero.svg` é só da boas-vindas). No macOS o `.icns` é
montado na instalação com as ferramentas do sistema (`sips` rasteriza o SVG, `iconutil` empacota); sem elas, cai no
PNG de 512 px (`assets/icon/brain-512.png`, também o ícone do Linux) embutido num `.icns` montado à mão.

Escreve só no diretório de destino (nada no vault, nada no ledger, nada na rede) e só apaga o que ele próprio criou
— o marcador vive no Info.plist / `.desktop`. O launcher guarda o caminho da instância (`BRAIN_HOME`) e do
framework; se você mover a pasta, reinstale.
"""
from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__, util

MARK = "segundo-cerebro-launcher"                 # marcador: só mexemos no que carrega isto
BUNDLE_ID = "app.segundo-cerebro.painel"
DEFAULT_NAME = "Brain"
LEGACY_NAMES = ("Segundo Cérebro",)              # nome antigo do app: a reinstalação remove a cópia que nós criamos
ICON_DIR = Path(__file__).resolve().parent / "assets" / "icon"
ICON_SVG = ICON_DIR / "brain.svg"                 # ícone do app (Dock, Aplicativos, marca do onboarding)
ICON_MARK = ICON_DIR / "brain-mark.svg"           # ≤ 32 px: 16/32 do .icns e favicon do onboarding (a barra lateral do painel usa o brain.svg, igual ao Dock)
ICON_HERO = ICON_DIR / "brain-hero.svg"           # arte detalhada: só a ilustração grande da boas-vindas
ICON_PNG = ICON_DIR / "brain-512.png"
SUPPORTED = ("darwin", "linux")


# ── ícone ────────────────────────────────────────────────────────────────────
ICNS_TYPES = ((b"ic07", 128), (b"ic08", 256), (b"ic09", 512))      # PNG embutido; 512 cobre o Dock em tela retina
ICONSET = ((16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2), (256, 1), (256, 2), (512, 1), (512, 2))


def icon_png() -> bytes:
    """O ícone em PNG 512×512 (Linux e reserva do macOS)."""
    return ICON_PNG.read_bytes()


def build_icns(pngs: dict[int, bytes]) -> bytes:
    """Contêiner .icns montado à mão com os PNGs dados (por tamanho); tamanhos ausentes ficam de fora."""
    body = b"".join(t + struct.pack(">I", 8 + len(pngs[size])) + pngs[size] for t, size in ICNS_TYPES if size in pngs)
    return b"icns" + struct.pack(">I", 8 + len(body)) + body


def _icns_from_svg(svg: Path, small: Path | None = None) -> bytes | None:
    """`.icns` completo (16→1024) a partir do SVG com `sips` + `iconutil` (vêm com o macOS). Até 32 px usa `small`
    (a marca simplificada), se dada. None se não der."""
    if not (shutil.which("sips") and shutil.which("iconutil")):
        return None
    with tempfile.TemporaryDirectory() as td:
        iconset = Path(td) / "Brain.iconset"
        iconset.mkdir()
        try:
            for size, scale in ICONSET:
                px = size * scale
                out = iconset / (f"icon_{size}x{size}" + ("@2x" if scale == 2 else "") + ".png")
                src = small if (small is not None and px <= 32) else svg
                subprocess.run(["sips", "-s", "format", "png", "-z", str(px), str(px), str(src), "--out", str(out)],
                               check=True, capture_output=True, timeout=60)
            icns = Path(td) / "Brain.icns"
            subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)],
                           check=True, capture_output=True, timeout=60)
            return icns.read_bytes()
        except (OSError, subprocess.SubprocessError):
            return None


def icon_icns() -> bytes:
    return _icns_from_svg(ICON_SVG, ICON_MARK) or build_icns({512: icon_png()})


# ── o script que roda no clique ──────────────────────────────────────────────
def launcher_script(root: Path, framework: Path, logs: Path, python: str, *, platform: str,
                    extra_env: dict[str, str] | None = None) -> str:
    q = shlex.quote
    env_lines = "".join(f"export {k}={q(v)}\n" for k, v in (extra_env or {}).items())
    if platform == "darwin":
        notify = ('osascript - "$LOG" >/dev/null 2>&1 <<\'OSA\'\n'
                  'on run argv\n'
                  '  display dialog "Não consegui abrir o Brain." & return & return & '
                  '"Detalhes em:" & return & (item 1 of argv) buttons {"OK"} default button "OK" with icon caution\n'
                  'end run\n'
                  'OSA\n')
    else:
        notify = ('command -v notify-send >/dev/null 2>&1 && '
                  'notify-send "Brain" "Não consegui abrir o Brain. Detalhes em: $LOG"\n')
    return (
        "#!/bin/sh\n"
        f"# {MARK} — gerado por `brain app install`; não edite (reinstale para atualizar).\n"
        '# Clique duplo = `brain open`: a configuração guiada na primeira vez; depois regenera as views e abre o painel.\n'
        'export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"\n'
        'export LANG="${LANG:-en_US.UTF-8}" PYTHONIOENCODING=utf-8\n'
        f"export BRAIN_HOME={q(str(root))}\n"
        f"{env_lines}"
        f"LOG={q(str(logs / 'app.log'))}\n"
        f"PY={q(python)}\n"
        '[ -x "$PY" ] || PY=python3\n'
        'mkdir -p "$(dirname "$LOG")"\n'
        f'{{ cd "$BRAIN_HOME" && "$PY" {q(str(framework / "brain"))} open; }} >"$LOG" 2>&1 && exit 0\n'
        f"{notify}"
        "exit 1\n")


# ── instalação ───────────────────────────────────────────────────────────────
def _platform() -> str:
    if sys.platform not in SUPPORTED:
        raise util.BrainError("o ícone do painel existe só para macOS e Linux — nos demais, use `brain open`")
    return sys.platform


def default_dest(platform: str | None = None) -> Path:
    """Onde o launcher mora por padrão. macOS: a pasta Aplicativos do sistema (é onde o usuário procura; contas de
    administrador escrevem lá sem senha) e, se não der, a do usuário (~/Applications). Linux: o menu de aplicativos."""
    if (platform or _platform()) == "darwin":
        system = Path("/Applications")
        return system if os.access(system, os.W_OK) else Path.home() / "Applications"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"


def _search_dests(platform: str) -> list[Path]:
    """Onde procurar um launcher nosso quando não há --dest: o padrão e, se o padrão é /Applications, também o
    ~/Applications onde versões anteriores instalavam."""
    d = default_dest(platform)
    return [d, Path.home() / "Applications"] if platform == "darwin" and d == Path("/Applications") else [d]


def _find_ours(name: str, platform: str) -> list[Path]:
    return [t for t in (_target(d, name, platform) for d in _search_dests(platform))
            if (t.exists() or t.is_symlink()) and owner_of(t) is not None]


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
            python: str | None = None, platform: str | None = None,
            replace_other: bool | None = None) -> Path:
    """Cria (ou recria) o launcher e devolve o caminho. Recusa sobrescrever algo que não foi feito por nós."""
    platform = platform or _platform()
    name = _safe_name(name)
    if framework is None:
        from .tui.bridge import FRAMEWORK
        framework = FRAMEWORK
    default = dest is None
    dest = Path(dest).expanduser() if dest else default_dest(platform)
    dest.mkdir(parents=True, exist_ok=True)
    target = _target(dest, name, platform)
    owner = owner_of(target)
    if (target.exists() or target.is_symlink()) and owner is None:
        raise util.BrainError(f"{target} já existe e não é um launcher do Brain — escolha outro --name ou --dest")
    if owner and Path(owner).resolve() != Path(inst.root).resolve():
        if replace_other is True:
            print(f"↻ o app Brain apontava para {owner} — agora aponta para esta instância")
        else:
            print(f"⚠ o app Brain já abre outra instância ({owner}) — mantido; rode `brain app install` num terminal para trocar")
            return target
    extra = {k: os.environ[k] for k in ("BRAIN_VAULT", "BRAIN_CONFIG") if os.environ.get(k)}
    script = launcher_script(inst.root, framework, inst.logs, python or sys.executable, platform=platform,
                             extra_env=extra)
    tmp = dest / f".{target.name}.tmp"
    _remove(tmp)
    if platform == "darwin":
        macos, res = tmp / "Contents" / "MacOS", tmp / "Contents" / "Resources"
        macos.mkdir(parents=True)
        res.mkdir(parents=True)
        (macos / "launcher").write_text(script, encoding="utf-8")
        (macos / "launcher").chmod(0o755)
        (res / "AppIcon.icns").write_bytes(icon_icns())
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
        (assets / "icon.png").write_bytes(icon_png())
        exec_path = str(assets / "launcher.sh").replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
        tmp.write_text(
            "[Desktop Entry]\nType=Application\nVersion=1.0\n"
            f"Name={name}\nComment=Abre o Brain\n"
            f'Exec="{exec_path}"\nIcon={assets / "icon.png"}\nTerminal=false\n'
            f"Categories=Office;\nX-{MARK}=true\nX-SegundoCerebroHome={inst.root}\n", encoding="utf-8")
        tmp.chmod(0o755)
        _swap(tmp, target)
    if default:                  # mudou de ~/Applications para /Applications, ou do nome antigo: não deixa cópia velha
        for old in [t for n in (name, *LEGACY_NAMES) for t in _find_ours(n, platform)]:
            if old != target:
                _remove(old)
    return target


def uninstall(dest: Path | None = None, name: str = DEFAULT_NAME, *, platform: str | None = None) -> Path | None:
    """Remove o launcher (só se for nosso). Devolve o caminho removido, ou None se não havia."""
    platform = platform or _platform()
    name = _safe_name(name)
    if dest:
        target = _target(Path(dest).expanduser(), name, platform)
    else:                                                # sem --dest: acha o nosso onde estiver (/Applications ou ~/Applications)
        target = next(iter(_find_ours(name, platform)), _target(default_dest(platform), name, platform))
    if not (target.exists() or target.is_symlink()):
        return None
    if owner_of(target) is None:
        raise util.BrainError(f"{target} não é um launcher do Brain — não vou apagar")
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


# ── atalho de um clique: Dock (macOS) · área de trabalho (Linux/WSLg) ─────────
_DOCK_TILE = ('<dict><key>tile-data</key><dict><key>file-data</key><dict>'
              '<key>_CFURLString</key><string>{app}</string><key>_CFURLStringType</key><integer>0</integer>'
              '</dict></dict><key>tile-type</key><string>file-tile</string></dict>')


def _dock_tiles() -> list:
    """Tiles do Dock como objetos (plutil → xml → plistlib). Ilegível/corrompido = lista vazia.
    Um tile nosso SEM tile-type (fragmento malformado de versão antiga) NÃO conta como pregado:
    o pin reescreve por cima e cura a instância ferida."""
    try:
        xml = subprocess.run(["/usr/bin/plutil", "-convert", "xml1", "-o", "-",
                              str(Path.home() / "Library/Preferences/com.apple.dock.plist")],
                             capture_output=True, timeout=5).stdout
        return plistlib.loads(xml).get("persistent-apps") or []
    except Exception:  # noqa: BLE001 — Dock ausente (Linux/CI), plutil fora, plist corrompida
        return []


def _docked(name: str) -> bool:
    """O app está no Dock como tile BEM-FORMADO (file-tile apontando pro nosso .app)?
    Aceita as duas grafias: caminho puro (a que escrevemos) e file:// URL normalizada
    pelo próprio Dock depois de um reload."""
    want = f"{name}.app"
    for tile in _dock_tiles():
        data = tile.get("tile-data") or {}
        url = str((data.get("file-data") or {}).get("_CFURLString") or "")
        url = url.removeprefix("file://").rstrip("/")
        if url.endswith(f"/{want}") and tile.get("tile-type") == "file-tile":
            return True
    return False


def pin_status(name: str = DEFAULT_NAME, *, platform: str | None = None) -> bool:
    """O atalho de um clique já existe? (Dock no macOS · .desktop na área de trabalho no Linux.)"""
    try:
        platform = platform or _platform()
    except util.BrainError:
        return False
    if platform == "darwin":
        return _docked(_safe_name(name))
    return (Path.home() / "Desktop" / f"{_safe_name(name).lower().replace(' ', '-')}.desktop").exists()


def pin_shortcut(name: str = DEFAULT_NAME, *, platform: str | None = None) -> str:
    """Prega o Brain onde o dono encontra com um clique. Idempotente; devolve a linha pro log do job."""
    platform = platform or _platform()
    name = _safe_name(name)
    ours = _find_ours(name, platform)
    if platform == "darwin":
        if not ours:
            raise util.BrainError("instale o app primeiro (`brain app install`) — sem o Brain.app não há o que pregar no Dock", code=4)
        if _docked(name):
            return f"✓ {name} já está no Dock"
        subprocess.run(["/usr/bin/defaults", "write", "com.apple.dock", "persistent-apps", "-array-add",
                        _DOCK_TILE.format(app=str(ours[0]))], check=True, timeout=10)
        subprocess.run(["/usr/bin/killall", "Dock"], check=False, timeout=10)
        return f"✓ {name} pregado no Dock — a um clique, como qualquer app"
    # Linux/WSLg: o menu de aplicativos já ganha o .desktop no install; o extra é a área de trabalho
    if not ours:
        raise util.BrainError("instale o launcher primeiro (`brain app install`) — depois eu copio pra área de trabalho", code=4)
    src = ours[0]
    desktop = Path.home() / "Desktop"
    if not desktop.is_dir():
        return "– sem pasta Desktop: o Brain já está no menu de aplicativos (tecla Super)"
    dst = desktop / f"{name.lower().replace(' ', '-')}.desktop"
    if src != dst:
        shutil.copy2(src, dst)
    dst.chmod(0o755)
    return f"✓ atalho do {name} na área de trabalho"


def is_installed(root: Path, dest: Path | None = None, name: str = DEFAULT_NAME) -> bool:
    """O launcher existe e aponta para ESTA instância?"""
    try:
        platform = _platform()
    except util.BrainError:
        return False
    targets = [_target(Path(dest).expanduser(), name, platform)] if dest else \
        [_target(d, name, platform) for d in _search_dests(platform)]
    owner = next((o for o in (owner_of(t) for t in targets) if o is not None), None)
    return owner is not None and Path(owner or "/nonexistent").resolve() == Path(root).resolve()


def other_owner(root: Path, dest: Path | None = None, name: str = DEFAULT_NAME, *,
                platform: str | None = None) -> str | None:
    """Se o launcher no destino aponta para OUTRA instância, devolve o caminho dela; senão None."""
    try:
        platform = platform or _platform()
    except util.BrainError:
        return None
    name = _safe_name(name)
    d = Path(dest).expanduser() if dest else default_dest(platform)
    owner = owner_of(_target(d, name, platform))
    if owner and Path(owner).resolve() != Path(root).resolve():
        return str(owner)
    return None


# ── CLI ──────────────────────────────────────────────────────────────────────
def cli(args) -> None:
    from . import config
    dest = Path(args.dest) if args.dest else None
    if args.acmd == "install":
        inst = config.load()
        other = other_owner(inst.root, dest, args.name)
        replace = (sys.stdin.isatty() and input(
            f"O app Brain abre outra instância ({other}). Trocar para esta? [s/N] "
        ).strip().lower() in ("s", "sim")) if other else None
        target = install(inst, dest, args.name, replace_other=replace)
        if other and not replace:
            return
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
