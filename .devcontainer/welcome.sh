#!/usr/bin/env bash
# Printed when a Codespace attaches. Keep it short — nobody reads a wall of text
# in a terminal they did not open on purpose.
cat <<'EOF'

  DevLink-MCP — try it here
  ─────────────────────────────────────────────────────────────

  Nothing below touches a real server. The test suite runs
  deployments against a local directory that stands in for one.

    1.  pytest -q                  run the suite (86 tests)

    2.  devlink init               create the demo layout
        devlink check              validate the example config

    3.  devlink gui --port 8765 --no-browser
        then open the forwarded port 8765 from the Ports tab

    4.  bash .devcontainer/demo.sh
        a full pull -> edit -> deploy -> rollback, end to end

  Do not put real credentials in a Codespace. servers.ini stores
  passwords in plain text; keep this environment for trying it out.

EOF
