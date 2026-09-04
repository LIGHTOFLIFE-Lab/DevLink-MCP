# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import Paths, generate, load_sites
from .i18n import set_language, t


def example_config() -> str:
    """The starter ``servers.ini``.

    Installed wheels carry it as package data. A development checkout runs from
    ``src/`` where that file does not exist, so fall back to the copy in
    ``examples/`` and then to a generated header, rather than writing nothing
    and leaving the person with an empty directory.
    """
    packaged = Path(__file__).parent / "data" / "servers.example.ini"
    if packaged.exists():
        return packaged.read_text(encoding="utf-8")

    checkout = Path(__file__).resolve().parents[2] / "examples" / "servers.example.ini"
    if checkout.exists():
        return checkout.read_text(encoding="utf-8")

    from .importer import render
    return render([])[0]


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--home", help="Root directory (default: $DEVLINK_HOME or ~/.devlink)")
    parser.add_argument("--lang", choices=["en", "ko"], help="Message language")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devlink",
        description="Configure SSH servers for MCP, pull sites, deploy with rollback.",
    )
    parser.add_argument("--version", action="version", version=f"devlink-mcp {__version__}")
    _add_common(parser)
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("gui", help="Open the settings panel in a browser")
    _add_common(p)
    p.add_argument("--no-browser", action="store_true", help="Do not open a browser")
    p.add_argument("--port", type=int, default=0, help="Bind to a fixed port")

    p = sub.add_parser("check", help="Validate settings without writing anything")
    _add_common(p)

    p = sub.add_parser("build", help="Write the MCP config from servers.ini")
    _add_common(p)

    p = sub.add_parser("serve", help="Run the MCP server on stdio (for your MCP client)")
    _add_common(p)

    p = sub.add_parser("init", help="Create the directory layout and an example file")
    _add_common(p)

    p = sub.add_parser("import", help="Import sessions from a WinSCP export")
    _add_common(p)
    p.add_argument("source", help="WinSCP .ini or .reg export")
    p.add_argument("-o", "--output", help="Where to write servers.ini")
    p.add_argument("--force", action="store_true", help="Overwrite an existing file")

    for name, help_text in (
        ("pull", "Fetch a site from its server and commit it"),
        ("deploy", "Upload changed files and tag the deployment"),
        ("rollback", "Restore the server from a deployment backup"),
        ("status", "Compare local, server, and last deployment"),
    ):
        p = sub.add_parser(name, help=help_text)
        _add_common(p)
        p.add_argument("site", help="Server name from servers.ini")
        if name == "deploy":
            p.add_argument("--tag", help="Tag for this deployment")
            p.add_argument("--since", help="Compare against this ref instead of the last tag")
            p.add_argument("--force", action="store_true",
                           help="Deploy even if the server has drifted (dangerous)")
        if name == "rollback":
            p.add_argument("--tag", help="Deployment tag to restore")

    return parser


def _report(result: dict) -> int:
    for line in result.get("warnings", []):
        print(f"  ! {line}")
    for line in result.get("skipped", []):
        print(f"  - {line}")
    for line in result.get("errors", []):
        print(f"  x {line}", file=sys.stderr)
    for name in result.get("servers", {}):
        site = result.get("sites", {}).get(name, {})
        print(f"  ok {name}  {site.get('user','?')}@{site.get('host','?')}"
              f"  -> {site.get('remote','?')}")
    return 0 if result.get("ok") else 1


def _secrets_for(paths: Paths, name: str) -> dict:
    """Credentials stay in this process; they are read straight from the ini."""
    from .config import read_ini
    parser = read_ini(paths.ini)
    for section in parser.sections():
        display = (parser[section].get("name") or section).strip()
        if display == name:
            sec = parser[section]
            return {
                "password": sec.get("password", ""),
                "key": sec.get("key", sec.get("privatekey", "")),
                "passphrase": sec.get("passphrase", ""),
            }
    return {}


def _sync_command(args, paths: Paths) -> int:
    from . import sync
    from .transport import connect

    sites = load_sites(paths)
    site = sync.resolve_site(sites, args.site)
    work = site.work_dir(paths.sites)

    with connect(sites[args.site], _secrets_for(paths, args.site)) as tr:
        if args.command == "pull":
            print(t("sync.pull_start", name=site.name, host=site.host, remote=site.remote))
            result = sync.pull(tr, site, work)
            print(t("sync.pull_done", count=result["files"], path=result["path"]))
            if result.get("saved_local"):
                print(t("sync.pull_saved_local"))
                print(f"    git checkout {result['saved_local'][:8]} -- <file>")
            if result.get("first_time"):
                print(t("sync.pull_first"))
            else:
                print(t("sync.pull_changed") if result["changed"]
                      else t("sync.pull_nochange"))
            return 0

        if args.command == "deploy":
            tag = args.tag or sync.default_tag()
            result = sync.deploy(tr, site, work, tag=tag,
                                 since=args.since or "", force=args.force)
            print(result["message"])
            for name in result["files"]:
                print(f"    {name}")
            return 0

        if args.command == "rollback":
            outcome = sync.rollback(tr, site, work, tag=args.tag or "")
            print(outcome["message"])
            if outcome.get("source") == "git-history":
                print(t("sync.rollback_from_git"))
            return 0

        state = sync.status(tr, site, work)
        if state["clean"]:
            print(t("sync.status_clean"))
            return 0
        if state["drift"]:
            print(t("sync.status_drift"))
            for name in state["drift"]:
                print(f"    {name}")
        if state["pending"]:
            print(t("sync.status_undeployed"))
            for name in state["pending"]:
                print(f"    {name}")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    set_language(getattr(args, "lang", None) or "")
    paths = Paths.discover(getattr(args, "home", None))

    command = args.command or "gui"

    if command == "init":
        paths.ensure()
        created = False
        if not paths.ini.exists():
            paths.ini.write_text(example_config(), encoding="utf-8")
            created = True
        print(f"Ready: {paths.root}")
        print(f"Edit:  {paths.ini}" + ("" if created else "  (already existed)"))
        return 0

    if command == "serve":
        from .mcpserver import serve as serve_mcp
        return serve_mcp(paths)

    if command == "gui":
        from .gui import serve
        paths.ensure()
        return serve(paths, open_browser=not args.no_browser, port=args.port)

    if command in ("check", "build"):
        result = generate(paths, write=(command == "build"))
        code = _report(result)
        if command == "build" and result["servers"]:
            print(t("cfg.written", count=len(result["servers"]), path=paths.mcp_json))
        return code

    if command == "import":
        from .winscp import read_sessions
        from .importer import write_servers_ini

        target = Path(args.output) if args.output else paths.ini
        if target.exists() and not args.force:
            print(f"{target} exists. Use --force to overwrite.", file=sys.stderr)
            return 2
        sessions = read_sessions(Path(args.source))
        count, notes = write_servers_ini(target, sessions)
        print(t("import.result", count=count))
        for note in notes:
            print(f"  ! {note}")
        return 0 if count else 1

    if command in ("pull", "deploy", "rollback", "status"):
        try:
            return _sync_command(args, paths)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
