# AAIT Runtime plugin

`aait-runtime` turns Hermes into a **replaceable execution engine** beneath an
Auckland Automate IT-owned commercial control boundary.

It deliberately does **not** fork or patch `run_agent.py`, `model_tools.py`, or
gateway dispatch. It uses Hermes's supported plugin hooks so upstream merges
remain manageable.

## What this plugin enforces now

- ordered per-tenant tool policy: `automatic`, `approval`, `forbidden`;
- approval-gated safe default when no tenant policy is available;
- exact-action SHA-256 approvals tied to tenant + session + tool + arguments;
- single-use approval consumption with expiry;
- SQLite approval state that survives process/container restarts;
- metadata-only JSONL audit logs;
- argument values and tool result bodies omitted from AAIT audit storage;
- `/aait status`, `approvals`, `approve`, `reject`, and `reload` commands.

The Docker integration adds a stricter managed-production option: set
`AAIT_REQUIRE_TENANT_CONFIG=1` and container startup fails if the tenant policy
is missing, unreadable, or malformed.

## What this plugin does not claim yet

This PR establishes the commercial policy/approval boundary and stable connector
contracts. It does **not** yet implement production Gmail, Calendar, Drive, or
MissedCallZero AAIT connectors. Those are follow-up modules that should expose
stable `aait.*` action names.

---

## Native / local enablement

The plugin is standalone and opt-in:

```bash
hermes plugins enable aait-runtime
```

Copy the example policy:

```bash
mkdir -p ~/.hermes/aait
cp examples/aait/tenant.yaml ~/.hermes/aait/tenant.yaml
```

Or point the plugin at another YAML file:

```bash
export AAIT_TENANT_CONFIG=/secure/path/tenant.yaml
```

Restart Hermes after first enabling the plugin. Later policy edits may be
reloaded in-session with:

```text
/aait reload
```

Check active state with:

```text
/aait status
```

---

## Docker enablement

The repository image contains the AAIT Python package and bundled plugin, but
AAIT remains **disabled by default**. With AAIT off, the entrypoint does not
create `/opt/data/aait` and does not enable the plugin.

For a managed customer deployment use:

```bash
-e AAIT_RUNTIME_ENABLED=1 \
-e AAIT_REQUIRE_TENANT_CONFIG=1 \
-v /srv/aait/customer-001/policy/tenant.yaml:/run/secrets/aait-tenant.yaml:ro
```

The Dockerfile default policy path is already:

```text
/run/secrets/aait-tenant.yaml
```

so `AAIT_TENANT_CONFIG` only needs to be set when using a different path.

Example local smoke run:

```bash
docker build --pull -t aait-hermes:dev .

mkdir -p runtime-smoke/data
cp examples/aait/tenant.yaml runtime-smoke/tenant.yaml

docker run --rm -it \
  -e AAIT_RUNTIME_ENABLED=1 \
  -e AAIT_REQUIRE_TENANT_CONFIG=1 \
  -v "$(pwd)/runtime-smoke/data:/opt/data" \
  -v "$(pwd)/runtime-smoke/tenant.yaml:/run/secrets/aait-tenant.yaml:ro" \
  aait-hermes:dev \
  bash
```

When AAIT is enabled, the entrypoint:

1. creates `/opt/data/aait` and restricts it to `0700`;
2. optionally requires the tenant-policy mount;
3. enables `aait-runtime` idempotently;
4. verifies real plugin discovery/load, not just config mutation;
5. requires `/aait` registration;
6. forces policy parsing during startup;
7. exits if plugin activation or policy validation fails.

The approval database is restricted to `0600` on POSIX systems. Mutable AAIT
state remains on the normal `HERMES_HOME` volume:

```text
/opt/data/aait/
├── approvals.sqlite3
└── audit/
    └── YYYY-MM-DD.jsonl
```

### Missing-policy behavior

For development/recovery, `AAIT_REQUIRE_TENANT_CONFIG=0` allows startup without
a policy, but unmatched actions remain approval-gated.

For managed production, use `AAIT_REQUIRE_TENANT_CONFIG=1`; a missing or
unreadable policy aborts startup. A present but malformed policy also aborts
startup because the entrypoint validates `/aait status` before Hermes starts.

---

## Approval flow

When an action matches an `approval` rule, Hermes receives a blocking result
similar to:

```text
AAIT approval required for 'aait.gmail.send'.
Approval ID: apr_abc123...
```

The user approves it:

```text
/aait approve apr_abc123...
```

The **exact same** tool call may then be retried once.

Any change to recipient, body, time, amount, target, or another argument changes
the action hash and requires a new approval. The approval is not a temporary
blanket permission.

### Stored approval metadata

The approval database stores:

- tenant ID;
- session ID;
- tool name;
- argument **keys**;
- exact-action digest;
- approval status/timestamps.

It does not persist argument values themselves.

---

## Stable connector namespace

New AAIT connectors should expose names such as:

```text
aait.gmail.search
aait.gmail.get_thread
aait.gmail.create_draft
aait.gmail.send
aait.calendar.read
aait.calendar.create
aait.calendar.reschedule
aait.calendar.cancel
aait.drive.read
aait.drive.write
aait.missedcallzero.lead.create
```

This keeps customer policy independent of Hermes internals and the concrete
API/MCP implementation behind each connector.

---

## Required validation before customer rollout

Use the repository's reproducible Docker gate:

```bash
./scripts/validate_aait_docker.sh
```

It builds the image and performs its runtime checks with `--network none`, so it
cannot call external model/provider APIs. It verifies stock AAIT-off behavior,
plugin activation, default secret-path resolution, strict missing-policy
failure, malformed-policy failure, state permissions, and the targeted Python
regression suite.

After that passes, verify one real end-to-end tool call from each policy class:

1. `automatic` executes without approval;
2. `approval` returns an ID and executes only after exact-action approval;
3. a modified retry requires a new approval;
4. a consumed approval cannot be replayed;
5. `forbidden` never dispatches;
6. restart preserves approval/audit state;
7. audit logs do not contain argument values.

For architecture, Docker production posture, rollout gates, and rollback policy,
see `docs/aait-runtime.md`.
