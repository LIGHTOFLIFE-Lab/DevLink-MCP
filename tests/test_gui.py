# Copyright 2026 sshpier contributors
# SPDX-License-Identifier: Apache-2.0
"""The settings panel, exercised over real HTTP."""

from __future__ import annotations

import base64
import json
import re
import threading
import urllib.error
import urllib.request
from html.parser import HTMLParser

import pytest

from sshpier import gui
from sshpier.config import Paths


@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setenv("SSHPIER_MCP_CONFIG", str(tmp_path / "mcp" / "config.json"))
    paths = Paths(tmp_path / "home")
    paths.ensure()

    token = "test-token"
    handler = gui.make_handler(paths, token)
    server = gui._Server(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{server.server_address[1]}"

    class Client:
        paths = None
        def get(self, path, t=token):
            url = f"{base}{path}" + (f"?t={t}" if t is not None else "")
            with urllib.request.urlopen(url) as response:
                return json.loads(response.read())

        def post(self, path, payload, t=token):
            request = urllib.request.Request(
                f"{base}{path}?t={t}", json.dumps(payload).encode(),
                {"Content-Type": "application/json"})
            with urllib.request.urlopen(request) as response:
                return json.loads(response.read())

        def status(self, path, t=token):
            try:
                url = f"{base}{path}" + (f"?t={t}" if t is not None else "")
                with urllib.request.urlopen(url) as response:
                    return response.status
            except urllib.error.HTTPError as exc:
                return exc.code

    client = Client()
    client.paths = paths
    client.base = base
    yield client
    server.shutdown()


# --------------------------------------------------------------------------
# access control
# --------------------------------------------------------------------------

def test_api_requires_the_token(panel):
    assert panel.status("/api/state", t=None) == 403
    assert panel.status("/api/state", t="wrong") == 403
    assert panel.status("/api/state") == 200


def test_page_is_served_without_a_token(panel):
    with urllib.request.urlopen(panel.base + "/") as response:
        body = response.read().decode()
    assert "<title>sshpier</title>" in body
    assert "__TOKEN__" not in body, "token placeholder was not substituted"
    assert "__MESSAGES__" not in body


# --------------------------------------------------------------------------
# round trip
# --------------------------------------------------------------------------

SERVER = {
    "name": "web1", "host": "10.0.0.1", "port": "22", "user": "root",
    "password": "s3cret", "key": "", "remote": "/var/www/html",
    "backup": "/var/backup", "exclude": "", "mode": "exec", "enabled": True,
}


def test_save_then_read_back(panel):
    result = panel.post("/api/save", {"servers": [SERVER]})
    assert result["ok"] is True

    state = panel.get("/api/state")
    assert state["servers"][0]["name"] == "web1"
    assert state["servers"][0]["has_password"] is True


def test_stored_password_never_reaches_the_page(panel):
    panel.post("/api/save", {"servers": [SERVER]})
    state = json.dumps(panel.get("/api/state"))
    assert "s3cret" not in state


def test_blank_password_keeps_the_existing_one(panel):
    panel.post("/api/save", {"servers": [SERVER]})
    changed = dict(SERVER, password=None, remote="/var/www/other")
    panel.post("/api/save", {"servers": [changed]})

    text = panel.paths.ini.read_text(encoding="utf-8")
    assert "password = s3cret" in text
    assert "/var/www/other" in text


def test_save_reports_validation_errors(panel):
    bad = dict(SERVER, remote="relative/path")
    result = panel.post("/api/save", {"servers": [bad]})
    assert result["ok"] is False
    assert result["errors"]


# --------------------------------------------------------------------------
# import and keys
# --------------------------------------------------------------------------

def _winscp_ini() -> bytes:
    from tests.test_winscp import encode_password
    pw = encode_password("root", "1.2.3.4", "fromwinscp")
    return (
        "[Sessions\\imported]\n"
        "HostName=1.2.3.4\nUserName=root\n"
        f"Password={pw}\nFSProtocol=0\n"
    ).encode("utf-16")


def test_import_brings_passwords_across(panel):
    payload = {"name": "WinSCP.ini",
               "data": base64.b64encode(_winscp_ini()).decode()}
    result = panel.post("/api/import", payload)
    assert result["ok"] is True
    assert result["servers"][0]["password"] == "fromwinscp"


def test_key_upload_rejects_ppk_and_public_keys(panel):
    private = b"-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n"
    ok = panel.post("/api/key", {"name": "good.pem",
                                 "data": base64.b64encode(private).decode()})
    assert ok["ok"] is True
    assert "good.pem" in ok["keys"]

    ppk = panel.post("/api/key", {"name": "bad.ppk",
                                  "data": base64.b64encode(private).decode()})
    assert ppk["ok"] is False

    pub = panel.post("/api/key", {"name": "id.pub",
                                  "data": base64.b64encode(b"ssh-rsa AAAA").decode()})
    assert pub["ok"] is False


# --------------------------------------------------------------------------
# MCP registration
# --------------------------------------------------------------------------

def test_register_merges_and_writes_without_bom(panel, tmp_path):
    target = tmp_path / "mcp" / "config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"mcpServers": {"other": {"command": "x"}}}', encoding="utf-8")

    result = panel.post("/api/register", {})
    assert result["ok"] is True

    raw = target.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "wrote a BOM into JSON"
    data = json.loads(raw.decode("utf-8"))
    assert "other" in data["mcpServers"], "existing entry was dropped"
    assert "ssh" in data["mcpServers"]
    assert any(p.name.startswith("config.json.bak-") for p in target.parent.iterdir())

    assert panel.get("/api/state")["registered"] is True


def test_register_refuses_to_touch_invalid_json(panel, tmp_path):
    target = tmp_path / "mcp" / "config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{ this is not json", encoding="utf-8")

    result = panel.post("/api/register", {})
    assert result["ok"] is False
    assert target.read_text(encoding="utf-8") == "{ this is not json"


# --------------------------------------------------------------------------
# page structure
# --------------------------------------------------------------------------

class _Tags(HTMLParser):
    VOID = {"br", "img", "input", "meta", "link", "hr", "source"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack:
            self.errors.append(f"</{tag}> with nothing open")
            return
        if self.stack[-1] != tag:
            self.errors.append(f"</{tag}> closes <{self.stack[-1]}>")
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
        else:
            self.stack.pop()


def test_page_html_is_balanced():
    parser = _Tags()
    parser.feed(gui.PAGE)
    assert parser.errors == []
    assert parser.stack == []


def test_every_element_the_script_touches_exists():
    ids = set(re.findall(r'\bid="([^"]+)"', gui.PAGE))
    used = set(re.findall(r'\$\("([^"]+)"\)', gui.PAGE))
    used |= set(re.findall(r'getElementById\(\'([^\']+)\'\)', gui.PAGE))
    assert used - ids == set()


def test_every_handler_is_defined():
    called = set(re.findall(r'on(?:click|change)="(\w+)\(', gui.PAGE))
    defined = set(re.findall(r"function (\w+)\(", gui.PAGE))
    assert called - defined == set()


def test_every_message_key_exists():
    from sshpier.i18n import MESSAGES

    used = set(re.findall(r'T\("([\w.]+)"', gui.PAGE))
    used |= set(re.findall(r'setText\("[^"]+","([\w.]+)"\)', gui.PAGE))
    missing = used - set(MESSAGES["en"])
    assert missing == set(), f"page uses unknown message keys: {sorted(missing)}"


def test_korean_catalogue_covers_english():
    from sshpier.i18n import MESSAGES

    missing = set(MESSAGES["en"]) - set(MESSAGES["ko"])
    assert missing == set(), f"untranslated keys: {sorted(missing)}"
