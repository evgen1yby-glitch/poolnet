#!/usr/bin/env python3
"""Render the nginx vhost template for a host. Called by `install.sh`.

    PYTHONPATH=src python3 deploy/render_nginx.py \\
        deploy/nginx-hub-8444.conf.in 203.0.113.10 > /etc/nginx/conf.d/hub.conf

Rendered rather than installed: publishing the hub on a port affects every other
vhost on the host, and that is the operator's decision. This prints the file and
stops, so the operator can read it, run `nginx -t` against it, and install it
when they mean to.

The template loses its `.conf` extension for `.conf.in` deliberately. It shipped
once as `nginx-hub-8444.conf` while holding `<HUB_HOST-DASHED>`, was copied into
`/etc/nginx/conf.d/`, and `nginx -t` failed with `cannot load certificate
".../hub-ip-<HUB_HOST-DASHED>/fullchain.pem"` — a message that names the
placeholder rather than the mistake. A `.in` suffix is the difference between a
file to install and a file to render.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from hub.deploy import render_nginx
except ImportError:  # pragma: no cover - the caller sets PYTHONPATH
    sys.stderr.write(
        "cannot import hub.deploy. Run with the project on PYTHONPATH:\n"
        f"  PYTHONPATH=<project>/src python3 {sys.argv[0]} ...\n"
    )
    raise SystemExit(2)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write(
            "usage: render_nginx.py TEMPLATE HOST\n"
            "writes the rendered vhost to stdout\n"
        )
        return 2
    template, host = argv[1], argv[2]
    try:
        text = render_nginx(Path(template), hub_host=host)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"{template}: {exc}\n")
        return 1
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
