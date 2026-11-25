"""Portão de dados do repositório público (`scripts/dev/public_gate.py`): o CI só deixa entrar o que a varredura deixa.

O repositório de prova é real (git de verdade) e a lista privada é um arquivo: termo bloqueado sem
eco do valor, lista ausente ou vazia, regras do brain e o PR que tenta ditar a própria varredura.

O log do gate é público e qualquer pessoa abre PR de fork: achado da lista privada sai sem onde
(só com `--detalhes`, fora do CI), e o que a proteção da main exige é o status de commit que só o
workflow da main consegue publicar.

Termo de empresa nos testes é inventado (`acme-corp`, `rede-interna`); nome de caminho de máquina vem
montado por partes, porque escrito inteiro o próprio arquivo de teste viraria achado.
"""
from __future__ import annotations

import gzip
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, upstream, util  # noqa: E402


def _load():
    spec = importlib.util.spec_from_file_location("public_gate", ROOT / "scripts" / "dev" / "public_gate.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)
    return r.stdout.strip()


def _repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "ci@example.invalid")
    _git(repo, "config", "user.name", "Teste")
    (repo / "notas.md").write_text("primeira revisão\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _write(repo: Path, name: str, data) -> None:
    p = repo / name
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data, encoding="utf-8")


def _commit_bytes(repo: Path, name: str, data: bytes | str, msg: str = "mais um",
                  author: tuple[str, str] | None = None, committer: tuple[str, str] | None = None) -> str:
    """Commita `name` com o conteúdo dado; autor e committer são os do repo, salvo os indicados."""
    _write(repo, name, data)
    _git(repo, "add", ".")
    args = []
    if author:
        args += ["-c", f"user.name={author[0]}", "-c", f"user.email={author[1]}"]
    env = {f"GIT_COMMITTER_{k}": v for k, v in zip(("NAME", "EMAIL"), committer)} if committer else {}
    with mock.patch.dict(os.environ, env):
        r = subprocess.run(["git", "-C", str(repo), *args, "commit", "-q", "-m", msg],
                           check=True, capture_output=True, text=True)
    assert not r.stderr.strip(), r.stderr
    return _git(repo, "rev-parse", "HEAD")


def _denylist(tmp: Path, text: str) -> Path:
    path = tmp / "lista-privada"
    path.write_text(text, encoding="utf-8")
    return path


# caminho de máquina montado por partes: escrito inteiro aqui, o próprio arquivo de teste viria achado
MACHINE_PATH = "/Use" + "rs/pessoa-real/projeto"

LISTA = "acme-corp\nrede-interna\n"


def _onde(arquivo: str, linha: int, regra: str) -> str:
    """Regex da linha de achado: `arquivo (commit <sha curto>):linha — regra` (sem sha no modo árvore de trabalho)."""
    where = re.escape(arquivo) + r"(?: \(commit [0-9a-f]{9}\))?"
    return rf"(?m)^  ✗ {where}:{linha} — {re.escape(regra)}"
OCULTO = "  ✗ lista privada: ao menos um termo aparece no alcance — sem arquivo nem linha"


class GateTests(unittest.TestCase):
    def setUp(self):
        self.mod = _load()
        self._leak = upstream._leak_terms
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.repo = _repo(self.tmp)
        self.base = _git(self.repo, "rev-parse", "HEAD")

    def tearDown(self):
        upstream._leak_terms = self._leak

    def _run(self, args: list[str], out: io.StringIO) -> int:
        with mock.patch("sys.stdout", out):
            return self.mod.main(args, trusted=self.tmp / "confiavel")

    def _gate(self, base: str | None = None, terms: str = LISTA, detalhes: bool = False) -> tuple[int, str]:
        out = io.StringIO()
        deny = _denylist(self.tmp, terms)
        args = ["gate", "--base", base or self.base, "--root", str(self.repo), "--denylist", str(deny)]
        return self._run(args + (["--detalhes"] if detalhes else []), out), out.getvalue()

    def _scan_commits(self, revs: list[str], terms: tuple[str, ...] = ("acme-corp",)) -> list[dict]:
        """Varredura de commits com um alcance dado (o hook pre-push monta `<novo> --not <remoto>`)."""
        src = config.load(self.tmp)
        inst = config.Instance(root=self.repo, vault=src.vault, config_dir=src.config_dir, cfg=src.cfg)
        restore = self.mod.install_denylist(list(terms))
        try:
            return upstream.scan(inst, None, committed=True, revsets=[revs])
        finally:
            upstream._leak_terms = restore
            upstream.PLAIN_KINDS.discard(self.mod.KIND)

    def _scan(self, base: str = "HEAD",
              terms: tuple[str, ...] = ("acme-corp", "rede-interna", "acme")) -> list[dict]:
        """Varredura da árvore de trabalho (`brain upstream scan`): arquivos sem commit contra `base`."""
        src = config.load(self.tmp / "confiavel")
        inst = config.Instance(root=self.repo, vault=src.vault, config_dir=src.config_dir, cfg=src.cfg)
        restore = self.mod.install_denylist(list(terms))
        try:
            return upstream.scan(inst, base, committed=False)
        finally:
            upstream._leak_terms = restore

    def test_lista_privada_uma_por_linha_ou_virgula_comentario_ignorado_e_termo_curto_e_erro(self):
        parse = self.mod.parse_denylist
        self.assertEqual(parse("acme-corp\n, rede-interna,,\n"), ["acme-corp", "rede-interna"])
        self.assertEqual(parse("ACME-corp, acme-corp"), ["ACME-corp"])
        self.assertEqual(parse(""), [])
        # linha que começa com `#` é comentário inteiro: a vírgula dentro dela não vira termo
        self.assertEqual(parse("# nota, com vírgula\nacme-corp\n\n   \n"), ["acme-corp"])
        # termo curto demais ao lado de um válido não some em silêncio: a lista deixaria de cobrir
        for lista in ("acme-corp\nab\n", "acme-corp, e:"):
            with self.subTest(lista=lista), self.assertRaises(RuntimeError) as cm:
                parse(lista)
            self.assertNotIn("ab", str(cm.exception))                 # o erro não ecoa o termo
            self.assertNotIn("e:", str(cm.exception))

    def test_diff_limpo_passa(self):
        _commit_bytes(self.repo, "cliente.md", "conta da marina-demo no relatório\n")
        self.assertEqual(self._gate(), (self.mod.CLEAN, "✓ portão de dados limpo em %s..HEAD\n" % self.base))

    def test_termo_da_lista_privada_bloqueia_e_nao_ecoa_o_valor(self):
        _commit_bytes(self.repo, "cliente.md", "conta da acme-corp no relatorio\n")
        code, out = self._gate(detalhes=True)
        self.assertEqual(code, self.mod.FOUND)
        self.assertIn("lista privada", out)
        self.assertRegex(out, _onde("cliente.md", 1, self.mod.PRIVATE_RULE))
        for valor in ("acme-corp", "rede-interna", "lista-privada"):     # só arquivo, linha e regra
            self.assertNotIn(valor, out)
        # rodou ou não, a regra da lista não fica colada na varredura do processo
        self.assertEqual(self._gate(terms="acme-corp\nab\n")[0], self.mod.ERROR)
        self.assertNotIn(self.mod.KIND, upstream.PLAIN_KINDS)
        self.assertEqual(upstream._leak_terms, self._leak)

    def test_no_ci_o_log_nao_diz_onde_nem_quantos_vezes_bateu_a_lista_privada(self):
        # o log é público e quem abre PR de fork escolhe o conteúdo do alcance: arquivo, linha,
        # impressão digital e contagem transformariam cada execução em medidor da lista privada
        _commit_bytes(self.repo, "cliente.md", "conta da acme-corp no relatorio\nrede-interna respondeu\n")
        _commit_bytes(self.repo, "pasta-da-acme-corp/notas.md", "mais uma linha da rede-interna\n")
        code, out = self._gate()
        self.assertEqual(code, self.mod.FOUND)
        self.assertIn(OCULTO, out)
        self.assertNotRegex(out, r"\d+ achado")                         # sem contagem
        for valor in ("acme-corp", "rede-interna", "cliente.md", "notas.md", "sha:", "chars)"):
            with self.subTest(valor=valor):
                self.assertNotIn(valor, out)
        # fora do CI, na máquina de quem mantém, sai onde — e o valor continua sem eco
        code, out = self._gate(detalhes=True)
        self.assertEqual(code, self.mod.FOUND)
        self.assertRegex(out, _onde("cliente.md", 1, self.mod.PRIVATE_RULE))
        self.assertRegex(out, _onde("pasta-da-acme-corp/notas.md", 1, self.mod.PRIVATE_RULE))
        self.assertNotIn(OCULTO.strip(), out)
        # o valor do conteúdo nunca sai; do termo só a aparição que é o próprio caminho do arquivo
        com_termo = [ln for ln in out.splitlines() if "acme-corp" in ln]
        self.assertTrue(com_termo)                                     # uma por achado, todas no caminho
        self.assertTrue(all("pasta-da-acme-corp/notas.md (commit " in ln for ln in com_termo), com_termo)
        self.assertNotIn("rede-interna", out)

    def test_no_ci_o_log_nao_distingue_arquivo_com_termo_da_lista_de_arquivo_sem(self):
        # quem abre PR de fork escolhe os nomes de arquivo. Achado de regra pública (anexo fechado,
        # caminho da máquina) saía com o caminho, salvo quando o caminho trazia termo da lista — no
        # lugar saía "caminho omitido": um candidato por linha, em vez de um bit por execução. Com o
        # mesmo bit da lista privada, o log tem de ser o mesmo byte a byte.
        outs = []
        for nome in ("dado/nao-listado-export.parquet", "dado/acme-corp-export.parquet",
                     "dado/ACME-corp-export.parquet"):
            _git(self.repo, "reset", "-q", "--hard", self.base)
            _git(self.repo, "clean", "-fdqx")
            _commit_bytes(self.repo, "notas.md", "conta da acme-corp no relatorio\n")       # o bit: igual nos três
            _commit_bytes(self.repo, "instalacao.md", f"roda em {MACHINE_PATH}/brain\n")
            _commit_bytes(self.repo, nome, b"PAR1dados")
            code, out = self._gate()
            self.assertEqual(code, self.mod.FOUND)
            outs.append(out)
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[0], outs[2])
        for valor in ("acme-corp", "ACME-corp", "nao-listado", "export.parquet", "notas.md", "instalacao.md",
                       "omitido"):
            with self.subTest(valor=valor):
                self.assertNotIn(valor, outs[0])
        self.assertEqual(outs[0].count("caminho da máquina"), 1)
        self.assertIn(OCULTO, outs[0])
        # fora do CI sai onde — inclusive o caminho que traz o termo
        code, det = self._gate(detalhes=True)
        self.assertEqual(code, self.mod.FOUND)
        self.assertRegex(det, _onde("dado/ACME-corp-export.parquet", 1, self.mod.OPAQUE_RULE))

    def test_excecao_imprevista_e_erro_do_portao_sem_traceback(self):
        # antes, só três classes eram pegas: qualquer outra derrubava o script com traceback — e
        # traceback no log público é a mensagem sem máscara, com o que ela carregar (nome de
        # arquivo do PR, por exemplo). No CI sai só a classe; a mensagem, só com --detalhes.
        _commit_bytes(self.repo, "notas.md", "diff limpo\n")
        erros = (util.BrainError("git log falhou: acme-corp/x: fatal"), KeyError("acme-corp/x"),
                 OSError("acme-corp/x"), subprocess.CalledProcessError(
                     128, ["git", "log", "acme-corp/x"], stderr=b"fatal: acme-corp/x"))
        for erro in erros:
            with self.subTest(erro=type(erro).__name__):
                with mock.patch.object(self.mod, "scan_range", side_effect=erro):
                    code, out = self._gate()
                    self.assertEqual(code, self.mod.ERROR)
                    code, det = self._gate(detalhes=True)
                    self.assertEqual(code, self.mod.ERROR)
                self.assertNotIn("Traceback", out)
                self.assertNotIn("acme-corp", out)
                self.assertNotIn("fatal", out)                          # a mensagem não vai ao log do CI
                self.assertNotIn("acme-corp", det)
                self.assertIn("•••", det)                               # com --detalhes, mascarada
                if isinstance(erro, subprocess.CalledProcessError):
                    self.assertIn("git falhou (código 128)", out)
                else:
                    self.assertIn(f"✗ portão de dados: {type(erro).__name__} — {self.mod.NO_WHERE}", out)

    def test_termo_da_lista_cola_em_outra_palavra_e_bloqueia_do_mesmo_jeito(self):
        # `<termo>_prod`, `<termo>VPN`: nome de empresa colado noutro nome é dado igual. Com fronteira
        # de palavra, o termo só aparecia quando estava sozinho.
        for texto in ("conta da acme-corp_prod\n", "acesso pela rede-internaVPN\n", "eu@acme-corp.com\n"):
            with self.subTest(texto=texto):
                head = _git(self.repo, "rev-parse", "HEAD")
                _commit_bytes(self.repo, "notas.md", texto)
                code, out = self._gate(base=head)
                self.assertEqual(code, self.mod.FOUND, out)
                self.assertNotIn("acme-corp", out)
                self.assertNotIn("rede-interna", out)

    def test_termo_na_mensagem_do_commit_tambem_bloqueia(self):
        _commit_bytes(self.repo, "notas.md", "sem dado nenhum aqui\n", msg="conta da rede-interna migrada")
        self.assertEqual(self._gate()[0], self.mod.FOUND)

    def _commitado_e_solto(self, nome: str, data, termos: str) -> None:
        """Achado da lista privada com o arquivo commitado (diff/blob) e sem commit (árvore de trabalho).

        Os termos saem do mesmo parser da lista privada: `quasaré labs` é UM termo — partido no espaço,
        `labs` sozinho casava e o teste passava sem a leitura que diz cobrir. E a chamada deixa a árvore
        como achou: o arquivo solto de uma entrava no `git add .` da seguinte e respondia por ela."""
        head = _git(self.repo, "rev-parse", "HEAD")
        try:
            _commit_bytes(self.repo, nome, data)
            self.assertEqual(self._gate(base=head, terms=termos)[0], self.mod.FOUND, f"commitado: {nome}")
            _git(self.repo, "reset", "-q", "--hard", head)
            _git(self.repo, "clean", "-fdqx")
            _write(self.repo, nome, data)
            achados = self._scan(base=head, terms=tuple(self.mod.parse_denylist(termos)))
            self.assertIn(self.mod.PRIVATE_RULE, {f["rule"] for f in achados}, f"árvore de trabalho: {nome}")
        finally:
            _git(self.repo, "reset", "-q", "--hard", head)
            _git(self.repo, "clean", "-fdqx")

    def test_sufixo_demo_nao_isenta_termo_da_lista_privada(self):
        # `-demo` é a marca de dado fictício do LEDGER (`marina-demo`). Na lista privada não há
        # "fictício": `<empresa>-demo` é host de demonstração de empresa de verdade, e a isenção
        # apagava o termo antes da busca
        for nome, data in (("notas.md", "host acme-corp-demo.internal\n"),
                            ("notas.md", "senha do Rede-Interna-DEMO\n"),
                            ("acme-corp-demo.md", "diff limpo\n")):
            with self.subTest(arquivo=nome, conteudo=data):
                self._commitado_e_solto(nome, data, "acme-corp\nrede-interna\n")
        # a isenção do ledger continua valendo para o termo do ledger
        res = [("pessoa", re.compile(r"(?<!\w)marina(?!\w)", re.I))]
        self.assertFalse(upstream._scan_line("falei com a Marina-demo ontem, id marina-demo", res, ""))

    def test_planilha_em_cp1252_e_varrida_como_tal(self):
        # planilha em pt-BR exportada pelo Excel é CP1252: o `é` do nome era um byte que o UTF-8 não
        # entende, e o termo com acento nunca casava — no diff, na árvore de trabalho e no binário
        for nome, data in (("clientes.csv", b"cliente;Quasar\xe9 Labs;10\n"),
                            ("clientes.dat", b"hdr\0cliente;Quasar\xe9 Labs;10\0fim\0")):
            with self.subTest(arquivo=nome):
                self._commitado_e_solto(nome, data, "quasaré labs\n")

    def test_trecho_de_binario_com_byte_invalido_e_achado_uma_vez(self):
        # o trecho que não é UTF-8 é lido uma vez só — a leitura em CP1252 é da busca. Lido em duas
        # leituras, ele virava duas linhas, e o mesmo trecho saía achado duas vezes
        _commit_bytes(self.repo, "dados.dat", b"hdr\0\xffconta da acme-corp\0fim\0")
        code, out = self._gate(detalhes=True)
        self.assertEqual(code, self.mod.FOUND)
        linhas = [ln for ln in out.splitlines() if "dados.dat" in ln]
        self.assertEqual(len(linhas), 1, linhas)
        self.assertRegex(linhas[0], r"^  ✗ dados\.dat \(commit [0-9a-f]{9}\) \[binário\]:1 — "
                         + re.escape(self.mod.PRIVATE_RULE))

    def test_texto_sem_byte_zero_e_com_byte_invalido_e_achado_uma_vez(self):
        # o mesmo, no caminho sem byte zero: texto que o `* -diff` do próprio alcance faz o git chamar
        # de binário (commitado) e arquivo solto que não é UTF-8 (árvore de trabalho). Este caminho
        # não depende do sistema de arquivos — os testes de nome com byte inválido pulam no macOS
        _commit_bytes(self.repo, ".gitattributes", b"* -diff\n")
        head = _git(self.repo, "rev-parse", "HEAD")
        _commit_bytes(self.repo, "notas.txt", b"\xffconta da acme-corp\n")
        code, out = self._gate(base=head, detalhes=True)
        self.assertEqual(code, self.mod.FOUND)
        linhas = [ln for ln in out.splitlines() if "notas.txt" in ln]
        self.assertEqual(len(linhas), 1, linhas)
        self.assertRegex(linhas[0], r"^  ✗ notas\.txt \(commit [0-9a-f]{9}\) \[binário\]:1 — "
                         + re.escape(self.mod.PRIVATE_RULE))
        _git(self.repo, "reset", "-q", "--hard", head)
        _write(self.repo, "solto.txt", b"\xffconta da acme-corp\n")
        achados = [(f["file"], f["line"]) for f in self._scan(base=head, terms=("acme-corp",))
                   if f["rule"] == self.mod.PRIVATE_RULE]
        self.assertEqual(achados, [("solto.txt [binário]", 1)])

    def test_nome_decomposto_ou_com_espaco_a_mais_e_o_mesmo_nome(self):
        # nome de arquivo vindo do macOS e texto de vários editores estão decompostos (NFD: `e` +
        # acento em vez de `é`). E `acme  corp` com dois espaços, ou com tabulação, é o mesmo nome
        for nome, data, termos in (("clientes.md", "cliente;Quasare\u0301 Labs\n".encode(), "quasaré labs\n"),
                                   ("Quasare\u0301 Labs.md", "diff limpo\n", "quasaré labs\n"),
                                   ("clientes.md", "cliente;Quasaré Labs\n".encode(), "quasare\u0301 labs\n"),
                                   ("clientes.md", "cliente;Quasare\u0301 Labs\n".encode(), "quasare\u0301 labs\n"),
                                   ("notas.md", b"cliente: acme  corp\n", "acme corp\n"),
                                   ("notas.md", b"cliente: acme\tcorp\n", "acme corp\n"),
                                   # termo sem acento, texto decomposto com o acento logo depois da
                                   # última letra: a NFC funde `e` + acento em `é` — só a leitura do
                                   # texto como veio casa, como casava antes
                                   ("clientes.md", "cliente;ZetaCafe\u0301 Ltd\n".encode(), "zetacafe\n")):
            with self.subTest(arquivo=nome, conteudo=data, termos=termos):
                self._commitado_e_solto(nome, data, termos)
        # o mesmo para o termo do ledger, com fronteira de palavra
        res = [("pessoa", upstream._term_regex("jose", "pessoa"))]
        self.assertTrue(upstream._scan_line("falei com o Jose\u0301 ontem", res, ""))
        # texto sem acento e com um espaço só continua limpo
        _git(self.repo, "reset", "-q", "--hard", "HEAD")
        _git(self.repo, "clean", "-fdqx")
        head = _git(self.repo, "rev-parse", "HEAD")
        _commit_bytes(self.repo, "limpo.md", b"cliente: outra empresa\n")
        self.assertEqual(self._gate(base=head, terms="quasaré labs\nacme corp\n")[0], self.mod.CLEAN)

    def test_nome_de_regra_publica_com_termo_da_lista_sai_mascarado(self):
        # o nome da regra é texto fixo do script, mas a lista é de quem mantém: se um termo dela aparece
        # no nome, o nome sai mascarado — o log do CI nunca carrega termo da lista
        _commit_bytes(self.repo, "export.parquet", b"PAR1dados")
        code, out = self._gate(terms="fechado\nacme-corp\n")
        self.assertEqual(code, self.mod.FOUND)
        self.assertIn(f"  ✗ anexo ••• (a varredura não lê o que há dentro) — {self.mod.NO_WHERE}", out)
        self.assertNotIn("fechado", out)

    def test_termo_de_4_ou_5_caracteres_em_binario_com_byte_nulo_e_achado(self):
        # de um binário só os trechos legíveis são buscados; o piso era de 6 bytes e um termo de 4
        # ou 5 caracteres sozinho entre dois bytes nulos não aparecia
        for data, termos in ((b"hdr\0acme\0end\0", "acme\n"), (b"hdr\0zeta0\0end\0", "zeta0\n")):
            with self.subTest(termos=termos):
                self._commitado_e_solto("dados.dat", data, termos)

    def test_endereco_noreply_sai_da_linha_mas_o_resto_da_linha_entra(self):
        # antes, a linha da mensagem com `noreply@` era pulada inteira: bastava escrever o dado na mesma
        # linha do trailer — e o formato do GitHub (`<login>@users.noreply.github.com`), que traz o noreply
        # no domínio, nem era reconhecido
        github = "Co-authored-by: Fulano <123+fulano@users.noreply.github.com>"
        _commit_bytes(self.repo, "notas.md", "diff limpo\n", msg=f"{github} — cliente acme-corp")
        self.assertEqual(self._gate()[0], self.mod.FOUND)
        # o domínio de empresa é dado, mesmo num endereço noreply
        head = _git(self.repo, "rev-parse", "HEAD")
        _commit_bytes(self.repo, "outro.md", "outro diff limpo\n", msg="Retorno: noreply@acme-corp.com")
        self.assertEqual(self._gate(base=head)[0], self.mod.FOUND)
        # sozinho, o endereço noreply não é achado: com o login no local (GitHub) ou com a palavra no local
        sozinhos = (github, "Co-authored-by: Zé <123+acme-corp@users.noreply.github.com>",
                    "Retorno: noreply@example.invalid", "Resposta: no-reply@example.invalid")
        for n, msg in enumerate(sozinhos):
            with self.subTest(mensagem=msg):
                head = _git(self.repo, "rev-parse", "HEAD")
                _commit_bytes(self.repo, f"arquivo-{n}.md", "mais um diff limpo\n", msg=msg)
                self.assertEqual(self._gate(base=head), (self.mod.CLEAN, "✓ portão de dados limpo em %s..HEAD\n" % head))

    def test_termo_depois_de_quebra_exotica_na_linha_adicionada_tambem_bloqueia(self):
        # `str.splitlines()` corta a linha do diff em \x0b, \x0c, \x1c, \x85…: o pedaço depois do corte
        # vinha sem marcador de diff e ficava fora da varredura
        for quebra in (b"\x0b", b"\x0c", b"\x1c", b"\x85", "\u2028".encode(), b"\r"):
            with self.subTest(quebra=quebra):
                head = _git(self.repo, "rev-parse", "HEAD")
                _commit_bytes(self.repo, "notas.md", b"cabecalho" + quebra + b"conta da acme-corp no relatorio\n")
                self.assertEqual(self._gate(base=head)[0], self.mod.FOUND)
                # sem commit (árvore de trabalho): a mesma linha de diff, lida pelo mesmo caminho
                _write(self.repo, "notas.md", b"cabecalho" + quebra + b"conta da rede-interna no relatorio\n")
                self.assertTrue(self._scan(), f"árvore de trabalho: termo depois de {quebra!r} não foi achado")

    def test_regra_do_brain_continua_valendo_caminho_de_maquina(self):
        _commit_bytes(self.repo, "instalacao.md", f"roda em {MACHINE_PATH}/brain\n")
        rules = {f["rule"] for f in self.mod.scan_range(self.repo, self.base, trusted=self.tmp)}
        self.assertIn("caminho da máquina", rules)

    def test_no_ci_regra_do_brain_sai_pelo_nome_uma_vez_e_sem_onde(self):
        # a regra é pública; o caminho, não — quem mantém vê onde com --detalhes, na própria máquina.
        # Duas ocorrências da mesma regra viram uma linha; regras diferentes saem em ordem alfabética
        _commit_bytes(self.repo, "instalacao.md", f"roda em {MACHINE_PATH}/brain\n")
        _commit_bytes(self.repo, "copia.md", f"copia em {MACHINE_PATH}/vault\n")
        _commit_bytes(self.repo, "cliente.md", "conta da acme-corp no relatorio\n")
        _commit_bytes(self.repo, "export.parquet", b"PAR1dados")
        code, out = self._gate()
        self.assertEqual(code, self.mod.FOUND)
        self.assertIn(OCULTO, out)
        self.assertEqual(out.splitlines()[3:], [
            f"  ✗ {self.mod.OPAQUE_RULE} — {self.mod.NO_WHERE}", f"  ✗ caminho da máquina — {self.mod.NO_WHERE}"])
        for arquivo in ("instalacao.md", "copia.md", "cliente.md", "export.parquet"):
            self.assertNotIn(arquivo, out)
        code, det = self._gate(detalhes=True)
        for arquivo in ("instalacao.md", "copia.md", "export.parquet"):
            self.assertIn(arquivo, det)

    def test_lista_privada_e_regra_da_instancia_somam(self):
        restore = self.mod.install_denylist(["acme-corp"])
        try:
            kinds = {kind for _, kind in upstream._leak_terms(config.load(self.tmp))}
        finally:
            upstream._leak_terms = restore
        self.assertIn(self.mod.KIND, kinds)

    def test_lista_privada_sem_termo_valido_e_erro_nao_limpo(self):
        _commit_bytes(self.repo, "notas.md", "diff limpo\n")            # o erro é da lista, não do diff
        out = io.StringIO()
        sem_termo = (("ausente", None), ("vazia", ""), ("só termo curto", "e:\nab\n"),
                     ("toda em comentário", "# tudo comentado, nada vale\n"),
                     ("termo curto ao lado de um válido", "acme-corp\nab\n"))
        for n, (rotulo, texto) in enumerate(sem_termo):
            path = self.tmp / f"lista-{n}"
            if texto is not None:
                path.write_text(texto, encoding="utf-8")
            with self.subTest(lista=rotulo), mock.patch("sys.stdout", out):
                code = self.mod.main(["gate", "--base", self.base, "--root", str(self.repo),
                                      "--denylist", str(path)], trusted=self.tmp)
            saida = out.getvalue()
            out.seek(0)
            out.truncate()
            # a lista veio inteira em comentário, veio vazia ou perdeu um termo: o portão não atesta "limpo"
            self.assertEqual(code, self.mod.ERROR, rotulo)
            self.assertIn("✗ portão de dados: lista privada", saida, rotulo)
            self.assertNotIn("limpo", saida, rotulo)
            self.assertNotIn(path.name, saida, rotulo)                  # nem o caminho da lista sai

    def test_o_pr_nao_dita_as_regras_da_varredura(self):
        # um config/brain.toml inválido na árvore do repo varrido não muda nada: a configuração
        # (e os termos dela) vem do checkout confiável, não do que o PR põe no disco
        _commit_bytes(self.repo, "notas.md", "diff limpo\n")
        (self.repo / "config").mkdir()
        (self.repo / "config" / "brain.toml").write_text("isto nao é toml =\n", encoding="utf-8")
        self.assertEqual(self._gate()[0], self.mod.CLEAN)

    def test_sem_root_varre_a_pasta_de_onde_foi_chamado(self):
        # o padrão antigo era o repositório do script: chamado de outro checkout, varria o lugar
        # errado — o alcance ficava vazio e o portão dava "limpo" sem olhar o commit
        _commit_bytes(self.repo, "instalacao.md", f"roda em {MACHINE_PATH}/brain\n")
        deny = _denylist(self.tmp, "acme-corp\n")
        out = io.StringIO()
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            code = self._run(["gate", "--base", self.base, "--denylist", str(deny)], out)
        finally:
            os.chdir(cwd)
        self.assertEqual(code, self.mod.FOUND, out.getvalue())

    def test_base_invalida_e_erro_nao_limpo(self):
        code, out = self._gate(base="ref-que-nao-existe")
        self.assertEqual(code, self.mod.ERROR)
        self.assertIn("✗ portão de dados:", out)

    def test_anexo_fechado_e_achado_pelo_nome_ou_pela_assinatura(self):
        # o dado pode estar dentro do anexo, num formato que a varredura não abre: o arquivo em si é o
        # achado, pelo nome ou pela assinatura. Binário sem formato fechado, que o portão lê em bytes, não é.
        _commit_bytes(self.repo, "binario-comum", b"\x00\xff\xfe dado comum\x00")
        self.assertEqual(self._gate()[0], self.mod.CLEAN)
        fechados = {
            "relatorio.gz": gzip.compress(b"texto comum, sem termo nenhum\n"),
            "documento.pdf": b"texto comum que so carrega o nome de documento\n",
            "dados.bin": b"PK\x03\x04compactado, sem extensao que entregue",
            "clientes.parquet": b"PAR1texto comum que so carrega o nome de planilha",
            "backup.db": b"texto comum que so carrega o nome de banco",
            "caixaPostal.eml": b"From: alguem@example.invalid\n\n texto comum\n",
            "dump.dat": b"SQLite format 3\x00texto comum que so carrega a assinatura de banco",
            "pacote.dat": b"\x28\xb5\x2f\xfdtexto comum que so carrega a assinatura de zstd",
            "imagem.iso": b"texto comum que so carrega o nome de imagem de disco",
            "copia.backup": b"texto comum que so carrega o nome de copia de arquivo\n",
            "copia.bak": b"texto comum que so carrega o nome de copia .bak\n",
            "estado.dump": b"texto comum que so carrega o nome de dump de banco\n",
            "chave.p12": b"texto comum que so carrega o nome de keystore PKCS12\n",
            "chave.pfx": b"texto comum que so carrega o nome de keystore PKCS12 da Microsoft\n",
            "cofre.kdbx": b"texto comum que so carrega o nome de cofre de senhas\n",
            "mensagem.gpg": b"texto comum que so carrega o nome de texto cifrado com GPG\n",
            "mensagem.age": b"texto comum que so carrega o nome de texto cifrado com age\n",
            "banco.dat": b"PGDMPtexto comum que so carrega a assinatura de dump do PostgreSQL",
        }
        for nome, dado in fechados.items():
            with self.subTest(nome=nome):
                _commit_bytes(self.repo, nome, dado)
        code, out = self._gate(detalhes=True)
        self.assertEqual(code, self.mod.FOUND)
        self.assertIn("anexo fechado", out)
        for nome in fechados:
            self.assertIn(nome, out)
        self.assertNotIn("binario-comum", out)

    def test_anexo_fechado_apagado_no_mesmo_pr_ainda_e_achado(self):
        # o arquivo sai da árvore, mas o blob continua no histórico que o PR leva para a main
        _commit_bytes(self.repo, "clientes.xlsx", b"PK\x03\x04planilha")
        _git(self.repo, "rm", "-q", "clientes.xlsx")
        _git(self.repo, "commit", "-q", "-m", "apaga o anexo")
        code, out = self._gate(detalhes=True)
        self.assertEqual(code, self.mod.FOUND)
        self.assertIn("clientes.xlsx", out)

    def test_zlib_nao_tem_assinatura_e_ainda_e_anexo_fechado(self):
        # zlib só tem dois bytes de cabeçalho, e o dado comprimido com ele entrava como binário comum:
        # ilegível para a busca, sem nome nem assinatura que o entregasse
        import zlib
        _commit_bytes(self.repo, "dados/arquivo", zlib.compress("conta da acme-corp\n".encode(), 9))
        code, out = self._gate(detalhes=True)
        self.assertEqual(code, self.mod.FOUND)
        self.assertIn(self.mod.OPAQUE_RULE, out)
        # texto que começa, por acaso, com os dois bytes de um cabeçalho zlib não é anexo
        for texto in ("x = f(y)\nprint(x)\n", "hC é o começo\n", "(4) quarto item\n"):
            with self.subTest(texto=texto):
                self.assertTrue(self.mod._zlib_header(texto.encode()[:2]))   # o começo passa pelo cabeçalho
                head = _git(self.repo, "rev-parse", "HEAD")
                _commit_bytes(self.repo, "texto.txt", texto)
                self.assertEqual(self._gate(base=head)[0], self.mod.CLEAN)

    def test_texto_em_utf_16_e_utf_32_e_lido_como_texto(self):
        # arquivo "Unicode" do Windows e do Excel: entre uma letra e outra vem um byte zero, os trechos
        # legíveis somem e a busca de texto passava direto
        texto = "lista de clientes da acme-corp\natualizada em janeiro\n"
        for rotulo, dado in (("utf-16-le com BOM", b"\xff\xfe" + texto.encode("utf-16-le")),
                             ("utf-16-be com BOM", b"\xfe\xff" + texto.encode("utf-16-be")),
                             ("utf-16-le sem BOM", texto.encode("utf-16-le")),
                             ("utf-16-be sem BOM", texto.encode("utf-16-be")),
                             ("utf-32-le", b"\xff\xfe\x00\x00" + texto.encode("utf-32-le")),
                             ("utf-32-be", b"\x00\x00\xfe\xff" + texto.encode("utf-32-be"))):
            with self.subTest(codificacao=rotulo):
                head = _git(self.repo, "rev-parse", "HEAD")
                _commit_bytes(self.repo, "notas.txt", dado)
                code, out = self._gate(base=head)
                self.assertEqual(code, self.mod.FOUND, rotulo)
                self.assertNotIn("acme-corp", out)
        # texto largo sem termo nenhum não dá achado
        head = _git(self.repo, "rev-parse", "HEAD")
        _commit_bytes(self.repo, "limpo.txt", b"\xff\xfe" + "conta da marina-demo no relatorio\n".encode("utf-16"))
        self.assertEqual(self._gate(base=head)[0], self.mod.CLEAN)
        # binário de verdade não vira "texto" por acaso: continua lido em trechos legíveis
        head = _git(self.repo, "rev-parse", "HEAD")
        _commit_bytes(self.repo, "ruido", bytes(range(256)) * 8)
        self.assertEqual(self._gate(base=head)[0], self.mod.CLEAN)
        # sem commit, a varredura da árvore de trabalho lê do mesmo jeito
        _write(self.repo, "solto.txt", texto.encode("utf-16"))
        self.assertEqual([f["file"] for f in self._scan()], ["solto.txt [binário]"])

    def test_texto_forcado_a_binario_por_atributos_do_pr_e_lido_linha_a_linha(self):
        # `* -diff` num .gitattributes do próprio PR faz o git chamar de binário o que é texto: por
        # trechos legíveis, termo curto sozinho numa linha não aparecia
        _commit_bytes(self.repo, ".gitattributes", b"* -diff\n")
        _commit_bytes(self.repo, "notas.txt", b"acme\n")
        code, out = self._gate(terms="acme\n", detalhes=True)
        self.assertEqual(code, self.mod.FOUND, out)
        self.assertIn("notas.txt", out)

    def test_arquivo_existente_que_a_varredura_nao_consegue_ler_e_achado_nao_limpo(self):
        # o git diz "Binary files … differ", o arquivo existe no commit e a leitura dele falha: antes era
        # pulado em silêncio. Arquivo que o commit apaga (só o pai tem o conteúdo) não é achado deste commit.
        _commit_bytes(self.repo, "sombra", b"\x00dado\x00")
        with mock.patch.object(upstream, "_blob", return_value=None):
            achados = self.mod.scan_range(self.repo, self.base, trusted=self.tmp)
            head = _git(self.repo, "rev-parse", "HEAD")
            _git(self.repo, "rm", "-q", "sombra")
            _git(self.repo, "commit", "-q", "-m", "apaga")
            self.assertEqual(self.mod.scan_range(self.repo, head, trusted=self.tmp), [])
        self.assertEqual([(f["file"].split(" (commit")[0], f["rule"]) for f in achados],
                         [("sombra", upstream.UNREADABLE_BLOB_RULE)])

    def test_binario_grande_demais_e_achado_nao_limpo(self):
        # acima do limite o arquivo não é varrido: antes era pulado em silêncio — "limpo" por tamanho
        with mock.patch.object(upstream, "MAX_BLOB_BYTES", 1024):
            _commit_bytes(self.repo, "dentro", bytes(512))
            self.assertEqual(self._gate()[0], self.mod.CLEAN)
            head = _git(self.repo, "rev-parse", "HEAD")
            _commit_bytes(self.repo, "grande", bytes(4096))
            code, out = self._gate(base=head, detalhes=True)
            self.assertEqual(code, self.mod.FOUND, out)
            self.assertIn(upstream.BIG_BLOB_RULE, out)
            self.assertIn("grande", out)
            _write(self.repo, "pesado", bytes(4096))
            _write(self.repo, "leve", bytes(512))
            regras = {f["file"]: f["rule"] for f in self._scan()}
            self.assertEqual(regras, {"pesado": upstream.BIG_BLOB_RULE})

    # ---- autor e committer de cada commit ------------------------------------------------------

    def _publico(self) -> None:
        """A base já está no remoto: a identidade dos commits dela é pública por definição."""
        _git(self.repo, "update-ref", "refs/remotes/origin/main", self.base)

    def _base_publica(self) -> None:
        """Commits já no remoto, com identidades que a lista cobriria se fossem novas."""
        _commit_bytes(self.repo, "base.md", "base\n", author=("Marina Dev", "dev@acme-corp.com"))
        _commit_bytes(self.repo, "base2.md", "base\n", author=("Teste", "dev@example.invalid"))
        self.base = _git(self.repo, "rev-parse", "HEAD")
        self._publico()

    def test_commit_feito_com_a_identidade_do_trabalho_bloqueia(self):
        # é metadado: não passa pelo diff nem pela mensagem — nome e e-mail, de autor e de committer
        self._publico()
        self.assertEqual(self.mod.scan_range(self.repo, _git(self.repo, "rev-parse", "HEAD"), trusted=self.tmp), [])
        casos = (("e-mail no domínio da empresa", ("Marina Dev", "dev@acme-corp.com"), None),
                 ("empresa no nome", ("Acme-corp Dev", "dev@example.invalid"), None),
                 ("nome público, e-mail novo", ("Teste", "teste@rede-interna.com.br"), None),
                 ("só quem commitou é novo", ("Alguem Novo", "alguem@example.invalid"),
                  ("Outra Pessoa", "pessoa@acme-corp.com")))
        for n, (rotulo, autor, committer) in enumerate(casos):
            with self.subTest(caso=rotulo):
                head = _git(self.repo, "rev-parse", "HEAD")
                _commit_bytes(self.repo, "notas.md", f"linha do caso {n}\n", author=autor, committer=committer)
                self.assertEqual(self._gate(base=head)[0], self.mod.FOUND)

    def test_identidade_que_o_repositorio_ja_mostra_nao_e_achado(self):
        # quem mantém é termo da própria instância: se a identidade dele contasse, todo commit seria achado
        self._base_publica()
        ja_mostrada = (("a mesma identidade de um commit público", ("Marina Dev", "dev@acme-corp.com")),
                       ("nome já público com e-mail novo", ("Marina Dev", "marina@example.invalid")),
                       ("e-mail já público com nome novo", ("Alguem Novo", "dev@example.invalid")),
                       # a parte antes do @ do e-mail novo não entra: costuma trazer o nome de quem commita
                       ("parte local do e-mail novo com o termo", ("Zé", "pessoa.acme-corp@example.invalid")))
        for n, (rotulo, (nome, email)) in enumerate(ja_mostrada):
            with self.subTest(caso=rotulo):
                head = _git(self.repo, "rev-parse", "HEAD")
                _commit_bytes(self.repo, "notas.md", f"linha do caso {n}\n", author=(nome, email))
                self.assertEqual(self._gate(base=head), (self.mod.CLEAN, f"✓ portão de dados limpo em {head}..HEAD\n"), rotulo)
        # nome NOVO traz o termo: é achado mesmo com e-mail que o repositório já mostra
        head = _git(self.repo, "rev-parse", "HEAD")
        _commit_bytes(self.repo, "outro.md", "outro diff limpo\n", author=("Acme-corp Dev", "dev@example.invalid"))
        self.assertEqual(self._gate(base=head)[0], self.mod.FOUND)
        # identidade que já aparece em outra ref pública (outro branch) também é pública
        head = _git(self.repo, "rev-parse", "HEAD")
        _commit_bytes(self.repo, "lado.md", "commit de outro branch\n", author=("Fulano Novo", "fulano.novo@example.invalid"))
        _git(self.repo, "update-ref", "refs/remotes/origin/outro-branch", _git(self.repo, "rev-parse", "HEAD"))
        _git(self.repo, "reset", "-q", "--hard", head)
        _commit_bytes(self.repo, "principal.md", "commit novo com a mesma identidade\n",
                      author=("Fulano Novo", "fulano.novo@example.invalid"))
        self.assertEqual(self._gate(base=head)[0], self.mod.CLEAN)

    def test_alcance_do_hook_pre_push_o_lado_que_fica_fora_e_publico(self):
        # o hook varre `<novo> --not <já publicado>` (ou `^<publicado> <novo>`): o lado que fica fora do
        # alcance é público por definição, esteja ou não num remoto
        _commit_bytes(self.repo, "base.md", "base\n", author=("Acme-corp Dev", "dev@example.invalid"))
        antigo = _git(self.repo, "rev-parse", "HEAD")
        _commit_bytes(self.repo, "principal.md", "commit novo\n", author=("Acme-corp Dev", "dev@example.invalid"))
        novo = _git(self.repo, "rev-parse", "HEAD")
        termos = ("acme-corp", "rede-interna")
        alcances = ([novo, "--not", antigo], ["^" + antigo, novo], [antigo + ".." + novo])
        for revs in alcances:
            with self.subTest(alcance=" ".join(r[:7] for r in revs)):
                self.assertEqual(self._scan_commits(revs, termos), [])
        # controle: identidade que o alcance não mostra é achado nas três formas
        head = novo
        _commit_bytes(self.repo, "outra.md", "outro commit\n", author=("Rede-interna Dev", "dev@example.invalid"))
        novo = _git(self.repo, "rev-parse", "HEAD")
        for revs in ([novo, "--not", head], ["^" + head, novo], [head + ".." + novo]):
            with self.subTest(alcance=" ".join(r[:7] for r in revs)):
                self.assertTrue(self._scan_commits(revs, termos))

    def test_identidade_nova_aparece_no_detalhe_e_o_valor_nunca(self):
        self._publico()
        _commit_bytes(self.repo, "notas.md", "diff limpo\n", author=("Marina Dev", "dev@acme-corp.com"))
        code, out = self._gate(detalhes=True)
        self.assertEqual(code, self.mod.FOUND)
        self.assertRegex(out, _onde("(identidade do commit 1: autor)", 0, self.mod.PRIVATE_RULE))
        self.assertNotIn("acme-corp", out)
        self.assertNotIn("Marina", out)
        self.assertNotIn("(identidade", self._gate()[1])                 # no CI, nem onde

    # ---- status de commit na ponta do PR -------------------------------------------------------

    SHA = "a" * 40
    CONTEXTO = {"GITHUB_TOKEN": "token-falso-do-job", "GITHUB_API_URL": "https://api.github.com",
                "GITHUB_REPOSITORY": "dono/repo"}
    RUN = "https://github.com/dono/repo/actions/runs/1"

    def _status(self, rc: str, sha: str = SHA, env: dict | None = None, side_effect=None) -> tuple[int, str, list]:
        pedidos: list = []

        def abrir(req, timeout):
            pedidos.append(req)
            if side_effect is not None:
                raise side_effect
            resp = mock.Mock()
            resp.status = 201
            resp.__enter__ = lambda s: s
            resp.__exit__ = lambda s, *exc: False
            return resp

        out = io.StringIO()
        with mock.patch.dict(os.environ, self.CONTEXTO if env is None else env, clear=True), \
                mock.patch.object(self.mod.urllib.request, "urlopen", abrir):
            code = self._run(["status", "--sha", sha, "--rc", rc, "--run", self.RUN], out)
        return code, out.getvalue(), pedidos

    def test_status_publica_o_resultado_do_portao_na_ponta_do_pr(self):
        # é este status que a proteção da main exige: PR de fork não tem token de escrita, não
        # consegue emitir um igual — diferente do check run, que casa pelo nome
        self.assertEqual(self.mod.STATUS_CONTEXT, "data-gate (status)")
        fixos = {texto for _, texto in self.mod.STATUS_TEXT.values()}
        fixos.add("erro: o portão não rodou até o fim — não atesta nada desta ponta")
        for rc, estado in (("0", "success"), ("4", "failure"), ("", "error"), ("1", "error"), ("x", "error")):
            with self.subTest(rc=rc):
                code, out, pedidos = self._status(rc)
                self.assertEqual(out, f"✓ status `data-gate (status)`: {estado}\n")
                self.assertEqual(code, self.mod.CLEAN)
                self.assertEqual(len(pedidos), 1)
                req = pedidos[0]
                self.assertEqual(req.full_url, f"https://api.github.com/repos/dono/repo/statuses/{self.SHA}")
                self.assertEqual(req.get_method(), "POST")
                self.assertEqual(req.get_header("Authorization"), "Bearer token-falso-do-job")
                corpo = json.loads(req.data)
                self.assertEqual((corpo["state"], corpo["context"], corpo["target_url"]),
                                 (estado, "data-gate (status)", self.RUN))
                self.assertIn(corpo["description"], fixos)              # texto fixo: nada do PR vai no status

    def test_status_sem_token_sem_contexto_ou_com_sha_errado_nao_publica_nada(self):
        sem = {k: v for k, v in self.CONTEXTO.items() if k != "GITHUB_REPOSITORY"}
        for rc, sha, env in (("0", "abc", None), ("0", "a" * 41, None),
                             ("0", self.SHA, {**self.CONTEXTO, "GITHUB_TOKEN": ""}),
                             ("0", self.SHA, sem),
                             ("0", self.SHA, {**self.CONTEXTO, "GITHUB_REPOSITORY": "dono/repo/extra"}),
                             ("0", self.SHA, {**self.CONTEXTO, "GITHUB_API_URL": "http://api.github.com"})):
            with self.subTest(rc=rc, sha=sha[:6], env=sorted(env or self.CONTEXTO)):
                code, out, pedidos = self._status(rc, sha=sha, env=env)
                self.assertEqual((code, pedidos), (self.mod.ERROR, []))
                self.assertIn("nada publicado", out)

    def test_status_que_a_api_recusa_e_erro_do_job(self):
        # sem o status publicado a ponta do PR fica sem o que a proteção exige: o passo tem de falhar
        for falha, esperado in ((urllib.error.HTTPError(self.RUN, 403, "Forbidden", None, None), "HTTP 403"),
                                (urllib.error.URLError("sem rede"), "URLError")):
            with self.subTest(falha=type(falha).__name__):
                code, out, pedidos = self._status("0", side_effect=falha)
                self.assertEqual((code, len(pedidos)), (self.mod.ERROR, 1))
                self.assertIn(esperado, out)
                self.assertNotIn("token-falso", out)


if __name__ == "__main__":
    unittest.main()
