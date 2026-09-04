# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
"""Open a socket to a server through a proxy.

Some servers are only reachable through a jump proxy, and the WinSCP importer
fills the ``proxy`` setting in automatically when a session had one. Honouring
it is not optional: a setting the tool wrote for you, that then does nothing, is
worse than one you never had.

SOCKS5 and HTTP CONNECT, both in the standard library. paramiko takes the
resulting socket as its ``sock`` argument and speaks SSH over it.

    proxy = socks5://user:pass@10.0.0.1:1080
    proxy = http://10.0.0.1:8080
"""

from __future__ import annotations

import base64
import socket
import struct
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

__all__ = ["ProxyError", "ProxySpec", "parse_proxy", "open_through_proxy"]


class ProxyError(RuntimeError):
    """The proxy refused, or spoke something we do not understand."""


@dataclass
class ProxySpec:
    scheme: str
    host: str
    port: int
    username: str = ""
    password: str = ""


DEFAULT_PORTS = {"socks5": 1080, "socks": 1080, "http": 8080, "https": 8080}


def parse_proxy(url: str) -> ProxySpec | None:
    """``socks5://user:pass@host:1080`` -> a spec. Empty input gives ``None``."""
    url = (url or "").strip()
    if not url:
        return None
    if "://" not in url:
        url = "socks5://" + url          # a bare host:port means SOCKS5

    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme == "socks":
        scheme = "socks5"
    if scheme not in ("socks5", "http", "https"):
        raise ProxyError(
            f"unsupported proxy scheme '{parsed.scheme}'. "
            f"Use socks5://, http:// or https://"
        )
    if not parsed.hostname:
        raise ProxyError(f"no host in proxy address: {url}")

    return ProxySpec(
        scheme=scheme,
        host=parsed.hostname,
        port=parsed.port or DEFAULT_PORTS[scheme],
        username=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
    )


def _recv_exactly(sock: socket.socket, count: int) -> bytes:
    chunks = []
    remaining = count
    while remaining:
        piece = sock.recv(remaining)
        if not piece:
            raise ProxyError("the proxy closed the connection early")
        chunks.append(piece)
        remaining -= len(piece)
    return b"".join(chunks)


def _socks5(sock: socket.socket, spec: ProxySpec, host: str, port: int) -> None:
    # Greeting: offer "no auth", and "username/password" when we have some.
    methods = b"\x00" if not spec.username else b"\x00\x02"
    sock.sendall(bytes([0x05, len(methods)]) + methods)

    version, method = _recv_exactly(sock, 2)
    if version != 0x05:
        raise ProxyError("the proxy did not answer as SOCKS5")
    if method == 0xFF:
        raise ProxyError("the proxy rejected every authentication method offered")

    if method == 0x02:
        if not spec.username:
            raise ProxyError("the proxy wants a username and password")
        user = spec.username.encode("utf-8")
        secret = spec.password.encode("utf-8")
        sock.sendall(bytes([0x01, len(user)]) + user + bytes([len(secret)]) + secret)
        _, status = _recv_exactly(sock, 2)
        if status != 0x00:
            raise ProxyError("the proxy rejected the username or password")
    elif method != 0x00:
        raise ProxyError(f"the proxy chose an authentication method we do not speak: {method}")

    # Connect request, sending the hostname so the proxy resolves it.
    target = host.encode("idna") if not _is_ip(host) else host.encode("ascii")
    if _is_ip(host):
        request = bytes([0x05, 0x01, 0x00, 0x01]) + socket.inet_aton(host)
    else:
        request = bytes([0x05, 0x01, 0x00, 0x03, len(target)]) + target
    sock.sendall(request + struct.pack(">H", port))

    version, reply, _, address_type = _recv_exactly(sock, 4)
    if reply != 0x00:
        raise ProxyError(f"the proxy refused to connect to {host}:{port} "
                         f"({SOCKS5_ERRORS.get(reply, reply)})")

    # Drain the bound address so the socket is left at the start of the stream.
    if address_type == 0x01:
        _recv_exactly(sock, 4)
    elif address_type == 0x03:
        length = _recv_exactly(sock, 1)[0]
        _recv_exactly(sock, length)
    elif address_type == 0x04:
        _recv_exactly(sock, 16)
    _recv_exactly(sock, 2)


SOCKS5_ERRORS = {
    0x01: "general failure",
    0x02: "connection not allowed",
    0x03: "network unreachable",
    0x04: "host unreachable",
    0x05: "connection refused",
    0x06: "TTL expired",
    0x07: "command not supported",
    0x08: "address type not supported",
}


def _is_ip(host: str) -> bool:
    try:
        socket.inet_aton(host)
        return True
    except OSError:
        return False


def _http_connect(sock: socket.socket, spec: ProxySpec, host: str, port: int) -> None:
    request = [f"CONNECT {host}:{port} HTTP/1.1", f"Host: {host}:{port}"]
    if spec.username:
        token = base64.b64encode(
            f"{spec.username}:{spec.password}".encode("utf-8")).decode("ascii")
        request.append(f"Proxy-Authorization: Basic {token}")
    sock.sendall(("\r\n".join(request) + "\r\n\r\n").encode("ascii"))

    # Read just the headers; whatever follows belongs to the tunnel.
    buffer = b""
    while b"\r\n\r\n" not in buffer:
        piece = sock.recv(1)
        if not piece:
            raise ProxyError("the proxy closed the connection before answering")
        buffer += piece
        if len(buffer) > 8192:
            raise ProxyError("the proxy sent an unreasonable response")

    status_line = buffer.split(b"\r\n", 1)[0].decode("latin-1")
    parts = status_line.split(None, 2)
    if len(parts) < 2 or not parts[1].startswith("2"):
        raise ProxyError(f"the proxy refused the tunnel: {status_line}")


def open_through_proxy(proxy_url: str, host: str, port: int,
                       timeout: float = 30.0) -> socket.socket:
    """Return a socket connected to ``host:port`` via the proxy."""
    spec = parse_proxy(proxy_url)
    if spec is None:
        raise ProxyError("no proxy address given")

    sock = socket.create_connection((spec.host, spec.port), timeout=timeout)
    try:
        if spec.scheme == "socks5":
            _socks5(sock, spec, host, port)
        else:
            _http_connect(sock, spec, host, port)
    except Exception:
        sock.close()
        raise
    # paramiko drives the socket itself; a timeout here would abort long
    # commands that are simply quiet for a while.
    sock.settimeout(None)
    return sock
