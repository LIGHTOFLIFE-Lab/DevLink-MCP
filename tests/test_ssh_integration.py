# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
"""The real thing: a live sshd, paramiko, and the whole working flow.

Every other test drives ``LocalTransport``. That proves the logic but never
touches ``SSHTransport``, which is the code that actually runs when someone
uses this. paramiko could break — an API change, a key type no longer
accepted, an SFTP quirk — and the rest of the suite would stay green.

So this module starts a real OpenSSH server on the loopback interface, points
the tool at it, and walks the sequence a person actually performs: configure,
inspect over MCP, pull, edit, deploy, get refused because someone edited the
server, roll back.

It skips when sshd, ssh-keygen or paramiko are missing, which is most CI
runners other than Linux.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

from devlink_mcp.config import Paths
from devlink_mcp.sync import Git, Site, deploy, pull, rollback, status
from devlink_mcp.transport import SSHTransport

SSHD = next((p for p in ("/usr/sbin/sshd", "/sbin/sshd", shutil.which("sshd") or "")
             if p and os.path.isfile(p)), None)
KEYGEN = shutil.which("ssh-keygen")
HAS_PARAMIKO = importlib.util.find_spec("paramiko") is not None

pytestmark = [
    pytest.mark.skipif(SSHD is None, reason="no sshd on this machine"),
    pytest.mark.skipif(KEYGEN is None, reason="no ssh-keygen on this machine"),
    pytest.mark.skipif(not HAS_PARAMIKO, reason="paramiko not installed"),
    pytest.mark.skipif(os.name == "nt", reason="the OpenSSH server setup here is POSIX"),
]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def ssh_server(tmp_path_factory):
    """A real sshd, serving a directory that stands in for a customer's site."""
    lab = tmp_path_factory.mktemp("sshlab")
    etc, home, web = lab / "etc", lab / "home", lab / "web"
    for directory in (etc, home / ".ssh", web / "inc", web / "uploads", lab / "backup"):
        directory.mkdir(parents=True)

    subprocess.run([KEYGEN, "-q", "-t", "ed25519", "-f", str(etc / "host"), "-N", ""],
                   check=True)
    subprocess.run([KEYGEN, "-q", "-t", "ed25519", "-f", str(etc / "client"), "-N", ""],
                   check=True)
    shutil.copy(etc / "client.pub", home / ".ssh" / "authorized_keys")
    (home / ".ssh").chmod(0o700)
    (home / ".ssh" / "authorized_keys").chmod(0o600)

    port = _free_port()
    (etc / "sshd_config").write_text(
        f"Port {port}\n"
        "ListenAddress 127.0.0.1\n"
        f"HostKey {etc / 'host'}\n"
        f"PidFile {lab / 'sshd.pid'}\n"
        f"AuthorizedKeysFile {home / '.ssh' / 'authorized_keys'}\n"
        "UsePAM no\nPasswordAuthentication no\nStrictModes no\n"
        "Subsystem sftp internal-sftp\nLogLevel ERROR\n",
        encoding="utf-8",
    )

    started = subprocess.run(
        [SSHD, "-f", str(etc / "sshd_config"), "-E", str(lab / "sshd.log")],
        capture_output=True, text=True,
    )
    if started.returncode != 0:
        pytest.skip(f"could not start sshd: {started.stderr.strip()}")

    # Wait for it to accept connections rather than guessing at a sleep.
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:  # pragma: no cover - only on a very slow machine
        pytest.skip("sshd did not start listening")

    yield {"port": port, "lab": lab, "web": web, "backup": lab / "backup",
           "key": etc / "client", "user": _current_user()}

    pid_file = lab / "sshd.pid"
    if pid_file.exists():
        try:
            os.kill(int(pid_file.read_text().strip()), 15)
        except (OSError, ValueError):  # pragma: no cover - best effort
            pass


def _current_user() -> str:
    try:
        import getpass
        return getpass.getuser()
    except Exception:  # pragma: no cover - unusual environments
        return os.environ.get("USER", "root")


@pytest.fixture
def site_files(ssh_server):
    """Reset the served directory to a known state for each test."""
    web = ssh_server["web"]
    for item in web.iterdir():
        shutil.rmtree(item) if item.is_dir() else item.unlink()
    (web / "inc").mkdir()
    (web / "uploads").mkdir()
    (web / "index.html").write_text("<h1>Site</h1>\n<p>live copy</p>\n", encoding="utf-8")
    (web / "style.css").write_text("body{color:#222}\n", encoding="utf-8")
    (web / "inc" / "header.php").write_text("<?php // header ?>\n", encoding="utf-8")
    (web / "uploads" / "customer.bin").write_bytes(os.urandom(2048))

    backup = ssh_server["backup"]
    if backup.exists():
        shutil.rmtree(backup)
    backup.mkdir()
    return web


@pytest.fixture
def transport(ssh_server):
    tr = SSHTransport(
        host="127.0.0.1", port=ssh_server["port"], user=ssh_server["user"],
        key_file=str(ssh_server["key"]),
    )
    yield tr
    tr.close()


@pytest.fixture
def site(ssh_server):
    return Site(
        name="web1", host="127.0.0.1", port=ssh_server["port"],
        user=ssh_server["user"],
        remote=str(ssh_server["web"]), backup=str(ssh_server["backup"]),
        exclude=("uploads/", "*.log"),
    )


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------

def test_commands_run_on_the_server(transport, site_files):
    result = transport.run("echo hello && pwd")
    assert result.ok
    assert "hello" in result.out


def test_failed_command_reports_its_exit_code(transport, site_files):
    result = transport.run("exit 3")
    assert result.code == 3
    assert not result.ok


def test_files_go_both_ways(transport, site_files, tmp_path):
    fetched = tmp_path / "fetched.html"
    transport.get(str(site_files / "index.html"), fetched)
    assert "live copy" in fetched.read_text(encoding="utf-8")

    outgoing = tmp_path / "new.html"
    outgoing.write_text("<h1>uploaded</h1>\n", encoding="utf-8")
    transport.put(outgoing, str(site_files / "uploaded.html"))
    assert (site_files / "uploaded.html").read_text(encoding="utf-8") == "<h1>uploaded</h1>\n"


def test_binary_files_survive_the_round_trip(transport, site_files, tmp_path):
    blob = bytes(range(256)) * 40
    source = tmp_path / "image.bin"
    source.write_bytes(blob)

    transport.put(source, str(site_files / "image.bin"))
    back = tmp_path / "back.bin"
    transport.get(str(site_files / "image.bin"), back)
    assert back.read_bytes() == blob


# --------------------------------------------------------------------------
# the working flow, over a real connection
# --------------------------------------------------------------------------

def test_the_whole_cycle(transport, site, site_files, tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.invalid")

    work = tmp_path / "work"

    # 1. collect what is on the server
    result = pull(transport, site, work)
    assert (work / "index.html").exists()
    assert not (work / "uploads").exists(), "excluded directory came across"
    Git(work).tag("deploy/base")

    # 2. edit locally and commit
    (work / "index.html").write_text("<h1>Site</h1>\n<p>my edit</p>\n", encoding="utf-8")
    Git(work).commit_all("edit the homepage")

    # 3. the application writes its own file on the server
    (site_files / "session-cache.txt").write_text("runtime\n", encoding="utf-8")

    # 4. deploy only what changed
    outcome = deploy(transport, site, work, tag="deploy/001", since="deploy/base")
    assert outcome["files"] == ["index.html"]
    assert "my edit" in (site_files / "index.html").read_text(encoding="utf-8")
    assert (site_files / "session-cache.txt").exists(), "deploy removed a server file"
    assert outcome["backup"], "no backup was taken"

    # 5. somebody edits the server directly
    (site_files / "index.html").write_text("<h1>Site</h1>\n<p>their edit</p>\n",
                                           encoding="utf-8")
    (work / "index.html").write_text("<h1>Site</h1>\n<p>my next edit</p>\n",
                                     encoding="utf-8")
    Git(work).commit_all("another edit")

    # 6. deploy must refuse rather than destroy their work
    with pytest.raises(RuntimeError) as exc:
        deploy(transport, site, work, tag="deploy/002", since="deploy/001")
    assert "index.html" in str(exc.value)
    assert "their edit" in (site_files / "index.html").read_text(encoding="utf-8")

    # 7. status says the same thing
    state = status(transport, site, work)
    assert "index.html" in state["drift"]
    assert state["clean"] is False

    # 8. roll the server back to what we deployed
    (site_files / "index.html").write_text("<h1>Site</h1>\n<p>my edit</p>\n",
                                           encoding="utf-8")
    restored = rollback(transport, site, work, tag="deploy/001")
    assert restored["restored"] >= 1
    assert "live copy" in (site_files / "index.html").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# the MCP server, over a real connection
# --------------------------------------------------------------------------

def test_mcp_tools_against_a_live_server(ssh_server, site_files, tmp_path):
    from devlink_mcp.mcpserver import Server

    paths = Paths(tmp_path / "home")
    paths.ensure()
    paths.ini.write_text(
        f"[web1]\n"
        f"host = 127.0.0.1\nport = {ssh_server['port']}\n"
        f"user = {ssh_server['user']}\nkey = {ssh_server['key']}\n"
        f"remote = {ssh_server['web']}\nbackup = {ssh_server['backup']}\n",
        encoding="utf-8",
    )
    server = Server(paths)

    def call(name, **args):
        response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": name, "arguments": args}})
        result = response["result"]
        return result["content"][0]["text"], result.get("isError", False)

    try:
        listing, is_error = call("execute-command", cmdString="ls -1",
                                 directory=str(ssh_server["web"]), connectionName="web1")
        assert not is_error, listing
        assert "index.html" in listing

        # an upload must back up the file it replaces
        local = tmp_path / "replacement.html"
        local.write_text("<h1>Site</h1>\n<p>from the assistant</p>\n", encoding="utf-8")
        text, is_error = call("upload", localPath=str(local),
                              remotePath=str(ssh_server["web"] / "index.html"),
                              connectionName="web1")
        assert not is_error, text
        assert "from the assistant" in (site_files / "index.html").read_text(encoding="utf-8")

        backups = list((ssh_server["backup"] / "mcp-uploads").rglob("index.html"))
        assert backups, "the MCP upload took no backup"
        assert "live copy" in backups[0].read_text(encoding="utf-8")

        # the rails hold against a real server too
        _, is_error = call("execute-command", cmdString="rm -rf /", connectionName="web1")
        assert is_error, "the denylist did not stop rm -rf /"

        _, is_error = call("upload", localPath=str(local),
                           remotePath="/etc/passwd", connectionName="web1")
        assert is_error, "an upload outside the allowed paths was permitted"
    finally:
        server.close()
