"""The deployment units must not carry one operator's paths and username.

`deploy/*.service` shipped with `User=astrobot` and `/home/dev/freevpn` written
into them — 26 occurrences across seven files. That is fine for the machine they
were written on and wrong for every other one, and it fails in the worst way: a
newcomer changes what the README tells them to change, runs the units, and gets
`status=217/USER` — a user that does not exist — with nothing connecting that to
a path baked into a file they never opened.

The fix is a template layer, and these tests are what keeps it honest: a unit
that keeps a literal path (a comment counts, because the next reader copies it)
fails here rather than on somebody's VPS.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"

#: Every unit the installer renders. The list is explicit rather than a glob so
#: a new unit has to be added here deliberately — a file nobody templated is
#: exactly the failure these tests exist for.
TEMPLATED = [
    "hub-api.service",
    "hub-worker.service",
    "hub-bot.service",
    "hub-audit-sources.service",
    "hub-probe.service",
    "hub-ns.service",
]


def test_every_unit_is_a_template_not_a_rendered_file():
    """The shipped file must contain placeholders, not one host's values.

    Checked by name *and* by content: a `.in` file that still holds a literal
    path is the same bug with a new extension, and it would render to that path
    on every machine.
    """
    for name in TEMPLATED:
        template = DEPLOY / f"{name}.in"
        assert template.is_file(), f"{name}.in is missing; only {name} exists"
        body = template.read_text(encoding="utf-8")
        assert "@HUB_DIR@" in body or "@HUB_USER@" in body, (
            f"{name}.in has no placeholder — it would render identically everywhere"
        )


def test_no_template_carries_a_literal_home_path_or_username():
    """No literal `/home/...` and no literal `User=<name>` anywhere, comments included.

    Comments are checked on purpose. The comments in these units are long and
    explain *why* each setting exists, which makes them the first thing a reader
    copies; a comment that says `ReadWritePaths=/home/dev/freevpn/data` teaches
    the next person to write their own path in the same place.
    """
    offenders = []
    for name in TEMPLATED:
        body = (DEPLOY / f"{name}.in").read_text(encoding="utf-8")
        for lineno, line in enumerate(body.splitlines(), 1):
            if re.search(r"/home/[a-z]", line):
                offenders.append(f"{name}:{lineno}: {line.strip()[:70]}")
            # `User=` / `Group=` must be a placeholder, not a name — and the
            # same check applies mid-line, because these units pass the user
            # through `setpriv --reuid=` and `sudo`, not only through systemd.
            #
            # Comments are skipped for *this* check and only this one: a comment
            # legitimately writes `User=$HUB_USER` while explaining why systemd
            # does not expand it, and flagging that is a false positive which
            # would get the whole test deleted. The literal-path check above and
            # the `astrobot` check below still read comments, because a copied
            # path or a copied username is a real defect wherever it sits.
            if not line.lstrip().startswith("#"):
                for match in re.finditer(r"(?:User|Group|reuid|regid)=([^\s,;\\)\"]+)", line):
                    if "@" not in match.group(1):
                        offenders.append(f"{name}:{lineno}: {line.strip()[:70]}")
                        break
            # A comment naming the author's account is the same defect as a
            # directive: it is what the next reader copies.
            if re.search(r"\bastrobot\b", line):
                offenders.append(f"{name}:{lineno}: {line.strip()[:70]}")
    assert not offenders, "literal paths or users in a template:\n" + "\n".join(offenders)


def test_render_installs_the_operators_values():
    """Rendering substitutes every placeholder and leaves nothing behind.

    The failure this catches is a placeholder with a typo in it — `@HUB_DIR@`
    spelled `@HUBS_DIR@` renders to a literal `@HUBS_DIR@` in a systemd unit,
    where it is accepted silently and produces a service pointed at a directory
    called that. `systemd-analyze verify` does not complain, because the value
    is a valid string.
    """
    from hub.deploy import render_unit

    text = render_unit(
        DEPLOY / "hub-api.service.in",
        hub_dir=Path("/opt/vpn-hub"),
        hub_user="vpn",
        hub_group="vpn",
    )
    assert "@" not in text, f"an unsubstituted placeholder survived:\n{text}"
    assert "User=vpn" in text
    assert "Group=vpn" in text
    assert "WorkingDirectory=/opt/vpn-hub" in text
    assert "HUB_ROOT=/opt/vpn-hub" in text
    assert "PYTHONPATH=/opt/vpn-hub/src" in text
    assert "ReadWritePaths=/opt/vpn-hub/data" in text
    # The example host's values must be gone entirely.
    assert "/home/dev/freevpn" not in text
    assert "astrobot" not in text


def test_render_does_not_require_a_trailing_slash_on_the_directory():
    """`/opt/hub/` and `/opt/hub` must render the same unit.

    A shell that tab-completes a directory leaves the slash, and the difference
    would land inside `PYTHONPATH=/opt/hub//src` and `ReadWritePaths=/opt/hub//data`.
    Both work, both look like a bug, and the double slash travels into the unit
    file where the next person has to decide whether it matters.
    """
    from hub.deploy import render_unit

    trailing = render_unit(
        DEPLOY / "hub-api.service.in",
        hub_dir=Path("/opt/hub/"),
        hub_user="vpn",
        hub_group="vpn",
    )
    plain = render_unit(
        DEPLOY / "hub-api.service.in",
        hub_dir=Path("/opt/hub"),
        hub_user="vpn",
        hub_group="vpn",
    )
    assert trailing == plain
    assert "//" not in trailing


def test_render_rejects_a_directory_that_would_break_the_unit():
    """Refuse values that produce a broken unit rather than writing one.

    A path with a space is a valid directory name and an invalid systemd value:
    `WorkingDirectory=/opt/my hub` parses as the directory `/opt/my` plus a
    stray token, and the service fails with an error about a directory that
    exists. Better to refuse at render time, where the message can say why.
    """
    from hub.deploy import render_unit

    for bad in (Path("relative/path"), Path("/opt/my hub"), Path("/")):
        with pytest.raises(ValueError):
            render_unit(
                DEPLOY / "hub-api.service.in",
                hub_dir=bad,
                hub_user="vpn",
                hub_group="vpn",
            )


def test_systemd_accepts_the_rendered_unit():
    """`systemd-analyze verify` on the rendered file, when it is available.

    Skipped where systemd is absent, which is the normal case in CI. The check
    is worth having because it is the only one that reads the file the way the
    init system will: everything else here is a text assertion, and a unit can
    satisfy every one of them and still be refused for a reason no text check
    models.
    """
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("systemd-analyze"):
        pytest.skip("no systemd-analyze on this host")

    from hub.deploy import render_unit

    text = render_unit(
        DEPLOY / "hub-api.service.in",
        hub_dir=Path("/opt/hub-render-test"),
        hub_user="root",
        hub_group="root",
    )
    with tempfile.NamedTemporaryFile("w", suffix=".service", delete=False) as handle:
        handle.write(text)
        path = handle.name
    try:
        result = subprocess.run(
            ["systemd-analyze", "verify", path],
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        Path(path).unlink()
    # A missing ExecStart binary is reported but is not a unit-syntax error, so
    # only "Unknown" / parse failures count.
    bad = [
        line
        for line in (result.stdout + result.stderr).splitlines()
        if "Unknown" in line or "Failed to parse" in line
    ]
    assert not bad, "\n".join(bad)


def test_the_installer_refuses_to_adopt_another_installation():
    """Re-pointing a live hub at a different checkout must be an explicit act.

    This guard exists because it already happened: the installer was run against
    a checkout in `/tmp` on a host that had a working hub, and it silently
    pointed the live units at `/tmp`. Nothing failed loudly — the running
    processes kept their old working directory, so the API kept answering, and
    the damage would have appeared at the next restart as a service that cannot
    find its project. An installer able to quietly re-point a live service is
    worse than one that refuses.

    Asserted on the script text rather than by running it: exercising the real
    path needs root and a second installation, and the assertion that matters is
    that the check exists and compares the *directories* rather than merely
    checking that a unit file is present.
    """
    script = (Path(__file__).resolve().parents[1] / "install.sh").read_text(encoding="utf-8")

    assert "HUB_ROOT=" in script, "the installer never reads the installed unit's directory"
    assert "existing_dir" in script, "no comparison against the installed directory"
    assert '--force' in script, "no way to override deliberately"
    # The refusal must name both directories, or the operator cannot tell which
    # installation they are about to replace.
    assert "$existing_dir" in script and "$HUB_DIR" in script


def test_the_nginx_vhost_is_a_template_too():
    """A file with unrendered placeholders must not be mistaken for a vhost.

    This is not hypothetical: the vhost was named `nginx-hub-8444.conf` while
    holding `<HUB_HOST-DASHED>`, it was copied into `/etc/nginx/conf.d/` as a
    .conf, and `nginx -t` failed with `cannot load certificate
    ".../hub-ip-<HUB_HOST-DASHED>/fullchain.pem"`. The reload was refused, so
    the site kept serving from the old workers — which is the good outcome and
    still a broken state nobody wants to discover later.

    Two things are checked, and the extension is the substantive one: a template
    with a `.conf` name is indistinguishable from an installable file.
    """
    template = DEPLOY / "nginx-hub-8444.conf.in"
    assert template.is_file(), "the vhost template lost its .in extension"
    assert not (DEPLOY / "nginx-hub-8444.conf").exists(), (
        "a rendered vhost sits beside its template — the next person copies the wrong one"
    )
    body = template.read_text(encoding="utf-8")
    assert "<HUB_HOST>" in body, "no placeholder to substitute"


def test_render_nginx_substitutes_both_placeholder_forms():
    """The dotted and dashed forms are separate placeholders with separate values."""
    from hub.deploy import render_nginx

    text = render_nginx(DEPLOY / "nginx-hub-8444.conf.in", hub_host="203.0.113.10")
    assert "<HUB_HOST" not in text, "an unsubstituted placeholder survived"
    assert "203.0.113.10:8444" in text
    # The lineage directory cannot contain a slash or a dot-separated address
    # reads as a path, which is why the dashed form exists.
    assert "hub-ip-203-0-113-10" in text
    assert "/live/hub-ip-203.0.113.10/" not in text


def test_render_nginx_refuses_a_host_that_would_break_the_vhost():
    """A host with whitespace or a slash produces a vhost nginx refuses."""
    from hub.deploy import render_nginx

    for bad in ("", "203.0.113.10 ", "host/path"):
        with pytest.raises((ValueError, OSError)):
            render_nginx(DEPLOY / "nginx-hub-8444.conf.in", hub_host=bad)


def test_the_admin_panel_is_denied_at_the_edge():
    """nginx must refuse `/admin` itself, not leave it to the application.

    Through this vhost nginx *is* the peer, so the API's loopback check passes
    for every visitor and the only thing left protecting the token list would be
    the shared secret. `allow 127.0.0.1; deny all;` is the layer that can
    distinguish a local request from a remote one.
    """
    body = (DEPLOY / "nginx-hub-8444.conf.in").read_text(encoding="utf-8")
    assert "location ^~ /admin" in body, "no deny rule for the operator panel"
    admin_block = body.split("location ^~ /admin", 1)[1].split("}", 1)[0]
    assert "allow 127.0.0.1;" in admin_block, admin_block
    assert "deny all;" in admin_block, admin_block
    # `^~` is load-bearing: without it the `location /` catch-all below wins and
    # every visitor reaches the panel.
    assert body.index("location ^~ /admin") < body.index("\n    location / {")
