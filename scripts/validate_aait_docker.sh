#!/usr/bin/env bash
# Build and validate the AAIT commercial runtime using Docker only.
#
# This script intentionally does not call external model/provider APIs. It
# validates packaging, AAIT unit tests, opt-in behavior, plugin enablement,
# policy loading, and persistent AAIT state creation.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
IMAGE="${AAIT_TEST_IMAGE:-aait-hermes:pr-test}"

if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker is required to run the AAIT container validation." >&2
    exit 1
fi

TMP_ROOT="$(mktemp -d)"
cleanup() {
    rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

mkdir -p "$TMP_ROOT/off-data" "$TMP_ROOT/on-data"
cp "$REPO_ROOT/examples/aait/tenant.yaml" "$TMP_ROOT/tenant.yaml"

printf '\n==> Building %s\n' "$IMAGE"
docker build --pull -t "$IMAGE" "$REPO_ROOT"

printf '\n==> Running targeted AAIT unit tests inside the image\n'
docker run --rm \
    -e AAIT_RUNTIME_ENABLED=0 \
    "$IMAGE" \
    pytest -q \
        tests/test_aait_policy.py \
        tests/test_aait_approvals.py \
        tests/test_aait_runtime.py

printf '\n==> Verifying stock Docker behavior when AAIT is disabled\n'
docker run --rm \
    -e AAIT_RUNTIME_ENABLED=0 \
    -v "$TMP_ROOT/off-data:/opt/data" \
    "$IMAGE" \
    python -c '
import pathlib, yaml
cfg = yaml.safe_load(pathlib.Path("/opt/data/config.yaml").read_text()) or {}
enabled = ((cfg.get("plugins") or {}).get("enabled") or [])
assert "aait-runtime" not in enabled, enabled
import aait_runtime
print("AAIT package present; runtime correctly remains disabled")
'

printf '\n==> Verifying AAIT opt-in, plugin discovery, and mounted policy\n'
docker run --rm \
    -e AAIT_RUNTIME_ENABLED=1 \
    -e AAIT_TENANT_CONFIG=/run/secrets/aait-tenant.yaml \
    -v "$TMP_ROOT/on-data:/opt/data" \
    -v "$TMP_ROOT/tenant.yaml:/run/secrets/aait-tenant.yaml:ro" \
    "$IMAGE" \
    python -c '
import pathlib, yaml
from hermes_cli.plugins import discover_plugins, get_plugin_command_handler, get_plugin_manager

cfg = yaml.safe_load(pathlib.Path("/opt/data/config.yaml").read_text()) or {}
enabled = ((cfg.get("plugins") or {}).get("enabled") or [])
assert "aait-runtime" in enabled, enabled

discover_plugins(force=True)
plugins = {p["key"]: p for p in get_plugin_manager().list_plugins()}
assert "aait-runtime" in plugins, plugins.keys()
assert plugins["aait-runtime"]["enabled"], plugins["aait-runtime"]

handler = get_plugin_command_handler("aait")
assert handler is not None
status = handler("status")
assert "Tenant: customer-001" in status, status
assert "Default mode: approval" in status, status
assert pathlib.Path("/opt/data/aait/approvals.sqlite3").is_file()
print(status)
'

printf '\n==> Verifying missing-policy mode stays fail-closed\n'
docker run --rm \
    -e AAIT_RUNTIME_ENABLED=1 \
    -e AAIT_TENANT_CONFIG=/run/secrets/does-not-exist.yaml \
    "$IMAGE" \
    python -c '
from hermes_cli.plugins import discover_plugins, get_plugin_command_handler

discover_plugins(force=True)
handler = get_plugin_command_handler("aait")
assert handler is not None
status = handler("status")
assert "Default mode: approval" in status, status
assert "missing; fail-closed defaults" in status, status
print(status)
'

printf '\nAAIT Docker validation passed for image %s\n' "$IMAGE"
