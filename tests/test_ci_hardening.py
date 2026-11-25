"""CI com `permissions` mínimo, actions fixadas por SHA (#113) e nenhum job fora dos runners do GitHub.

O repositório é público e o workflow do `pull_request` é o do PR: quem abre o PR escolhe onde o job
roda. Por isso nenhum job pode rodar em runner próprio, e a lista privada do portão — um segredo —
só pode chegar ao job que não executa nada do PR.
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
GITHUB_RUNNER = "ubuntu-24.04"
# o portão só lê texto do PR: roda em todo PR, pelo evento que usa o workflow da main
GATE_EVENTS = "github.event_name != 'pull_request'"
# a lista privada é um segredo do repositório; só o portão o recebe
PRIVATE_LIST = "${{ secrets.PUBLIC_DENYLIST_B64 }}"
# um HOME que não existe: a varredura o procura no texto como "caminho da máquina"
NO_HOME = "/lugar/que/nao/existe-em-arquivo-nenhum"


def _jobs(text: str) -> dict[str, str]:
    """Cada job do workflow, do cabeçalho (2 espaços sob `jobs:`) até o próximo."""
    parts = re.split(r"(?m)^(?=  [A-Za-z][\w-]*:[ \t]*$)", text[text.index("\njobs:\n") + 1:])
    return {part.split(":", 1)[0].strip(): part for part in parts[1:]}


def _guards(job: str) -> list[str]:
    return re.findall(r"(?m)^    if: (.+)$", job)


def _job_env(job: str) -> str:
    """O bloco `env:` do job (4 espaços): vale para todos os passos."""
    block = re.search(r"(?m)^    env:\n((?:      .*\n|\n)+)", job)
    return block.group(1) if block else ""


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

    def test_the_gate_runs_on_the_base_workflow_and_the_suite_never_does(self):
        # `pull_request` usa o workflow do PR; `pull_request_target`, o da main. O portão roda no
        # segundo — é o que impede um PR de enfraquecer o próprio portão. Em troca, o evento não pode
        # alcançar nenhum job que execute código do PR.
        self.assertRegex(self.text, r"(?m)^  pull_request:\s*$")
        self.assertRegex(self.text, r"(?m)^  pull_request_target:\s*$")
        self.assertNotIn("pull_request_target", self.jobs["tests"])

    def test_no_job_runs_outside_the_github_runners(self):
        # O repositório é público: o workflow do `pull_request` é o do PR, e quem abre o PR escolhe
        # onde o job roda e o que ele executa. Um job em runner próprio entregaria a máquina do
        # mantenedor a qualquer fork — por isso a suíte roda para todo PR, inclusive de fork, e só
        # numa máquina do GitHub, nova para cada job.
        self.assertEqual(sorted(self.jobs), ["data-gate", "tests"])
        for name, job in self.jobs.items():
            with self.subTest(job=name):
                self.assertEqual(re.findall(r"(?m)^    runs-on: (.+)$", job), [GITHUB_RUNNER])
        for proibido in ("self-hosted", "docker.sock", "privileged", "volumes:"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, self.text)
        self.assertEqual(_guards(self.jobs["tests"]), [], "a suíte roda para todo PR, sem guarda de repositório")
        self.assertEqual(_guards(self.jobs["data-gate"]), [GATE_EVENTS], "o portão roda em todo PR")
        # no evento do workflow da main, o único contato com o PR é texto: a ponta do PR entra num
        # worktree destacado, e quem varre é o script da main
        self.assertIn("git checkout -q --force origin/main", self.jobs["data-gate"])
        self.assertIn("git worktree add --detach /tmp/entrada", self.jobs["data-gate"])

    def test_the_workflow_itself_passes_the_scan(self):
        # o portão de dados roda este workflow no PR: um caminho de máquina escrito aqui se acusaria
        hits = [(n, rule) for n, line in enumerate(self.text.splitlines(), 1)
                for rule, _ in upstream._scan_line(line, [], NO_HOME)]
        self.assertEqual(hits, [], "o workflow tem linha que o portão de dados acusaria")

    def test_the_private_list_is_a_secret_that_only_the_gate_receives(self):
        gate, tests = self.jobs["data-gate"], self.jobs["tests"]
        self.assertEqual(re.findall(r"\$\{\{ secrets\.\w+ \}\}", self.text), [PRIVATE_LIST])
        self.assertIn(PRIVATE_LIST, gate)
        self.assertNotIn("secrets.", tests, "o job que executa o código do PR não pode ver a lista privada")
        # a lista vira um arquivo 0600 que sai com o job, e entra no portão por esse caminho só
        self.assertIn("umask 077\n", gate)
        self.assertIn("trap 'rm -f \"$LISTA\"' EXIT", gate)
        self.assertIn('--denylist "$LISTA"', gate)
        self.assertNotIn("--denylist /", gate)
        # nada no workflow pede rastro de shell: o eco dos comandos levaria o segredo ao log
        for rastro in ("set -x", "set -v", "set -o xtrace", "set -o verbose"):
            self.assertNotIn(rastro, self.text)

    def test_data_gate_scans_with_the_scripts_from_main(self):
        gate = self.jobs["data-gate"]
        self.assertIn("+refs/heads/main:refs/remotes/origin/main", gate)
        self.assertIn('git remote add origin "$GITHUB_SERVER_URL/$GITHUB_REPOSITORY.git"', gate)
        self.assertIn("git checkout -q --force origin/main", gate)
        self.assertIn("--root /tmp/entrada", gate)
        self.assertIn("git worktree add --detach /tmp/entrada", gate)
        # sem exceção de bootstrap: o portão é sempre o da main, nunca o do PR — o PR não escolhe as regras
        self.assertNotIn("/tmp/entrada/scripts", gate)
        self.assertIn('python3 scripts/dev/public_gate.py gate --root /tmp/entrada', gate)

    def test_the_gate_does_not_take_the_server_root_for_a_machine_path(self):
        # a varredura procura o caminho do HOME no diff; no container ele é /root, que documentação de
        # servidor cita legitimamente — o job aponta o HOME para uma pasta do workspace antes de varrer
        self.assertRegex(self.jobs["data-gate"], r'(?m)^ *export HOME="\$PWD/\.home-do-portao"$')

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

    def test_the_suite_runs_the_whole_matrix_without_waiting_for_the_gate(self):
        # os dois jobs ficam em execuções diferentes (eventos diferentes): um `needs` entre eles só
        # faria a suíte nunca rodar em PR, onde a execução do `pull_request` pula o portão
        tests = self.jobs["tests"]
        self.assertNotRegex(tests, r"(?m)^    needs:")
        self.assertIn('python: ["3.11", "3.12", "3.13", "3.14"]', tests)
        self.assertIn("image: python:${{ matrix.python }}", tests)

    def test_the_suite_installs_only_pinned_code(self):
        # nada entra no job por confiança: o `pip` só instala o que o requirements trava por hash, e o
        # `node` só entra pelo tarball cujo checksum está fixado no workflow
        tests = self.jobs["tests"]
        self.assertIn("pip install --no-cache-dir --require-hashes -r requirements-tui.txt", tests)
        self.assertIn("sha256sum --ignore-missing -c node-shasums", tests)

    def test_the_suite_runs_without_the_job_token(self):
        # o token do job é do passo do checkout, em `env` próprio: nunca no `env` do job, que vale para
        # todos os passos — a suíte executa o código do PR. E o passo da suíte o tira do ambiente de vez.
        tests = self.jobs["tests"]
        self.assertEqual(re.findall(r"\$\{\{ github\.token \}\}", tests), ["${{ github.token }}"])
        self.assertNotIn("GITHUB_TOKEN", _job_env(tests))
        self.assertRegex(tests, r'(?m)^        env:\n          GITHUB_TOKEN: ""\n        run: python -m unittest discover -s tests$')

    def test_concurrency_group_keeps_the_two_pull_request_events_apart(self):
        # em pull_request_target o `github.ref` é o da main: sem o evento no grupo, todos os PRs
        # cairiam num grupo só, e a execução da suíte cancelaria a do portão
        group = re.search(r"(?m)^  group: (.+)$", self.text)
        assert group
        self.assertIn("${{ github.event_name }}", group.group(1))
        self.assertIn("${{ github.event.pull_request.number || github.ref }}", group.group(1))
        self.assertIn("cancel-in-progress: ${{ github.event_name != 'push' }}", self.text)


if __name__ == "__main__":
    unittest.main()
