# AAIT Runtime plugin

`aait-runtime` turns Hermes into a **replaceable execution engine** beneath an
Auckland Automate IT-owned commercial control boundary.

It deliberately does **not** fork or patch `run_agent.py`, `model_tools.py`, or
gateway dispatch. It uses Hermes's supported plugin hooks so upstream merges
remain manageable.

## What this plugin enforces now

- per-tenant ordered tool policy: `automatic`, `approval`, `forbidden`;
- fail-closed default when enabled without a valid tenant policy;
- exact-action SHA-256 approvals tied to tenant + session + tool + arguments;
- single-use approval consumption with expiry;
- SQLite approval state that survives process/container restarts;
- metadata-only JSONL audit logs;
- argument values and tool result bodies are omitted from AAIT audit storage;
- `/aait status`, `approvals`, `approve`, `reject`, and `reload` commands.

## What this plugin does not claim yet

This PR establishes the commercial policy/approval boundary and stable connector
contracts. It does **not** yet implement the production Gmail, Calendar, Drive,
or MissedCallZero AAIT connectors. Those are follow-up modules that should use
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

Alternatively point the plugin at a different YAML file:

```bash
export AAIT_TENANT_CONFIG=/secure/path/tenant.yaml
```

Restart Hermes after first enabling the plugin. Later policy edits may be
reloaded in-session with:

```text
/aait reload
```

Check the active state:

```text
/aait status
```

---

## Docker enablement

The repository Docker image contains the AAIT Python package and bundled
plugin, but AAIT enforcement remains **disabled by default** to preserve normal
Hermes behavior.

Enable it explicitly:

```bash
-e AAIT_RUNTIME_ENABLED=1
```

The default container policy path is:

```text
/opt/data/aait/tenant.yaml
```

For production, prefer a read-only external policy mount:

```bash
-e AAIT_TENANT_CONFIG=/run/secrets/aait-tenant.yaml \
-v /srv/aait/customer-001/policy/tenant.yaml:/run/secrets/aait-tenant.yaml:ro
```

Example local smoke run:

```bash
docker build --pull -t aait-hermes:dev .

mkdir -p runtime-smoke/data
cp examples/aait/tenant.yaml runtime-smoke/tenant.yaml

docker run --rm -it \
  -e AAIT_RUNTIME_ENABLED=1 \
  -e AAIT_TENANT_CONFIG=/run/secrets/aait-tenant.yaml \
  -v "$(pwd)/runtime-smoke/data:/opt/data" \
  -v "$(pwd)/runtime-smoke/tenant.yaml:/run/secrets/aait-tenant.yaml:ro" \
  aait-hermes:dev \
  bash
```

When `AAIT_RUNTIME_ENABLED=1`, the entrypoint enables `aait-runtime`
idempotently. If plugin activation itself fails, container startup fails rather
than silently proceeding without the commercial policy layer.

If the tenant policy path is missing or unreadable, startup warns and the
plugin falls back to its **fail-closed approval default**. A managed customer
deployment should still treat that warning as a provisioning failure.

AAIT mutable state is persisted under the normal `HERMES_HOME` volume:

```text
/opt/data/aait/
├── approvals.sqlite3
└── audit/
    └── YYYY-MM-DD.jsonl
```

Tenant policy may also live there for simple installations, but an external
read-only mount gives a cleaner production separation between operator policy
and mutable runtime state.

---

## Approval flow

When an action matches an `approval` rule, Hermes receives a blocking tool
result similar to:

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

It does not persist the argument values themselves.

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

This keeps customer policy independent of Hermes internals and of the concrete
API/MCP implementation behind each connector.

---

## Required validation before customer rollout

Run at minimum:

```bash
pytest -q \
  tests/test_aait_policy.py \
  tests/test_aait_approvals.py \
  tests/test_aait_runtime.py

docker build --pull -t aait-hermes:pr-test .
```

Then verify one real tool call from each policy class:

1. `automatic` executes without approval;
2. `approval` returns an ID and executes only after exact-action approval;
3. a modified retry requires a new approval;
4. a consumed approval cannot be replayed;
5. `forbidden` never dispatches;
6. restart preserves approval/audit state;
7. audit logs do not contain argument values;
8. non-AAIT Docker usage remains unchanged when `AAIT_RUNTIME_ENABLED=0`.

For the full architecture, Docker production guidance, upgrade/rollback policy,
and adversarial rollout gates, see `docs/aait-runtime.md`.
