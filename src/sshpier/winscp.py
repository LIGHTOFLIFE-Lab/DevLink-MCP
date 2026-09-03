# Copyright 2026 sshpier contributors
# SPDX-License-Identifier: Apache-2.0
"""Read WinSCP session exports.

WinSCP stores sessions either in ``WinSCP.ini`` or under
``HKCU\\Software\\Martin Prikryl\\WinSCP 2\\Sessions``. Both are supported;
the format is detected from the file contents rather than the extension,
because people rename these files.

Stored passwords
----------------
Unless a WinSCP master password is set, session passwords are stored with a
reversible obfuscation, not encryption. :func:`decrypt_password` undoes it so
that you can migrate your own saved sessions in one step instead of retyping
dozens of passwords.

This is implemented from the publicly documented scheme and contains no WinSCP
code. It cannot read sessions protected by a master password: those fail the
key check and return ``None`` rather than returning garbage.

If you would rather not have this capability on disk at all, delete this
module's :func:`decrypt_password` body — the importer treats a failure as
"password not available" and leaves the field blank.
"""

from __future__ import annotations

import codecs
import re
from pathlib import Path
from urllib.parse import unquote

__all__ = [
    "FS_PROTOCOL",
    "decrypt_password",
    "decode_bytes",
    "parse",
    "read_sessions",
]

# WinSCP FSProtocol values. Only the SSH-based ones are useful to us.
FS_PROTOCOL = {
    "0": "SFTP",
    "1": "SCP",
    "2": "SFTP",
    "3": "FTP",
    "5": "WebDAV",
    "6": "S3",
}

SSH_PROTOCOLS = ("SFTP", "SCP")

_MAGIC = 0xA3
_FLAG = 0xFF
_HEX = "0123456789ABCDEF"


# --------------------------------------------------------------------------
# password obfuscation
# --------------------------------------------------------------------------

class _Reader:
    __slots__ = ("s", "i")

    def __init__(self, s: str) -> None:
        self.s = s
        self.i = 0

    def byte(self) -> int:
        try:
            a = _HEX.index(self.s[self.i].upper())
            b = _HEX.index(self.s[self.i + 1].upper())
        except (IndexError, ValueError):
            self.i += 2
            return 0
        self.i += 2
        return (~(((a << 4) + b) ^ _MAGIC)) & 0xFF


def decrypt_password(username: str, hostname: str, stored: str) -> str | None:
    """Return the plaintext password, or ``None`` if it cannot be recovered.

    ``None`` means the value is protected by a master password, or is not in
    the format we understand. The caller should leave the password blank
    rather than storing whatever came out.
    """
    if not stored:
        return ""

    key = (username or "") + (hostname or "")
    reader = _Reader(stored.strip())

    flag = reader.byte()
    if flag == _FLAG:
        reader.byte()          # reserved, unused
        length = reader.byte()
    else:
        length = flag

    padding = reader.byte()
    reader.i += padding * 2    # skip the random prefix

    raw = bytes(reader.byte() for _ in range(length))

    # WinSCP stores (key + password). If the key prefix is not there, we did
    # not decode a real password.
    if key:
        key_bytes = key.encode("utf-8")
        if raw[: len(key_bytes)] != key_bytes:
            return None
        raw = raw[len(key_bytes):]

    return decode_bytes(raw)


def decode_bytes(raw: bytes) -> str:
    for encoding in ("utf-8", "cp949", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", "replace")  # pragma: no cover - unreachable


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def read_text(path: Path) -> str:
    """Read an export file. WinSCP writes UTF-16 more often than not."""
    return decode_file_bytes(path.read_bytes())


def decode_file_bytes(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "utf-8", "cp949", "latin-1"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("latin-1")  # pragma: no cover - unreachable


def parse_ini(text: str) -> dict[str, dict[str, str]]:
    sessions: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            if section.startswith("Sessions\\"):
                current = sessions.setdefault(unquote(section.split("\\", 1)[1]), {})
            else:
                current = None
        elif current is not None and "=" in line:
            key, value = line.split("=", 1)
            current[key.strip()] = unquote(value.strip())
    return sessions


_REG_KEY = re.compile(r"^\[.*WinSCP 2\\Sessions\\(.+)\]$", re.IGNORECASE)
_REG_VAL = re.compile(r'^"([^"]+)"=(.*)$')


def parse_reg(text: str) -> dict[str, dict[str, str]]:
    sessions: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for line in text.splitlines():
        line = line.strip()
        match = _REG_KEY.match(line)
        if match:
            current = sessions.setdefault(unquote(match.group(1)), {})
            continue
        if line.startswith("["):
            current = None
            continue
        if current is None:
            continue
        match = _REG_VAL.match(line)
        if not match:
            continue
        name, raw = match.group(1), match.group(2).strip()
        if raw.lower().startswith("dword:"):
            current[name] = str(int(raw[6:], 16))
        elif raw.startswith('"') and raw.endswith('"'):
            current[name] = codecs.decode(raw[1:-1], "unicode_escape")
    return sessions


def parse(text: str) -> dict[str, dict[str, str]]:
    """Parse either format, deciding from the contents.

    Filenames lie: people export to ``.txt``, rename ``.reg`` to ``.ini``, and
    so on. If the first guess yields nothing we try the other parser before
    giving up.
    """
    looks_like_reg = (
        "Windows Registry Editor" in text[:200]
        or "HKEY_CURRENT_USER" in text[:4000]
    )
    first, second = (parse_reg, parse_ini) if looks_like_reg else (parse_ini, parse_reg)
    return first(text) or second(text)


def read_sessions(source: Path | bytes) -> list[dict]:
    """Normalise an export into a list of plain dicts, SSH sessions only.

    Each entry has: ``name``, ``host``, ``port``, ``user``, ``password``,
    ``key``, ``proxy``, plus ``password_failed`` when a stored password was
    present but could not be recovered.
    """
    text = decode_file_bytes(source) if isinstance(source, bytes) else read_text(source)
    result = []

    for raw_name, values in parse(text).items():
        host = values.get("HostName")
        protocol = FS_PROTOCOL.get(values.get("FSProtocol", "0"), "SFTP")
        name = re.sub(r"[\[\]=;#\r\n]+", "-", raw_name).strip() or "session"

        entry = {
            "name": name,
            "raw_name": raw_name,
            "host": host or "",
            "port": values.get("PortNumber", "22") or "22",
            "user": values.get("UserName", ""),
            "key": values.get("PublicKeyFile", ""),
            "password": "",
            "password_failed": False,
            "proxy": "",
            "protocol": protocol,
            "usable": bool(host) and protocol in SSH_PROTOCOLS,
        }

        stored = values.get("Password", "")
        if stored and not entry["key"]:
            recovered = decrypt_password(entry["user"], entry["host"], stored)
            if recovered:
                entry["password"] = recovered
            else:
                entry["password_failed"] = True

        if values.get("ProxyMethod") in ("2", "3"):
            proxy_host = values.get("ProxyHost")
            proxy_port = values.get("ProxyPort")
            if proxy_host and proxy_port:
                entry["proxy"] = f"socks5://{proxy_host}:{proxy_port}"

        result.append(entry)

    return result
