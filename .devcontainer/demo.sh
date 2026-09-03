#!/usr/bin/env bash
# A complete pull -> edit -> deploy -> rollback, with a local directory standing
# in for the server. No SSH, no credentials, nothing to clean up afterwards.
#
#   bash .devcontainer/demo.sh
set -euo pipefail

DEMO="${TMPDIR:-/tmp}/devlink-demo"
rm -rf "$DEMO"
mkdir -p "$DEMO"

say() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
show() { printf '\033[2m  %s\033[0m\n' "$*"; }

git config --global user.name  >/dev/null 2>&1 || git config --global user.name demo
git config --global user.email >/dev/null 2>&1 || git config --global user.email demo@example.invalid

# ---------------------------------------------------------------- the "server"
say "Setting up a pretend server at $DEMO/server/srv/www"
mkdir -p "$DEMO/server/srv/www"
cat > "$DEMO/server/srv/www/index.html" <<'HTML'
<h1>Live site</h1>
<p>This is what the customer sees right now.</p>
HTML
echo "body { color: #222 }" > "$DEMO/server/srv/www/style.css"
mkdir -p "$DEMO/server/srv/www/uploads"
head -c 4096 /dev/urandom > "$DEMO/server/srv/www/uploads/customer-file.bin"
show "index.html, style.css, and an uploads/ directory we must not touch"

python3 - "$DEMO" <<'PY'
import sys
from pathlib import Path

from devlink_mcp.sync import Site, Git, pull, deploy, rollback, status
from devlink_mcp.transport import LocalTransport

demo = Path(sys.argv[1])
site = Site(name="demo", host="localhost", remote="/srv/www",
            backup="/srv/backup", exclude=("uploads/", "*.log"))
tr = LocalTransport(demo / "server")
work = demo / "work"

def head(text):
    print(f"\n\033[1;36m▸ {text}\033[0m")

def note(text):
    print(f"\033[2m  {text}\033[0m")

head("devlink pull — take the server's current state into git")
result = pull(tr, site, work)
note(f"{result['files']} files collected into {work}")
note(f"uploads/ pulled? {(work / 'uploads').exists()}  <- excluded on purpose")
Git(work).tag("deploy/base")

head("Editing the site locally, as you would in your editor")
(work / "index.html").write_text(
    "<h1>Live site</h1>\n<p>Updated copy, edited locally.</p>\n")
Git(work).commit_all("update the homepage copy")
note("committed")

head("Meanwhile the application writes a file of its own on the server")
(demo / "server/srv/www/session-cache.txt").write_text("generated at runtime\n")
note("session-cache.txt — a whole-directory upload would destroy this")

head("devlink deploy — only what changed, backed up first")
outcome = deploy(tr, site, work, tag="deploy/001", since="deploy/base")
note(f"uploaded: {outcome['files']}")
note(f"server backup: {outcome['backup']}")
note(f"session-cache.txt survived? "
     f"{(demo / 'server/srv/www/session-cache.txt').exists()}")
note("live now: " + (demo / "server/srv/www/index.html").read_text().splitlines()[1])

head("Somebody edits the server directly, outside the tool")
(demo / "server/srv/www/index.html").write_text(
    "<h1>Live site</h1>\n<p>Hand-edited on the server by a colleague.</p>\n")
(work / "index.html").write_text("<h1>Live site</h1>\n<p>My next change.</p>\n")
Git(work).commit_all("another change")

head("devlink deploy — refuses, rather than destroying their work")
try:
    deploy(tr, site, work, tag="deploy/002", since="deploy/001")
    note("!! it should not have got here")
except RuntimeError as exc:
    for line in str(exc).splitlines():
        note(line)
note("still on the server: "
     + (demo / "server/srv/www/index.html").read_text().splitlines()[1])

head("devlink rollback — put the server back")
(demo / "server/srv/www/index.html").write_text(
    "<h1>Live site</h1>\n<p>Updated copy, edited locally.</p>\n")
back = rollback(tr, site, work, tag="deploy/001")
note(back["message"])
note("restored to: "
     + (demo / "server/srv/www/index.html").read_text().splitlines()[1])
PY

say "Done"
show "Everything happened under $DEMO — delete it whenever."
show "Read src/devlink_mcp/sync.py to see how each step works."
