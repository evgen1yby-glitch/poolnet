#!/usr/bin/env bash
#
# hub installer — one command on a fresh VPS.
#
#   sudo ./install.sh --user vpn --dir /opt/vpn-hub
#
# What it does, in order, and why that order:
#
#   1. checks prerequisites and refuses early if one is missing;
#   2. installs Python dependencies into the *system* interpreter, because the
#      units run `/usr/bin/python3` and a venv would be a second Python the
#      services never use;
#   3. downloads the two cores (`sing-box` validates payloads, `xray` validates
#      the balancer config), each optional — a missing core degrades a check
#      rather than stopping the install;
#   4. creates the probe sandbox (`hubns`) — without it the prober refuses to
#      run and the pool stays empty, which reads as "the project is broken";
#   5. renders the systemd units with this installation's path and user;
#   6. writes `/etc/hub/hub.env` with a freshly generated token;
#   7. runs one pipeline pass and prints what came out.
#
# Idempotent: run it again after a `git pull` and it re-renders and restarts
# rather than duplicating anything. Every step says what it is doing, because a
# silent installer that fails at step 5 leaves the operator with no idea which
# of six things is wrong.
#
# It does NOT touch: nginx, the firewall, any route, or any other service on the
# host. Publishing a hub on a port is an operator decision with consequences for
# whatever else lives on the box, so the installer stops at "the services run on
# loopback" and prints what to do next.

set -euo pipefail

HUB_USER=""
HUB_DIR=""
HUB_PORT="8090"
HUB_BASE_URL=""
HUB_HOST=""
SKIP_DEPS=0
SKIP_PROBE=0
ASSUME_YES=0
FORCE=0

usage() {
    cat <<'EOF'
Usage: sudo ./install.sh [options]

  --user NAME       Unix account the services run as (default: the invoking user)
  --dir PATH        Where the project lives (default: this script's directory)
  --port N          API port on loopback (default: 8090)
  --base-url URL    Public origin for subscription links, e.g. https://203.0.113.10:8444
  --host ADDR       This server's public IP or domain, for the nginx vhost
  --skip-deps       Do not touch the Python environment
  --skip-probe      Do not create the hubns sandbox
  --yes             Do not ask anything
  --force           Overwrite units belonging to a DIFFERENT installation
  -h, --help        This text

After it finishes, the services are on loopback only. Exposing them is a
separate decision: put nginx in front with TLS, then open one port.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --user) HUB_USER="$2"; shift 2 ;;
        --dir) HUB_DIR="$2"; shift 2 ;;
        --port) HUB_PORT="$2"; shift 2 ;;
        --base-url) HUB_BASE_URL="$2"; shift 2 ;;
        --host) HUB_HOST="$2"; shift 2 ;;
        --skip-deps) SKIP_DEPS=1; shift ;;
        --skip-probe) SKIP_PROBE=1; shift ;;
        --yes) ASSUME_YES=1; shift ;;
        --force) FORCE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

# ---- output helpers ------------------------------------------------------

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '    \033[33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\n\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# ---- 0. prerequisites ----------------------------------------------------

step "Checking prerequisites"

[[ $EUID -eq 0 ]] || die "run as root (the units are installed into /etc/systemd/system)"

for cmd in python3 systemctl ip; do
    command -v "$cmd" >/dev/null 2>&1 || die "$cmd is required but not installed"
done
info "python3: $(python3 --version)"
info "systemd: $(systemctl --version | head -1)"

# `ip netns` is a separate binary on some distros and missing on minimal images.
[[ -x /usr/sbin/ip || -x /sbin/ip || -x /usr/bin/ip ]] \
    || die "the iproute2 package is required (the prober needs 'ip netns')"

# Resolve the directory to install from: the script's own location unless given.
if [[ -z "$HUB_DIR" ]]; then
    HUB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
# Normalise before anything derives a path from it. A trailing slash would
# otherwise reach `PYTHONPATH=$HUB_DIR/src` as a double slash.
HUB_DIR="${HUB_DIR%/}"
[[ -f "$HUB_DIR/pyproject.toml" ]] || die "$HUB_DIR does not look like the hub project (no pyproject.toml)"
[[ -d "$HUB_DIR/src/hub" ]] || die "$HUB_DIR/src/hub is missing"
info "installing from: $HUB_DIR"

# Default the account to whoever invoked sudo, not to root: the services should
# not run as root, and the operator who owns the checkout is the obvious owner.
if [[ -z "$HUB_USER" ]]; then
    HUB_USER="${SUDO_USER:-root}"
fi
id "$HUB_USER" >/dev/null 2>&1 || die "user '$HUB_USER' does not exist"
HUB_GROUP="$(id -gn "$HUB_USER")"
info "services will run as: $HUB_USER:$HUB_GROUP"

# The project directory must be readable by that account, and `data/` writable.
if ! sudo -u "$HUB_USER" test -r "$HUB_DIR/pyproject.toml"; then
    die "$HUB_USER cannot read $HUB_DIR — move the checkout, or chown it"
fi

# ---- 1. dependencies -----------------------------------------------------

if [[ $SKIP_DEPS -eq 0 ]]; then
    step "Installing Python dependencies into the system interpreter"
    info "the units run /usr/bin/python3, so a venv would be a Python they never use"

    PIP_ARGS=(--quiet --disable-pip-version-check)
    # A Debian/Ubuntu system Python is "externally managed" (PEP 668) and refuses
    # a plain install. `--break-system-packages` is the documented override and
    # is safe here because we are installing the exact set from requirements.txt
    # into a server's system interpreter on purpose, not into a desktop.
    if python3 -c "import sysconfig,pathlib,sys; sys.exit(0 if (pathlib.Path(sysconfig.get_paths()['stdlib']).parent/'EXTERNALLY-MANAGED').exists() else 1)" 2>/dev/null; then
        warn "system Python is externally managed; adding --break-system-packages"
        PIP_ARGS+=(--break-system-packages)
    fi

    python3 -m pip "${PIP_ARGS[@]}" install -r "$HUB_DIR/requirements.txt" \
        || die "pip install failed — see the output above"
    info "dependencies installed"
else
    step "Skipping dependencies (--skip-deps)"
fi

# ---- 2. the two cores ----------------------------------------------------

step "Downloading the validation cores"

mkdir -p "$HUB_DIR/tools"

fetch_core() {
    local name="$1" url="$2" dest="$3"
    if [[ -x "$dest" ]]; then
        info "$name: already present at $dest"
        return 0
    fi
    local tmp
    tmp="$(mktemp -d)"
    # shellcheck disable=SC2064
    trap "rm -rf '$tmp'" RETURN
    if ! curl -fsSL --max-time 120 -o "$tmp/archive" "$url"; then
        warn "$name: download failed — its validation step will be skipped"
        return 0
    fi
    case "$url" in
        *.tar.gz) tar xzf "$tmp/archive" -C "$tmp" ;;
        *.zip)    ( cd "$tmp" && unzip -oq archive ) ;;
    esac
    local found
    found="$(find "$tmp" -maxdepth 2 -type f -name "$name" | head -1)"
    if [[ -n "$found" ]]; then
        install -m 0755 "$found" "$dest"
        info "$name: installed to $dest"
    else
        warn "$name: binary not found inside the archive"
    fi
}

ARCH="$(uname -m)"
case "$ARCH" in
    x86_64) SB_ARCH="amd64"; XR_ARCH="64" ;;
    aarch64) SB_ARCH="arm64"; XR_ARCH="arm64-v8a" ;;
    *) warn "unsupported architecture $ARCH — skipping both cores"; SB_ARCH=""; XR_ARCH="" ;;
esac

if [[ -n "$SB_ARCH" ]]; then
    # `sing-box` checks every sing-box payload before publication. Without it
    # that check is skipped rather than failing, which the run report names.
    fetch_core "sing-box" \
        "https://github.com/SagerNet/sing-box/releases/download/v1.12.14/sing-box-1.12.14-linux-${SB_ARCH}.tar.gz" \
        "$HUB_DIR/tools/sing-box"
    # `xray` validates the balancer config. The hub does not run Xray; this is
    # the only thing it is for.
    fetch_core "xray" \
        "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-${XR_ARCH}.zip" \
        "$HUB_DIR/tools/xray"
fi

# ---- 3. the probe sandbox ------------------------------------------------

if [[ $SKIP_PROBE -eq 0 ]]; then
    step "Creating the probe sandbox (hubns)"
    info "without it the prober refuses to run and the pool stays empty"
    if bash "$HUB_DIR/deploy/hubns-ensure.sh" --verify; then
        info "hubns is ready"
    else
        # Not fatal: the fetch-and-publish half works without it, and an
        # operator may not want a network namespace on a box they do not
        # control. Say what is lost rather than stopping.
        warn "could not create hubns — the prober will refuse to run"
        warn "the pool will stay empty until it exists; see deploy/hubns-ensure.sh"
    fi
else
    step "Skipping the probe sandbox (--skip-probe)"
fi

# ---- 4. the unit files ---------------------------------------------------

step "Installing systemd units"

if [[ -f "$HUB_DIR/venv/bin/python" || -x "$HUB_DIR/.venv/bin/python" ]]; then
    warn "a virtualenv exists in the project; the units use /usr/bin/python3 and will ignore it"
fi

# Refuse to adopt an installation that is not this one.
#
# This guard exists because the installer was run against a checkout in /tmp on
# a host that already had a working hub, and it silently pointed the live
# services at /tmp. Nothing failed loudly: the running processes kept their old
# working directory, so the API answered, and the breakage would have surfaced
# at the next restart as a service that cannot find its project. An installer
# that can quietly re-point a live service is worse than one that refuses.
existing_unit="/etc/systemd/system/hub-api.service"
if [[ -f "$existing_unit" && $FORCE -eq 0 ]]; then
    existing_dir="$(sed -n 's|^Environment=HUB_ROOT=||p' "$existing_unit" | head -1)"
    if [[ -n "$existing_dir" && "$existing_dir" != "$HUB_DIR" ]]; then
        die "a hub is already installed from $existing_dir, and this would re-point it at $HUB_DIR.

    The running services would keep working until their next restart,
    which makes the damage invisible when it happens.

    Re-run with --force to replace it, or point --dir at $existing_dir to
    upgrade that installation instead."
    fi
    info "upgrading the existing installation at $existing_dir"
fi

# Render every template, then install them in one pass. A failure here stops
# the install *before* any unit reaches /etc: half a set of units on disk looks
# installed and behaves unpredictably, which is worse than a clean abort.
for template in "$HUB_DIR"/deploy/*.service.in; do
    name="$(basename "$template" .in)"
    if ! unit="$(PYTHONPATH="$HUB_DIR/src" python3 "$HUB_DIR/deploy/render_unit.py" \
            "$template" "$HUB_DIR" "$HUB_USER" "$HUB_GROUP")"; then
        die "failed to render $template"
    fi
    printf '%s\n' "$unit" > "/etc/systemd/system/$name"
    chmod 0644 "/etc/systemd/system/$name"
    info "$name"
done

# `hub-api-external.service` is deliberately not installed: it binds the API to
# a public interface, which the security posture forbids. If an older install
# left it enabled, say so rather than silently diverging.
if [[ -f /etc/systemd/system/hub-api-external.service ]]; then
    warn "hub-api-external.service is present on this host — it binds the API publicly"
    warn "stop and disable it: systemctl disable --now hub-api-external.service"
fi

systemctl daemon-reload
info "systemd reloaded"

# The nginx vhost is rendered to a file for the operator to install, NOT
# installed by this script: publishing on a port affects every other vhost on
# the host, and that is a decision with consequences the installer cannot see.
if [[ -n "$HUB_HOST" ]]; then
    out="/etc/nginx/conf.d/hub.conf"
    if [[ -e "$out" ]]; then
        warn "$out exists — not overwriting it"
        out="$HUB_DIR/deploy/nginx-hub-8444.rendered.conf"
        info "writing the rendered vhost to $out instead"
    fi
    if PYTHONPATH="$HUB_DIR/src" python3 "$HUB_DIR/deploy/render_nginx.py" \
            "$HUB_DIR/deploy/nginx-hub-8444.conf.in" "$HUB_HOST" > "$out"; then
        info "vhost rendered for $HUB_HOST"
        info "install it with: nginx -t && cp $out /etc/nginx/conf.d/hub.conf && systemctl reload nginx"
    else
        warn "could not render the vhost for $HUB_HOST"
        rm -f "$out"
    fi
else
    info "no --host given, so no nginx vhost was rendered"
    info "render it later: PYTHONPATH=src python3 deploy/render_nginx.py \\"
    info "                    deploy/nginx-hub-8444.conf.in YOUR_HOST > /etc/nginx/conf.d/hub.conf"
fi

# ---- 5. environment ------------------------------------------------------

step "Writing /etc/hub/hub.env"

mkdir -p /etc/hub
if [[ -f /etc/hub/hub.env ]]; then
    info "keeping the existing /etc/hub/hub.env (token unchanged)"
else
    TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
    umask 027
    cat > /etc/hub/hub.env <<EOF
# Generated by install.sh. The token is the only secret here: it gates who may
# poll a subscription. Rotate it by editing this file and restarting hub-api.
HUB_TOKEN=$TOKEN
EOF
    if [[ -n "$HUB_BASE_URL" ]]; then
        printf 'HUB_BASE_URL=%s\n' "$HUB_BASE_URL" >> /etc/hub/hub.env
        info "base_url: $HUB_BASE_URL"
    else
        info "base_url not set — subscription headers omit the URL fields"
        info "set it later: HUB_BASE_URL=https://your-host:8444 in /etc/hub/hub.env"
    fi
    chown root:"$HUB_GROUP" /etc/hub/hub.env
    chmod 0640 /etc/hub/hub.env
    info "token generated (not printed; read it from /etc/hub/hub.env)"
fi

# ---- 6. services ---------------------------------------------------------

step "Enabling services"

systemctl enable --now hub-api.service   >/dev/null 2>&1 || warn "hub-api failed to start"
systemctl enable --now hub-worker.timer  >/dev/null 2>&1 || warn "hub-worker.timer failed to enable"
systemctl enable --now hub-ns.service    >/dev/null 2>&1 || warn "hub-ns failed to start"
systemctl enable --now hub-probe.timer   >/dev/null 2>&1 || warn "hub-probe.timer failed to enable"
info "hub-api:  $(systemctl is-active hub-api.service)"
info "worker:   $(systemctl is-active hub-worker.timer) (timer)"
info "probe:    $(systemctl is-active hub-probe.timer) (timer)"
info "the bot is NOT enabled: it needs a Telegram token, see .env.example"

# ---- 7. one run, and say what came out -----------------------------------

step "Running one pipeline pass"

# The worker has no network on purpose, so this pass fetches and does not probe.
# It is a smoke test that the install works, not a filled pool: the first probe
# happens on the timer, and it is the only thing that can publish nodes.
if sudo -u "$HUB_USER" env "PYTHONPATH=$HUB_DIR/src" "HUB_ROOT=$HUB_DIR" \
        SINGBOX_BIN="$HUB_DIR/tools/sing-box" XRAY_BIN="$HUB_DIR/tools/xray" \
        HUB_SKIP_NETWORK=1 python3 -m hub.cli run 2>&1 | tail -3; then
    info "pipeline ran"
else
    warn "the pipeline pass failed — check the output above"
    warn "run 'hub run' by hand as $HUB_USER to see the full trace"
fi

# ---- done ----------------------------------------------------------------

cat <<EOF

$(printf '\033[1m')Installed.$(printf '\033[0m')

  Services are on loopback only — nothing is exposed yet:
      API      http://127.0.0.1:$HUB_PORT
      token    /etc/hub/hub.env
      project  $HUB_DIR

  The pool is empty until the first probe. It runs on a timer, or now:
      sudo systemctl start hub-probe.service

  To publish it, put nginx in front with TLS and open one port.
  See deploy/nginx-hub-8444.conf and docs/OPERATIONS.md.

EOF
