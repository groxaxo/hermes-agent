#!/bin/bash
# Docker/Podman entrypoint: bootstrap config files into the mounted volume, then run hermes.
set -e

HERMES_HOME="${HERMES_HOME:-/opt/data}"
INSTALL_DIR="/opt/hermes"

_is_truthy() {
    case "${1:-}" in
        1|true|TRUE|True|yes|YES|Yes|on|ON|On) return 0 ;;
        *) return 1 ;;
    esac
}

# --- Privilege dropping via gosu ---
# When started as root (the default for Docker, or fakeroot in rootless Podman),
# optionally remap the hermes user/group to match host-side ownership, fix volume
# permissions, then re-exec as hermes.
if [ "$(id -u)" = "0" ]; then
    if [ -n "$HERMES_UID" ] && [ "$HERMES_UID" != "$(id -u hermes)" ]; then
        echo "Changing hermes UID to $HERMES_UID"
        usermod -u "$HERMES_UID" hermes
    fi

    if [ -n "$HERMES_GID" ] && [ "$HERMES_GID" != "$(id -g hermes)" ]; then
        echo "Changing hermes GID to $HERMES_GID"
        # -o allows non-unique GID (e.g. macOS GID 20 "staff" may already exist
        # as "dialout" in the Debian-based container image)
        groupmod -o -g "$HERMES_GID" hermes 2>/dev/null || true
    fi

    # Fix ownership of the data volume. When HERMES_UID remaps the hermes user,
    # files created by previous runs (under the old UID) become inaccessible.
    # Always chown -R when UID was remapped; otherwise only if top-level is wrong.
    actual_hermes_uid=$(id -u hermes)
    needs_chown=false
    if [ -n "$HERMES_UID" ] && [ "$HERMES_UID" != "10000" ]; then
        needs_chown=true
    elif [ "$(stat -c %u "$HERMES_HOME" 2>/dev/null)" != "$actual_hermes_uid" ]; then
        needs_chown=true
    fi
    if [ "$needs_chown" = true ]; then
        echo "Fixing ownership of $HERMES_HOME to hermes ($actual_hermes_uid)"
        # In rootless Podman the container's "root" is mapped to an unprivileged
        # host UID — chown will fail. That's fine: the volume is already owned
        # by the mapped user on the host side.
        chown -R hermes:hermes "$HERMES_HOME" 2>/dev/null || \
            echo "Warning: chown failed (rootless container?) — continuing anyway"
    fi

    # Ensure config.yaml is readable by the hermes runtime user even if it was
    # edited on the host after initial ownership setup. Must run here (as root)
    # rather than after the gosu drop, otherwise a non-root caller like
    # `docker run -u $(id -u):$(id -g)` hits "Operation not permitted" (#15865).
    if [ -f "$HERMES_HOME/config.yaml" ]; then
        chown hermes:hermes "$HERMES_HOME/config.yaml" 2>/dev/null || true
        chmod 640 "$HERMES_HOME/config.yaml" 2>/dev/null || true
    fi

    echo "Dropping root privileges"
    exec gosu hermes "$0" "$@"
fi

# --- Running as hermes from here ---
source "${INSTALL_DIR}/.venv/bin/activate"

# Create essential directory structure. Cache and platform directories
# (cache/images, cache/audio, platforms/whatsapp, etc.) are created on
# demand by the application — don't pre-create them here so new installs
# get the consolidated layout from get_hermes_dir().
# The "home/" subdirectory is a per-profile HOME for subprocesses (git,
# ssh, gh, npm …). Without it those tools write to /root which is
# ephemeral and shared across profiles. See issue #4426.
#
# AAIT state is deliberately NOT created in stock mode. This preserves the
# existing container filesystem contract when AAIT_RUNTIME_ENABLED is false.
mkdir -p "$HERMES_HOME"/{cron,sessions,logs,hooks,memories,skills,skins,plans,workspace,home}

# .env
if [ ! -f "$HERMES_HOME/.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$HERMES_HOME/.env"
fi

# config.yaml
if [ ! -f "$HERMES_HOME/config.yaml" ]; then
    cp "$INSTALL_DIR/cli-config.yaml.example" "$HERMES_HOME/config.yaml"
fi

# --- Optional AAIT commercial runtime ---
# AAIT is intentionally disabled unless AAIT_RUNTIME_ENABLED is explicitly
# truthy. When enabled, the entrypoint creates a private state directory,
# optionally requires the tenant policy mount, enables the plugin, verifies
# actual discovery/registration, and parses the active policy before Hermes
# is allowed to start.
#
# Tenant policy is never copied into the image or generated from secrets.
# Production deployments should mount it read-only at
# /run/secrets/aait-tenant.yaml and set AAIT_REQUIRE_TENANT_CONFIG=1.
if _is_truthy "${AAIT_RUNTIME_ENABLED:-0}"; then
    AAIT_STATE_DIR="$HERMES_HOME/aait"
    export AAIT_TENANT_CONFIG="${AAIT_TENANT_CONFIG:-/run/secrets/aait-tenant.yaml}"

    if ! mkdir -p "$AAIT_STATE_DIR" || ! chmod 700 "$AAIT_STATE_DIR"; then
        echo "ERROR: AAIT runtime could not create a private state directory at $AAIT_STATE_DIR." >&2
        exit 1
    fi
    if [ ! -w "$AAIT_STATE_DIR" ]; then
        echo "ERROR: AAIT state directory is not writable: $AAIT_STATE_DIR" >&2
        exit 1
    fi

    if _is_truthy "${AAIT_REQUIRE_TENANT_CONFIG:-0}" && [ ! -r "$AAIT_TENANT_CONFIG" ]; then
        echo "ERROR: AAIT tenant policy is required but not readable at $AAIT_TENANT_CONFIG." >&2
        exit 1
    fi

    echo "AAIT runtime requested; enabling aait-runtime plugin"
    if ! hermes plugins enable aait-runtime >/tmp/aait-plugin-enable.log 2>&1; then
        echo "ERROR: AAIT runtime was requested but aait-runtime could not be enabled." >&2
        cat /tmp/aait-plugin-enable.log >&2 || true
        rm -f /tmp/aait-plugin-enable.log
        exit 1
    fi
    rm -f /tmp/aait-plugin-enable.log

    # `hermes plugins enable` persists allow-list state and takes effect on the
    # next process/session. Verify that next-process behavior now rather than
    # trusting config mutation alone. Calling /aait status also forces policy
    # parsing and state-store initialization, so malformed/read-protected policy
    # files fail startup instead of waiting for the first tool call.
    if ! python - <<'PY'
from hermes_cli.plugins import (
    discover_plugins,
    get_plugin_command_handler,
    get_plugin_manager,
)

discover_plugins(force=True)
plugins = {p["key"]: p for p in get_plugin_manager().list_plugins()}
record = plugins.get("aait-runtime")
if record is None:
    raise SystemExit("aait-runtime was not discovered")
if not record.get("enabled"):
    raise SystemExit(
        "aait-runtime failed to load: " + str(record.get("error") or "unknown error")
    )
handler = get_plugin_command_handler("aait")
if handler is None:
    raise SystemExit("aait-runtime loaded without registering /aait")
status = handler("status")
if status.startswith("AAIT runtime error:"):
    raise SystemExit(status)
print(status)
PY
    then
        echo "ERROR: AAIT runtime failed startup validation." >&2
        exit 1
    fi

    if [ -r "$AAIT_TENANT_CONFIG" ]; then
        echo "AAIT tenant policy validated: $AAIT_TENANT_CONFIG"
    else
        echo "WARNING: AAIT tenant policy is missing at $AAIT_TENANT_CONFIG; all unmatched actions require approval." >&2
    fi
fi

# SOUL.md
if [ ! -f "$HERMES_HOME/SOUL.md" ]; then
    cp "$INSTALL_DIR/docker/SOUL.md" "$HERMES_HOME/SOUL.md"
fi

# Sync bundled skills (manifest-based so user edits are preserved)
if [ -d "$INSTALL_DIR/skills" ]; then
    python3 "$INSTALL_DIR/tools/skills_sync.py"
fi

# Optionally start `hermes dashboard` as a side-process.
#
# Toggled by HERMES_DASHBOARD=1 (also accepts "true"/"yes", case-insensitive).
# Host/port/TUI can be overridden via:
#   HERMES_DASHBOARD_HOST  (default 0.0.0.0 — exposed outside the container)
#   HERMES_DASHBOARD_PORT  (default 9119, matches `hermes dashboard` default)
#   HERMES_DASHBOARD_TUI   (already honored by `hermes dashboard` itself)
#
# The dashboard is a long-lived server. We background it *before* the final
# `exec hermes "$@"` so the user's chosen foreground command (chat, gateway,
# sleep infinity, …) remains PID-of-interest for the container runtime. When
# the container stops the whole process tree is torn down, so no explicit
# cleanup is needed.
case "${HERMES_DASHBOARD:-}" in
    1|true|TRUE|True|yes|YES|Yes)
        dash_host="${HERMES_DASHBOARD_HOST:-0.0.0.0}"
        dash_port="${HERMES_DASHBOARD_PORT:-9119}"
        dash_args=(--host "$dash_host" --port "$dash_port" --no-open)
        # Binding to anything other than localhost requires --insecure — the
        # dashboard refuses otherwise because it exposes API keys. Inside a
        # container this is the expected deployment (host reaches it via
        # published port), so opt in automatically.
        if [ "$dash_host" != "127.0.0.1" ] && [ "$dash_host" != "localhost" ]; then
            dash_args+=(--insecure)
        fi
        echo "Starting hermes dashboard on ${dash_host}:${dash_port} (background)"
        # Prefix dashboard output so it's distinguishable from the main
        # process in `docker logs`. stdbuf keeps the pipe line-buffered.
        (
            stdbuf -oL -eL hermes dashboard "${dash_args[@]}" 2>&1 \
                | sed -u 's/^/[dashboard] /'
        ) &
        ;;
esac

# Final exec: two supported invocation patterns.
#
#   docker run <image>                 -> exec `hermes` with no args (legacy default)
#   docker run <image> chat -q "..."   -> exec `hermes chat -q "..."` (legacy wrap)
#   docker run <image> sleep infinity  -> exec `sleep infinity` directly
#   docker run <image> bash            -> exec `bash` directly
#
# If the first positional arg resolves to an executable on PATH, we assume the
# caller wants to run it directly (needed by the launcher which runs long-lived
# `sleep infinity` sandbox containers — see tools/environments/docker.py).
# Otherwise we treat the args as a hermes subcommand and wrap with `hermes`,
# preserving the documented `docker run <image> <subcommand>` behavior.
if [ $# -gt 0 ] && command -v "$1" >/dev/null 2>&1; then
    exec "$@"
fi
exec hermes "$@"
