#!/usr/bin/env bash
# Build and validate the AAIT commercial runtime using Docker only.
#
# This gate intentionally performs no external model/provider calls. Runtime
# checks use --network none so packaging/activation/policy tests cannot reach
# external services even if future code accidentally attempts to do so.
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
printf 'policy: [this, is, invalid-for-aait]\n' > "$TMP_ROOT/invalid-tenant.yaml"

printf '\n==> Building %s\n' "$IMAGE"
docker build --pull -t "$IMAGE" "$REPO_ROOT"

printf '\n==> Running targeted AAIT unit tests inside the image\n'
docker run --rm --network none \
    -e AAIT_RUNTIME_ENABLED=0 \
    "$IMAGE" \
    pytest -q \
        tests/test_aait_policy.py \
        tests/test_aait_approvals.py \
        tests/test_aait_runtime.py

printf '\n==> Verifying stock Docker behavior when AAIT is disabled\n'
docker run --rm --network none \
    -e AAIT_RUNTIME_ENABLED=0 \
    -v "$TMP_ROOT/off-data:/opt/data" \
    "$IMAGE" \
    python -c '
import pathlib, yaml
cfg = yaml.safe_load(pathlib.Path("/opt/data/config.yaml").read_text()) or {}
enabled = ((cfg.get("plugins") or {}).get("enabled") or [])
assert "aait-runtime" not in enabled, enabled
assert not pathlib.Path("/opt/data/aait").exists(), "AAIT state leaked into stock mode"
import aait_runtime
print("AAIT package present; stock runtime remains disabled and state-free")
'

printf '\n==> Verifying production-style AAIT opt-in and default secret path\n'
docker run --rm --network none \
    -e AAIT_RUNTIME_ENABLED=1 \
    -e AAIT_REQUIRE_TENANT_CONFIG=1 \
    -v "$TMP_ROOT/on-data:/opt/data" \
    -v "$TMP_ROOT/tenant.yaml:/run/secrets/aait-tenant.yaml:ro" \
    "$IMAGE" \
    python -c '
import pathlib, stat, yaml
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
state = pathlib.Path("/opt/data/aait")
db = state / "approvals.sqlite3"
assert db.is_file()
assert stat.S_IMODE(state.stat().st_mode) == 0o700, oct(stat.S_IMODE(state.stat().st_mode))
assert stat.S_IMODE(db.stat().st_mode) == 0o600, oct(stat.S_IMODE(db.stat().st_mode))
print(status)
'

printf '\n==> Verifying optional missing-policy mode remains approval-gated\n'
docker run --rm --network none \
    -e AAIT_RUNTIME_ENABLED=1 \
    -e AAIT_REQUIRE_TENANT_CONFIG=0 \
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

printf '\n==> Verifying production strict mode rejects a missing tenant policy\n'
if docker run --rm --network none \
    -e AAIT_RUNTIME_ENABLED=1 \
    -e AAIT_REQUIRE_TENANT_CONFIG=1 \
    -e AAIT_TENANT_CONFIG=/run/secrets/does-not-exist.yaml \
    "$IMAGE" \
    python -c 'raise SystemExit("entrypoint should have blocked startup")'; then
    echo "ERROR: strict AAIT startup unexpectedly accepted a missing tenant policy." >&2
    exit 1
fi

printf '\n==> Verifying malformed tenant policy fails startup validation\n'
if docker run --rm --network none \
    -e AAIT_RUNTIME_ENABLED=1 \
    -e AAIT_REQUIRE_TENANT_CONFIG=1 \
    -v "$TMP_ROOT/invalid-tenant.yaml:/run/secrets/aait-tenant.yaml:ro" \
    "$IMAGE" \
    python -c 'raise SystemExit("entrypoint should have rejected malformed policy")'; then
    echo "ERROR: AAIT startup unexpectedly accepted a malformed tenant policy." >&2
    exit 1
fi

printf '\nAAIT Docker validation passed for image %s\n' "$IMAGE"
