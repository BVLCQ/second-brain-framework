"""One-pager de oportunidade no Google Docs (porta 6): Resumo em tabelas + Detalhamento.

Duas metades com donos diferentes:
- **Resumo** — duas tabelas derivadas do ledger (área/tipo/status; problema, sugestão, ganho, prioridade, relacionado,
  arquivos, fontes). É do cérebro: o agente reescreve sem pedir aprovação sempre que o Brain muda. Cada célula de valor
  é um intervalo nomeado `brain:<campo>`, então a atualização é `replaceNamedRangeContent` — sem aritmética de índice.
- **Detalhamento** — escrito pelo agente na criação (proposta de solução, procedimentos, o que fazer e não fazer, e a
  Timeline — decisões e conversas, na ordem em que aconteceram — como último tópico); depois disso é de quem edita no
  Drive: o agente só deixa sugestões.

Quem lê o one-pager não tem acesso ao Brain: todo ID aparece como `ID: Título` e, sendo de oportunidade com one-pager,
vira link para ele (`expand`, `expand_detail`, `links`). Reunião entra só como dia + participantes — nunca a transcrição.

Se alguém mexeu no Resumo e o texto do doc diverge do Brain, o cérebro não sobrescreve: vira pergunta (`ASK-####`).
Este módulo só monta texto e pedidos `documents.batchUpdate`; quem chama o Docs é o agente, pelo MCP.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import model, share, util

RANGE = "brain:"                    # prefixo dos intervalos nomeados que o cérebro mantém
STAMP = "carimbo"
HEAD = [("area", "Área"), ("tipo", "Tipo"), ("status", "Status")]
BODY = [("problema", "Problema"), ("sugestao", "Sugestão"), ("ganho", "Ganho esperado"), ("prioridade", "Prioridade"),
        ("relacionado", "Relacionado"), ("arquivos", "Arquivos relacionados"), ("fontes", "Fontes (para auditoria)")]
KEYS = [k for k, _ in HEAD + BODY]
LABEL = dict(HEAD + BODY)
NONE = "não consta"
# padrão de tabela (marca da instância, `[oppdrive.brand]`): cabeçalho/rótulo na cor da marca com texto branco em
# negrito; corpo preto 10 pt; bordas cinza. Sem `brand` no config, um padrão neutro.
def _rgb(hexa: str) -> dict:
    return {"color": {"rgbColor": {k: round(int(hexa[i:i + 2], 16) / 255, 4) for k, i in (("red", 0), ("green", 2), ("blue", 4))}}}


BRAND = {"header": "1F3A5F", "border": "CCCCCC", "font": "Arial"}
WHITE, BLACK = _rgb("FFFFFF"), _rgb("000000")
HEAD_BG, BORDER, FONT = _rgb(BRAND["header"]), _rgb(BRAND["border"]), BRAND["font"]


def use_brand(cfg: dict | None) -> None:
    """Aplica `[oppdrive.brand]` (header/border = hex sem #, font = família do Google Docs) aos pedidos de estilo."""
    global HEAD_BG, BORDER, FONT
    b = {**BRAND, **(cfg or {})}
    HEAD_BG, BORDER, FONT = _rgb(str(b["header"]).lstrip("#")), _rgb(str(b["border"]).lstrip("#")), str(b["font"])
LABEL_WIDTH = 130                   # pt — coluna de rótulos da tabela 2 (o resto do corpo da página fica com o valor)


ID_RE = re.compile(r"\b(OPP|PROC|TASK|DEC|WIN|PROP)-(\d{4})\b")   # IDs zero-padded são do Brain (PROJ-1 pode ser do Jira)
NO_LINK_KINDS = ("pasta", "one-pager", "fontes", "fonte")             # docs ligados que não são "arquivo relacionado"
MEETING = {"reuniao", "reunião"}
DOC_URL = "https://docs.google.com/document/d/{}/edit"
FILE_URL = "https://drive.google.com/file/d/{}/view"


def entity_title(b, eid: str) -> str:
    st = b.state
    coll = {"OPP": st.opportunities, "PROC": st.processes, "TASK": st.actions, "DEC": st.decisions,
            "WIN": st.deliveries, "PROP": st.proposals}[eid.split("-")[0]]
    e = coll.get(eid)
    return (getattr(e, "title", None) or getattr(e, "summary", "") or "") if e else ""


def label(b, eid: str) -> str:
    """`ID: Título` — quem lê o one-pager não tem o Brain, então ID sozinho não diz nada."""
    t = entity_title(b, eid)
    return f"{eid}: {t}" if t else eid


def onepager_url(b, oid: str) -> str | None:
    o = b.state.opportunities.get(oid)
    d = next((d for d in (o.docs if o else []) if d.kind == "one-pager" and d.ref), None)
    return DOC_URL.format(d.ref) if d else None


def expand(b, text: str) -> str:
    """Todo ID do Brain no texto vira `ID: Título` (o que já vem assim fica como está)."""
    def sub(m):
        t = entity_title(b, m.group(0))
        if not t or text[m.end():m.end() + 2 + len(t)] == f": {t}":
            return m.group(0)
        return f"{m.group(0)}: {t}"
    return ID_RE.sub(sub, text)


_MD_ID = re.compile(r"(\[[^\]]*\]\([^)]*\))|" + ID_RE.pattern)


def expand_detail(b, detail: str) -> str:
    """Detalhamento em Markdown: ID vira `ID: Título` e, sendo OPP com one-pager, `[ID: Título](url)`. Links que o agente
    já escreveu ficam como estão; OPP sem one-pager fica só `ID: Título`."""
    out, pos = [], 0
    for m in _MD_ID.finditer(detail):
        out.append(detail[pos:m.start()])
        pos = m.end()
        if m.group(1):
            out.append(m.group(1))
            continue
        eid = m.group(0)
        t = entity_title(b, eid)
        if t and detail.startswith(f": {t}", pos):
            pos += 2 + len(t)
        text = f"{eid}: {t}" if t else eid
        url = onepager_url(b, eid) if eid.startswith("OPP") else None
        out.append(f"[{text}]({url})" if url else text)
    out.append(detail[pos:])
    return "".join(out)


def uploaded(b, o) -> dict[str, str]:
    """{nome do arquivo RAW: id do arquivo na pasta Fontes} — o que a porta já subiu para esta OPP."""
    return {d.title: d.ref for d in o.docs if d.kind == "fonte"}


def source_line(b, o, path: str) -> str:
    """Uma fonte como o leitor do one-pager a entende: reunião = dia + participantes (nunca a transcrição); documento
    = título e data (e, se subiu para a pasta Fontes, o arquivo está lá)."""
    st = b.state
    a = st.artifacts.get((path or "").split("#")[0])
    if not a:
        return model.ModelBuilder(b).source_label(path)
    title = re.sub(r"\s*[—-]\s*\d{2}/\d{2}/\d{4}$", "", a.title)
    when = a.date.strftime("%d/%m/%Y") if a.date else ""
    if a.kind in MEETING or "/meetings/" in a.raw:
        names = ", ".join(st.person_name(p) for p in a.people)
        return f"Reunião {title} — {when}" + (f" · participantes: {names}" if names else "")
    return f"{title} ({when})" if when else title


def fields(b, oid: str) -> tuple[str, dict]:
    """(título, {campo: texto}) — o Resumo como o Brain o vê agora. Mesma base do `share opportunity`."""
    title, sections, sources = share._sections_opportunity(b, model.build(b), oid)
    sec = {name: items for name, items in sections}
    o = b.state.opportunities[oid]
    area = re.search(r"\*\*Área:\*\* (.*?) · \*\*Tipo:\*\* (.*?) · \*\*Status:\*\* (.*)$", sec[""][0])
    related = [f"{d.title or d.ref} — {d.ref}" for d in o.docs if d.kind not in NO_LINK_KINDS]
    rel = [ln.replace("Processo: ", f"Processo — {o.process}: ", 1) if o.process and ln.startswith("Processo: ") else
           ln.replace("Entregável: ", f"Entregável — {o.deliverable}: ", 1) if o.deliverable and ln.startswith("Entregável: ") else
           ln.replace("Projeto: ", f"Projeto — {o.project}: ", 1) if o.project and ln.startswith("Projeto: ") else ln
           for ln in sec["Relacionado"]]
    src = [f"origem: {source_line(b, o, o.source)}"] + [f"evidência: {source_line(b, o, e)}" for e in o.evidence]
    out = {"area": area.group(1), "tipo": area.group(2), "status": area.group(3),
           "problema": sec["Problema"], "sugestao": sec["Sugestão"], "ganho": sec["Ganho esperado"],
           "prioridade": sec["Prioridade"], "relacionado": rel, "arquivos": related, "fontes": src}
    return title, {k: expand(b, "\n".join(v) if isinstance(v, list) else v or NONE) or NONE for k, v in out.items()}


def links(b, oid: str, f: dict) -> dict[str, str]:
    """{texto: url} do que, no Resumo, deve ser link: OPP com one-pager (`OPP-0023: Título`) e documento já enviado à
    pasta Fontes. Texto que o doc mostra exatamente assim; a própria OPP não se linka."""
    o = b.state.opportunities[oid]
    text = "\n".join(f.values())
    out = {}
    for m in re.finditer(r"\bOPP-\d{4}\b", text):
        if m.group(0) != oid and (url := onepager_url(b, m.group(0))):
            out[label(b, m.group(0))] = url
    up = uploaded(b, o)
    for path in [o.source, *o.evidence]:
        a = b.state.artifacts.get((path or "").split("#")[0])
        fid = up.get(Path(a.raw).name) if a and a.raw else None
        if fid and (line := source_line(b, o, path)) in text:
            out[line] = FILE_URL.format(fid)
    return out


def stamp() -> str:
    return f"Resumo atualizado em {util.now().strftime('%d/%m/%Y %H:%M')}"


def norm(s: str | None) -> str:
    """Texto comparável: sem marcação Markdown, escapes, marcadores de lista nem diferença de espaço."""
    s = re.sub(r"<br\s*/?>", "\n", s or "", flags=re.I)
    s = re.sub(r"\[([^\]]*)\]\(([^)]*)\)", r"\1 \2", s)
    for _ in range(3):                                   # exports diferentes escapam em camadas (`\\\#`)
        s = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|>~])", r"\1", s)
    s = s.replace("**", "").replace("__", "")
    s = re.sub(r"(^|\n)\s*(?:[-*•]|\d+[.)])\s+", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


# ── Markdown (prévia local e fallback com a porta desligada) ─────────────────────────────────────────────────────
def markdown(title: str, oid: str, f: dict, detail: str | None, lk: dict | None = None) -> str:
    def cell(s: str) -> str:
        for text, url in sorted((lk or {}).items(), key=lambda kv: -len(kv[0])):
            s = s.replace(text, f"[{text}]({url})")
        return s.replace("|", "\\|").replace("\n", "<br>")
    out = [f"# {oid}: {title}", f"_{stamp()}_", "", "## Resumo", "",
           "| " + " | ".join(lab for _, lab in HEAD) + " |", "|" + " --- |" * len(HEAD),
           "| " + " | ".join(cell(f[k]) for k, _ in HEAD) + " |", "", "| | |", "| --- | --- |"]
    out += [f"| **{lab}** | {cell(f[k])} |" for k, lab in BODY]
    out += ["", "## Detalhamento", "", (detail or "_(o agente escreve na criação)_").strip(), ""]
    return "\n".join(out)


def parse_markdown(text: str) -> dict:
    """{campo: texto} do Resumo num export Markdown do doc (snapshot do /update). Vazio = resumo não encontrado."""
    rows = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", ln.strip("|"))]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        rows.append(cells)
    by_label = {norm(lab).lower(): k for k, lab in HEAD + BODY}
    out = {}
    for i, cells in enumerate(rows):
        keys = [by_label.get(norm(c).lower()) for c in cells]
        if keys and all(k in dict(HEAD) for k in keys) and i + 1 < len(rows):
            out.update({k: v for k, v in zip(keys, rows[i + 1])})
        elif len(cells) >= 2 and keys[0] in dict(BODY):
            out[keys[0]] = cells[1]
    return out


# ── pedidos documents.batchUpdate ───────────────────────────────────────────────────────────────────────────────────
def u16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _inline(text: str) -> tuple[str, list]:
    """`**negrito**` e `[texto](url)` → (texto puro, [(início, fim, 'bold' | url)]) em unidades UTF-16."""
    plain, marks, pos = "", [], 0
    text = re.sub(r"`([^`]+)`", r"\1", text)          # sem fonte mono no Docs: `código` vira texto
    for m in re.finditer(r"\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)\s]+)\)", text):
        plain += text[pos:m.start()]
        inner = m.group(1) or m.group(2)
        a = u16(plain)
        plain += inner
        marks.append((a, u16(plain), "bold" if m.group(1) else m.group(3)))
        pos = m.end()
    return plain + text[pos:], marks


def blocks(detail: str) -> list[tuple[str, str]]:
    """Markdown simples do Detalhamento → [(tipo, texto)]: h3/h4, p, ul, ol (itens seguidos do mesmo tipo juntos)."""
    out: list[tuple[str, str]] = []
    para: list[str] = []

    def flush():
        if para:
            out.append(("p", " ".join(para)))
            para.clear()
    for raw in detail.splitlines():
        ln = raw.strip()
        m_h = re.match(r"(#{1,6})\s+(.*)", ln)
        m_ul = re.match(r"[-*•]\s+(.*)", ln)
        m_ol = re.match(r"\d+[.)]\s+(.*)", ln)
        if not ln:
            flush()
        elif m_h:
            flush()
            out.append(("h3" if len(m_h.group(1)) <= 3 else "h4", m_h.group(2).strip("# ")))
        elif m_ul or m_ol:
            flush()
            kind, item = ("ul", m_ul.group(1)) if m_ul else ("ol", m_ol.group(1))
            if out and out[-1][0] == kind:
                out[-1] = (kind, out[-1][1] + "\n" + item)
            else:
                out.append((kind, item))
        else:
            para.append(ln)
    flush()
    return out


STYLE = {"h1": "HEADING_1", "h2": "HEADING_2", "h3": "HEADING_3", "h4": "HEADING_4", "p": "NORMAL_TEXT",
         "ul": "NORMAL_TEXT", "ol": "NORMAL_TEXT", "meta": "NORMAL_TEXT"}
PRESET = {"ul": "BULLET_DISC_CIRCLE_SQUARE", "ol": "NUMBERED_DECIMAL_ALPHA_ROMAN"}


class _Plan:
    """Monta o documento de baixo para cima, sempre inserindo no índice 1: o que já entrou só desce, então todo índice
    usado num pedido é conhecido na hora (nada de reler o doc entre um passo e outro)."""

    def __init__(self):
        self.reqs: list[dict] = []
        self.below = {"style": "NORMAL_TEXT", "list": False, "styled": True}   # o parágrafo vazio final pode ter herança

    def _rng(self, a: int, z: int) -> dict:
        return {"startIndex": a, "endIndex": z}

    def para(self, kind: str, text: str, named: str | None = None) -> None:
        plain, marks = _inline(text)
        n = u16(plain) + 1
        r = self.reqs
        r.append({"insertText": {"location": {"index": 1}, "text": plain + "\n"}})
        if self.below["style"] != STYLE[kind] or kind == "meta":
            r.append({"updateParagraphStyle": {"range": self._rng(1, 1 + n), "paragraphStyle": {"namedStyleType": STYLE[kind]},
                                               "fields": "namedStyleType"}})
        if self.below["styled"] or kind == "meta":
            r.append({"updateTextStyle": {"range": self._rng(1, 1 + n), "textStyle": {"italic": kind == "meta"},
                                          "fields": "bold,italic,link"}})
        if kind in PRESET:
            r.append({"createParagraphBullets": {"range": self._rng(1, n), "bulletPreset": PRESET[kind]}})
        elif self.below["list"]:
            r.append({"deleteParagraphBullets": {"range": self._rng(1, 1 + n)}})
        for a, z, what in marks:
            style, flds = ({"bold": True}, "bold") if what == "bold" else ({"link": {"url": what}}, "link")
            r.append({"updateTextStyle": {"range": self._rng(1 + a, 1 + z), "textStyle": style, "fields": flds}})
        if named:
            r.append({"createNamedRange": {"name": RANGE + named, "range": self._rng(1, n)}})
        self.below = {"style": STYLE[kind], "list": kind in PRESET, "styled": kind == "meta" or bool(marks and marks[0][0] == 0)}

    def table(self, rows: list[list[tuple[str, str | None, bool]]], shade: list[tuple[int, int]],
              lk: dict | None = None) -> None:
        """rows[r][c] = (texto, intervalo nomeado | None, negrito). Insere num parágrafo normal e vazio (os parágrafos
        das células herdam dele), preenche de trás para frente e aplica o padrão de tabela (`style_table`)."""
        self.para("p", "")
        rr, cc = len(rows), len(rows[0])
        self.reqs.append({"insertTable": {"rows": rr, "columns": cc, "location": {"index": 1}}})
        start = 2                                         # o Docs põe um "\n" antes da tabela
        link_reqs: list[dict] = []
        for r in reversed(range(rr)):
            for c in reversed(range(cc)):
                text, named, bold = rows[r][c]
                p = start + 3 + r * (2 * cc + 1) + 2 * c
                self.reqs.append({"insertText": {"location": {"index": p}, "text": text}})
                if bold:
                    self.reqs.append({"updateTextStyle": {"range": self._rng(p, p + u16(text)), "textStyle": {"bold": True},
                                                          "fields": "bold"}})
                if named:
                    self.reqs.append({"createNamedRange": {"name": RANGE + named, "range": self._rng(p, p + u16(text))}})
                link_reqs += link_text(text, p, lk or {})
        cells, at = [], start + 1
        for r in range(rr):
            at += 1                                       # marcador da linha
            row = []
            for c in range(cc):
                n = u16(rows[r][c][0])
                row.append((at + 1, at + 1 + n))          # marcador da célula + texto (sem o "\n" final)
                at += 2 + n
            cells.append(row)
        self.reqs += style_table(start, cells, set(shade), label_col=cc == 2) + link_reqs   # depois: o estilo da tabela pinta o texto
        self.reqs += shrink(at + 1) + shrink(1)            # o vazio depois da tabela e o "\n" que o Docs pôs antes
        self.below = {"style": "NORMAL_TEXT", "list": False, "styled": False}


LINK_BLUE = _rgb("1155CC")


def link_style(url: str) -> dict:
    return {"textStyle": {"link": {"url": url}, "foregroundColor": LINK_BLUE, "underline": True},
            "fields": "link,foregroundColor,underline"}


def link_text(text: str, base: int, lk: dict) -> list[dict]:
    """Pedidos de link para cada `texto` de `lk` dentro de `text`, que começa no índice `base` do doc."""
    out = []
    for label_, url in lk.items():
        for m in re.finditer(re.escape(label_), text):
            a = base + u16(text[:m.start()])
            out.append({"updateTextStyle": {"range": {"startIndex": a, "endIndex": a + u16(label_)}, **link_style(url)}})
    return out


def _body(doc: dict) -> list:
    inner = doc.get("content", doc)
    return ((inner.get("tabs") or [{}])[0].get("documentTab", {}).get("body", {}).get("content")
            if "tabs" in inner else inner.get("body", {}).get("content", [])) or []


def link_requests(doc: dict, lk: dict) -> list[dict]:
    """Links do Resumo de um doc já escrito (JSON do `read_doc`): o texto de `lk` que ainda não é link para aquela URL,
    só dentro das duas tabelas — o Detalhamento é de quem edita e não se toca."""
    out = []
    for e in [e for e in _body(doc) if "table" in e][:2]:
        for row in e["table"]["tableRows"]:
            for cell in row["tableCells"]:
                for para in cell["content"]:
                    for el in para.get("paragraph", {}).get("elements", []):
                        run = el.get("textRun")
                        if not run:
                            continue
                        have = (run.get("textStyle") or {}).get("link", {}).get("url")
                        if have and lk.get(run["content"].rstrip("\n")) == have:
                            continue                      # o trecho todo já é o link certo
                        if have:                          # texto novo herdou o link de quem ele substituiu: limpa e refaz
                            out.append({"updateTextStyle": {"range": {"startIndex": el["startIndex"], "endIndex": el["endIndex"]},
                                                            "textStyle": {"foregroundColor": BLACK, "underline": False},
                                                            "fields": "link,foregroundColor,underline"}})
                        out += link_text(run["content"], el["startIndex"], lk)
    return out


def style_table(start: int, cells: list[list[tuple[int, int]]], heads: set, label_col: bool = False) -> list[dict]:
    """Pedidos do padrão de tabela (`use_brand`) para uma tabela já preenchida. `cells[r][c]` = (início, fim) do texto da célula;
    `heads` = células de cabeçalho/rótulo."""
    loc = {"index": start}
    edge = {"color": BORDER, "width": {"magnitude": 0.5, "unit": "PT"}, "dashStyle": "SOLID"}
    pad = lambda v: {"magnitude": v, "unit": "PT"}   # noqa: E731
    out = [{"updateTableCellStyle": {"tableStartLocation": loc, "tableCellStyle": {
        "backgroundColor": WHITE, "borderTop": edge, "borderBottom": edge, "borderLeft": edge, "borderRight": edge,
        "paddingTop": pad(4), "paddingBottom": pad(4), "paddingLeft": pad(6), "paddingRight": pad(6),
        "contentAlignment": "MIDDLE"},
        "fields": "backgroundColor,borderTop,borderBottom,borderLeft,borderRight,paddingTop,paddingBottom,paddingLeft,"
                  "paddingRight,contentAlignment"}}]
    rows_, cols_ = {r for r, _ in heads}, {c for _, c in heads}   # cabeçalho = uma faixa (linha 0 ou coluna 0)
    out.append({"updateTableCellStyle": {
        "tableRange": {"tableCellLocation": {"tableStartLocation": loc, "rowIndex": min(rows_), "columnIndex": min(cols_)},
                       "rowSpan": len(rows_), "columnSpan": len(cols_)},
        "tableCellStyle": {"backgroundColor": HEAD_BG}, "fields": "backgroundColor"}})
    text = {"startIndex": cells[0][0][0], "endIndex": cells[-1][-1][1]}      # do 1º ao último texto: a tabela toda
    out.append({"updateTextStyle": {"range": text, "textStyle": {
        "bold": False, "italic": False, "foregroundColor": BLACK, "fontSize": pad(10), "weightedFontFamily": {"fontFamily": FONT}},
        "fields": "bold,italic,foregroundColor,fontSize,weightedFontFamily"}})
    out.append({"updateParagraphStyle": {"range": text, "paragraphStyle": {
        "alignment": "JUSTIFIED", "spaceAbove": pad(0), "spaceBelow": pad(0)}, "fields": "alignment,spaceAbove,spaceBelow"}})
    for r, c in sorted(heads):
        a, z = cells[r][c]
        out.append({"updateTextStyle": {"range": {"startIndex": a, "endIndex": z},
                                        "textStyle": {"bold": True, "foregroundColor": WHITE}, "fields": "bold,foregroundColor"}})
        out.append({"updateParagraphStyle": {"range": {"startIndex": a, "endIndex": z + 1},
                                             "paragraphStyle": {"alignment": "START"}, "fields": "alignment"}})
    if label_col:
        out.append({"updateTableColumnProperties": {"tableStartLocation": loc, "columnIndices": [0], "tableColumnProperties": {
            "widthType": "FIXED_WIDTH", "width": pad(LABEL_WIDTH)}, "fields": "widthType,width"}})
    return out


def shrink(at: int, n: int = 1) -> list[dict]:
    """O(s) parágrafo(s) vazio(s) que o Docs exige em volta de uma tabela viram um respiro mínimo."""
    rng = {"startIndex": at, "endIndex": at + n}
    return [{"updateParagraphStyle": {"range": rng, "paragraphStyle": {
                "spaceAbove": {"magnitude": 0, "unit": "PT"}, "spaceBelow": {"magnitude": 0, "unit": "PT"}, "lineSpacing": 100},
                "fields": "spaceAbove,spaceBelow,lineSpacing"}},
            {"updateTextStyle": {"range": rng, "textStyle": {"fontSize": {"magnitude": 6, "unit": "PT"}}, "fields": "fontSize"}}]


def restyle_requests(doc: dict) -> list[dict]:
    """Aplica o padrão às duas tabelas do Resumo de um doc já escrito (JSON do `read_doc`). A tabela de 3 colunas tem
    cabeçalho na 1ª linha; a de 2 colunas, rótulos na 1ª coluna."""
    content = _body(doc)
    tables = [e for e in content or [] if "table" in e][:2]
    if len(tables) < 2:
        raise ValueError("o doc não tem as duas tabelas do Resumo")
    out = []
    for e in tables:
        t = e["table"]
        cells = [[(cl["content"][0]["startIndex"], cl["endIndex"] - 1) for cl in row["tableCells"]] for row in t["tableRows"]]
        heads = ({(0, c) for c in range(t["columns"])} if t["columns"] == 3 else {(r, 0) for r in range(t["rows"])})
        out += style_table(e["startIndex"], cells, heads, label_col=t["columns"] == 2)
    empty = {e["startIndex"] for e in content if "paragraph" in e and
             "".join(x.get("textRun", {}).get("content", "") for x in e["paragraph"]["elements"]) == "\n"}
    around = {tables[0]["startIndex"] - 1, tables[0]["endIndex"], tables[0]["endIndex"] + 1, tables[1]["endIndex"]}
    runs: list[list[int]] = []
    for at in sorted(empty & around):
        if runs and runs[-1][0] + runs[-1][1] == at:
            runs[-1][1] += 1
        else:
            runs.append([at, 1])
    for at, n in runs:
        out += shrink(at, n)
    return out


def build_requests(title: str, oid: str, f: dict, detail: str, end: int, lk: dict | None = None) -> list[dict]:
    """Pedidos que (re)escrevem o doc inteiro: apaga o corpo atual (`end` = endIndex do último elemento do corpo,
    do `read_doc`; 2 = doc vazio) e monta título, carimbo, Resumo (2 tabelas) e Detalhamento."""
    pl = _Plan()
    for kind, text in reversed(blocks(detail)):
        pl.para(kind, text)
    pl.para("h2", "Detalhamento")
    pl.table([[(LABEL[k], None, True), (f[k], k, False)] for k, _ in BODY], [(r, 0) for r in range(len(BODY))], lk)
    pl.table([[(lab, None, True) for _, lab in HEAD], [(f[k], k, False) for k, _ in HEAD]], [(0, c) for c in range(len(HEAD))], lk)
    pl.para("h2", "Resumo")
    pl.para("meta", stamp(), named=STAMP)
    pl.para("h1", f"{oid}: {title}")
    head: list[dict] = []
    if end > 2:
        head.append({"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end - 1}}})
    head += [{"deleteParagraphBullets": {"range": {"startIndex": 1, "endIndex": 2}}},
             {"updateParagraphStyle": {"range": {"startIndex": 1, "endIndex": 2},
                                       "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"}, "fields": "namedStyleType"}}]
    return head + pl.reqs


def sync_requests(f: dict, keys: list[str]) -> list[dict]:
    reqs = [{"replaceNamedRangeContent": {"namedRangeName": RANGE + k, "text": f[k]}} for k in keys if k in KEYS]
    return reqs + [{"replaceNamedRangeContent": {"namedRangeName": RANGE + STAMP, "text": stamp()}}] if reqs else []


def same(a: str | None, b: str | None) -> bool:
    """Igualdade de conteúdo: cada export do Docs quebra linha (ou não) de um jeito dentro da célula."""
    return re.sub(r"\s+", "", norm(a)) == re.sub(r"\s+", "", norm(b))


def compare(brain: dict, last: dict | None, doc: dict | None) -> dict:
    """Estado do Resumo. `last` = o que o cérebro escreveu por último (ledger); `doc` = o que o doc diz agora (export)."""
    if not last:
        return {"state": "template-antigo", "changed": KEYS, "divergent": []}
    if doc is not None and not doc:
        return {"state": "resumo-ausente", "changed": [], "divergent": []}
    doc = doc or {}
    edited = [k for k in KEYS if k in doc and not same(doc[k], last.get(k))]
    divergent = [k for k in edited if not same(doc[k], brain[k])]
    changed = [k for k in KEYS if not same(brain[k], last.get(k)) and k not in edited]
    state = "divergente" if divergent else "desatualizado" if changed else "ok"
    return {"state": state, "changed": changed, "divergent": divergent, "edited": edited}
