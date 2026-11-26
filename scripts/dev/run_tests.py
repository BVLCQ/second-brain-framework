#!/usr/bin/env python3
"""Roda a suíte em paralelo. Só stdlib; o mesmo comando vale no CI e na máquina de quem desenvolve.

    python3 scripts/dev/run_tests.py                 # tudo, um worker por CPU (teto 8)
    python3 scripts/dev/run_tests.py -j 4 test_tui   # só o que começa por test_tui, 4 workers
    python3 scripts/dev/run_tests.py test_brain.DashboardAssetTests

Por que existe: `unittest discover` roda 1.600+ testes em série num processo só. Os testes de TUI (~115)
levam metade do tempo e não dependem uns dos outros. Aqui a unidade é a classe de teste; classe grande é
partida em pedaços. Cada worker é um processo novo (`spawn`), então um teste não herda o estado de outro
worker. O que o `discover` fazia de graça continua igual: os módulos são importados na ordem alfabética
no processo pai, antes dos workers (o `test_brain` fixa o BRAIN_NOW de que os demais dependem).

Saída: só o que importa. Falha e erro com traceback e o stdout capturado da unidade; as unidades mais
lentas no fim. Código de saída 0 só se tudo passou e ao menos um teste rodou.
"""
from __future__ import annotations

import argparse
import contextlib
import faulthandler
import io
import multiprocessing
import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPLIT_AT = 10          # classe com mais testes que isto é partida
CHUNK = 5              # tamanho do pedaço
STALL_S = int(os.environ.get("BRAIN_TEST_STALL_S", 180))   # unidade parada além disto imprime a pilha (diagnóstico, não mata)
HEAVY_HINTS = ("run_test", "subprocess", "textual")


def _paths(tests_dir: Path) -> None:
    for p in (str(tests_dir), str(ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)


def _flat(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from _flat(t)
        else:
            yield t


def discover(tests_dir: Path, prefixes: list[str]) -> list[str]:
    """Ids de todos os testes, na ordem do `discover` (alfabética por arquivo)."""
    _paths(tests_dir)
    suite = unittest.defaultTestLoader.discover(str(tests_dir), top_level_dir=str(tests_dir))
    ids = [t.id() for t in _flat(suite)]
    if prefixes:
        ids = [i for i in ids if any(i == p or i.startswith(p + ".") or i.startswith(p) for p in prefixes)]
    return ids


def make_units(ids: list[str], tests_dir: Path) -> list[tuple[str, list[str], float]]:
    """(rótulo, ids, peso). Agrupa por classe; classe grande vira pedaços. Mais pesadas primeiro."""
    by_cls: dict[str, list[str]] = {}
    for i in ids:
        by_cls.setdefault(i.rsplit(".", 1)[0], []).append(i)
    heavy_cache: dict[str, bool] = {}

    def heavy(module: str) -> bool:
        if module not in heavy_cache:
            f = tests_dir / (module.split(".")[0] + ".py")
            text = f.read_text(encoding="utf-8", errors="replace") if f.is_file() else ""
            heavy_cache[module] = any(h in text for h in HEAVY_HINTS)
        return heavy_cache[module]

    units = []
    for cls, members in by_cls.items():
        w = 6.0 if heavy(cls) else 1.0
        if len(members) > SPLIT_AT:
            for k in range(0, len(members), CHUNK):
                part = members[k:k + CHUNK]
                units.append((f"{cls}[{k // CHUNK + 1}]", part, w * len(part)))
        else:
            units.append((cls, members, w * len(members)))
    units.sort(key=lambda u: -u[2])
    return units


def _init_worker(tests_dir: str, env: dict) -> None:
    os.environ.update(env)
    _paths(Path(tests_dir))


def run_unit(unit: tuple[str, list[str]]) -> dict:
    label, ids = unit
    out, err = io.StringIO(), io.StringIO()
    t0 = time.perf_counter()
    faulthandler.dump_traceback_later(STALL_S, repeat=False, file=2)      # fd 2: o redirect acima não engole a pilha
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            suite = unittest.defaultTestLoader.loadTestsFromNames(ids)
            res = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    finally:
        faulthandler.cancel_dump_traceback_later()
    bad = [(t.id(), tb) for t, tb in res.failures + res.errors]
    return {"label": label, "ran": res.testsRun, "skipped": len(res.skipped), "bad": bad,
            "secs": time.perf_counter() - t0, "log": (out.getvalue() + err.getvalue())[-3000:]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="suíte em paralelo")
    ap.add_argument("prefixes", nargs="*", help="módulo, classe ou teste (prefixo do id)")
    ap.add_argument("-j", "--jobs", type=int, default=int(os.environ.get("BRAIN_TEST_JOBS", 0)) or min(os.cpu_count() or 2, 8))
    ap.add_argument("--timings", help="grava o tempo de cada unidade neste arquivo JSON")
    ap.add_argument("--tests-dir", default=str(ROOT / "tests"), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    tests_dir = Path(a.tests_dir).resolve()

    t0 = time.perf_counter()
    ids = discover(tests_dir, a.prefixes)          # importa os módulos aqui: o BRAIN_NOW do test_brain entra no ambiente
    if not ids:
        print("nenhum teste encontrado", file=sys.stderr)
        return 1
    units = make_units(ids, tests_dir)
    jobs = max(1, min(a.jobs, len(units)))
    env = {k: v for k, v in os.environ.items() if k == "BRAIN_NOW"}
    ctx = multiprocessing.get_context("spawn")
    done, ran, skipped, bad, slow = 0, 0, 0, [], []
    with ctx.Pool(jobs, initializer=_init_worker, initargs=(str(tests_dir), env)) as pool:
        for r in pool.imap_unordered(run_unit, [(u[0], u[1]) for u in units]):
            done += 1
            ran += r["ran"]
            skipped += r["skipped"]
            slow.append((r["secs"], r["label"], r["ran"]))
            if r["bad"]:
                bad.append(r)
                print(f"[{done}/{len(units)}] FALHOU {r['label']}", flush=True)
    wall = time.perf_counter() - t0
    for r in bad:
        for tid, tb in r["bad"]:
            print(f"\n{'=' * 70}\nFAIL: {tid}\n{tb}")
        if r["log"].strip():
            print(f"--- saída capturada de {r['label']}:\n{r['log']}")
    slow.sort(reverse=True)
    if a.timings:
        import json
        Path(a.timings).write_text(json.dumps({"wall": wall, "jobs": jobs, "units": slow}), encoding="utf-8")
    print("\nunidades mais lentas:")
    for secs, label, n in slow[:8]:
        print(f"  {secs:6.1f}s  {n:3d} testes  {label}")
    nbad = sum(len(r["bad"]) for r in bad)
    print(f"\n{ran} testes em {wall:.0f}s com {jobs} workers · {skipped} pulados · {nbad} com falha")
    return 1 if (nbad or ran == 0) else 0


if __name__ == "__main__":
    sys.exit(main())
