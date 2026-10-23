"""Vídeo e áudio no /dump: transcrição no dispositivo e quadros amostrados — sem ffmpeg, sem nuvem (só macOS 26+).

Transcrição: SpeechAnalyzer do macOS, por idioma; com mais de um idioma (reunião bilíngue), o texto de cada minuto vem
do idioma que de fato se fala nele. Quadros: AVFoundation, um PNG a cada N segundos (slides, tela compartilhada).
Nada aqui grava no vault: a saída vai para o stdout ou para uma pasta temporária; quem arquiva é o /dump.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from . import util
from .swift import swift_tool

HINT = ("transcrição/quadros precisam do macOS 26+ com as Command Line Tools (`xcode-select --install`) — "
        "em outro sistema, use o whisper.cpp ou o ffmpeg e coloque o texto na inbox")

# Palavras marcadoras (sem acento colapsado): servem só para decidir o idioma de cada minuto.
MARKERS = {
    "pt": set("não você vocês então também são nós isso pra uma com está tem têm aqui já ainda fazer agora porque quando mas muito "
              "pode podem vamos vou gente bom tudo coisa só os as do da dos das em um é".split()),
    "es": set("los las el usted ustedes entonces también son nosotros eso una con está tiene tienen aquí ya todavía hacer ahora porque "
              "cuando pero muy puede pueden vamos voy gente bueno todo cosa solo qué cómo cuál y de la en un es".split()),
    "en": set("the and you we they that this with for are is was have has not but what when how can will would from your our".split()),
}

SWIFT_STT = r'''import Foundation
import Speech
import AVFoundation

func err(_ s: String) { FileHandle.standardError.write(Data((s + "\n").utf8)) }

@main
struct STT {
    static func main() async {
        let a = CommandLine.arguments
        guard a.count >= 2 else { err("uso: stt <arquivo> [locale] [inicioSeg] [duracaoSeg]"); exit(2) }
        guard #available(macOS 26.0, *) else { err("precisa do macOS 26 ou mais novo (SpeechAnalyzer)"); exit(3) }
        do { try await run(a) } catch { err("erro: \(error)"); exit(1) }
    }

    @available(macOS 26.0, *)
    static func run(_ a: [String]) async throws {
        let src = URL(fileURLWithPath: a[1])
        let locale = Locale(identifier: a.count > 2 ? a[2] : "pt-BR")
        let startSec = a.count > 3 ? Double(a[3]) ?? 0 : 0
        let durSec = a.count > 4 ? Double(a[4]) ?? 0 : 0

        // 1) áudio: extrai a trilha (e o trecho pedido) para um m4a temporário
        let asset = AVURLAsset(url: src)
        let audioURL = FileManager.default.temporaryDirectory.appendingPathComponent("brain-stt-\(UUID().uuidString).m4a")
        defer { try? FileManager.default.removeItem(at: audioURL) }
        guard let session = AVAssetExportSession(asset: asset, presetName: AVAssetExportPresetAppleM4A) else { throw NSError(domain: "stt", code: 1, userInfo: [NSLocalizedDescriptionKey: "sem exportador de áudio"]) }
        if durSec > 0 || startSec > 0 {
            let total = try await asset.load(.duration).seconds
            let d = durSec > 0 ? min(durSec, total - startSec) : total - startSec
            session.timeRange = CMTimeRange(start: CMTime(seconds: startSec, preferredTimescale: 600), duration: CMTime(seconds: d, preferredTimescale: 600))
        }
        try await session.export(to: audioURL, as: .m4a)

        // 2) fala: SpeechAnalyzer no dispositivo
        let transcriber = SpeechTranscriber(locale: locale, transcriptionOptions: [], reportingOptions: [], attributeOptions: [.audioTimeRange])
        if let req = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) {
            err("baixando o modelo de fala (\(locale.identifier))...")
            try await req.downloadAndInstall()
        }
        let analyzer = SpeechAnalyzer(modules: [transcriber])
        let file = try AVAudioFile(forReading: audioURL)
        let offset = startSec
        let collector = Task {
            for try await r in transcriber.results {
                let t = (r.text.runs.first?.audioTimeRange?.start.seconds ?? 0) + offset
                let h = Int(t) / 3600, m = (Int(t) % 3600) / 60, s = Int(t) % 60
                print(String(format: "[%02d:%02d:%02d] ", h, m, s) + String(r.text.characters))
                fflush(stdout)
            }
        }
        if let last = try await analyzer.analyzeSequence(from: file) {
            try await analyzer.finalizeAndFinish(through: last)
        } else {
            await analyzer.cancelAndFinishNow()
        }
        try await collector.value
    }
}
'''

SWIFT_FRAMES = r'''import Foundation
import AVFoundation
import AppKit

func err(_ s: String) { FileHandle.standardError.write(Data((s + "\n").utf8)) }

@main
struct Frames {
    static func main() async {
        let a = CommandLine.arguments
        guard a.count >= 4 else { err("uso: frames <video> <pasta> <cada-segundos> [largura] [inicio] [fim]"); exit(2) }
        let asset = AVURLAsset(url: URL(fileURLWithPath: a[1]))
        let out = a[2]
        let step = Double(a[3]) ?? 120
        let width = a.count > 4 ? Double(a[4]) ?? 960 : 960
        do {
            let total = try await asset.load(.duration).seconds
            let from = a.count > 5 ? Double(a[5]) ?? 0 : 0
            let to = a.count > 6 ? min(Double(a[6]) ?? total, total) : total
            let gen = AVAssetImageGenerator(asset: asset)
            gen.appliesPreferredTrackTransform = true
            gen.maximumSize = CGSize(width: width, height: width)
            gen.requestedTimeToleranceBefore = CMTime(seconds: 2, preferredTimescale: 600)
            gen.requestedTimeToleranceAfter = CMTime(seconds: 2, preferredTimescale: 600)
            var t = from
            while t < to {
                let time = CMTime(seconds: t, preferredTimescale: 600)
                if let (cg, _) = try? await gen.image(at: time) {
                    let rep = NSBitmapImageRep(cgImage: cg)
                    if let png = rep.representation(using: .png, properties: [:]) {
                        let name = String(format: "%@/frame-%05d.png", out, Int(t))
                        try png.write(to: URL(fileURLWithPath: name))
                        print(name)
                    }
                }
                t += step
            }
        } catch { err("erro: \(error)"); exit(1) }
    }
}
'''

LINE = re.compile(r"\[(\d+):(\d+):(\d+)\]\s?(.*)")


def parse(text: str) -> list[tuple[int, str]]:
    return [(int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]), m[4].strip()) for ln in text.splitlines() if (m := LINE.match(ln))]


def _rate(rows: list[tuple[int, str]], lang: str) -> float:
    words = re.findall(r"\w+", " ".join(t for _, t in rows).lower())
    marks = MARKERS.get(lang, set())
    return sum(w in marks for w in words) / max(len(words), 1)


def merge(by_locale: dict[str, list[tuple[int, str]]], bucket: int = 60) -> list[tuple[int, str, str]]:
    """Por minuto, escolhe o idioma cujo texto mais "soa" no próprio idioma. Devolve (segundos, texto, locale)."""
    buckets: dict[str, dict[int, list]] = {loc: defaultdict(list) for loc in by_locale}
    for loc, rows in by_locale.items():
        for t, x in rows:
            buckets[loc][t // bucket].append((t, x))
    out: list[tuple[int, str, str]] = []
    for k in sorted({k for b in buckets.values() for k in b}):
        best = max(by_locale, key=lambda loc: (_rate(buckets[loc].get(k, []), loc[:2].lower()), len(buckets[loc].get(k, []))))
        out += [(t, x, best) for t, x in buckets[best].get(k, [])]
    return out


def _fmt(t: int) -> str:
    return f"[{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}]"


def transcribe(path: str | Path, locales: list[str] | None = None, start: float = 0, length: float = 0) -> str:
    p = Path(path)
    if not p.is_file():
        raise util.BrainError(f"arquivo não encontrado: {p}", code=3)
    locales = locales or ["pt-BR"]
    tool = swift_tool(SWIFT_STT, "stt", library=True)
    if not tool:
        raise util.BrainError(HINT, code=3)
    procs = {loc: subprocess.Popen([*tool, str(p), loc, str(start), str(length)], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True) for loc in locales}
    rows: dict[str, list[tuple[int, str]]] = {}
    try:
        for loc, pr in procs.items():
            out, err = pr.communicate()
            if pr.returncode != 0:
                raise util.BrainError(f"transcrição ({loc}) falhou: {err.strip().splitlines()[-1] if err.strip() else 'erro'}", code=3)
            rows[loc] = parse(out)
    finally:
        for pr in procs.values():          # um idioma falhou (ou Ctrl-C): os outros não ficam rodando órfãos
            if pr.poll() is None:
                pr.kill()
                pr.wait()
    merged = merge(rows) if len(rows) > 1 else [(t, x, locales[0]) for t, x in rows[locales[0]]]
    return "\n".join(f"{_fmt(t)} {x}" for t, x, _ in merged) + "\n"


def frames(path: str | Path, every: int = 150, width: int = 900, start: float = 0, end: float = 0,
           out: str | Path | None = None) -> list[Path]:
    p = Path(path)
    if not p.is_file():
        raise util.BrainError(f"arquivo não encontrado: {p}", code=3)
    if every <= 0 or width <= 0:
        # o programa swift avança `t += every`: 0 (ou negativo) nunca chega ao fim e enche o disco de PNG
        raise util.BrainError("--every e --width precisam ser maiores que zero", code=2)
    tool = swift_tool(SWIFT_FRAMES, "frames", library=True)
    if not tool:
        raise util.BrainError(HINT, code=3)
    dest = Path(out) if out else Path(tempfile.mkdtemp(prefix="brain-video-"))
    dest.mkdir(parents=True, exist_ok=True)
    args = [*tool, str(p), str(dest), str(every), str(width), str(start)] + ([str(end)] if end else [])
    res = subprocess.run(args, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise util.BrainError(f"não consegui extrair os quadros: {res.stderr.strip() or 'erro do AVFoundation'}", code=3)
    return [Path(x) for x in res.stdout.splitlines() if x.strip()]


def cli(args, brain) -> None:
    if args.vcmd == "transcribe":
        text = transcribe(args.file, [x.strip() for x in args.locales.split(",") if x.strip()], args.start, args.length)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"✓ transcrição ({len(text.splitlines())} trechos) → {args.out}")
        else:
            sys.stdout.write(text)
    else:
        for f in frames(args.file, args.every, args.width, args.start, args.end, args.out):
            print(f)
