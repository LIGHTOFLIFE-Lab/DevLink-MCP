# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
"""The MCP server, driven over the real JSON-RPC protocol."""

from __future__ import annotations

import io
import json

import pytest

from devlink_mcp import mcpserver
from devlink_mcp.config import Paths
from devlink_mcp.mcpserver import Server
from devlink_mcp.transport import LocalTransport

INI = """
[DEFAULT]
port = 22

[web1]
host     = 192.0.2.10
user     = deploy
password = s3cret
remote   = /srv/www
backup   = /srv/backup

[locked]
host     = 192.0.2.11
user     = ops
password = s3cret
remote   = /srv/app
backup   = /srv/backup
allow    = ^ls( .*)?|^cat .*
"""


@pytest.fixture
def fake_remote(tmp_path):
    root = tmp_path / "remote"
    (root / "srv" / "www").mkdir(parents=True)
    (root / "srv" / "www" / "index.html").write_text("<h1>live</h1>\n")
    (root / "srv" / "app").mkdir(parents=True)
    return root


@pytest.fixture
def server(tmp_path, fake_remote, monkeypatch):
    paths = Paths(tmp_path / "home")
    paths.ensure()
    paths.ini.write_text(INI, encoding="utf-8")

    srv = Server(paths)
    # Swap the SSH transport for a directory that stands in for the machine, so
    # the tool logic runs for real without needing a host.
    for conn in srv.connections.values():
        conn._transport = LocalTransport(fake_remote)
    srv.remote_root = fake_remote
    return srv


def call(server, name, **args):
    response = server.handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": args},
    })
    result = response["result"]
    return result["content"][0]["text"], result.get("isError", False)


# --------------------------------------------------------------------------
# protocol
# --------------------------------------------------------------------------

def test_initialize_handshake(server):
    response = server.handle({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "test", "version": "1"}},
    })
    result = response["result"]
    assert result["protocolVersion"] == mcpserver.PROTOCOL_VERSION
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == "devlink-mcp"


def test_notifications_get_no_response(server):
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_are_listed_with_schemas(server):
    tools = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {"list-servers", "execute-command", "upload", "download"}
    for tool in tools:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"


def test_unknown_method_is_a_protocol_error(server):
    response = server.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})
    assert response["error"]["code"] == -32601


def test_stdio_loop_round_trip(tmp_path, fake_remote, monkeypatch):
    paths = Paths(tmp_path / "home")
    paths.ensure()
    paths.ini.write_text(INI, encoding="utf-8")

    monkeypatch.setattr(mcpserver, "SSHTransport",
                        lambda **kw: LocalTransport(fake_remote))

    stdin = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
        + "not json at all\n"
        + json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                      "params": {"name": "list-servers", "arguments": {}}}) + "\n"
    )
    stdout = io.StringIO()
    assert mcpserver.serve(paths, stdin=stdin, stdout=stdout) == 0

    replies = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert [r["id"] for r in replies] == [1, 2, 3], "malformed input broke the stream"
    assert "web1" in replies[2]["result"]["content"][0]["text"]


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def test_execute_command_returns_output(server):
    text, is_error = call(server, "execute-command",
                          cmdString="cat /srv/www/index.html", connectionName="web1")
    assert not is_error
    assert "live" in text


def test_denylist_blocks_destructive_commands(server):
    text, is_error = call(server, "execute-command",
                          cmdString="rm -rf /srv/www", connectionName="web1")
    assert is_error
    assert "denylist" in text
    # and the file is still there
    assert (server.remote_root / "srv" / "www" / "index.html").exists()


def test_denylist_catches_a_chained_command(server):
    text, is_error = call(server, "execute-command",
                          cmdString="ls /srv && rm -rf /srv/www", connectionName="web1")
    assert is_error


def test_allowlist_rejects_anything_not_listed(server):
    text, is_error = call(server, "execute-command",
                          cmdString="whoami", connectionName="locked")
    assert is_error
    assert "allowlist" in text

    text, is_error = call(server, "execute-command",
                          cmdString="ls /srv/app", connectionName="locked")
    assert not is_error


def test_failed_command_reports_exit_code(server):
    text, _ = call(server, "execute-command",
                   cmdString="cat /srv/www/missing.txt", connectionName="web1")
    assert "[exit code]" in text


def test_unknown_server_is_reported(server):
    text, is_error = call(server, "execute-command",
                          cmdString="ls", connectionName="nosuch")
    assert is_error
    assert "unknown server" in text


# --------------------------------------------------------------------------
# uploads — the reason this server exists
# --------------------------------------------------------------------------

def test_upload_backs_up_the_file_it_replaces(server, tmp_path):
    local = tmp_path / "new.html"
    local.write_text("<h1>replacement</h1>\n")

    text, is_error = call(server, "upload", localPath=str(local),
                          remotePath="/srv/www/index.html", connectionName="web1")
    assert not is_error

    target = server.remote_root / "srv" / "www" / "index.html"
    assert target.read_text() == "<h1>replacement</h1>\n"

    backups = list((server.remote_root / "srv" / "backup" / "mcp-uploads").rglob("index.html"))
    assert backups, "no backup was taken before overwriting"
    assert backups[0].read_text() == "<h1>live</h1>\n"
    assert "previous version" in text


def test_upload_of_a_new_file_needs_no_backup(server, tmp_path):
    local = tmp_path / "brand-new.txt"
    local.write_text("hello\n")

    text, is_error = call(server, "upload", localPath=str(local),
                          remotePath="/srv/www/brand-new.txt", connectionName="web1")
    assert not is_error
    assert "no existing file" in text
    assert (server.remote_root / "srv" / "www" / "brand-new.txt").read_text() == "hello\n"


def test_upload_outside_the_allowed_paths_is_refused(server, tmp_path):
    local = tmp_path / "evil.sh"
    local.write_text("#!/bin/sh\n")

    text, is_error = call(server, "upload", localPath=str(local),
                          remotePath="/etc/cron.d/evil", connectionName="web1")
    assert is_error
    assert "outside the allowed directories" in text
    assert not (server.remote_root / "etc").exists()


def test_path_traversal_is_refused(server, tmp_path):
    local = tmp_path / "x.txt"
    local.write_text("x\n")
    text, is_error = call(server, "upload", localPath=str(local),
                          remotePath="/srv/www/../../etc/passwd", connectionName="web1")
    assert is_error
    assert ".." in text


def test_upload_requires_an_existing_local_file(server):
    text, is_error = call(server, "upload", localPath="/nonexistent/file",
                          remotePath="/srv/www/x", connectionName="web1")
    assert is_error
    assert "local file not found" in text


def test_download_writes_the_file(server, tmp_path):
    target = tmp_path / "fetched.html"
    text, is_error = call(server, "download", remotePath="/srv/www/index.html",
                          localPath=str(target), connectionName="web1")
    assert not is_error
    assert target.read_text() == "<h1>live</h1>\n"


def test_download_outside_allowed_paths_is_refused(server, tmp_path):
    text, is_error = call(server, "download", remotePath="/etc/shadow",
                          localPath=str(tmp_path / "out"), connectionName="web1")
    assert is_error


# --------------------------------------------------------------------------
# credentials
# --------------------------------------------------------------------------

def test_no_tool_result_ever_contains_a_password(server):
    outputs = [
        call(server, "list-servers")[0],
        call(server, "execute-command", cmdString="ls /srv", connectionName="web1")[0],
        json.dumps(server.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/list"})),
    ]
    for text in outputs:
        assert "s3cret" not in text
