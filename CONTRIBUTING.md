# Contributing

Thanks for looking. Issues and pull requests are both welcome.

## Getting set up

```bash
git clone https://github.com/LIGHTOFLIFE-Lab/DevLink-MCP
cd DevLink-MCP
pip install -e '.[dev]'
pytest
```

The whole suite runs in a couple of seconds and needs no server: deployments
are exercised against a local directory that stands in for one
(`LocalTransport`). If you are changing `sync.py`, that is where to add tests.

## What a good change looks like

**Tests for anything that touches a server.** `deploy` and `rollback` overwrite
other people's websites. A change there without a test is not reviewable. The
existing tests show the pattern — build a fake server directory, run the real
code path against it, assert on what ended up on disk.

**Comments that say why.** The code has a fair number of comments explaining
reasoning that is not visible from the code: why deploy sends only changed
files, why the config is written atomically, why passwords are not sent to the
browser. Keep that up. Comments restating what the line does are noise; a
comment explaining a decision someone might otherwise "simplify" away is worth
its space.

**Both languages.** Every user-visible string lives in `src/devlink_mcp/i18n.py`.
Add the English and the Korean; a test fails if the Korean catalogue is missing
a key. If you do not write Korean, add the English and say so in the PR — we
will fill it in.

**Small, focused pull requests.** Easier to review, easier to revert.

## Adding a language

Add a dict to `MESSAGES` in `i18n.py` keyed by the two-letter code, and extend
the `--lang` choices in `cli.py`. Missing keys fall back to English, so a
partial translation is usable from the first commit. Please relax
`test_korean_catalogue_covers_english` into a loop over languages if you add a
third.

## Things to be careful about

- **Never commit a real credential**, including in a test fixture. Test
  passwords should be obviously fake.
- **Windows details are load-bearing.** `.ps1` files need a UTF-8 BOM or
  Windows PowerShell 5.1 misreads them; `.cmd` files need CRLF. `.gitattributes`
  encodes this — please do not "normalise" it away.
- **JSON must be written without a BOM.** Some clients' parsers reject it.

## Style

Standard library first; a new runtime dependency needs a reason in the PR.
Follow the surrounding code — roughly PEP 8, 4-space indents, type hints on new
public functions.

## Licensing

Contributions are accepted under the Apache License 2.0, the same as the
project. By opening a pull request you confirm you have the right to submit the
work under that license.

## Code of conduct

Be decent to each other. Harassment or personal attacks are not welcome and
maintainers will act on them.
