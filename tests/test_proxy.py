# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
"""Proxy support, against proxies that actually answer.

The WinSCP importer fills the ``proxy`` setting in by itself when a session had
one, so this path has to work rather than merely exist. These tests stand up a
SOCKS5 and an HTTP CONNECT proxy on loopback and push real bytes through them.
"""

from __future__ import annotations

import base64
import socket
import struct
import threading

import pytest

from devlink_mcp.proxy import ProxyError, open_through_proxy, parse_proxy


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

@pytest.mark.parametrize("url, scheme, host, port, user", [
    ("socks5://1.2.3.4:1080", "socks5", "1.2.3.4", 1080, ""),
    ("socks://host:9050", "socks5", "host", 9050, ""),
    ("socks5://alice:s3cret@host:1080", "socks5", "host", 1080, "alice"),
    ("http://proxy:3128", "http", "proxy", 3128, ""),
    ("http://proxy", "http", "proxy", 8080, ""),
    ("https://u:p@proxy:8443", "https", "proxy", 8443, "u"),
    # A bare host:port is the shape people paste; assume SOCKS5.
    ("127.0.0.1:1080", "socks5", "127.0.0.1", 1080, ""),
])
def test_parse(url, scheme, host, port, user):
    spec = parse_proxy(url)
    assert (spec.scheme, spec.host, spec.port, spec.username) == (scheme, host, port, user)


def test_percent_encoded_credentials():
    spec = parse_proxy("socks5://user%40corp:p%40ss@host:1080")
    assert spec.username == "user@corp"
    assert spec.password == "p@ss"


def test_no_proxy_is_not_an_error():
    assert parse_proxy("") is None
    assert parse_proxy("   ") is None


@pytest.mark.parametrize("url", ["ftp://host", "socks5://", "gopher://h:70"])
def test_bad_proxy_is_rejected_clearly(url):
    with pytest.raises(ProxyError):
        parse_proxy(url)


# --------------------------------------------------------------------------
# proxies that answer
# --------------------------------------------------------------------------

def _serve_once(handler) -> tuple[str, int, threading.Thread]:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    host, port = listener.getsockname()

    def run():
        try:
            client, _ = listener.accept()
            with client:
                handler(client)
        except OSError:  # pragma: no cover - listener closed
            pass
        finally:
            listener.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return host, port, thread


@pytest.fixture
def echo_target():
    """A server that answers HELLO, standing in for sshd."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    host, port = listener.getsockname()

    def run():
        try:
            client, _ = listener.accept()
            with client:
                client.sendall(b"HELLO")
        except OSError:  # pragma: no cover
            pass

    threading.Thread(target=run, daemon=True).start()
    yield host, port
    listener.close()


def _socks5_handler(target, *, require_auth=False, reply=0x00):
    def handle(client):
        version, count = client.recv(2)
        methods = client.recv(count)
        if require_auth:
            if 0x02 not in methods:
                client.sendall(bytes([0x05, 0xFF]))
                return
            client.sendall(bytes([0x05, 0x02]))
            client.recv(1)                          # auth version
            user_len = client.recv(1)[0]
            client.recv(user_len)
            pass_len = client.recv(1)[0]
            client.recv(pass_len)
            client.sendall(bytes([0x01, 0x00]))
        else:
            client.sendall(bytes([0x05, 0x00]))

        header = client.recv(4)                     # ver, cmd, rsv, atyp
        atyp = header[3]
        if atyp == 0x01:
            client.recv(4)
        elif atyp == 0x03:
            client.recv(client.recv(1)[0])
        client.recv(2)                              # port

        client.sendall(bytes([0x05, reply, 0x00, 0x01]) + b"\x00\x00\x00\x00"
                       + struct.pack(">H", 0))
        if reply != 0x00:
            return

        # Tunnel through to the real target.
        upstream = socket.create_connection(target)
        with upstream:
            data = upstream.recv(64)
            if data:
                client.sendall(data)
    return handle


def test_socks5_tunnel_carries_data(echo_target):
    host, port, _ = _serve_once(_socks5_handler(echo_target))
    sock = open_through_proxy(f"socks5://{host}:{port}", "example.invalid", 22)
    with sock:
        assert sock.recv(16) == b"HELLO"


def test_socks5_with_credentials(echo_target):
    host, port, _ = _serve_once(_socks5_handler(echo_target, require_auth=True))
    sock = open_through_proxy(f"socks5://alice:secret@{host}:{port}",
                              "example.invalid", 22)
    with sock:
        assert sock.recv(16) == b"HELLO"


def test_socks5_refusal_is_explained(echo_target):
    host, port, _ = _serve_once(_socks5_handler(echo_target, reply=0x05))
    with pytest.raises(ProxyError) as exc:
        open_through_proxy(f"socks5://{host}:{port}", "example.invalid", 22)
    assert "refused" in str(exc.value).lower()


def test_socks5_wanting_auth_we_do_not_have(echo_target):
    host, port, _ = _serve_once(_socks5_handler(echo_target, require_auth=True))
    with pytest.raises(ProxyError):
        open_through_proxy(f"socks5://{host}:{port}", "example.invalid", 22)


def _http_handler(target, *, status=b"HTTP/1.1 200 Connection established",
                  expect_auth=None):
    def handle(client):
        request = b""
        while b"\r\n\r\n" not in request:
            piece = client.recv(1024)
            if not piece:
                return
            request += piece
        if expect_auth is not None:
            token = base64.b64encode(expect_auth.encode()).decode()
            if f"Proxy-Authorization: Basic {token}".encode() not in request:
                client.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
                return
        client.sendall(status + b"\r\n\r\n")
        if not status.split()[1].startswith(b"2"):
            return
        upstream = socket.create_connection(target)
        with upstream:
            data = upstream.recv(64)
            if data:
                client.sendall(data)
    return handle


def test_http_connect_tunnel(echo_target):
    host, port, _ = _serve_once(_http_handler(echo_target))
    sock = open_through_proxy(f"http://{host}:{port}", "example.invalid", 22)
    with sock:
        assert sock.recv(16) == b"HELLO"


def test_http_connect_with_credentials(echo_target):
    host, port, _ = _serve_once(_http_handler(echo_target, expect_auth="bob:hunter2"))
    sock = open_through_proxy(f"http://bob:hunter2@{host}:{port}",
                              "example.invalid", 22)
    with sock:
        assert sock.recv(16) == b"HELLO"


def test_http_refusal_is_explained(echo_target):
    host, port, _ = _serve_once(
        _http_handler(echo_target, status=b"HTTP/1.1 403 Forbidden"))
    with pytest.raises(ProxyError) as exc:
        open_through_proxy(f"http://{host}:{port}", "example.invalid", 22)
    assert "403" in str(exc.value)


def test_unreachable_proxy_raises_rather_than_hanging():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]
    with pytest.raises((OSError, ProxyError)):
        open_through_proxy(f"socks5://127.0.0.1:{dead_port}", "h", 22, timeout=2)
