# DevLink-MCP

A local control panel for the servers you maintain.

Describe your servers once in a plain text file. From that, DevLink-MCP hands a
locked-down configuration to an MCP server so an AI assistant can work on those
machines, pulls a site down so you can edit it in your own editor, and puts
your changes back with git as the undo button.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/LIGHTOFLIFE-Lab/DevLink-MCP)
[![CI](https://github.com/LIGHTOFLIFE-Lab/DevLink-MCP/actions/workflows/ci.yml/badge.svg)](https://github.com/LIGHTOFLIFE-Lab/DevLink-MCP/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)

한국어 문서: [docs/README.ko.md](docs/README.ko.md)

> **Status: alpha.** The interfaces described here work and are covered by
> tests, but this is a young project and details may change.

---

## Why

If you maintain other people's websites you probably have a pile of saved
sessions in an SFTP client, and you edit files on the server because setting up
a local copy for each one is not worth it. That works until the day you
overwrite something and there is no way back.

DevLink-MCP is the small amount of structure that removes that risk without
changing how you work:

- **One config, many consumers.** `servers.ini` is the only file you maintain.
  It generates the MCP server config and the deployment settings, so they cannot
  drift apart.
- **Guard rails you did not have to think about.** Every generated connection
  gets a destructive-command denylist, a path allowlist limited to the
  directories you named, a command timeout, and an output cap.
- **Deployments you can undo.** Only changed files are uploaded, the files
  about to be overwritten are backed up on the server first, and every
  deployment is a git tag.
- **It notices when someone else edited the server.** Before writing, DevLink-MCP
  compares the server against what it recorded last time. If a colleague — or
  the client — changed a file directly, it stops instead of destroying their
  work.

## Download and run

No Python needed — grab the build for your system from the
[latest release](https://github.com/LIGHTOFLIFE-Lab/DevLink-MCP/releases/latest), unpack it, and run
it. It opens the settings panel in your browser.

| System | File |
|---|---|
| Windows | `DevLink-MCP-windows-x64.zip` |
| macOS (Apple Silicon) | `DevLink-MCP-macos-arm64.dmg` |
| macOS (Intel) | `DevLink-MCP-macos-x64.dmg` |
| Linux | `DevLink-MCP-linux-x64.tar.gz` |

**These builds are not code-signed**, because a certificate costs money this
project does not have. Your system will say so:

- *Windows* — SmartScreen shows a blue warning. Choose **More info**, then
  **Run anyway**.
- *macOS* — Gatekeeper refuses the first launch. Right-click the app and choose
  **Open**, or run
  `xattr -dr com.apple.quarantine /Applications/DevLink-MCP.app`.

Each release includes a `.sha256` file if you want to verify what you
downloaded. The builds are produced by
[a GitHub Actions workflow](.github/workflows/release.yml) from the tagged
source, on GitHub's own runners — you can read exactly how each one was made.

## Try it without installing anything

Press **Open in GitHub Codespaces** above. It builds a container, installs the
package, and drops you in a terminal.

```bash
bash .devcontainer/demo.sh
```

That runs a whole cycle — pull a site, edit it, deploy, watch a deployment get
refused because someone changed the server, then roll back — against a local
directory standing in for a server. No SSH, no credentials, nothing to undo.

```bash
pytest -q                                   # the full suite, 86 tests
devlink gui --port 8765 --no-browser        # the settings panel, on the
                                            # forwarded port 8765
```

> Do not put real credentials in a Codespace. `servers.ini` stores passwords in
> plain text, and a cloud development container is not the place for your
> customers' servers. Install locally for real work.

## Install

```bash
pip install devlink-mcp          # settings panel, config, MCP server (no Node.js)
pip install 'devlink-mcp[sync]'  # adds pull / deploy / rollback (needs paramiko)
```

Python 3.9 or newer. The panel and config generation use only the standard
library; `paramiko` is needed only to talk to a server.

## Quick start

```bash
devlink init     # create the directory layout
devlink gui      # open the settings panel in your browser
```

The panel walks through it: check your environment, add servers (or import
them from WinSCP in one step), then register with your MCP client.

Prefer the terminal:

```bash
devlink import ~/Desktop/WinSCP.ini   # bring your saved sessions over
devlink check                         # validate without writing
devlink build                         # write the MCP config
```

## A server entry

```ini
[DEFAULT]
port    = 22
exclude = data/, uploads/, cache/, *.log, node_modules/, .env

[web1]
host     = 10.0.0.1
user     = deploy
key      = ~/.devlink/config/keys/web1.pem
remote   = /var/www/html
backup   = /var/backup/devlink
allow    = ^ls( .*)?|^cat .*|^grep .*
```

Six lines per server. `exclude` is the one to get right: it keeps customer
uploads and logs out of your working copy, which is the difference between a
repository of a few megabytes and one of several gigabytes.

Full reference: [`examples/servers.example.ini`](examples/servers.example.ini).

## Working on a site

```bash
devlink pull web1                 # fetch the current server state, commit it
# ... edit locally, commit as you like ...
devlink deploy web1               # upload only what changed, tag it
devlink status web1               # local vs server vs last deployment
devlink rollback web1             # put the server back
```

`pull` first is not a formality. It is what gives `rollback` something to
return to, and it is when you find out that someone changed the server since
you last looked.

## What is backed up, and when

Backups are not a step you have to remember. Every operation that could lose
work takes a copy first.

| Moment | What is preserved | Where |
|---|---|---|
| `pull`, with uncommitted local edits | your edits, committed as `wip:` before the working copy is replaced | git history |
| `pull` | the server's state at that moment | a commit |
| `deploy` | the server files about to be overwritten | an archive under `backup`, plus the deploy tag |
| `deploy` | what you deployed | a git tag |
| `rollback` | — | restores the archive, or rebuilds from history if there is none |

Two consequences worth knowing:

**A site without a `backup` path is still reversible.** `rollback` falls back to
the commit history and re-deploys the previous version. Setting `backup` is
still worth it — restoring from the server is faster and survives losing your
machine — so `devlink check` warns when it is missing.

**Uploads through MCP are backed up too.** DevLink-MCP is the MCP server, so when
an assistant writes a file, the version being replaced is copied into the
site's backup directory first. There is no configuration for this and no way to
forget it.

**Writes from other tools are not.** An SFTP client, or a different MCP server,
bypasses all of this. DevLink-MCP will notice on the next `deploy` and refuse rather
than overwrite, and `pull` brings the change into git — but that write itself
had no safety net.

## Importing from WinSCP

WinSCP exports either an INI file (Tools > Export/Backup Configuration) or a
registry dump. DevLink-MCP reads both, and decides which is which by looking at the
contents rather than the file extension.

Host, port, user, key path and proxy come across. **Saved passwords come across
too**, unless the session is protected by a WinSCP master password — those
cannot be recovered and are left blank for you to fill in.

## About stored passwords

Two things worth being explicit about, so you can decide for yourself.

**`servers.ini` holds passwords in plain text.** Anyone who can read the file
can read the passwords. Key authentication avoids this and is what the examples
use. Keep the config directory readable only by you.

**DevLink-MCP can decrypt WinSCP's saved passwords.** Without a master password,
WinSCP stores them with a reversible obfuscation rather than encryption. The
implementation is in [`src/devlink_mcp/winscp.py`](src/devlink_mcp/winscp.py), written
from the published algorithm; it contains no WinSCP code. It exists so that
migrating fifty sessions does not mean retyping fifty passwords. If you would
rather not have that capability installed, delete the body of
`decrypt_password` — the importer treats a failure as "no password available"
and leaves the field empty.

More in [SECURITY.md](SECURITY.md).

## How the pieces fit

```
                    ┌──► devlink serve ──► your MCP client ──► assistant
servers.ini ──► DevLink-MCP
                    └──► pull / deploy / rollback ──► sites/<name>/  (a git repo)
```

`devlink serve` is an MCP server in its own right, speaking JSON-RPC over stdio
and SSH over paramiko. It offers four tools — `list-servers`,
`execute-command`, `upload`, `download` — and applies the allowlist, denylist,
path limits, timeouts and output caps from your config. There is no Node.js
anywhere in this.

`devlink build` still writes `ssh-mcp-config.json` for people who would rather
point [`@fangjunjie/ssh-mcp-server`](https://github.com/classfang/ssh-mcp-server)
at it. That server has no upload backups, which is why DevLink-MCP grew its own.

## Layout

`$DEVLINK_HOME` (default `~/.devlink`):

```
config/
  servers.ini            you edit this
  keys/                  private keys, copied here by the panel
  ssh-mcp-config.json    generated
  sites.json             generated
sites/<name>/            working copy, a git repository
repos/                   optional local bare mirrors
logs/
```

## Contributing

Bug reports and patches welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
The test suite runs without any server: deployments are exercised against a
local directory that stands in for one.

```bash
pip install -e '.[dev]'
pytest
```

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
