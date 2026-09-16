#!/usr/bin/env python3
"""Conector Google Drive/Docs — pull-only, read-only, via OAuth.

Uso (noturno, watchlist gdocs: do watch.yaml):
  python3 scripts/connectors/gdrive.py
Uso (/drive <termo> — busca ad-hoc):
  python3 scripts/connectors/gdrive.py "dicionario de dados"

Para cada doc da watchlist (Google Docs/Sheets/Slides): exporta conteúdo +
comentários → snapshot. Hash idêntico ao pull anterior = silêncio (nada escrito).
Requer: GOOGLE_* no config/.env (google_auth.py). Escopo: drive.readonly.
Usa apenas urllib (stdlib). NENHUMA chamada de escrita existe.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import common  # noqa: E402

API = "https://www.googleapis.com/drive/v3"


def get(path: str, token: str) -> dict | str:
    req = urllib.request.Request(f"{API}{path}",
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            ct = resp.headers.get("Content-Type", "")
            body = resp.read().decode()
            return json.loads(body) if "json" in ct else body
    except Exception as e:  # noqa: BLE001
        common.die(f"Drive API falhou ({type(e).__name__}): {e}", code=2)


def export_doc(file_id: str, token: str) -> str:
    """Docs/Sheets/Slides → texto (export link). PDFs/otros: metadata só."""
    meta = get(f"/files/{file_id}?fields=name,mimeType", token)
    mime = meta.get("mimeType", "")
    if "google-apps" not in mime:
        return f"(não editável no Google Apps: {mime} — só metadata)\nname: {meta.get('name')}"
    kind = mime.split(".")[-1]  # document | spreadsheet | presentation
    export_mime = {"document": "text/markdown",
                   "spreadsheet": "text/csv",
                   "presentation": "text/plain"}.get(kind, "text/plain")
    return str(get(f"/files/{file_id}/export?mimeType={urllib.parse.quote(export_mime)}",
                   token))[:200_000]


def comments(file_id: str, token: str) -> list[str]:
    out: list[str] = []
    page_token = None
    while True:
        q = "&fields=nextPageToken,comments(authorDisplayName,content,createdTime)"
        if page_token:
            q += f"&pageToken={page_token}"
        data = get(f"/files/{file_id}/comments?{q}", token)
        for c in data.get("comments", []):
            out.append(f"- {c.get('authorDisplayName', '?')} ({(c.get('createdTime') or '')[:10]}): "
                       f"{c.get('content', '')}")
        page_token = data.get("nextPageToken")
        if not page_token:
            return out


def snapshot_doc(doc: dict, token: str) -> str:
    body = export_doc(doc["id"], token)
    cmts = comments(doc["id"], token)
    return (f"# GDoc · {doc.get('name') or doc['id']}\n"
            f"_pull: {common.ts()} · id: {doc['id']}_\n\n"
            f"## Conteúdo\n{body}\n\n## Comentários ({len(cmts)})\n" + "\n".join(cmts) + "\n")


def main() -> None:
    common.load_env()
    state = common.load_state()
    token = common.google_access_token()
    args = sys.argv[1:]

    if args:  # /drive <termo|id> — busca por nome OU exportação direta por id
        arg = " ".join(args)
        if len(arg) > 20 and arg[0].isalnum():  # parece um id do Drive → exporta direto
            text = snapshot_doc({"id": arg, "name": ""}, token)
            path = common.write_snapshot("gdoc", arg, text)
            print(f"  drive/id {arg}: exportado → {path.relative_to(common.INSTANCE_ROOT)}")
            print("→ rode /dump para processar")
            return
        term = arg
        name_q = urllib.parse.quote(f"name contains '{term}'")
        data = get(f"/files?q={name_q}&fields=files(id,name,mimeType,modifiedTime)&pageSize=20",
                   token)
        files = data.get("files", []) if isinstance(data, dict) else []
        lines = [f"# Drive · busca '{term}'", f"_pull: {common.ts()} · {len(files)} resultados_", ""]
        for f in files:
            lines.append(f"- **{f['name']}** ({f.get('mimeType', '?').split('.')[-1]}) · "
                         f"modificado {(f.get('modifiedTime') or '?')[:10]} · id `{f['id']}`")
        text = "\n".join(lines) + "\n"
        path = common.write_snapshot("gdrive-search", term, text)
        print(f"  drive/busca '{term}': {len(files)} resultados → "
              f"{path.relative_to(common.INSTANCE_ROOT)}")
        print("→ rode /dump para processar; exporte um doc via /drive <id>")
        return

    # noturno: watchlist gdocs
    docs_raw = common.load_watch().get("gdocs") or []
    docs, off = common.watch_items(docs_raw, "id")
    for d in off:
        print(f"  gdoc/{d}: desligado no watch.yaml (mudo — não puxa, não debuga)")
    docs = [d for d in docs_raw if isinstance(d, dict) and d.get("id") not in off]
    if not docs:
        print("gdrive: watchlist 'gdocs:' vazia (ou toda desligada) — nada a fazer")
        return
    print("gdrive: puxando watchlist…")
    any_new = False
    for doc in docs:
        name = doc.get("name") or doc.get("id", "doc")
        text = snapshot_doc(doc, token)
        changed, _ = common.changed_since_last(f"gdoc:{doc.get('id')}", text, state)
        if changed:
            path = common.write_snapshot("gdoc", name, text)
            print(common.summary_line(f"gdoc/{name}", True, path))
            any_new = True
        else:
            print(common.summary_line(f"gdoc/{name}", False, None))
    common.save_state(state)
    print("→ rode /dump para processar" if any_new else "→ nada novo")


if __name__ == "__main__":
    main()
