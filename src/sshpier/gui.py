# Copyright 2026 sshpier contributors
# SPDX-License-Identifier: Apache-2.0
"""The settings panel: a local web page, served by the standard library.

Why a browser instead of a desktop toolkit: tkinter is missing from many Python
builds, and a page can be driven by a test suite. Everything here is stdlib, so
the panel works wherever Python does.

Two rules this module keeps:

*Bound to loopback, gated by a per-run token.* Anything without the token gets
403, including a page left open from a previous run.

*Stored passwords are never sent to the browser.* The page is told only whether
a password exists. A blank field on save means "leave it alone", so passwords
are not read back out of the file to be echoed into a form.
"""

from __future__ import annotations

import base64
import http.server
import json
import os
import re
import secrets
import shutil
import socketserver
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config as cfg
from . import winscp
from .config import Paths
from .i18n import catalogue, language, t

MAX_UPLOAD = 4 * 1024 * 1024

INI_HEADER = """; sshpier servers
;
; This file holds passwords. It must stay out of version control.
; Edited by the settings panel; hand edits are fine but comments are not kept.
;
; Last saved: {when}

[DEFAULT]
port    = 22
mode    = exec
exclude = {exclude}
backup  = /var/backup/sshpier
"""


class SaveBlocked(Exception):
    """Refusing to write because the existing file cannot be read."""


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------

def load_servers(paths: Paths) -> list[dict]:
    if not paths.ini.exists() or cfg.problem_with(paths.ini):
        return []
    try:
        parser = cfg.read_ini(paths.ini)
    except (cfg.ConfigError, OSError):
        return []

    out = []
    for section_name in parser.sections():
        section = parser[section_name]
        out.append({
            "name": section_name,
            "host": section.get("host", ""),
            "port": section.get("port", "22"),
            "user": section.get("user", section.get("username", "")),
            "has_password": bool(section.get("password", "").strip()),
            "key": section.get("key", section.get("privatekey", "")),
            "has_passphrase": bool(section.get("passphrase", "").strip()),
            "remote": section.get("remote", ""),
            "backup": section.get("backup", ""),
            "exclude": section.get("exclude", ""),
            "mode": section.get("mode", "exec"),
            "proxy": section.get("proxy", ""),
            "allow": section.get("allow", section.get("whitelist", "")),
            "enabled": cfg.as_bool(section.get("enabled", "yes")),
        })
    return out


def _existing_secrets(paths: Paths) -> dict[str, dict[str, str]]:
    if not paths.ini.exists():
        return {}
    try:
        parser = cfg.read_ini(paths.ini)
    except (cfg.ConfigError, OSError):
        return {}
    return {name: {"password": parser[name].get("password", ""),
                   "passphrase": parser[name].get("passphrase", "")}
            for name in parser.sections()}


def save_servers(paths: Paths, servers: list[dict]) -> None:
    """Write servers.ini, carrying forward passwords the page did not send.

    If the current file cannot be read we refuse rather than overwrite: the
    passwords in it would be lost silently.
    """
    problem = cfg.problem_with(paths.ini)
    if problem:
        raise SaveBlocked(problem)

    keep = _existing_secrets(paths)
    lines = [INI_HEADER.format(when=datetime.now().strftime("%Y-%m-%d %H:%M"),
                               exclude=", ".join(cfg.DEFAULT_EXCLUDE))]

    for server in servers:
        name = (server.get("name") or "").strip()
        if not name:
            continue

        password = server.get("password")
        if password is None:
            password = keep.get(name, {}).get("password", "")
        passphrase = server.get("passphrase")
        if passphrase is None:
            passphrase = keep.get(name, {}).get("passphrase", "")

        block = [f"\n[{name}]"]
        if not server.get("enabled", True):
            block.append("enabled  = no")
        block.append(f"host     = {(server.get('host') or '').strip()}")
        port = str(server.get("port") or "22").strip()
        if port != "22":
            block.append(f"port     = {port}")
        block.append(f"user     = {(server.get('user') or '').strip()}")

        key_file = (server.get("key") or "").strip()
        if key_file:
            block.append(f"key      = {key_file}")
            if passphrase:
                block.append(f"passphrase = {passphrase}")
        if password:
            block.append(f"password = {password}")

        block.append(f"remote   = {(server.get('remote') or '').strip()}")

        for field, label in (("backup", "backup  "), ("exclude", "exclude "),
                             ("mode", "mode    "), ("proxy", "proxy   "),
                             ("allow", "allow   ")):
            value = (server.get(field) or "").strip()
            if value and not (field == "mode" and value == "exec"):
                block.append(f"{label} = {value}")

        lines.append("\n".join(block) + "\n")

    paths.config_dir.mkdir(parents=True, exist_ok=True)
    tmp = paths.ini.with_suffix(".ini.tmp")
    tmp.write_text("".join(lines), encoding="utf-8")
    tmp.replace(paths.ini)


def check_env() -> list[dict]:
    def version_of(executable: str) -> str:
        try:
            return subprocess.run([executable, "-v"], capture_output=True,
                                  text=True, timeout=10).stdout.strip()
        except Exception:
            return ""

    node = shutil.which("node")
    items = [{
        "name": t("env.node"), "ok": bool(node),
        "detail": (version_of(node) if node else t("env.missing")),
        "hint": t("env.hint.node"),
    }]
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    items.append({"name": t("env.npx"), "ok": bool(npx),
                  "detail": t("env.present") if npx else t("env.missing"),
                  "hint": t("env.hint.npx")})
    items.append({"name": t("env.python"), "ok": True,
                  "detail": sys.version.split()[0], "hint": ""})
    git = shutil.which("git")
    items.append({"name": t("env.git"), "ok": bool(git),
                  "detail": t("env.present") if git else t("env.missing"),
                  "hint": t("env.hint.git")})
    return items


# --------------------------------------------------------------------------
# keys
# --------------------------------------------------------------------------

def list_keys(paths: Paths) -> list[str]:
    if not paths.keys.exists():
        return []
    return sorted(p.name for p in paths.keys.iterdir() if p.is_file())


def save_key(paths: Paths, name: str, raw: bytes) -> dict:
    """Copy a chosen key into the keys folder.

    Browsers do not reveal a file's real path, so the page uploads the bytes.
    Collecting keys in one folder is the better outcome anyway.
    """
    safe = re.sub(r"[^\w.\-]", "_", (name or "key").strip(), flags=re.UNICODE) or "key"
    if safe.lower().endswith(".ppk"):
        return {"ok": False, "message": t("key.ppk")}

    head = raw[:200].decode("latin-1", "ignore")
    if "PRIVATE KEY" not in head:
        return {"ok": False, "message": t("key.not_private")}

    paths.keys.mkdir(parents=True, exist_ok=True)
    destination = paths.keys / safe
    destination.write_bytes(raw)
    try:
        os.chmod(destination, 0o600)
    except OSError:
        pass
    return {"ok": True, "path": str(destination), "name": safe,
            "message": t("key.saved", name=safe)}


# --------------------------------------------------------------------------
# MCP client registration
# --------------------------------------------------------------------------

def mcp_config_path() -> Path:
    """Where the MCP client keeps its server list."""
    override = os.environ.get("SSHPIER_MCP_CONFIG")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / "Claude"
                / "claude_desktop_config.json")
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def launcher_command(paths: Paths) -> dict:
    """How the MCP client should start the SSH server."""
    return {
        "command": "npx",
        "args": ["-y", "@fangjunjie/ssh-mcp-server",
                 "--config-file", str(paths.mcp_json)],
    }


def is_registered(paths: Paths, name: str = "ssh") -> bool:
    path = mcp_config_path()
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return False
    entry = (data.get("mcpServers") or {}).get(name)
    return bool(entry) and str(paths.mcp_json) in " ".join(entry.get("args", []))


def register(paths: Paths, name: str = "ssh") -> dict:
    path = mcp_config_path()
    data: dict = {}
    backup_name = ""

    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            return {"ok": False, "message": t("mcp.bad_json", error=exc, path=path)}
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(path.name + f".bak-{stamp}")
        shutil.copy2(path, backup)
        backup_name = backup.name
    else:
        path.parent.mkdir(parents=True, exist_ok=True)

    data.setdefault("mcpServers", {})
    existed = name in data["mcpServers"]
    data["mcpServers"][name] = launcher_command(paths)

    # No BOM: a byte-order mark in front of JSON breaks strict parsers.
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")

    message = t("mcp.replaced") if existed else t("mcp.done")
    if backup_name:
        message += t("mcp.backup", name=backup_name)
    return {"ok": True, "message": message + t("mcp.restart")}


# --------------------------------------------------------------------------
# import
# --------------------------------------------------------------------------

def import_sessions(paths: Paths, payload: dict) -> dict:
    if payload.get("data"):
        try:
            raw = base64.b64decode(payload["data"])
        except Exception:
            return {"ok": False, "message": t("import.unreadable")}
        if len(raw) > MAX_UPLOAD:
            return {"ok": False, "message": t("import.too_big")}
        source: Path | bytes = raw
    else:
        candidate = Path((payload.get("path") or "").strip().strip('"'))
        if not str(candidate) or not candidate.exists():
            return {"ok": False, "message": t("import.not_found", path=candidate)}
        source = candidate

    try:
        sessions = winscp.read_sessions(source)
    except Exception:
        return {"ok": False, "message": t("import.unreadable")}

    if not sessions:
        return {"ok": False, "message": t("import.no_sessions")}

    existing = {s["name"] for s in load_servers(paths)}
    added, skipped, items = [], [], []

    for session in sessions:
        if not session["usable"]:
            key = "import.skip_nohost" if not session["host"] else "import.skip_proto"
            skipped.append(t(key, name=session["name"], proto=session["protocol"]))
            continue
        if session["name"] in existing:
            skipped.append(t("import.skip_exists", name=session["name"]))
            continue

        items.append({
            "name": session["name"], "host": session["host"],
            "port": session["port"], "user": session["user"],
            "password": session["password"], "passphrase": "",
            "key": session["key"], "remote": "", "backup": "",
            "exclude": "", "mode": "exec", "proxy": session["proxy"],
            "allow": "", "enabled": True,
            "has_password": bool(session["password"]),
            "pw_failed": session["password_failed"],
        })
        added.append(session["name"])

    if not added:
        return {"ok": False, "message": t("import.nothing"), "skipped": skipped,
                "servers": []}

    recovered = sum(1 for i in items if i["has_password"])
    failed = sum(1 for i in items if i["pw_failed"])
    parts = [t("import.result", count=len(added))]
    if recovered:
        parts.append(t("import.result_pw", count=recovered))
    if failed:
        parts.append(t("import.result_failed", count=failed))
    parts.append(t("import.result_next"))

    return {"ok": True, "added": added, "skipped": skipped,
            "servers": items, "message": " ".join(parts)}


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def make_handler(paths: Paths, token: str):

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "sshpier"

        def log_message(self, fmt, *args):
            pass

        def handle_one_request(self):
            # A stack trace in the console helps nobody; the page is where the
            # person is looking.
            try:
                super().handle_one_request()
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            except Exception as exc:  # pragma: no cover - defensive
                print(f"  request error: {exc}", flush=True)
                self.close_connection = True

        # -- helpers --
        def _authed(self) -> bool:
            query = parse_qs(urlparse(self.path).query)
            return secrets.compare_digest(query.get("t", [""])[0], token)

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        # -- routes --
        def do_GET(self):
            route = urlparse(self.path).path

            if route == "/":
                html = (PAGE
                        .replace("__TOKEN__", token)
                        .replace("__ROOT__", str(paths.root))
                        .replace("__LANG__", language())
                        .replace('"__MESSAGES__"',
                                 json.dumps(catalogue(), ensure_ascii=False)))
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                return

            if not self._authed():
                self._json({"error": "forbidden"}, 403)
                return

            if route == "/api/state":
                self._json({
                    "root": str(paths.root),
                    "ini": str(paths.ini),
                    "problem": cfg.problem_with(paths.ini),
                    "env": check_env(),
                    "servers": load_servers(paths),
                    "keys": list_keys(paths),
                    "keys_dir": str(paths.keys),
                    "registered": is_registered(paths),
                    "mcp_config": str(mcp_config_path()),
                })
                return

            self._json({"error": "not found"}, 404)

        def do_POST(self):
            route = urlparse(self.path).path
            if not self._authed():
                self._json({"error": "forbidden"}, 403)
                return

            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_UPLOAD * 2:
                self._json({"ok": False, "message": t("import.too_big")}, 413)
                return
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._json({"error": "bad request"}, 400)
                return

            try:
                if route == "/api/save":
                    try:
                        save_servers(paths, payload.get("servers", []))
                    except SaveBlocked as exc:
                        self._json({"ok": False, "errors": [str(exc)], "blocked": True,
                                    "warnings": [], "servers": []})
                        return
                    result = cfg.generate(paths)
                    self._json({
                        "ok": result["ok"],
                        "errors": result["errors"],
                        "warnings": result["warnings"],
                        "skipped": result["skipped"],
                        "servers": [
                            {"name": n,
                             "line": f"{s['user']}@{s['host']}:{s['port']} -> {s['remote']}"}
                            for n, s in result["sites"].items()
                        ],
                        "servers_state": load_servers(paths),
                    })
                    return

                if route == "/api/register":
                    self._json(register(paths))
                    return

                if route == "/api/import":
                    self._json(import_sessions(paths, payload))
                    return

                if route == "/api/key":
                    try:
                        raw = base64.b64decode(payload.get("data", ""))
                    except Exception:
                        self._json({"ok": False, "message": t("import.unreadable")})
                        return
                    if len(raw) > MAX_UPLOAD:
                        self._json({"ok": False, "message": t("import.too_big")})
                        return
                    result = save_key(paths, payload.get("name", ""), raw)
                    result["keys"] = list_keys(paths)
                    self._json(result)
                    return

                if route == "/api/quit":
                    self._json({"ok": True})
                    threading.Timer(0.5, lambda: os._exit(0)).start()
                    return
            except Exception as exc:  # pragma: no cover - defensive
                self._json({"ok": False, "errors": [str(exc)],
                            "warnings": [], "servers": []}, 500)
                return

            self._json({"error": "not found"}, 404)

    return Handler


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(paths: Paths, open_browser: bool = True, port: int = 0) -> int:
    token = secrets.token_urlsafe(16)
    handler = make_handler(paths, token)

    with _Server(("127.0.0.1", port), handler) as httpd:
        bound = httpd.server_address[1]
        url = f"http://127.0.0.1:{bound}/?t={token}"
        print("sshpier settings panel")
        print(f"  {url}", flush=True)
        print("  Ctrl+C to stop.", flush=True)
        if open_browser:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print()
    return 0


PAGE = r"""<!doctype html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>sshpier</title>
<style>
  :root{
    --bg:#f6f6f4; --card:#fff; --ink:#1a1a18; --dim:#6b6b66;
    --line:#e2e2dd; --accent:#3b6ea5; --ok:#2f7d4f; --warn:#9a6b12; --bad:#b3392f;
  }
  @media (prefers-color-scheme: dark){
    :root{ --bg:#16161a; --card:#1e1e23; --ink:#e8e8e4; --dim:#9a9a94;
           --line:#32323a; --accent:#6d9fd4; --ok:#6fbf8b; --warn:#d8b45f; --bad:#e08b82; }
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:14px/1.6 system-ui,"Malgun Gothic","맑은 고딕",sans-serif}
  .wrap{max-width:940px;margin:0 auto;padding:28px 20px 80px}
  h1{font-size:20px;margin:0 0 4px}
  .sub{color:var(--dim);font-size:13px;margin-bottom:24px;word-break:break-all}
  .card{background:var(--card);border:1px solid var(--line);border-radius:10px;
        padding:18px 20px;margin-bottom:16px}
  .card h2{font-size:15px;margin:0 0 14px;display:flex;align-items:center;gap:8px}
  .step{display:inline-flex;align-items:center;justify-content:center;
        width:22px;height:22px;border-radius:50%;background:var(--accent);
        color:#fff;font-size:12px;font-weight:700;flex:none}
  .env{display:flex;flex-wrap:wrap;gap:8px}
  .pill{border:1px solid var(--line);border-radius:6px;padding:5px 10px;font-size:13px}
  .pill.ok{color:var(--ok)} .pill.bad{color:var(--bad)}
  .tablewrap{overflow-x:auto}
  table{width:100%;border-collapse:collapse}
  th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line);
        font-size:13px;vertical-align:middle}
  th{color:var(--dim);font-weight:600;font-size:12px;white-space:nowrap}
  td.name{font-weight:600}
  .muted{color:var(--dim)}
  .tag{display:inline-block;border-radius:4px;padding:1px 6px;font-size:11px;
       border:1px solid var(--line);color:var(--dim)}
  button{font:inherit;border:1px solid var(--line);background:var(--card);
         color:var(--ink);border-radius:7px;padding:7px 13px;cursor:pointer}
  button:hover{border-color:var(--accent)}
  button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
  button.danger{color:var(--bad)}
  button:disabled{opacity:.5;cursor:default}
  .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:14px}
  .grid{display:grid;grid-template-columns:130px 1fr;gap:10px 14px;align-items:center}
  @media (max-width:560px){ .grid{grid-template-columns:1fr} }
  .grid label{color:var(--dim);font-size:13px}
  input[type=text],input[type=password],select,textarea{
    width:100%;font:inherit;padding:7px 9px;border:1px solid var(--line);
    border-radius:6px;background:var(--bg);color:var(--ink)}
  textarea{min-height:56px;resize:vertical}
  .hint{color:var(--dim);font-size:12px;margin-top:3px}
  dialog{border:1px solid var(--line);border-radius:12px;padding:0;max-width:560px;
         width:92%;background:var(--card);color:var(--ink)}
  dialog::backdrop{background:rgba(0,0,0,.45)}
  .dlg-head{padding:16px 20px;border-bottom:1px solid var(--line);font-weight:600}
  .dlg-body{padding:18px 20px;max-height:65vh;overflow:auto}
  .dlg-foot{padding:14px 20px;border-top:1px solid var(--line);
            display:flex;justify-content:flex-end;gap:8px}
  .msg{border-radius:8px;padding:11px 13px;margin-top:12px;font-size:13px;
       white-space:pre-wrap;border:1px solid var(--line)}
  .msg.ok{border-color:var(--ok)} .msg.bad{border-color:var(--bad)}
  .msg.warn{border-color:var(--warn)}
  .msg b{display:block;margin-bottom:4px}
  .msg ul{margin:4px 0 0;padding-left:18px}
  .empty{color:var(--dim);text-align:center;padding:22px 0;font-size:13px}
  code{background:var(--bg);padding:1px 5px;border-radius:4px;font-size:12px;
       word-break:break-all}
</style>
</head>
<body>
<div class="wrap">
  <h1 id="h_title"></h1>
  <div class="sub">__ROOT__</div>
  <div id="problem"></div>

  <div class="card">
    <h2><span class="step">1</span><span id="h_env"></span></h2>
    <div class="env" id="env"></div>
  </div>

  <div class="card">
    <h2><span class="step">2</span><span id="h_servers"></span></h2>
    <div class="tablewrap">
      <table id="tbl"><thead><tr>
        <th id="th_name"></th><th id="th_conn"></th>
        <th id="th_auth"></th><th id="th_root"></th><th></th>
      </tr></thead><tbody id="rows"></tbody></table>
    </div>
    <div class="empty" id="empty" hidden></div>
    <div class="row">
      <button class="primary" id="btnAdd" onclick="openEdit(-1)"></button>
      <button id="btnImport" onclick="openImport()"></button>
      <button id="saveBtn" onclick="save()"></button>
    </div>
    <div id="saveMsg"></div>
  </div>

  <div class="card">
    <h2><span class="step">3</span><span id="h_mcp"></span></h2>
    <div id="regState" class="muted"></div>
    <div class="row"><button class="primary" id="regBtn" onclick="register()"></button></div>
    <div id="regMsg"></div>
  </div>

  <div class="row"><button id="btnQuit" onclick="quit()"></button></div>
</div>

<dialog id="edit"><form method="dialog">
  <div class="dlg-head" id="editTitle"></div>
  <div class="dlg-body"><div class="grid">
    <label id="l_name"></label>
    <div><input type="text" id="f_name"><div class="hint" id="h_name"></div></div>
    <label id="l_host"></label><input type="text" id="f_host">
    <label id="l_port"></label><input type="text" id="f_port" value="22">
    <label id="l_user"></label><input type="text" id="f_user">
    <label id="l_auth"></label>
    <select id="f_auth" onchange="authChanged()">
      <option value="password" id="opt_pw"></option>
      <option value="key" id="opt_key"></option>
    </select>
    <label id="l_pw"></label>
    <div id="w_pw"><input type="password" id="f_password">
      <div class="hint" id="pwHint"></div></div>
    <label id="l_key" hidden></label>
    <div id="w_key" hidden>
      <select id="f_keysel" onchange="keySelChanged()"></select>
      <div id="w_keypath" hidden style="margin-top:6px"><input type="text" id="f_key"></div>
      <div style="margin-top:7px">
        <button type="button" id="btnKeyPick"
                onclick="document.getElementById('keyFile').click()"></button>
        <input type="file" id="keyFile" hidden onchange="uploadKey(this)">
        <span class="hint" id="keyMsg" style="margin-left:8px"></span>
      </div>
      <div class="hint" id="h_key"></div>
    </div>
    <label id="l_pp" hidden></label>
    <div id="w_pp" hidden><input type="password" id="f_passphrase">
      <div class="hint" id="h_pp"></div></div>
    <label id="l_remote"></label>
    <div><input type="text" id="f_remote"><div class="hint" id="h_remote"></div></div>
    <label id="l_backup"></label><input type="text" id="f_backup">
    <label id="l_exclude"></label>
    <div><textarea id="f_exclude"></textarea><div class="hint" id="h_exclude"></div></div>
    <label id="l_mode"></label>
    <select id="f_mode">
      <option value="exec" id="opt_exec"></option>
      <option value="shell" id="opt_shell"></option>
    </select>
    <label id="l_enabled"></label>
    <div><label style="color:var(--ink)">
      <input type="checkbox" id="f_enabled" checked> <span id="t_enabled"></span></label></div>
  </div><div id="editMsg"></div></div>
  <div class="dlg-foot">
    <button value="cancel" id="btnEditCancel"></button>
    <button class="primary" value="ok" id="btnEditOk"></button>
  </div>
</form></dialog>

<dialog id="imp"><form method="dialog">
  <div class="dlg-head" id="impTitle"></div>
  <div class="dlg-body">
    <p class="muted" style="margin-top:0" id="impIntro"></p>
    <p style="margin:12px 0 4px"><b id="impM1"></b></p>
    <p class="muted" style="margin:0" id="impM1b"></p>
    <p style="margin:14px 0 4px"><b id="impM2"></b></p>
    <p class="muted" style="margin:0" id="impM2b"></p>
    <p style="margin:6px 0 0"><code>reg export "HKCU\Software\Martin Prikryl\WinSCP 2\Sessions" "$env:USERPROFILE\Desktop\winscp.reg"</code></p>
    <div style="margin-top:16px">
      <button type="button" class="primary" id="btnImpPick"
              onclick="document.getElementById('impFile').click()"></button>
      <input type="file" id="impFile" accept=".ini,.reg" hidden onchange="impPicked(this)">
      <span class="hint" id="impChosen" style="margin-left:8px"></span>
    </div>
    <details style="margin-top:12px">
      <summary class="hint" style="cursor:pointer" id="impManual"></summary>
      <input type="text" id="impPath" style="margin-top:6px">
    </details>
    <p class="hint" id="impPwNote"></p>
    <div id="impMsg"></div>
  </div>
  <div class="dlg-foot">
    <button value="cancel" id="btnImpCancel"></button>
    <button class="primary" value="ok" id="btnImpOk"></button>
  </div>
</form></dialog>

<script>
const T_TABLE = "__MESSAGES__";
const TOKEN = "__TOKEN__";
let servers = [], keys = [], keysDir = "", editIdx = -1, impData = null;

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function T(key, vars){
  let s = T_TABLE[key] || key;
  if(vars) for(const k in vars) s = s.split("{"+k+"}").join(vars[k]);
  return s;
}
function setText(id, key){ const el = $(id); if(el) el.textContent = T(key); }

async function api(path, body){
  const opt = body ? {method:"POST", headers:{"Content-Type":"application/json"},
                      body:JSON.stringify(body)} : {};
  const r = await fetch(path + "?t=" + TOKEN, opt);
  return r.json();
}

function show(el, kind, title, lines){
  if(!title && (!lines || !lines.length)){ el.innerHTML = ""; return; }
  const list = (lines && lines.length)
    ? "<ul>" + lines.map(l => "<li>" + esc(l) + "</li>").join("") + "</ul>" : "";
  el.innerHTML = '<div class="msg ' + kind + '"><b>' + esc(title) + "</b>" + list + "</div>";
}

function labels(){
  setText("h_title","app.title"); setText("h_env","env.title");
  setText("h_servers","servers.title"); setText("h_mcp","mcp.title");
  setText("th_name","servers.name"); setText("th_conn","servers.connection");
  setText("th_auth","servers.auth"); setText("th_root","servers.root");
  setText("empty","servers.empty"); setText("btnAdd","servers.add");
  setText("btnImport","servers.import"); setText("saveBtn","servers.save");
  setText("btnQuit","app.close");
  setText("l_name","edit.name"); setText("h_name","edit.name_hint");
  setText("l_host","edit.host"); setText("l_port","edit.port");
  setText("l_user","edit.user"); setText("l_auth","edit.auth");
  setText("opt_pw","servers.auth.password"); setText("opt_key","servers.auth.key");
  setText("l_pw","edit.password"); setText("l_key","edit.key");
  setText("btnKeyPick","edit.key_pick"); setText("h_key","edit.key_hint");
  setText("l_pp","edit.passphrase"); setText("h_pp","edit.passphrase_hint");
  setText("l_remote","edit.remote"); setText("h_remote","edit.remote_hint");
  setText("l_backup","edit.backup"); setText("l_exclude","edit.exclude");
  setText("h_exclude","edit.exclude_hint"); setText("l_mode","edit.mode");
  setText("opt_exec","edit.mode_exec"); setText("opt_shell","edit.mode_shell");
  setText("l_enabled","edit.enabled"); setText("t_enabled","edit.enabled_label");
  setText("btnEditCancel","edit.cancel"); setText("btnEditOk","edit.ok");
  setText("impTitle","import.title"); setText("impIntro","import.intro");
  setText("impM1","import.method1"); setText("impM1b","import.method1_body");
  setText("impM2","import.method2"); setText("impM2b","import.method2_body");
  setText("btnImpPick","import.pick"); setText("impChosen","import.none");
  setText("impManual","import.manual"); setText("impPwNote","import.pw_note");
  setText("btnImpCancel","edit.cancel"); setText("btnImpOk","import.pick");
  $("f_name").placeholder = T("edit.name");
  $("f_remote").placeholder = "/var/www/html";
}

function render(){
  const rows = $("rows");
  rows.innerHTML = "";
  $("empty").hidden = servers.length > 0;
  $("tbl").hidden = servers.length === 0;

  servers.forEach((s, i) => {
    const auth = s.key ? T("servers.auth.key")
               : (s.has_password || s.password ? T("servers.auth.password")
                                               : T("servers.auth.none"));
    const off = s.enabled === false
      ? ' <span class="tag">' + T("servers.disabled") + "</span>" : "";
    const mode = s.mode === "shell" ? ' <span class="tag">shell</span>' : "";
    const tr = document.createElement("tr");
    tr.innerHTML =
      '<td class="name">' + esc(s.name) + off + mode + "</td>" +
      '<td class="muted">' + esc(s.user || "?") + "@" + esc(s.host || "?") +
        (String(s.port) !== "22" ? ":" + esc(s.port) : "") + "</td>" +
      '<td class="muted">' + auth + "</td>" +
      '<td class="muted">' + (esc(s.remote) ||
        '<span style="color:var(--bad)">' + T("servers.root_missing") + "</span>") + "</td>" +
      '<td style="text-align:right"></td>';
    const cell = tr.lastElementChild;
    const edit = document.createElement("button");
    edit.textContent = T("servers.edit"); edit.onclick = () => openEdit(i);
    const del = document.createElement("button");
    del.textContent = T("servers.delete"); del.className = "danger";
    del.style.marginLeft = "6px";
    del.onclick = () => {
      if(confirm(T("servers.confirm_delete", {name: s.name}))){ servers.splice(i,1); render(); }
    };
    cell.append(edit, del);
    rows.append(tr);
  });
}

function authChanged(){
  const useKey = $("f_auth").value === "key";
  $("l_key").hidden = $("w_key").hidden = !useKey;
  $("l_pp").hidden  = $("w_pp").hidden  = !useKey;
  $("l_pw").hidden  = $("w_pw").hidden  = useKey;
}

function fillKeys(current){
  const sel = $("f_keysel");
  sel.innerHTML = "";
  const add = (v,t) => { const o = document.createElement("option");
                         o.value = v; o.textContent = t; sel.append(o); };
  add("", T("edit.key_none"));
  keys.forEach(k => add(keysDir + "/" + k, k));
  add("__manual__", T("edit.key_manual"));
  const known = keys.some(k => (keysDir + "/" + k) === current);
  sel.value = (current && !known) ? "__manual__" : (current || "");
  keySelChanged();
}
function keySelChanged(){ $("w_keypath").hidden = $("f_keysel").value !== "__manual__"; }
function currentKey(){
  const v = $("f_keysel").value;
  return v === "__manual__" ? $("f_key").value.trim() : v;
}

function toB64(buf){
  const b = new Uint8Array(buf); let s = "";
  for(let i=0; i<b.length; i+=0x8000) s += String.fromCharCode.apply(null, b.subarray(i,i+0x8000));
  return btoa(s);
}

async function uploadKey(input){
  const f = input.files && input.files[0];
  if(!f) return;
  $("keyMsg").textContent = T("key.uploading");
  const r = await api("/api/key", {name: f.name, data: toB64(await f.arrayBuffer())});
  input.value = "";
  if(r.ok){
    keys = r.keys || keys; fillKeys(r.path);
    $("f_keysel").value = r.path; keySelChanged();
    $("keyMsg").textContent = r.message;
  } else {
    $("keyMsg").textContent = "";
    show($("editMsg"), "bad", r.message, []);
  }
}

function openEdit(i){
  editIdx = i;
  const s = i < 0 ? {port:"22", mode:"exec", enabled:true} : servers[i];
  $("editTitle").textContent = i < 0 ? T("edit.add_title")
                                     : T("edit.edit_title", {name: s.name});
  $("f_name").value = s.name || ""; $("f_host").value = s.host || "";
  $("f_port").value = s.port || "22"; $("f_user").value = s.user || "";
  $("f_key").value = s.key || ""; $("f_remote").value = s.remote || "";
  $("f_backup").value = s.backup || ""; $("f_exclude").value = s.exclude || "";
  $("f_mode").value = s.mode || "exec"; $("f_enabled").checked = s.enabled !== false;
  $("f_auth").value = s.key ? "key" : "password";
  $("f_password").value = ""; $("f_passphrase").value = "";
  $("pwHint").textContent = s.has_password ? T("edit.password_set") : "";
  $("keyMsg").textContent = ""; $("editMsg").innerHTML = "";
  fillKeys(s.key || ""); authChanged();
  $("edit").showModal();
}

$("edit").addEventListener("close", () => {
  if($("edit").returnValue !== "ok") return;
  const useKey = $("f_auth").value === "key";
  const prev = editIdx < 0 ? {} : servers[editIdx];
  const item = {
    name: $("f_name").value.trim(), host: $("f_host").value.trim(),
    port: $("f_port").value.trim() || "22", user: $("f_user").value.trim(),
    key: useKey ? currentKey() : "", remote: $("f_remote").value.trim(),
    backup: $("f_backup").value.trim(), exclude: $("f_exclude").value.trim(),
    mode: $("f_mode").value, enabled: $("f_enabled").checked,
    proxy: prev.proxy || "", allow: prev.allow || "",
  };
  const pw = $("f_password").value, pp = $("f_passphrase").value;
  item.password = useKey ? "" : (pw !== "" ? pw : null);
  item.passphrase = useKey ? (pp !== "" ? pp : null) : "";
  item.has_password = editIdx < 0 ? (pw !== "") : (prev.has_password || pw !== "");
  if(editIdx < 0) servers.push(item); else servers[editIdx] = item;
  render();
});

function openImport(){
  $("impPath").value = ""; $("impFile").value = ""; impData = null;
  $("impChosen").textContent = T("import.none"); $("impMsg").innerHTML = "";
  $("imp").showModal();
}
async function impPicked(input){
  const f = input.files && input.files[0];
  if(!f){ impData = null; $("impChosen").textContent = T("import.none"); return; }
  impData = {name: f.name, data: toB64(await f.arrayBuffer())};
  $("impChosen").textContent = f.name;
}
$("imp").addEventListener("close", async () => {
  if($("imp").returnValue !== "ok") return;
  if(!impData && !$("impPath").value.trim()){
    show($("saveMsg"), "bad", T("import.no_file"), []); return;
  }
  const r = await api("/api/import", impData || {path: $("impPath").value});
  if(r.ok){
    servers = servers.concat(r.servers); render();
    show($("saveMsg"), "ok", r.message, r.skipped);
  } else {
    show($("saveMsg"), "bad", r.message, r.skipped || []);
  }
});

async function save(){
  const btn = $("saveBtn");
  btn.disabled = true; btn.textContent = T("servers.saving");
  try{
    const r = await api("/api/save", {servers});
    if(r.servers_state) servers = r.servers_state;
    render();
    const lines = (r.servers || []).map(s => s.name + "  " + s.line);
    if(r.errors && r.errors.length) show($("saveMsg"), "bad", T("save.errors"), r.errors);
    else if(r.warnings && r.warnings.length)
      show($("saveMsg"), "warn", T("save.warn"), lines.concat(r.warnings));
    else show($("saveMsg"), "ok", T("save.ok"), lines);
  } catch(e){
    show($("saveMsg"), "bad", T("save.failed", {error: e}), []);
  } finally {
    btn.disabled = false; btn.textContent = T("servers.save");
  }
}

async function register(){
  const r = await api("/api/register", {});
  show($("regMsg"), r.ok ? "ok" : "bad", r.message, []);
  if(r.ok) load();
}

async function quit(){
  await api("/api/quit", {});
  document.body.innerHTML = '<div class="wrap"><div class="card">' +
    T("app.closed") + "</div></div>";
}

async function load(){
  const st = await api("/api/state");
  servers = st.servers; keys = st.keys || []; keysDir = st.keys_dir || "";
  render();
  $("env").innerHTML = st.env.map(e =>
    '<span class="pill ' + (e.ok ? "ok" : "bad") + '">' + (e.ok ? "✓ " : "✗ ") +
    esc(e.name) + " " + esc(e.detail) + "</span>" +
    (e.ok || !e.hint ? "" : '<span class="pill">' + esc(e.hint) + "</span>")).join("");

  if(st.problem){
    $("problem").innerHTML = '<div class="card msg bad"><b>' +
      T("save.blocked_title") + "</b><pre style=\"white-space:pre-wrap;margin:8px 0 0;" +
      "font:inherit\">" + esc(st.problem) + "</pre>" +
      '<div class="row"><button onclick="load()">' + T("app.recheck") +
      "</button></div></div>";
    $("saveBtn").disabled = true;
  } else {
    $("problem").innerHTML = ""; $("saveBtn").disabled = false;
  }

  $("regState").textContent = st.registered ? T("mcp.registered")
                                            : T("mcp.not_registered", {path: st.mcp_config});
  $("regBtn").textContent = st.registered ? T("mcp.reregister") : T("mcp.register");
}

labels();
load();
</script>
</body>
</html>
"""
