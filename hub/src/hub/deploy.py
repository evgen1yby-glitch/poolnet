"""Render the systemd units for a particular installation.

Why a template layer exists at all: systemd does **not** expand variables in
`User=`, `Group=` or `WorkingDirectory=`. `Environment=HUB_USER=vpn` plus
`User=$HUB_USER` does not work — the directive is taken literally and systemd
looks for a user named `$HUB_USER`. So the values have to be substituted before
the file is installed, which means a render step and a template to render.

The units shipped with one operator's username and home directory written into
them — 26 occurrences across seven files. On the machine they were written on
that is invisible; anywhere else it produces `status=217/USER`, which names a
user that does not exist and says nothing about a path baked into a file the
operator never opened.

`install.sh` calls `render_unit` per file. Everything here is pure: it takes
paths and strings, returns a string, and touches nothing — which is what makes
it testable without root, without systemd, and without a second machine.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["render_unit", "render_nginx", "PLACEHOLDERS"]

#: The substitutions a unit may contain. Kept as a mapping rather than passed
#: through as `**kwargs` so an unsubstituted placeholder is a detectable state
#: rather than a silent survivor: `render_unit` fails on any `@…@` left behind.
PLACEHOLDERS = ("HUB_DIR", "HUB_USER", "HUB_GROUP")


def _check_dir(path: Path) -> str:
    """Validate a directory for use in a unit file, and normalise it.

    Two rejections, both for a failure that systemd reports misleadingly:

    * **A relative path.** systemd resolves it against its own working
      directory, not the project's, so the service starts in `/` or fails with
      a directory that exists somewhere else entirely.
    * **A path containing whitespace.** `WorkingDirectory=/opt/my hub` parses as
      the directory `/opt/my` plus a stray token. The service then fails with an
      error about `/opt/my`, which exists.

    `/` is refused as well: it is not a valid `ReadWritePaths` target and is
    almost certainly a mistake rather than an intent.

    Trailing slashes are stripped rather than rejected. A shell tab-completes a
    directory *with* the slash, so it arrives constantly, and it would end up in
    `PYTHONPATH=/opt/hub//src` — harmless to Python, confusing to a reader, and
    carried into the unit file where the next person has to decide whether it
    matters.
    """
    text = str(path)
    if not text.startswith("/"):
        raise ValueError(f"hub_dir must be absolute, got {text!r}")
    if text != "/" and text.endswith("/"):
        text = text.rstrip("/")
    if text == "/":
        raise ValueError("hub_dir must not be the filesystem root")
    if any(ch.isspace() for ch in text):
        raise ValueError(
            f"hub_dir must not contain whitespace, got {text!r}: systemd reads it "
            "as two tokens and reports an error about the first"
        )
    return text


def _check_name(value: str, what: str) -> str:
    """Validate a Unix user or group name.

    Checked rather than trusted because the value goes into a line systemd
    parses: a name with a newline in it would inject a second directive into the
    unit, and one with a space produces `User=my user`, which systemd reads as a
    name that does not exist.
    """
    if not value or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*\$?", value):
        raise ValueError(f"{what} must be a plain Unix name, got {value!r}")
    return value


def render_nginx(template: Path, *, hub_host: str, hub_port: int = 8444) -> str:
    """Substitute the host into the nginx vhost template.

    Separate from `render_unit` because the substitution is a *host address*
    rather than a directory and a user, and one shared function taking four
    unrelated parameters would be a function nobody could call correctly.

    `hub_host` becomes both the bare address and a dashed form for the
    certificate lineage, because the lineage directory is named after the
    address and a slash cannot appear in a filename.
    """
    # Validated, not trusted: this value lands in a `server_name`, an
    # `ssl_certificate` path and a directory name. A slash is the one that
    # matters — `host/path` produces `/etc/letsencrypt/live/hub-ip-host/path-x/`,
    # which nginx reports as a missing certificate and which reads as a typo in
    # the lineage name rather than as a bad host.
    if not hub_host:
        raise ValueError("hub_host must not be empty")
    if any(ch.isspace() for ch in hub_host):
        raise ValueError(f"hub_host must not contain whitespace, got {hub_host!r}")
    if "/" in hub_host or "\\" in hub_host:
        raise ValueError(f"hub_host must be a bare host, not a path: {hub_host!r}")
    dashed = hub_host.replace(".", "-").replace(":", "-")
    text = template.read_text(encoding="utf-8")
    text = text.replace("<HUB_HOST-DASHED>", dashed)
    text = text.replace("<HUB_HOST>", hub_host)
    leftover = sorted(set(re.findall(r"<HUB_HOST[^>]*>", text)))
    if leftover:
        raise ValueError(
            f"{template.name} has placeholders with no value: {', '.join(leftover)}"
        )
    return text


def render_unit(
    template: Path,
    *,
    hub_dir: Path,
    hub_user: str,
    hub_group: str,
) -> str:
    """Substitute the installation's values into a unit template.

    Every placeholder must be consumed. A leftover `@HUB_DIR@` is not a cosmetic
    problem: systemd accepts it as a literal string, so a unit whose path was
    misspelled renders to a service pointed at a directory with that name, and
    `systemd-analyze` does not complain because the string is valid.
    """
    directory = _check_dir(hub_dir)
    user = _check_name(hub_user, "hub_user")
    group = _check_name(hub_group, "hub_group")

    text = template.read_text(encoding="utf-8")
    for key, value in (
        ("HUB_DIR", directory),
        ("HUB_USER", user),
        ("HUB_GROUP", group),
    ):
        text = text.replace(f"@{key}@", value)

    leftover = sorted(set(re.findall(r"@[A-Z_]+@", text)))
    if leftover:
        raise ValueError(
            f"{template.name} has placeholders with no value: {', '.join(leftover)}"
        )
    return text
