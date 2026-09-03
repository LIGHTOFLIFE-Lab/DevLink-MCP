# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
"""An MCP server that speaks SSH, over stdio.

Why DevLink-MCP ships its own rather than configuring somebody else's: we already
hold the connection details and a working SSH transport, so the remaining piece
is a JSON-RPC loop. Owning it buys three things that matter here.

*No Node.js.* The whole tool becomes "you need Python", instead of Python for
the panel and Node for the server.

*Uploads are backed up.* This is the gap that motivated it. When an assistant
writes a file through this server, the version being overwritten is copied to
the site's backup directory first. A write that used to be irreversible now
leaves a trail.

*One place enforces the rules.* The command allowlist, denylist, path limits,
timeouts and output caps are applied by the same code that generates them, so
they cannot fall out of step.

The protocol surface is small — ``initialize``, ``tools/list``, ``tools/call``
and a couple of notifications — and is implemented directly rather than through
an SDK, keeping the core dependency-free.

Anything written to stdout is protocol. Diagnostics go to stderr.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
import threading
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import __version__
from .config import Paths, generate, read_ini
from .transport import SSHTransport, quote

PROTOCOL_VERSION = "2024-11-05"

__all__ = ["serve", "Server"]


def log(message: str) -> None:
    print(f"[devlink] {message}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# connections
# --------------------------------------------------------------------------

class Connection:
    """One configured server, with its rules and a lazily opened transport."""

    def __init__(self, name: str, entry: dict, site: dict, secrets: dict):
        self.name = name
        self.entry = entry
        self.site = site
        self.secrets = secrets
        self._transport = None
        self._lock = threading.Lock()

        self.allow = [re.compile(p) for p in entry.get("commandWhitelist", [])]
        self.deny = [re.compile(p) for p in entry.get("commandBlacklist", [])]
        self.allowed_paths = [p.rstrip("/") for p in entry.get("allowedRemotePaths", [])]
        self.timeout = int(entry.get("commandTimeoutMs", 60000)) / 1000
        self.max_output = int(entry.get("maxOutputBytes", 10 * 1024 * 1024))

    @property
    def transport(self) -> SSHTransport:
        with self._lock:
            if self._transport is None:
                self._transport = SSHTransport(
                    host=self.entry["host"],
                    port=int(self.entry.get("port", 22)),
                    user=self.entry["username"],
                    password=self.secrets.get("password", ""),
                    key_file=self.secrets.get("key", ""),
                    passphrase=self.secrets.get("passphrase", ""),
                )
            return self._transport

    def close(self) -> None:
        if self._transport is not None:
            try:
                self._transport.close()
            except Exception:  # pragma: no cover - best effort
                pass
            self._transport = None

    # -- rules --------------------------------------------------------
    def check_command(self, command: str) -> str | None:
        """Reason the command is not allowed, or None."""
        if self.allow and not any(r.search(command) for r in self.allow):
            return "command is not in the allowlist for this server"
        for rule in self.deny:
            if rule.search(command):
                return "command matches the denylist for this server"
        return None

    def check_path(self, remote: str) -> str | None:
        """Reason the path is out of bounds, or None."""
        if not remote.startswith("/"):
            return "remote path must be absolute"
        if ".." in PurePosixPath(remote).parts:
            return "remote path may not contain '..'"
        if not self.allowed_paths:
            return None
        target = PurePosixPath(remote)
        for allowed in self.allowed_paths:
            root = PurePosixPath(allowed)
            if target == root or root in target.parents:
                return None
        return (f"remote path is outside the allowed directories "
                f"({', '.join(self.allowed_paths)})")


def load_connections(paths: Paths) -> dict[str, Connection]:
    result = generate(paths, write=True)
    if not result["servers"]:
        raise RuntimeError("; ".join(result["errors"]) or "no usable connections")

    # Credentials are read here and stay in this process. They are never part
    # of a tool result, so the model does not see them.
    secrets: dict[str, dict] = {}
    parser = read_ini(paths.ini)
    for section in parser.sections():
        name = (parser[section].get("name") or section).strip()
        sec = parser[section]
        secrets[name] = {
            "password": sec.get("password", ""),
            "key": sec.get("key", sec.get("privatekey", "")),
            "passphrase": sec.get("passphrase", ""),
        }

    return {
        name: Connection(name, entry, result["sites"].get(name, {}), secrets.get(name, {}))
        for name, entry in result["servers"].items()
    }


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------

TOOLS = [
    {
        "name": "list-servers",
        "description": "List the configured SSH servers and their working directories.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "execute-command",
        "description": "Run a shell command on a configured server and return its output.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cmdString": {"type": "string", "description": "Command to run"},
                "connectionName": {"type": "string", "description": "Server name"},
                "directory": {"type": "string", "description": "Working directory"},
                "timeout": {"type": "number", "description": "Timeout in milliseconds"},
            },
            "required": ["cmdString"],
        },
    },
    {
        "name": "upload",
        "description": ("Upload a local file to a server. The file being replaced is "
                        "copied into the server's backup directory first."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "localPath": {"type": "string"},
                "remotePath": {"type": "string"},
                "connectionName": {"type": "string"},
            },
            "required": ["localPath", "remotePath"],
        },
    },
    {
        "name": "download",
        "description": "Download a file from a server to a local path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "remotePath": {"type": "string"},
                "localPath": {"type": "string"},
                "connectionName": {"type": "string"},
            },
            "required": ["remotePath", "localPath"],
        },
    },
]


class ToolError(Exception):
    pass


class Server:
    def __init__(self, paths: Paths):
        self.paths = paths
        self.connections = load_connections(paths)
        self.default = next(iter(self.connections))

    # -- helpers ------------------------------------------------------
    def pick(self, name: str | None) -> Connection:
        key = (name or "").strip() or self.default
        if key not in self.connections:
            raise ToolError(f"unknown server '{key}'. "
                            f"Known: {', '.join(self.connections)}")
        return self.connections[key]

    def backup_remote_file(self, conn: Connection, remote_path: str) -> str:
        """Copy the file about to be overwritten into the backup directory.

        Returns a description of what happened. A failure here stops the upload:
        silently overwriting without the copy is exactly the situation this is
        meant to prevent.
        """
        backup_root = (conn.site.get("backup") or "").rstrip("/")
        if not backup_root:
            return "no backup directory configured for this server"

        if not conn.transport.run(f"test -f {quote(remote_path)}").ok:
            return "no existing file to back up"

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = PurePosixPath(remote_path).name
        target_dir = f"{backup_root}/mcp-uploads/{stamp}"
        target = f"{target_dir}/{name}"

        conn.transport.run(f"mkdir -p {quote(target_dir)}").check("create backup directory")
        conn.transport.run(
            f"cp -p {quote(remote_path)} {quote(target)}"
        ).check("copy file to backup")
        return target

    # -- tools --------------------------------------------------------
    def tool_list_servers(self, _args: dict) -> str:
        lines = []
        for name, conn in self.connections.items():
            site = conn.site
            lines.append(
                f"{name}: {conn.entry['username']}@{conn.entry['host']}:"
                f"{conn.entry.get('port', 22)}  root={site.get('remote', '?')}"
                f"  backup={site.get('backup') or '(none)'}"
            )
        return "\n".join(lines)

    def tool_execute_command(self, args: dict) -> str:
        command = (args.get("cmdString") or "").strip()
        if not command:
            raise ToolError("cmdString is required")

        conn = self.pick(args.get("connectionName"))
        refusal = conn.check_command(command)
        if refusal:
            raise ToolError(f"refused: {refusal}")

        directory = (args.get("directory") or "").strip()
        if directory:
            refusal = conn.check_path(directory)
            if refusal:
                raise ToolError(f"refused: {refusal}")
            command = f"cd -- {quote(directory)} && {command}"

        result = conn.transport.run(command)

        out = result.out
        if len(out.encode("utf-8", "ignore")) > conn.max_output:
            out = out[: conn.max_output] + "\n[output truncated]"

        sections = [out] if out else []
        if result.err:
            sections.append(f"[stderr]\n{result.err}")
        if result.code != 0:
            sections.append(f"[exit code] {result.code}")
        return "\n".join(sections) or "(no output)"

    def tool_upload(self, args: dict) -> str:
        local = Path(args.get("localPath") or "")
        remote = (args.get("remotePath") or "").strip()
        if not local or not remote:
            raise ToolError("localPath and remotePath are required")
        if not local.is_file():
            raise ToolError(f"local file not found: {local}")

        conn = self.pick(args.get("connectionName"))
        refusal = conn.check_path(remote)
        if refusal:
            raise ToolError(f"refused: {refusal}")

        backup = self.backup_remote_file(conn, remote)
        parent = str(PurePosixPath(remote).parent)
        conn.transport.run(f"mkdir -p {quote(parent)}").check("create remote directory")
        conn.transport.put(local, remote)

        return (f"uploaded {local} -> {remote}\n"
                f"previous version: {backup}")

    def tool_download(self, args: dict) -> str:
        remote = (args.get("remotePath") or "").strip()
        local = Path(args.get("localPath") or "")
        if not remote or not local:
            raise ToolError("remotePath and localPath are required")

        conn = self.pick(args.get("connectionName"))
        refusal = conn.check_path(remote)
        if refusal:
            raise ToolError(f"refused: {refusal}")

        conn.transport.get(remote, local)
        return f"downloaded {remote} -> {local}"

    def call_tool(self, name: str, args: dict) -> str:
        handlers = {
            "list-servers": self.tool_list_servers,
            "execute-command": self.tool_execute_command,
            "upload": self.tool_upload,
            "download": self.tool_download,
        }
        handler = handlers.get(name)
        if handler is None:
            raise ToolError(f"unknown tool '{name}'")
        return handler(args)

    # -- protocol -----------------------------------------------------
    def handle(self, message: dict) -> dict | None:
        """Handle one JSON-RPC message. Returns a response, or None for notifications."""
        method = message.get("method")
        msg_id = message.get("id")

        if method == "initialize":
            return self._ok(msg_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "devlink-mcp", "version": __version__},
            })

        if method in ("notifications/initialized", "initialized", "notifications/cancelled"):
            return None

        if method == "ping":
            return self._ok(msg_id, {})

        if method == "tools/list":
            return self._ok(msg_id, {"tools": TOOLS})

        if method == "tools/call":
            params = message.get("params") or {}
            name = params.get("name", "")
            args = params.get("arguments") or {}
            try:
                text = self.call_tool(name, args)
                return self._ok(msg_id, {"content": [{"type": "text", "text": text}]})
            except (ToolError, RuntimeError, OSError) as exc:
                # Tool failures are reported inside the result, not as protocol
                # errors, so the model can read and act on them.
                return self._ok(msg_id, {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                })

        if msg_id is None:
            return None
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": f"unknown method: {method}"}}

    @staticmethod
    def _ok(msg_id, result) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def close(self) -> None:
        for conn in self.connections.values():
            conn.close()


# --------------------------------------------------------------------------
# stdio loop
# --------------------------------------------------------------------------

def serve(paths: Paths, stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout

    try:
        server = Server(paths)
    except Exception as exc:
        log(f"cannot start: {exc}")
        return 1

    log(f"ready — {len(server.connections)} server(s): {', '.join(server.connections)}")
    if any(not c.allow for c in server.connections.values()):
        log("warning: some servers have no command allowlist")

    try:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                log("ignoring malformed input")
                continue

            response = server.handle(message)
            if response is not None:
                stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                stdout.flush()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        server.close()
    return 0
