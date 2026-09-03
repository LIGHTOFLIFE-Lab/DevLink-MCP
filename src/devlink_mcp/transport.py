# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
"""Remote execution and file transfer, behind one small interface.

Two implementations:

:class:`SSHTransport`
    the real thing, over paramiko
:class:`LocalTransport`
    runs against a directory on this machine

``LocalTransport`` exists so the deploy and rollback logic can be tested end to
end without a server. Those are the operations that overwrite other people's
websites; they deserve tests that actually run.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .i18n import t

__all__ = ["Result", "Transport", "LocalTransport", "SSHTransport", "connect"]


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.code == 0

    def check(self, what: str = "") -> "Result":
        if not self.ok:
            detail = (self.err or self.out or "").strip()
            raise RuntimeError(f"{what or 'remote command'} failed: {detail}")
        return self


class Transport:
    """What the sync code needs from a connection."""

    def run(self, command: str) -> Result:            # pragma: no cover - interface
        raise NotImplementedError

    def get(self, remote: str, local: Path) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def put(self, local: Path, remote: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def tmp_path(self, name: str) -> str:
        """A writable scratch path on the far side, for staging archives."""
        return f"/tmp/{name}"

    def close(self) -> None:
        pass

    def __enter__(self) -> "Transport":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class LocalTransport(Transport):
    """Treat a local directory as if it were the remote machine.

    Remote absolute paths are mapped under ``root``. Used by the test suite and
    by ``--dry-run``, so the same code path is exercised either way.
    """

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        # Commands stage archives under /tmp; give that a home inside the fake
        # root so the mapping below has somewhere to write.
        (self.root / "tmp").mkdir(exist_ok=True)

    def _map(self, remote: str) -> Path:
        return self.root / PurePosixPath(remote).relative_to("/")

    def run(self, command: str) -> Result:
        # Remote commands are written as POSIX shell; run them with the root as
        # the filesystem origin by rewriting absolute paths.
        rewritten = command.replace(" /", f" {self.root}/")
        if rewritten.startswith("/"):
            rewritten = f"{self.root}{rewritten}"
        proc = subprocess.run(
            rewritten, shell=True, cwd=self.root,
            capture_output=True, text=True,
        )
        return Result(proc.returncode, proc.stdout, proc.stderr)

    def get(self, remote: str, local: Path) -> None:
        source = self._map(remote)
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, local)

    def put(self, local: Path, remote: str) -> None:
        target = self._map(remote)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local, target)


class SSHTransport(Transport):
    """paramiko-backed transport."""

    def __init__(self, host: str, port: int, user: str,
                 password: str = "", key_file: str = "", passphrase: str = "",
                 timeout: int = 30):
        try:
            import paramiko
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise RuntimeError(t("sync.need_paramiko")) from exc

        self._paramiko = paramiko
        self.client = paramiko.SSHClient()
        self.client.load_system_host_keys()
        # Unknown hosts are added rather than refused. This mirrors what the
        # person already does in their SFTP client; it is not a substitute for
        # verifying a fingerprint on a server that matters.
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        kwargs = {
            "hostname": host,
            "port": int(port or 22),
            "username": user,
            "timeout": timeout,
            "allow_agent": not password,
            "look_for_keys": not password,
        }
        if key_file:
            kwargs["key_filename"] = os.path.expanduser(key_file)
            if passphrase:
                kwargs["passphrase"] = passphrase
        if password:
            kwargs["password"] = password

        self.client.connect(**kwargs)
        self._sftp = None

    @property
    def sftp(self):
        if self._sftp is None:
            self._sftp = self.client.open_sftp()
        return self._sftp

    def run(self, command: str) -> Result:
        _, stdout, stderr = self.client.exec_command(command)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        return Result(stdout.channel.recv_exit_status(), out, err)

    def get(self, remote: str, local: Path) -> None:
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        self.sftp.get(remote, str(local))

    def put(self, local: Path, remote: str) -> None:
        self.sftp.put(str(local), remote)

    def close(self) -> None:
        if self._sftp is not None:
            try:
                self._sftp.close()
            except Exception:  # pragma: no cover - best effort
                pass
        self.client.close()


def connect(site: dict, secrets: dict | None = None) -> Transport:
    """Open a transport for one site definition."""
    secrets = secrets or {}
    return SSHTransport(
        host=site["host"],
        port=int(site.get("port", 22)),
        user=site["user"],
        password=secrets.get("password", ""),
        key_file=secrets.get("key", ""),
        passphrase=secrets.get("passphrase", ""),
    )


def quote(path: str) -> str:
    return shlex.quote(path)
