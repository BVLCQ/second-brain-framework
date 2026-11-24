"""CI com `permissions` mínimo, actions fixadas por SHA (#113) e runner do mantenedor isolado de fork.

O runner é do mantenedor e o repositório é público: nenhum job pode rodar código que veio de fora.
O workflow é lido como texto — o repo não depende de parser de YAML.
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import upstream  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
FORK_GUARD = "github.event.pull_request.head.repo.full_name == github.repository"
ONLY_INSIDE = f"github.event_name == 'push' || {FORK_GUARD}"
# um HOME que não existe: a varredura o procura no texto como "caminho da máquina"
NO_HOME = "/lugar/que/nao/existe-em-arquivo-nenhum"


def _jobs(text: str) -> dict[str, str]:
    """Cada job do workflow, do cabeçalho (2 espaços sob `jobs:`) até o próximo."""
    parts = re.split(r"(?m)^(?=  [A-Za-z][\w-]*:[ \t]*$)", text[text.index("\njobs:\n") + 1:])
    return {part.split(":", 1)[0].strip(): part for part in parts[1:]}


class WorkflowHardeningTest(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")
        self.jobs = _jobs(self.text)

    def test_top_level_permissions_is_read_only(self):
        block = re.search(r"^permissions:\n((?:[ \t]+.*\n)+)", self.text, flags=re.M)
        self.assertIsNotNone(block, "o workflow não declara `permissions:` no topo")
        assert block
        perms = dict(re.findall(r"^[ \t]+(\w+):[ \t]*(\S+)[ \t]*$", block.group(1), flags=re.M))
        self.assertEqual(perms, {"contents": "read"})

    def test_every_action_is_pinned_to_a_sha(self):
        uses = re.findall(r"^[ \t]*-?[ \t]*uses:[ \t]*(\S+)", self.text, flags=re.M)
        for used in uses:
            with self.subTest(uses=used):
                self.assertRegex(used, r"^[^@\s]+@[0-9a-f]{40}$", "action fixada em tag móvel — fixe pelo SHA da versão")

    def test_pull_request_trigger_is_not_a_target_fork_event(self):
        self.assertRegex(self.text, r"(?m)^  pull_request:\s*$")
        self.assertNotIn("pull_request_target", self.text)

    def test_no_job_reaches_the_maintainer_runner_from_a_fork(self):
        self.assertEqual(sorted(self.jobs), ["data-gate", "tests"])
        for name, job in self.jobs.items():
            with self.subTest(job=name):
                self.assertRegex(job, r"(?m)^    runs-on: \[self-hosted, [^\]]+\]$")
                guards = re.findall(r"(?m)^    if: (.+)$", job)
                self.assertEqual(guards, [ONLY_INSIDE], "todo job roda só para push em main ou PR deste repositório")

    def test_the_workflow_itself_passes_the_scan(self):
        # o portão de dados roda este workflow no PR: um caminho de máquina escrito aqui se acusaria
        hits = [(n, rule) for n, line in enumerate(self.text.splitlines(), 1)
                for rule, _ in upstream._scan_line(line, [], NO_HOME)]
        self.assertEqual(hits, [], "o workflow tem linha que o portão de dados acusaria")

    def test_data_gate_reads_the_private_list_from_the_runner_host(self):
        gate = self.jobs["data-gate"]
        self.assertIn("- brain-public-denylist:/denylist:ro", gate)
        self.assertIn("--denylist /denylist/denylist", gate)
        self.assertNotIn("secrets.", self.text)

    def test_data_gate_scans_with_the_scripts_from_main(self):
        gate = self.jobs["data-gate"]
        self.assertIn("+refs/heads/main:refs/remotes/origin/main", gate)
        self.assertIn("git checkout -q --force origin/main", gate)
        self.assertIn("--root /tmp/entrada", gate)
        self.assertIn("git worktree add --detach /tmp/entrada", gate)

    def test_checkout_header_is_what_git_and_github_accept(self):
        # `git config chave=valor` num argumento só: o git das imagens do CI recusa ("invalid key") e o
        # checkout morre antes de começar. Com um token falso, o cabeçalho tem que decodificar para o
        # par que o GitHub espera do job: o login fixo e o token, sem sobra de quebra de linha.
        self.assertNotIn("extraheader=AUTH", self.text)
        values = re.findall(r"(?m)^ *git config http\.extraheader (.+)$", self.text)
        self.assertEqual(len(values), 2, "cada job monta o cabeçalho uma vez")
        env = {**os.environ, "GITHUB_TOKEN": "token-falso-do-job"}
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            for value in values:
                subprocess.run(["bash", "-c", f"git config http.extraheader {value}"], cwd=tmp, env=env, check=True, capture_output=True)
            header = subprocess.run(["git", "config", "--get", "http.extraheader"], cwd=tmp, capture_output=True, text=True, check=True).stdout.strip()
        scheme, _, encoded = header.partition(" ")
        self.assertEqual(scheme, "AUTHORIZATION:")
        kind, _, b64 = encoded.partition(" ")
        self.assertEqual(kind, "basic")
        self.assertEqual(base64.b64decode(b64, validate=True), b"x-access-" + b"token:" + env["GITHUB_TOKEN"].encode())

    def test_tests_wait_for_the_gate_and_run_the_whole_matrix(self):
        tests = self.jobs["tests"]
        self.assertRegex(tests, r"(?m)^    needs: data-gate$")
        self.assertIn('python: ["3.11", "3.12", "3.13", "3.14"]', tests)
        self.assertIn('image: python:${{ matrix.python }}', tests)


if __name__ == "__main__":
    unittest.main()
