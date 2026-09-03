# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import random

from devlink_mcp import winscp

_HEX = "0123456789ABCDEF"


def _encode_byte(value: int) -> str:
    return "%02X" % (((~value) & 0xFF) ^ winscp._MAGIC)


def encode_password(username: str, hostname: str, password: str) -> str:
    """Produce a value in the same form WinSCP writes, for round-trip testing."""
    payload = (username + hostname).encode("utf-8") + password.encode("utf-8")
    padding = random.randint(0, 5)
    noise = "".join(random.choice(_HEX) for _ in range(padding * 2))
    head = (_encode_byte(winscp._FLAG) + _encode_byte(0)
            + _encode_byte(len(payload)) + _encode_byte(padding) + noise)
    return head + "".join(_encode_byte(b) for b in payload)


def encode_password_short(username: str, hostname: str, password: str) -> str:
    """The older form, where the first byte is the length rather than a flag."""
    payload = (username + hostname).encode("utf-8") + password.encode("utf-8")
    padding = 2
    head = _encode_byte(len(payload)) + _encode_byte(padding) + "AB" * padding
    return head + "".join(_encode_byte(b) for b in payload)


# --------------------------------------------------------------------------
# password recovery
# --------------------------------------------------------------------------

def test_round_trip_ascii():
    assert winscp.decrypt_password(
        "root", "1.2.3.4", encode_password("root", "1.2.3.4", "p@ss123")
    ) == "p@ss123"


def test_round_trip_special_characters():
    secret = "P@ss=,{}%word!#"
    assert winscp.decrypt_password(
        "deploy", "example.com",
        encode_password("deploy", "example.com", secret)
    ) == secret


def test_round_trip_non_ascii():
    secret = "가나다abc123"
    assert winscp.decrypt_password(
        "user", "host.kr", encode_password("user", "host.kr", secret)
    ) == secret


def test_empty_password():
    assert winscp.decrypt_password("u", "h", encode_password("u", "h", "")) == ""


def test_legacy_short_form():
    assert winscp.decrypt_password(
        "root", "1.2.3.4", encode_password_short("root", "1.2.3.4", "short")
    ) == "short"


def test_master_password_yields_none_not_garbage():
    """A value we cannot decode must not be presented as a password."""
    encoded = encode_password("root", "1.2.3.4", "secret")
    assert winscp.decrypt_password("other", "9.9.9.9", encoded) is None


def test_blank_input():
    assert winscp.decrypt_password("u", "h", "") == ""


# --------------------------------------------------------------------------
# session parsing
# --------------------------------------------------------------------------

INI_SESSIONS = """[Configuration\\General]
Version=6.3.4

[Sessions\\%EC%84%9C%EC%9A%B8]
HostName=1.2.3.4
UserName=root
Password={pw}
FSProtocol=0

[Sessions\\legacy%20ftp]
HostName=ftp.example.com
UserName=ftpuser
FSProtocol=3

[Sessions\\keyonly]
HostName=k.example.com
UserName=ops
PublicKeyFile=C:\\keys\\ops.ppk
FSProtocol=2
"""

REG_SESSIONS = """Windows Registry Editor Version 5.00

[HKEY_CURRENT_USER\\Software\\Martin Prikryl\\WinSCP 2\\Sessions\\dev%20box]
"HostName"="10.0.0.5"
"PortNumber"=dword:0000232a
"UserName"="alice"
"FSProtocol"=dword:00000000
"""


def _ini_bytes(password_plain: str = "hunter2", encoding: str = "utf-16") -> bytes:
    pw = encode_password("root", "1.2.3.4", password_plain)
    return INI_SESSIONS.format(pw=pw).encode(encoding)


def test_reads_utf16_ini_the_way_winscp_writes_it():
    sessions = winscp.read_sessions(_ini_bytes())
    by_name = {s["name"]: s for s in sessions}
    assert "서울" in by_name
    assert by_name["서울"]["host"] == "1.2.3.4"
    assert by_name["서울"]["password"] == "hunter2"


def test_ftp_sessions_are_marked_unusable():
    sessions = {s["name"]: s for s in winscp.read_sessions(_ini_bytes())}
    assert sessions["legacy ftp"]["usable"] is False
    assert sessions["legacy ftp"]["protocol"] == "FTP"


def test_key_sessions_keep_password_empty():
    sessions = {s["name"]: s for s in winscp.read_sessions(_ini_bytes())}
    entry = sessions["keyonly"]
    assert entry["key"].endswith(".ppk")
    assert entry["password"] == ""
    assert entry["password_failed"] is False


def test_registry_export_with_dword_port():
    sessions = winscp.read_sessions(REG_SESSIONS.encode("utf-8"))
    entry = sessions[0]
    assert entry["name"] == "dev box"
    assert entry["port"] == "9002"          # 0x232a
    assert entry["user"] == "alice"


def test_format_detected_from_content_not_extension():
    """People rename these files; the parser should not care."""
    as_ini = winscp.parse(INI_SESSIONS.format(pw="00"))
    as_reg = winscp.parse(REG_SESSIONS)
    assert as_ini and as_reg


def test_master_password_session_flagged_not_filled():
    # a password encoded for a different host: mimics an undecodable value
    pw = encode_password("someone", "elsewhere", "x")
    data = INI_SESSIONS.format(pw=pw).encode("utf-16")
    sessions = {s["name"]: s for s in winscp.read_sessions(data)}
    entry = sessions["서울"]
    assert entry["password"] == ""
    assert entry["password_failed"] is True
