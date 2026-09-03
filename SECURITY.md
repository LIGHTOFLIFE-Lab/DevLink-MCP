# Security

## Reporting a vulnerability

Please report security issues privately through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository, rather than opening a public issue. We will acknowledge
within a few days and keep you informed while a fix is prepared.

## What this tool is, and is not

DevLink-MCP is a convenience layer for someone who already has full administrative
access to the servers involved. It does not add a trust boundary. Everything
below follows from that.

### Credentials are stored in plain text

`servers.ini` holds passwords and key paths as written text. Anyone who can
read that file can use those credentials. This is a deliberate trade: the file
has to be readable by an unattended process, and adding a passphrase-protected
store would move the secret rather than remove it.

What follows from that:

- **Prefer key authentication.** The examples use it.
- **Keep the config directory to yourself.** On POSIX, `chmod 700`. On Windows,
  the default per-user profile permissions are usually adequate; be careful
  with `icacls` on a directory you cannot afford to lock yourself out of.
- **Never commit it.** The shipped `.gitignore` excludes `servers.ini`, key
  files, and the generated config. Verify before you push.

### WinSCP password recovery

`src/devlink_mcp/winscp.py` implements WinSCP's stored-password obfuscation so that
saved sessions can be migrated in one step.

This is not an attack on WinSCP. Without a master password, WinSCP stores
session passwords with a reversible transformation, which the project documents
and several tools implement. Our implementation was written from that public
description; it contains no WinSCP source.

Consequences you should weigh:

- Having this module installed means that anyone who obtains a WinSCP session
  file **and** this machine can recover those passwords. If the session file is
  already on the same machine, this changes little.
- Sessions protected by a WinSCP master password **cannot** be recovered here.
  The key check fails and the importer records "no password" rather than
  producing wrong output.
- If you would rather not carry the capability, empty the body of
  `decrypt_password`. Everything else continues to work.

### Command restrictions are a safety net, not a sandbox

Generated connections carry a denylist of destructive commands. It is regular
expression matching on a command string, and it can be evaded — by quoting
(`r''m`), by encoding, by variable expansion, by a script. It exists to catch
mistakes, not attackers.

For a server that matters, set `allow` (an allowlist). An allowlist fails
closed; a denylist fails open. DevLink-MCP warns on every connection that has no
allowlist for exactly this reason.

### Host keys

The SSH transport uses `AutoAddPolicy`: unknown host keys are accepted and
recorded. This matches what an SFTP client does when you click through the
first-connection dialog. It means the first connection to a host is
unauthenticated and could in principle be intercepted. If that matters for your
environment, connect once with your normal SSH client and verify the
fingerprint, so that the key is already in `known_hosts` before DevLink-MCP runs.

### The settings panel

The panel binds to `127.0.0.1` on an ephemeral port and requires a token
generated fresh each run; requests without it get 403. Stored passwords are
never sent to the browser — the page is told only whether one exists.

Passwords do pass through the browser during a WinSCP import, because the page
carries them from the import step to the save step. Over loopback, to the same
user, into a file that stores them in plain text anyway.

### The update check

The settings panel asks `api.github.com` once a day whether a newer release
exists. It sends nothing but the request itself — no identifiers, no
configuration, no server names. The answer is cached for a day, including a
failed one, so a machine without a network does not retry on every launch.

It never downloads or installs anything. `DEVLINK_NO_UPDATE_CHECK=1` disables
it entirely.

### Archive extraction

Content pulled from a server is unpacked with path traversal checks, and
symlinks and hard links in the archive are skipped. A compromised server should
not be able to write outside the working directory through a crafted tarball.

## Supported versions

While the project is at 0.x, only the latest release receives fixes.
