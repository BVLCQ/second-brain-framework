"""Porta do calendário — escrita ESTREITA no Google Calendar.

Só cria, lê e apaga eventos de foco que ela mesma criou: todo evento leva
extendedProperties.private.brain_focus = "1" e o ID da ação. Antes de apagar,
o evento é relido e a marca é conferida — evento sem marca nunca é tocado.
Escopo OAuth: calendar.events.owned (guides/google-oauth.md).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from . import config, util

API = "https://www.googleapis.com/calendar/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
MARK = "brain_focus"

Http = Callable[[str, str, dict | None, dict], tuple[int, dict]]


def _urllib_http(method: str, url: str, body: dict | None, headers: dict) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={**headers, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode() or "{}"
            return r.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"error": {"message": raw[:300]}}


def access_token(inst, http_post=None) -> str:
    env = config.load_env(inst)
    missing = [k for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN") if not env.get(k)]
    if missing:
        raise util.BrainError(f"faltam no config/.env: {', '.join(missing)} — veja guides/google-oauth.md", code=3)
    form = urllib.parse.urlencode({"client_id": env["GOOGLE_CLIENT_ID"], "client_secret": env["GOOGLE_CLIENT_SECRET"],
                                   "refresh_token": env["GOOGLE_REFRESH_TOKEN"], "grant_type": "refresh_token"}).encode()
    if http_post:
        return http_post(form)
    req = urllib.request.Request(TOKEN_URL, data=form, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())["access_token"]
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        if "invalid_grant" in body:
            raise util.BrainError("refresh token expirado/revogado — rode scripts/google_auth.py de novo "
                                  "(app em 'Testing' expira em 7 dias; publique em produção)", code=2) from e
        if "invalid_client" in body:
            raise util.BrainError("OAuth client inválido (invalid_client) — confira GOOGLE_CLIENT_ID/SECRET "
                                  "ou crie um client novo (guides/google-oauth.md)", code=2) from e
        raise util.BrainError(f"token Google falhou ({e.code}): {body}", code=2) from e


class GoogleCalendar:
    def __init__(self, inst, http: Http | None = None, token: str | None = None):
        self.inst = inst
        self.calendar = inst.cfg["focus"]["calendar"]
        self.http = http or _urllib_http
        self._token = token

    def _call(self, method: str, path: str, body: dict | None = None, query: dict | None = None) -> dict:
        if self._token is None:
            self._token = access_token(self.inst)
        url = f"{API}/calendars/{urllib.parse.quote(self.calendar)}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        status, data = self.http(method, url, body, {"Authorization": f"Bearer {self._token}"})
        if status >= 400:
            msg = (data.get("error") or {}).get("message", str(data))[:300]
            raise util.BrainError(f"Google Calendar {method} {path} → {status}: {msg}", code=2)
        return data

    def list_events(self, time_min: str, time_max: str) -> list[dict]:
        items, page = [], None
        while True:
            q = {"timeMin": time_min, "timeMax": time_max, "singleEvents": "true", "orderBy": "startTime",
                 "maxResults": "250"}
            if page:
                q["pageToken"] = page
            data = self._call("GET", "/events", query=q)
            items.extend(data.get("items", []))
            page = data.get("nextPageToken")
            if not page:
                return items

    def insert_focus(self, block: dict, plan_id: str, title: str, description: str, decline_message: str) -> dict:
        body = {
            "summary": title, "description": description,
            "start": {"dateTime": block["start"]}, "end": {"dateTime": block["end"]},
            "transparency": "opaque", "visibility": "private",
            "eventType": "focusTime",
            "focusTimeProperties": {"chatStatus": "doNotDisturb",
                                    "autoDeclineMode": "declineOnlyNewConflictingInvitations",
                                    "declineMessage": decline_message},
            "extendedProperties": {"private": {MARK: "1", "brain_action": block["action"], "brain_plan": plan_id}},
        }
        try:
            return self._call("POST", "/events", body)
        except util.BrainError as e:
            if "focus" not in str(e).lower() and "eventtype" not in str(e).lower():
                raise
            # Conta sem Focus Time (não-Workspace): evento comum, opaco, com a mesma marca.
            for k in ("eventType", "focusTimeProperties"):
                body.pop(k)
            return self._call("POST", "/events", body)

    def delete_guarded(self, event_id: str, action: str | None = None) -> bool:
        try:
            ev = self._call("GET", f"/events/{urllib.parse.quote(event_id)}")
        except util.BrainError as e:
            if "404" in str(e) or "410" in str(e):
                return False
            raise
        private = (ev.get("extendedProperties") or {}).get("private") or {}
        if private.get(MARK) != "1" or (action and private.get("brain_action") != action):
            raise util.BrainError(f"recusado: evento {event_id} não tem a marca do cérebro — nunca é tocado", code=4)
        if ev.get("status") == "cancelled":
            return False
        self._call("DELETE", f"/events/{urllib.parse.quote(event_id)}")
        return True
