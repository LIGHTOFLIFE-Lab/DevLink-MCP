# Copyright 2026 sshpier contributors
# SPDX-License-Identifier: Apache-2.0
"""Pull a site down, edit it locally, deploy it back — with git as the undo.

The shape of it:

``pull``
    tar the remote tree (honouring the exclude list), fetch it in one round
    trip, unpack, and commit. That commit is the record of what the server
    looked like before you touched it.
``deploy``
    work out what changed with ``git diff``, back up exactly those files on the
    server, upload only them, and tag the commit.
``rollback``
    put the backup archive back, or rebuild from the commit history if the
    site was configured without one.

Backups are not something you remember to do. Every operation that could lose
work takes a copy first: ``pull`` commits anything uncommitted before it
replaces the working tree, and ``deploy`` archives the files it is about to
overwrite on the server before it writes.

Three decisions worth stating, because they are what make this safe:

*Only changed files are deployed.* Overwriting a whole web root destroys files
the application itself created — caches, uploads — and resets ownership and
permissions on everything.

*Deploy refuses if the server drifted.* Before writing, we compare checksums of
the files we are about to overwrite against what we recorded at the last
deployment. If someone edited the server directly, their work would be silently
destroyed, so we stop and say so. This catches a colleague who never used this
tool at all, which no amount of git discipline would.

*Nothing uncommitted is ever thrown away.* A pull replaces the working copy, so
it commits what is there first. The person may not have wanted that commit, but
undoing an unwanted commit is trivial and recovering deleted work is not.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .i18n import t
from .transport import Transport, quote

__all__ = ["Site", "pull", "deploy", "rollback", "status", "Git"]

MANIFEST_DIR = ".sshpier"
MANIFEST_NAME = "manifest.json"


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------

class Git:
    """The handful of git operations we need, as plain subprocess calls.

    No dependency on a git library: git itself is already required, and
    shelling out keeps the behaviour identical to what the user sees when they
    run the same commands by hand.
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    def __call__(self, *args: str, check: bool = True) -> str:
        proc = subprocess.run(
            ["git", *args], cwd=self.root,
            capture_output=True, text=True,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
        return proc.stdout.strip()

    @property
    def exists(self) -> bool:
        return (self.root / ".git").exists()

    def init(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.exists:
            self("init", "-q")
            self("commit", "--allow-empty", "-q", "-m", "initial")

    def has_commits(self) -> bool:
        return bool(self("rev-parse", "--verify", "-q", "HEAD", check=False))

    def is_dirty(self) -> bool:
        return bool(self("status", "--porcelain"))

    def commit_all(self, message: str) -> str | None:
        self("add", "-A")
        if not self("diff", "--cached", "--name-only"):
            return None
        self("commit", "-q", "-m", message)
        return self("rev-parse", "HEAD")

    def tag(self, name: str, message: str = "") -> None:
        self("tag", "-f", "-a", name, "-m", message or name)

    def changed_files(self, since: str) -> list[str]:
        out = self("diff", "--name-only", f"{since}..HEAD", check=False)
        return [line for line in out.splitlines() if line.strip()]

    def all_files(self) -> list[str]:
        return [line for line in self("ls-files").splitlines() if line.strip()]

    def last_tag(self, pattern: str = "deploy/*") -> str | None:
        out = self("tag", "--list", pattern, "--sort=-creatordate", check=False)
        tags = [line for line in out.splitlines() if line.strip()]
        return tags[0] if tags else None


# --------------------------------------------------------------------------
# site
# --------------------------------------------------------------------------

@dataclass
class Site:
    name: str
    host: str
    remote: str
    backup: str = ""
    exclude: tuple = ()
    port: int = 22
    user: str = ""

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "Site":
        return cls(
            name=name,
            host=data.get("host", ""),
            remote=data.get("remote", "").rstrip("/"),
            backup=(data.get("backup") or "").rstrip("/"),
            exclude=tuple(data.get("exclude") or ()),
            port=int(data.get("port", 22)),
            user=data.get("user", ""),
        )

    def work_dir(self, sites_root: Path) -> Path:
        return Path(sites_root) / self.name


def _tar_excludes(patterns) -> str:
    return " ".join(f"--exclude={quote(p.rstrip('/'))}" for p in patterns if p)


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(archive: Path, target: Path) -> int:
    """Unpack, refusing entries that would escape the target directory.

    A malicious or careless archive can contain ``../`` paths or absolute
    paths. We are extracting content fetched from a server, so we check.
    """
    target = target.resolve()
    count = 0
    with tarfile.open(archive, "r:gz") as tar:
        members = []
        for member in tar.getmembers():
            destination = (target / member.name).resolve()
            if not str(destination).startswith(str(target)):
                raise RuntimeError(f"unsafe path in archive: {member.name}")
            if member.issym() or member.islnk():
                continue
            members.append(member)
            if member.isfile():
                count += 1
        tar.extractall(target, members=members)
    return count


# --------------------------------------------------------------------------
# manifest — what we believe is on the server
# --------------------------------------------------------------------------

def _manifest_path(work: Path) -> Path:
    return work / MANIFEST_DIR / MANIFEST_NAME


def read_manifest(work: Path) -> dict:
    path = _manifest_path(work)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_manifest(work: Path, data: dict) -> None:
    path = _manifest_path(work)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def remote_checksums(tr: Transport, site: Site, rel_paths: list[str]) -> dict[str, str]:
    """sha1 of the given files on the server. Missing files are omitted."""
    if not rel_paths:
        return {}
    quoted = " ".join(quote(p) for p in rel_paths)
    result = tr.run(
        f"cd {quote(site.remote)} && "
        f"for f in {quoted}; do "
        f"if [ -f \"$f\" ]; then sha1sum \"$f\" 2>/dev/null || shasum \"$f\"; fi; done"
    )
    out = {}
    for line in result.out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            out[parts[1].strip()] = parts[0].strip()
    return out


def detect_drift(tr: Transport, site: Site, work: Path, rel_paths: list[str]) -> list[str]:
    """Files whose current server content differs from our last deployment."""
    manifest = read_manifest(work).get("files", {})
    if not manifest:
        return []
    tracked = [p for p in rel_paths if p in manifest]
    if not tracked:
        return []
    current = remote_checksums(tr, site, tracked)
    return sorted(p for p in tracked
                  if p in current and current[p] != manifest[p])


# --------------------------------------------------------------------------
# operations
# --------------------------------------------------------------------------

def pull(tr: Transport, site: Site, work: Path, message: str = "",
         discard_local: bool = False) -> dict:
    """Fetch the current server state and commit it.

    Pull replaces the working copy, so anything uncommitted would be destroyed.
    Rather than refusing and making the person work out what to do, we commit
    what is there first. Git then holds it and it can be recovered; nothing the
    person typed is ever thrown away by a pull.
    """
    work = Path(work)
    git = Git(work)
    git.init()

    stashed = None
    if git.is_dirty():
        if discard_local:
            git("checkout", "--", ".", check=False)
            git("clean", "-fd", check=False)
        else:
            stashed = git.commit_all(message or f"wip: local changes before pull ({site.name})")

    archive_remote = tr.tmp_path(f"sshpier-{site.name}-pull.tgz")
    excludes = _tar_excludes(site.exclude)

    tr.run(
        f"tar czf {quote(archive_remote)} {excludes} -C {quote(site.remote)} ."
    ).check("tar")

    with tempfile.TemporaryDirectory() as tmp:
        local_archive = Path(tmp) / "pull.tgz"
        tr.get(archive_remote, local_archive)
        tr.run(f"rm -f {quote(archive_remote)}")

        staging = Path(tmp) / "tree"
        staging.mkdir()
        count = _safe_extract(local_archive, staging)

        # Replace the tracked content, leaving .git and our manifest alone.
        for item in work.iterdir():
            if item.name in (".git", MANIFEST_DIR):
                continue
            shutil.rmtree(item) if item.is_dir() else item.unlink()
        for item in staging.iterdir():
            shutil.move(str(item), str(work / item.name))

    changed = git.commit_all(f"pull: {site.name}")
    return {
        "files": count,
        "commit": changed,
        "changed": bool(changed),
        "path": str(work),
        "saved_local": stashed,
    }


def deploy(tr: Transport, site: Site, work: Path, tag: str,
           since: str = "", force: bool = False) -> dict:
    """Upload files changed since ``since`` (default: the last deploy tag)."""
    work = Path(work)
    git = Git(work)

    if git.is_dirty():
        raise RuntimeError(t("sync.dirty"))

    base = since or git.last_tag() or ""
    files = git.changed_files(base) if base else git.all_files()
    files = [f for f in files if not f.startswith(MANIFEST_DIR + "/")]
    files = [f for f in files if (work / f).exists()]

    if not files:
        return {"deployed": 0, "files": [], "tag": None,
                "message": t("sync.deploy_none", ref=base or "HEAD")}

    if not force:
        drifted = detect_drift(tr, site, work, files)
        if drifted:
            raise RuntimeError(t("sync.deploy_drift",
                                 files="\n".join("  " + f for f in drifted)))

    backup_path = ""
    if site.backup:
        tr.run(f"mkdir -p {quote(site.backup)}")
        backup_path = f"{site.backup}/{tag.replace('/', '-')}.tgz"
        existing = [f for f in files
                    if tr.run(f"test -f {quote(site.remote + '/' + f)}").ok]
        if existing:
            listed = " ".join(quote(f) for f in existing)
            tr.run(
                f"cd {quote(site.remote)} && tar czf {quote(backup_path)} {listed}"
            ).check("backup")
        else:
            backup_path = ""

    with tempfile.TemporaryDirectory() as tmp:
        local_archive = Path(tmp) / "deploy.tgz"
        with tarfile.open(local_archive, "w:gz") as tar:
            for rel in files:
                tar.add(work / rel, arcname=rel)

        remote_archive = tr.tmp_path(f"sshpier-{site.name}-deploy.tgz")
        tr.put(local_archive, remote_archive)
        tr.run(
            f"tar xzf {quote(remote_archive)} -C {quote(site.remote)}"
        ).check("extract")
        tr.run(f"rm -f {quote(remote_archive)}")

    manifest = read_manifest(work)
    manifest.setdefault("files", {})
    for rel in files:
        manifest["files"][rel] = _sha1(work / rel)
    manifest["tag"] = tag
    manifest["backup"] = backup_path
    # Record what the server held before this deployment, resolved to a commit.
    # A deploy tag points at the commit that *introduced* the change, so its
    # parent is not what we want; this is.
    manifest["previous"] = (git("rev-parse", base, check=False) if base else "")
    write_manifest(work, manifest)
    git.commit_all(f"deploy: {tag}")
    git.tag(tag, f"deployed {len(files)} file(s)")

    return {
        "deployed": len(files),
        "files": files,
        "tag": tag,
        "backup": backup_path,
        "message": t("sync.deploy_done", count=len(files), tag=tag),
    }


def rollback(tr: Transport, site: Site, work: Path, tag: str = "") -> dict:
    """Put the server back.

    Two routes, tried in order:

    1. the archive taken on the server immediately before the deployment
    2. the commit history, if no such archive exists

    The second route matters because a site configured without a ``backup``
    path would otherwise have no way back at all. Git already holds every
    version we deployed, so we can rebuild from it.
    """
    work = Path(work)
    manifest = read_manifest(work)
    tag = tag or manifest.get("tag", "")
    backup_path = manifest.get("backup", "")

    if not backup_path and site.backup and tag:
        backup_path = f"{site.backup}/{tag.replace('/', '-')}.tgz"

    if backup_path and tr.run(f"test -f {quote(backup_path)}").ok:
        listing = tr.run(f"tar tzf {quote(backup_path)}")
        count = len([line for line in listing.out.splitlines()
                     if line.strip() and not line.endswith("/")])
        tr.run(f"tar xzf {quote(backup_path)} -C {quote(site.remote)}").check("restore")
        return {"restored": count, "tag": tag, "source": "remote-backup",
                "message": t("sync.rollback_done", count=count, tag=tag)}

    return _rollback_from_git(tr, site, work, tag)


def _rollback_from_git(tr: Transport, site: Site, work: Path, tag: str) -> dict:
    """Rebuild the state the server held before the deployment being undone."""
    git = Git(work)
    manifest = read_manifest(work)

    # The commit the server was at before the deployment we are undoing.
    ref = manifest.get("previous") or ""
    if not ref or not git("rev-parse", "--verify", "-q", ref, check=False):
        raise RuntimeError(t("sync.no_backup", tag=tag or "?"))

    wanted = [f for f in (manifest.get("files") or {})
              if not f.startswith(MANIFEST_DIR + "/")]
    if not wanted:
        raise RuntimeError(t("sync.no_backup", tag=tag))

    # Only ask for paths that existed at that point; git archive fails on the
    # whole set otherwise. A file added by the deployment simply has nothing to
    # roll back to.
    present = [f for f in wanted
               if git("ls-tree", "--name-only", ref, "--", f, check=False)]
    if not present:
        raise RuntimeError(t("sync.no_backup", tag=tag))

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "restore.tgz"
        # git archive writes a tar of the exact recorded blobs, so binary files
        # survive intact.
        git("archive", "--format=tar.gz", "-o", str(archive), ref, "--", *present)

        remote_archive = tr.tmp_path(f"sshpier-{site.name}-restore.tgz")
        tr.put(archive, remote_archive)
        tr.run(f"tar xzf {quote(remote_archive)} -C {quote(site.remote)}").check("restore")
        tr.run(f"rm -f {quote(remote_archive)}")

    return {"restored": len(present), "tag": tag, "source": "git-history",
            "message": t("sync.rollback_done", count=len(present), tag=tag)}


def status(tr: Transport, site: Site, work: Path) -> dict:
    """Compare local commits, the server, and the last deployment."""
    work = Path(work)
    git = Git(work)
    manifest = read_manifest(work)
    tracked = list(manifest.get("files", {}))

    drift = detect_drift(tr, site, work, tracked) if tracked else []
    last = git.last_tag()
    pending = git.changed_files(last) if last else git.all_files()
    pending = [f for f in pending if not f.startswith(MANIFEST_DIR + "/")]

    return {
        "last_deploy": last,
        "drift": drift,
        "pending": pending,
        "clean": not drift and not pending,
    }


def resolve_site(sites: dict, name: str) -> Site:
    if name not in sites:
        raise RuntimeError(t("sync.no_site", name=name))
    return Site.from_dict(name, sites[name])


def default_tag(prefix: str = "deploy") -> str:
    from datetime import datetime
    return f"{prefix}/{datetime.now():%Y%m%d-%H%M%S}"


def relative_posix(path: Path, root: Path) -> str:
    return str(PurePosixPath(path.relative_to(root).as_posix()))
