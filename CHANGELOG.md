# Changelog

Notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `devlink serve` — DevLink-MCP is now an MCP server itself, over stdio, using
  paramiko. Node.js is no longer required anywhere.
- Uploads through MCP copy the file they replace into the site's backup
  directory before writing.

### Changed

- The settings panel registers `devlink serve` with the MCP client instead of
  an external Node package. `devlink build` still writes `ssh-mcp-config.json`
  for anyone who prefers that server.
- The environment check no longer asks for Node.js or npx; it checks for
  paramiko instead.

## [0.1.0] — 2026-09-03

First public release.

### Added

- `servers.ini` as the single source of truth, generating both the MCP server
  configuration and the deployment settings.
- Automatic safety rails on every generated connection: destructive-command
  denylist, path allowlist limited to the directories named in the config,
  command timeout, and output cap.
- Settings panel (`devlink gui`) served from the standard library over
  loopback, gated by a per-run token. Environment check, server list, WinSCP
  import, key upload, and MCP client registration.
- `devlink pull` / `deploy` / `rollback` / `status`. Deployments send only
  changed files, back up the files they will overwrite on the server first, and
  tag the commit.
- Drift detection: deploy stops if the server no longer matches what was
  recorded at the last deployment, rather than silently overwriting someone
  else's edits.
- WinSCP import from both INI and registry exports, detected by content rather
  than file extension. Saved passwords are recovered unless a master password
  is set.
- English and Korean throughout, including the panel.

### Security

- Stored passwords are never sent to the browser; the panel is told only
  whether one exists, and a blank field on save leaves the stored value alone.
- Saving is refused when the existing settings file cannot be read, so that
  stored passwords are not silently lost by overwriting it.
- Archives pulled from a server are extracted with path traversal checks, and
  links inside them are skipped.
- MCP client configuration is written without a byte order mark, and the
  previous file is backed up first.

[Unreleased]: https://github.com/kimajun0919/DevLink-MCP/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/kimajun0919/DevLink-MCP/releases/tag/v0.1.0
