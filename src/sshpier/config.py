# Copyright 2026 sshpier contributors
# SPDX-License-Identifier: Apache-2.0
"""``servers.ini`` — reading, validating, and turning it into MCP config.

One human-editable file describes every server. From it we generate:

``ssh-mcp-config.json``
    consumed by an MCP SSH server, with safety rails filled in automatically
``sites.json``
    consumed by :mod:`sshpier.sync` for pulling and deploying

Keeping one source of truth means the person maintains six lines per server
instead of a nested JSON document, and the rails cannot drift out of sync.
"""

from __future__ import annotations

import configparser
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .i18n import t

__all__ = [
    "ConfigError",
    "Paths",
    "DEFAULT_DENY",
    "DEFAULT_EXCLUDE",
    "read_ini",
    "convert",
    "write_json",
    "problem_with",
]


class ConfigError(Exception):
    """The settings file cannot be used as written."""


# Commands blocked by default on every connection.
#
# These are regular expressions matched anywhere in the command string, so they
# also catch a dangerous command chained after ``&&`` or ``;``.
#
# This is a safety net, not a security boundary: string matching is easy to
# evade (``r''m``, base64, variable expansion). The real control is the
# per-server ``allow`` list. We warn when one is absent.
DEFAULT_DENY = [
    r"(^|[;&|]\s*)rm\s",
    r"(^|[;&|]\s*)(shutdown|reboot|halt|poweroff|init)\b",
    r"(^|[;&|]\s*)mkfs",
    r"(^|[;&|]\s*)dd\s+.*of=/dev/",
    r">\s*/dev/(sd|nvme|hd)",
    r"(^|[;&|]\s*)(userdel|groupdel|passwd|chpasswd)\b",
    r"(^|[;&|]\s*)(iptables|ufw|firewall-cmd)\b",
    r"(^|[;&|]\s*)chmod\s+-R\s+777\s+/",
    r"(^|[;&|]\s*)chown\s+-R\s+[^;&|]*\s+/\s*$",
    r":\(\)\s*\{.*\};\s*:",
    r"/etc/(shadow|sudoers)",
    r"authorized_keys",
    r"(^|[;&|]\s*)(curl|wget)\b[^;&|]*\|\s*(ba)?sh",
    r"(^|[;&|]\s*)history\s+-c",
]

# Directories that hold data rather than code. Pulling these turns a small
# repository into a huge one and copies customer data onto a workstation.
DEFAULT_EXCLUDE = [
    "data/", "files/", "upload/", "uploads/", "cache/", "tmp/",
    "*.log", "*.sql", "node_modules/", ".env", ".git/",
]

KNOWN_KEYS = {
    "host", "port", "user", "username", "password", "key", "privatekey",
    "passphrase", "remote", "backup", "exclude", "mode", "proxy", "timeout",
    "maxoutput", "allow", "deny", "whitelist", "blacklist", "template",
    "name", "enabled", "lang",
}

PLACEHOLDERS = {"change_me", "changeme", "xxx", "여기에직접입력", "your_password"}

_TRUE = {"1", "yes", "y", "true", "on", "예"}
_FALSE = {"0", "no", "n", "false", "off", "아니오"}


@dataclass
class Paths:
    """Where everything lives. One object so nothing hardcodes a layout."""

    root: Path
    ini: Path = field(init=False)
    mcp_json: Path = field(init=False)
    sites_json: Path = field(init=False)
    keys: Path = field(init=False)
    sites: Path = field(init=False)
    repos: Path = field(init=False)
    logs: Path = field(init=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root).expanduser().resolve()
        config = self.root / "config"
        self.ini = config / "servers.ini"
        self.mcp_json = config / "ssh-mcp-config.json"
        self.sites_json = config / "sites.json"
        self.keys = config / "keys"
        self.sites = self.root / "sites"
        self.repos = self.root / "repos"
        self.logs = self.root / "logs"

    @property
    def config_dir(self) -> Path:
        return self.ini.parent

    def ensure(self) -> None:
        for directory in (self.config_dir, self.keys, self.sites, self.repos, self.logs):
            directory.mkdir(parents=True, exist_ok=True)

    @classmethod
    def discover(cls, explicit: str | os.PathLike | None = None) -> "Paths":
        """Root directory: argument, then ``SSHPIER_HOME``, then ``~/.sshpier``."""
        if explicit:
            return cls(Path(explicit))
        env = os.environ.get("SSHPIER_HOME")
        if env:
            return cls(Path(env))
        return cls(Path.home() / ".sshpier")


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

def problem_with(path: Path) -> str | None:
    """Why the settings file cannot be opened, in words. ``None`` if fine."""
    if not path.exists():
        return None
    try:
        with path.open("rb"):
            pass
    except PermissionError:
        return t("cfg.no_permission", path=path)
    except OSError as exc:
        return t("cfg.open_failed", path=path, error=exc)
    return None


def read_ini(path: Path) -> configparser.ConfigParser:
    if not path.exists():
        raise ConfigError(t("cfg.ini_missing"))

    parser = configparser.ConfigParser(
        interpolation=None,              # so '%' in a password survives
        inline_comment_prefixes=(";",),
        delimiters=("=",),
    )
    parser.optionxform = str.lower

    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            parser.read_string(path.read_text(encoding=encoding))
            return parser
        except UnicodeDecodeError:
            continue
        except configparser.Error as exc:
            raise ConfigError(str(exc)) from exc
    raise ConfigError(t("cfg.open_failed", path=path, error="unknown encoding"))


def as_bool(value: str, default: bool = True) -> bool:
    text = (value or "").strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return default


def split_list(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def split_patterns(value: str) -> list[str]:
    """Regex lists are separated by ``|`` or newlines — commas appear inside them."""
    parts: list[str] = []
    for line in (value or "").splitlines():
        parts.extend(p.strip() for p in line.split("|") if p.strip())
    return parts


def _norm_remote(path: str) -> str:
    return (path or "").strip().replace("\\", "/").rstrip("/")


# --------------------------------------------------------------------------
# conversion
# --------------------------------------------------------------------------

def _build(name: str, section, warnings: list[str]) -> tuple[dict, dict]:
    def get(*keys: str, default: str = "") -> str:
        for key in keys:
            if key in section:
                value = section.get(key, "").strip()
                if value:
                    return value
        return default

    host = get("host")
    user = get("user", "username")
    password = get("password")
    key_file = get("key", "privatekey")
    remote = _norm_remote(get("remote"))
    backup = _norm_remote(get("backup"))

    missing = [label for label, value in
               (("host", host), ("user", user), ("remote", remote)) if not value]
    if missing:
        raise ConfigError(t("cfg.missing_fields", name=name, fields=", ".join(missing)))

    if not password and not key_file:
        raise ConfigError(t("cfg.no_auth", name=name))

    if password.strip().lower() in PLACEHOLDERS or password.strip() in PLACEHOLDERS:
        raise ConfigError(t("cfg.placeholder_pw", name=name))

    if not remote.startswith("/"):
        raise ConfigError(t("cfg.remote_abs", name=name, value=remote))

    try:
        port = int(get("port", default="22"))
    except ValueError:
        raise ConfigError(t("cfg.bad_port", name=name, value=get("port"))) from None

    mode = get("mode", default="exec").lower()
    if mode not in ("exec", "shell"):
        raise ConfigError(t("cfg.bad_mode", name=name, value=mode))

    try:
        timeout_s = float(get("timeout", default="60"))
        max_mb = float(get("maxoutput", default="10"))
    except ValueError:
        raise ConfigError(t("cfg.bad_number", name=name)) from None

    entry: dict = {"host": host, "port": port, "username": user}

    if key_file:
        entry["privateKey"] = key_file
        if key_file.lower().endswith(".ppk"):
            warnings.append(t("cfg.ppk", name=name))
        elif not Path(os.path.expanduser(key_file)).exists():
            warnings.append(t("cfg.key_missing", name=name, path=key_file))
        passphrase = get("passphrase")
        if passphrase:
            entry["passphrase"] = passphrase
    if password:
        entry["password"] = password

    entry["allowedRemotePaths"] = [p for p in dict.fromkeys([remote, backup]) if p]

    if mode == "shell":
        entry["transportMode"] = "shell"
        entry["shellReadyTimeoutMs"] = 15000
        entry["shellCommandTimeoutMs"] = int(timeout_s * 1000)
        warnings.append(t("cfg.shell_mode", name=name))
    else:
        entry["commandTimeoutMs"] = int(timeout_s * 1000)

    entry["maxOutputBytes"] = int(max_mb * 1024 * 1024)
    entry["connectionTimeoutMs"] = 30000

    proxy = get("proxy")
    if proxy:
        entry["proxy"] = proxy

    template = get("template")
    if template:
        entry["commandTemplate"] = template

    allow = split_patterns(get("allow", "whitelist"))
    if allow:
        entry["commandWhitelist"] = allow
    else:
        warnings.append(t("cfg.no_whitelist", name=name))

    entry["commandBlacklist"] = DEFAULT_DENY + split_patterns(get("deny", "blacklist"))

    exclude = split_list(get("exclude")) or list(DEFAULT_EXCLUDE)
    site = {
        "connection": name,
        "host": host,
        "port": port,
        "user": user,
        "remote": remote,
        "backup": backup,
        "exclude": exclude,
        "mode": mode,
    }
    return entry, site


def convert(parser: configparser.ConfigParser) -> tuple[dict, dict, list[str], list[str], list[str]]:
    """Turn a parsed ini into (mcp servers, sites, errors, warnings, skipped).

    A bad section does not stop the rest: one mistyped server should not take
    every other connection offline.
    """
    servers: dict[str, dict] = {}
    sites: dict[str, dict] = {}
    errors: list[str] = []
    warnings: list[str] = []
    skipped: list[str] = []

    defaults = parser.defaults()

    for section_name in parser.sections():
        section = parser[section_name]

        for key in section.keys():
            if key not in KNOWN_KEYS and key not in defaults:
                warnings.append(t("cfg.unknown_key", name=section_name, key=key))

        if not as_bool(section.get("enabled", "yes")):
            skipped.append(t("cfg.skipped", name=section_name))
            continue

        name = (section.get("name") or section_name).strip()
        if name in servers:
            errors.append(t("cfg.dup_name", name=section_name, value=name))
            continue

        try:
            entry, site = _build(name, section, warnings)
        except ConfigError as exc:
            errors.append(str(exc))
            continue

        servers[name] = entry
        sites[name] = site

    return servers, sites, errors, warnings, skipped


def write_json(path: Path, data) -> None:
    """Write atomically.

    A half-written config that an MCP server then tries to load is a confusing
    failure. Write to a temporary file and rename over the target instead.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def generate(paths: Paths, write: bool = True) -> dict:
    """Read the ini and produce both output files. Returns a result summary."""
    problem = problem_with(paths.ini)
    if problem:
        return {"ok": False, "errors": [problem], "warnings": [],
                "skipped": [], "servers": {}, "sites": {}}
    try:
        parser = read_ini(paths.ini)
    except ConfigError as exc:
        return {"ok": False, "errors": [str(exc)], "warnings": [],
                "skipped": [], "servers": {}, "sites": {}}

    servers, sites, errors, warnings, skipped = convert(parser)

    if servers and write:
        write_json(paths.mcp_json, servers)
        write_json(paths.sites_json, sites)

    return {
        "ok": bool(servers) and not errors,
        "errors": errors,
        "warnings": warnings,
        "skipped": skipped,
        "servers": servers,
        "sites": sites,
    }


def load_sites(paths: Paths) -> dict[str, dict]:
    """Site definitions for the sync commands, regenerating if needed."""
    if paths.sites_json.exists():
        try:
            return json.loads(paths.sites_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return generate(paths, write=True)["sites"]
