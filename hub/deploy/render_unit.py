#!/usr/bin/env python3
"""Render one systemd unit template. Called by `install.sh`, usable by hand.

    PYTHONPATH=src python3 deploy/render_unit.py \\
        deploy/hub-api.service.in /opt/vpn-hub vpn vpn > /etc/systemd/system/hub-api.service

A separate entry point rather than an inline `python3 -c` in the installer, for
two reasons that both showed up while writing it:

* a heredoc inside a shell loop that is itself building a string is a quoting
  trap — the first version of the loop lost its own `PY` terminator and the
  render never ran;
* a file is something an operator can run to see the output before committing
  to it, which an inline one-liner is not.

Exits non-zero with the reason on stderr, so `install.sh` can stop on a bad path
rather than write a broken unit.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The project is a source tree, not an installed package: `hub` resolves only
# with `src` on the path, which the caller sets. Imported here rather than at the
# top so the error message names the path instead of raising ImportError.
try:
    from hub.deploy import render_unit
except ImportError:  # pragma: no cover - the installer sets PYTHONPATH
    sys.stderr.write(
        "cannot import hub.deploy. Run with the project on PYTHONPATH:\n"
        f"  PYTHONPATH=<project>/src python3 {sys.argv[0]} ...\n"
    )
    raise SystemExit(2)


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        sys.stderr.write(
            "usage: render_unit.py TEMPLATE HUB_DIR HUB_USER HUB_GROUP\n"
            "writes the rendered unit to stdout\n"
        )
        return 2
    template, hub_dir, hub_user, hub_group = argv[1:]
    try:
        text = render_unit(
            Path(template),
            hub_dir=Path(hub_dir),
            hub_user=hub_user,
            hub_group=hub_group,
        )
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"{template}: {exc}\n")
        return 1
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
