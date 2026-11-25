"""CI com `permissions` mínimo, sem action e nenhum job fora dos runners do GitHub.

O repositório é público. O workflow do `pull_request` é o DO PR: quem abre o PR escolhe onde o job
roda e pode editar o próprio arquivo. Por isso nenhum job roda em runner próprio, a lista privada do
portão (um segredo) só chega ao job que não executa nada do PR, e o portão mora em OUTRO arquivo, no
evento que usa o workflow da main.

No mesmo arquivo, um job com `if:` fica "skipped" no `pull_request` — e o GitHub conta "skipped" como
sucesso: um fork apagava o `if:` e escolhia o resultado do próprio portão. E o check run casa pelo
nome: um job de mesmo nome no workflow do PR produz o check "data-gate" que a proteção exigiria. O que
a proteção da main exige é o status de commit `data-gate (status)`, que só o workflow da main consegue
publicar (PR de fork não tem token de escrita).

Os workflows são lidos como texto — o repo não depende de parser de YAML.
"""
from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from brainlib import upstream  # noqa: E402

WORKFLOWS = ROOT / ".github" / "workflows"
GITHUB_RUNNER = "ubuntu-24.04"
PRIVATE_LIST = "${{ secrets.PUBLIC_DENYLIST_B64 }}"
# o cabeçalho de autenticação do checkout, montado por partes: escrito inteiro, o próprio arquivo de
# teste viraria achado da varredura
CHECKOUT_HEADER = "AUTHORIZATION: basic $(echo -n \"x-access-" + "token:$GITHUB_TOKEN\" | base64 -w0)"
GATE_IMAGE_DIGEST = "sha256:9dd21fafb95870b99f9faa703a947d08feeb673048ad556e92ce503d0c086a95"   # python:3.12
STATUS_CONTEXT = "data-gate (status)"


def _gate_script():
    spec = importlib.util.spec_from_file_location("public_gate", ROOT / "scripts" / "dev" / "public_gate.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _jobs(text: str) -> dict[str, str]:
    """Cada job, do cabeçalho (2 espaços sob `jobs:`) até o próximo."""
    parts = re.split(r"(?m)^(?=  [A-Za-z][\w-]*:[ \t]*$)", text[text.index("\njobs:\n") + 1:])
    return {part.split(":", 1)[0].strip(): part for part in parts[1:]}


def _steps(job: str) -> list[str]:
    """Cada passo do job, do `- name:` (6 espaços sob `steps:`) até o próximo."""
    return re.split(r"(?m)^(?=      - name:)", job[job.index("\n    steps:\n") + 1:])[1:]


def _step(job: str, needle: str) -> str:
    hits = [s for s in _steps(job) if needle in s.split("\n", 1)[0]]
    assert len(hits) == 1, (needle, len(hits))
    return hits[0]


def _run(step: str) -> str:
    """O `run:` do passo, inteiro (comentário e tudo): bloco `|` com a indentação tirada, ou a linha única."""
    block = re.search(r"(?m)^        run: \|\n((?:          .*\n|\n)+)", step)
    if block:
        return "".join(ln[10:] if ln.startswith(" " * 10) else ln for ln in block.group(1).splitlines(keepends=True))
    line = re.search(r"(?m)^        run: (.+?)[ \t]*$", step)
    assert line, step.split("\n", 1)[0]
    return line.group(1) + "\n"


def _triggers(text: str) -> str:
    """O bloco `on:` inteiro, até a próxima chave de topo."""
    block = re.search(r"(?m)^on:\n((?:[ \t].*\n|\n)+)(?=\S)", text)
    assert block
    return block.group(1)


def _guards(job: str) -> list[str]:
    return re.findall(r"(?m)^    if: (.+)$", job)


def _permissions(block: str, indent: str) -> dict[str, str]:
    """`permissions:` de um workflow (`indent=""`) ou de um job (indent de 4 espaços): escopo → valor."""
    m = re.search(rf"(?m)^{indent}permissions:[ \t]*\n((?:{indent}(?:[ \t]+.*)?\n)*)", block)
    return dict(re.findall(rf"(?m)^{indent}[ \t]+([a-z-]+):[ \t]*(\w+)[ \t]*$", m.group(1))) if m else {}


def _job_env(job: str) -> str:
    """O bloco `env:` do job (4 espaços): vale para todos os passos."""
    block = re.search(r"(?m)^    env:\n((?:      .*\n|\n)+)", job)
    return block.group(1) if block else ""


class BothWorkflowsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.texts = {name: (WORKFLOWS / name).read_text(encoding="utf-8") for name in ("ci.yml", "data-gate.yml")}
        cls.jobs = {name: _jobs(text) for name, text in cls.texts.items()}

    def all_steps(self) -> list[tuple[str, str, str]]:
        return [(name, job, step) for name, jobs in self.jobs.items() for job, text in jobs.items() for step in _steps(text)]

    def test_each_trust_boundary_has_its_own_workflow_file(self):
        # a suíte executa o código do PR (workflow do PR); o portão lê o PR sem executar nada (workflow da
        # main). Se dividissem o arquivo, um `if:` do próprio PR decidiria se o portão roda.
        self.assertEqual(list(self.jobs["ci.yml"]), ["tests"])
        self.assertEqual(list(self.jobs["data-gate.yml"]), ["data-gate"])
        for step in _steps(self.jobs["ci.yml"]["tests"]):
            self.assertNotIn("data-gate", step.split("\n", 1)[0])

    def test_top_level_permissions_are_read_only(self):
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertEqual(_permissions(text, ""), {"contents": "read"})

    def test_no_action_and_no_javascript_checkout(self):
        # (#113) action de marketplace é código de terceiros com os segredos do job ao alcance
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertEqual(re.findall(r"(?m)^[ \t]*-?[ \t]*uses:[ \t]*(\S+)", text), [])
                self.assertNotIn("actions/checkout", text)

    def test_no_job_runs_outside_the_github_runners(self):
        # quem abre o PR escolhe onde o job roda: em repo público, runner próprio entrega a máquina de
        # quem mantém a qualquer fork
        for name, jobs in self.jobs.items():
            self.assertTrue(jobs, f"{name} sem job nenhum")
            for job, text in jobs.items():
                with self.subTest(workflow=name, job=job):
                    self.assertRegex(text, rf"(?m)^    runs-on: {re.escape(GITHUB_RUNNER)}[ \t]*$")
                    for proibido in ("self-hosted", "runs-on: ${{", "labels:", "privileged"):
                        self.assertNotIn(proibido, text)

    def test_the_workflows_themselves_pass_the_scan(self):
        # o portão varre o que entra; os workflows são o que entra a cada mudança deles
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertEqual(upstream._scan_line(text, [], ""), [])

    def test_no_shell_trace(self):
        # `set -x` imprime o valor expandido de cada variável — a lista privada, por exemplo
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertNotIn("set -x", text)
                self.assertNotRegex(text, r"(?m)^[ \t]*(?:\S+=\S+[ \t]+)*bash[ \t]+-[a-zA-Z]*x")

    def test_no_event_data_is_interpolated_into_a_run_block(self):
        # `${{ }}` dentro de `run:` é texto do evento colado no shell: título de PR é código
        for name, job, step in self.all_steps():
            with self.subTest(workflow=name, job=job, passo=step.split("\n", 1)[0]):
                self.assertNotIn("${{", _run(step))

    def test_checkout_header_is_what_git_and_github_accept(self):
        # mesmo valor nos dois workflows (um divergente passaria despercebido); o token é variável de
        # ambiente no passo, nunca escrito no arquivo
        headers = set()
        for _, _, step in self.all_steps():
            headers.update(re.findall(r'(?m)^\s*git config http\.extraheader "(.*)"$', _run(step)))
            if "Checkout" in step.split("\n", 1)[0]:
                # o token sai da configuração logo depois do fetch: nada que toque em objeto do PR o usa
                self.assertLess(_run(step).index("git fetch"), _run(step).index("git config --unset http.extraheader"))
        self.assertEqual(headers, {CHECKOUT_HEADER})
        # o token do job entra por `env:` de passo (checkout; no portão, também os dois passos do status) —
        # nunca no `env:` do job, que valeria para todo passo
        counts = {name: len(re.findall(r"(?m)^          GITHUB_TOKEN: \$\{\{ github\.token \}\}$", text))
                  for name, text in self.texts.items()}
        self.assertEqual(counts, {"ci.yml": 1, "data-gate.yml": 3})
        self.assertNotRegex("".join(self.texts.values()), r"(?m)^ {3,8}GITHUB_TOKEN:")
        self.assertNotIn("ghp_", "".join(self.texts.values()))

    def test_the_container_is_the_official_python_image(self):
        images = []
        for jobs in self.jobs.values():
            for text in jobs.values():
                images += re.findall(r"(?m)^      image: (.+?)\s*$", text)
        # a suíte não recebe segredo e roda a matriz por tag; o portão, que carrega a lista privada, roda a
        # imagem fixada por digest: tag móvel muda de baixo do repositório, sem PR nenhum
        self.assertEqual(images, ["python:${{ matrix.python }}", f"python:3.12@{GATE_IMAGE_DIGEST}"])


class SuiteWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        self.jobs = _jobs(self.text)
        self.job = self.jobs["tests"]

    def test_the_suite_runs_on_the_pr_workflow_only(self):
        self.assertEqual(re.findall(r"(?m)^  ([a-z_]+):", _triggers(self.text)), ["pull_request", "push"])
        self.assertRegex(_triggers(self.text), r"(?m)^  push:\n    branches: \[main\]\s*$")

    def test_the_suite_never_sees_a_secret(self):
        self.assertNotIn("secrets.", self.text)

    def test_every_job_of_the_suite_runs_on_every_push(self):
        # a suíte é do PR: `if:` ali é o PR decidindo se a suíte roda
        self.assertEqual(_guards(self.job), [])
        self.assertNotIn("needs:", self.job)
        self.assertNotIn("continue-on-error", self.job)

    def test_the_suite_installs_only_pinned_code(self):
        pip = _run(_step(self.job, "TUI opcional"))
        self.assertIn("pip install --no-cache-dir --require-hashes -r requirements-tui.txt", pip)
        node = _run(_step(self.job, "Node (os testes do painel"))
        self.assertRegex(node, r"(?m)^V=v\d+\.\d+\.\d+\s*$")                       # versão fixada no arquivo
        self.assertIn('printf \'%s  %s\\n\'', node)                               # checksum declarado aqui
        self.assertIn("sha256sum --ignore-missing -c node-shasums", node)
        self.assertEqual(len(re.findall(r"\b[0-9a-f]{64}\b", node)), 2)            # um por arquitetura
        self.assertIn('curl -fsSL -m 120 "https://nodejs.org/dist/$V/$F"', node)   # só do site oficial

    def test_the_suite_runs_without_the_job_token(self):
        # `config.load_env` dá ao ambiente a precedência sobre o config/.env: um teste que grava um
        # token falso no .env leria o token do job, se ele ainda estivesse no ar
        suite = _step(self.job, "unittest discover")
        self.assertRegex(suite, r'(?m)^          GITHUB_TOKEN: ""$')
        self.assertNotIn("GITHUB_TOKEN", _run(suite))
        self.assertEqual(suite.count("GITHUB_TOKEN"), 1)                           # e nenhum passo depois o repõe
        self.assertEqual(_steps(self.job)[-1], suite)

    def test_suite_cancellation_never_reaches_main(self):
        block = re.search(r"(?m)^concurrency:\n((?:  .*\n)+)", self.text)
        assert block
        self.assertRegex(block.group(1), r"(?m)^  group: ci-")
        self.assertIn("cancel-in-progress: ${{ github.event_name != 'push' }}", block.group(1))


class GateWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.text = (WORKFLOWS / "data-gate.yml").read_text(encoding="utf-8")
        self.jobs = _jobs(self.text)
        self.job = self.jobs["data-gate"]
        self.checkout = _step(self.job, "Checkout da main")
        self.gate = _step(self.job, "Portão de dados")

    def test_the_gate_runs_on_the_base_workflow_and_the_suite_never_does(self):
        # `pull_request` usa o workflow do PR; `pull_request_target`, o da main. O portão roda no
        # segundo — é o que impede um PR de enfraquecer o próprio portão.
        triggers = _triggers(self.text)
        self.assertEqual(re.findall(r"(?m)^  ([a-z_]+):", triggers), ["pull_request_target", "push"])
        self.assertRegex(triggers, r"(?m)^  pull_request_target:\n    types: \[opened, synchronize, reopened, edited\]\s*$")
        self.assertRegex(triggers, r"(?m)^  push:\n    branches: \[main\]\s*$")
        # sem filtro de branch nem de caminho no `pull_request_target`: o portão roda em TODO PR
        self.assertNotIn("branches-ignore", triggers.split("  push:")[0])
        self.assertNotIn("paths", triggers)
        self.assertNotIn("pull_request_target", (WORKFLOWS / "ci.yml").read_text(encoding="utf-8").split("\nname:")[1])

    def test_the_gate_job_is_never_skipped(self):
        # job "skipped" conta como sucesso na proteção: sem `if:` no job e nos passos até o portão
        self.assertEqual(_guards(self.job), [])
        for step in (self.checkout, self.gate):
            self.assertNotRegex(step, r"(?m)^        if:")
        self.assertNotIn("continue-on-error", self.job)
        # os únicos passos com `if:` são o primeiro e o último (os dois do status); nenhum decide pelo
        # conteúdo do PR
        guarded = [i for i, step in enumerate(_steps(self.job)) if re.search(r"(?m)^        if:", step)]
        self.assertEqual(guarded, [0, len(_steps(self.job)) - 1])

    def test_only_the_gate_job_can_write_and_only_statuses(self):
        self.assertEqual(_permissions(self.job, "    "), {"contents": "read", "statuses": "write"})
        suite = _jobs((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))["tests"]
        self.assertEqual(_permissions(suite, "    "), {})                          # sem bloco próprio: só o read do topo

    def test_the_private_list_is_a_secret_that_only_the_gate_receives(self):
        self.assertNotIn("secrets.", (WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
        self.assertEqual([s for s in _steps(self.job) if "secrets." in s], [self.gate])
        self.assertIn(f"          PUBLIC_DENYLIST_B64: {PRIVATE_LIST}", self.gate)
        self.assertNotIn("secrets.", _job_env(self.job))                           # não no `env:` do job: só no passo

    def test_data_gate_scans_with_the_scripts_from_main(self):
        run = _run(self.checkout)
        self.assertIn('git fetch -q --no-tags origin "+refs/heads/main:refs/remotes/origin/main" "$TARGET_SHA"', run)
        self.assertIn("git checkout -q --force origin/main", run)
        # o token sai da configuração ANTES de o job tocar em objeto que vem do PR
        self.assertLess(run.index("git fetch"), run.index("git config --unset http.extraheader"))
        self.assertEqual(run.rstrip().split("\n")[-1], "git config --unset http.extraheader")

    def test_the_gate_does_not_take_the_server_root_for_a_machine_path(self):
        # a varredura procura o caminho do HOME no diff; o do container (/root) é caminho de servidor
        # que documentação legítima cita
        run = _run(self.gate)
        self.assertIn('export HOME="$PWD/.home-do-portao"', run)
        self.assertLess(run.index("export HOME="), run.index("public_gate.py gate"))

    def test_the_gate_never_prints_where_the_private_list_matched(self):
        # o log do job é público: quem abre PR de fork testaria candidato a termo contra ele
        self.assertNotIn("--detalhes", self.gate)
        self.assertNotIn("set -x", _run(self.gate))

    def test_the_result_that_protection_requires_is_a_commit_status_from_the_base_workflow(self):
        # o check run `data-gate` casa pelo nome — um fork emite um igual. Status de commit exige
        # token de escrita: só este workflow publica, e é o que a proteção da main exige.
        status = _steps(self.job)[-1]
        self.assertIn(STATUS_CONTEXT, status.split("\n", 1)[0])
        self.assertEqual(_gate_script().STATUS_CONTEXT, STATUS_CONTEXT)
        self.assertIn(f'public_gate.py status --sha "$TARGET_SHA" --rc "$RC"', _run(status))
        self.assertIn("RC: ${{ steps.gate.outputs.rc }}", status)                  # código do gate, por `env`
        self.assertRegex(status, r"(?m)^        if: always\(\) && github\.event_name == 'pull_request_target'$")
        self.assertRegex(self.gate, r"(?m)^        id: gate$")
        self.assertIn('echo "rc=$rc" >> "$GITHUB_OUTPUT"', _run(self.gate))
        self.assertRegex(_run(self.gate), r"(?m)^python3 scripts/dev/public_gate\.py gate .* \|\| rc=\$\?$")
        self.assertIn('exit "$rc"', _run(self.gate))

    def _curl_posts(self, text: str) -> list[tuple[str, str]]:
        """(estado, contexto) de cada status que um `curl … -d '{…}'` do texto publica."""
        return re.findall(r'\{"state":"([a-z]+)","context":"([^"]+)"', text)

    def test_the_status_is_pending_before_any_checkout(self):
        # o GitHub exige status e check de mesmo nome OS DOIS só quando os dois existem: até o último
        # passo publicar, só existia o check do fork — e bastava. O primeiro passo publica `pending`, sem
        # ler nada do repositório: só o curl da imagem e o token do job
        steps = _steps(self.job)
        first = steps[0]
        self.assertEqual(first.split("\n", 1)[0],
                         "      - name: Status pendente na ponta do PR (antes de qualquer checkout)")
        self.assertLess(steps.index(first), steps.index(self.checkout))
        self.assertRegex(first, r"(?m)^        if: github\.event_name == 'pull_request_target'$")  # em push não há status
        run = _run(first)
        self.assertEqual(self._curl_posts(run), [("pending", STATUS_CONTEXT)])
        self.assertIn('curl -fsS -m 60 -X POST "$GITHUB_API_URL/repos/$GITHUB_REPOSITORY/statuses/$TARGET_SHA"', run)
        self.assertIn("          GITHUB_TOKEN: ${{ github.token }}\n", first)       # token de passo, não de job
        self.assertNotIn("git ", run)
        self.assertNotIn("secrets.", first)                                          # a lista privada não entra aqui

    def test_the_final_status_does_not_depend_on_the_checkout(self):
        # job que morreu no checkout (fetch que falhou) não tem o script no disco: o mesmo pedido sai
        # com curl, e publica `error` — o status nunca fica pendente nem some
        status = _steps(self.job)[-1]
        run = _run(status)
        self.assertIn("if [ -f scripts/dev/public_gate.py ]; then\n", run)
        self.assertIn('python3 scripts/dev/public_gate.py status --sha "$TARGET_SHA" --rc "$RC" --run "$RUN"', run)
        self.assertEqual(self._curl_posts(run.split("else", 1)[1]), [("error", STATUS_CONTEXT)])

    def test_the_pr_tip_and_the_base_come_from_the_event_not_from_the_pr_itself(self):
        env = _job_env(self.job)
        self.assertIn("TARGET_SHA: ${{ github.event.pull_request.head.sha || github.sha }}", env)
        self.assertIn("GATE_BASE: ${{ github.event.pull_request.head.sha && 'origin/main' || github.event.before }}", env)


if __name__ == "__main__":
    unittest.main()
