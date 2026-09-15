# Auckland Automate IT commercial runtime

## Purpose

Hermes is the current **agent engine**, not the commercial product boundary.
Auckland Automate IT (AAIT) owns the controls that must remain stable when the
underlying agent engine, model vendor, connector implementation, or deployment
method changes.

```text
Customer / Telegram / API
          |
          v
+-----------------------------------+
| AAIT commercial runtime           |
|                                   |
| tenant identity + configuration   |
| policy + exact-action approvals   |
| metadata-only audit               |
| logical model tiers               |
| connector contracts               |
| future workflow/memory ownership  |
+----------------+------------------+
                 |
                 v
          Hermes agent engine
                 |
                 v
        skills / tools / MCP
```

The first implementation ships as the bundled `plugins/aait-runtime` plugin
plus the engine-independent `aait_runtime` Python package. It uses supported
Hermes plugin hooks and deliberately avoids modifications to `run_agent.py`,
`model_tools.py`, or gateway dispatch.

---

## Security invariants

Every tool call is classified by an ordered per-tenant policy:

| Mode | Meaning |
| --- | --- |
| `automatic` | Tool may execute without an additional approval step. |
| `approval` | The exact proposed action must be approved once before dispatch. |
| `forbidden` | Tool must never execute. |

The tenant default is `approval`.

If the AAIT plugin is enabled but its tenant policy cannot be loaded, the
runtime **fails closed** rather than silently allowing tools.

### Exact-action approval

The approval digest is SHA-256 over canonical JSON containing:

```text
tenant_id + tool_name + full arguments
```

An approval is:

1. tenant scoped;
2. session scoped;
3. bound to the exact action digest;
4. time limited;
5. atomically consumed once.

Changing an email recipient/body, calendar time, filesystem target, payment
amount, or any other tool argument creates a different digest and therefore
requires a new approval.

Only the digest and argument **names** are persisted. Argument values are not
written to the AAIT approval database or AAIT audit log.

### Approval flow

```text
Agent proposes tool call
        |
        v
AAIT policy decision
        |
        +--> automatic --> execute
        |
        +--> forbidden --> block
        |
        +--> approval
                |
                v
          exact action hash
                |
                v
          apr_xxxxxxxxxxxx
                |
                v
     /aait approve <approval-id>
                |
                v
        retry exact action
                |
                v
      consume approval once
```

The approval record never acts as a general permission grant.

---

## Stable AAIT connector namespace

Commercial integrations should be exposed to policy through stable AAIT action
names instead of upstream-specific tool names:

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

The implementation behind a connector may use a Google API, MCP server,
internal service, or a future out-of-process connector service. Customer policy
should not need to change when that implementation changes.

> **Current scope:** this PR establishes the connector contract and policy
> boundary. Gmail, Calendar, Drive, and MissedCallZero connector
> implementations are follow-up milestones; they are not implied to exist by
> this document.

---

## Provider abstraction

Product-facing configuration uses logical quality tiers:

```text
standard
advanced
maximum
```

Example:

```yaml
providers:
  routes:
    - tier: standard
      provider: openai
      model: gpt-5.6-luna
      priority: 10

    - tier: standard
      provider: bedrock
      model: amazon-nova-lite
      priority: 20

    - tier: advanced
      provider: openai
      model: gpt-5.6-terra
      priority: 10

    - tier: maximum
      provider: openai
      model: gpt-5.6-sol
      priority: 10
```

Customer workflows should request a logical tier rather than hard-code a model
vendor. `ProviderRouter` is the AAIT-owned contract; Hermes can continue using
its native provider stack as the execution implementation until a measurable
commercial reason exists to replace it.

---

## Runtime state

By default AAIT state is kept beneath `HERMES_HOME/aait`:

```text
/opt/data/aait/                  # Docker default
├── tenant.yaml                  # optional local policy location
├── approvals.sqlite3            # exact-action approval state
└── audit/
    └── YYYY-MM-DD.jsonl          # metadata-only security audit
```

For production Docker deployments, prefer mounting `tenant.yaml` read-only at a
separate path such as `/run/secrets/aait-tenant.yaml` and set
`AAIT_TENANT_CONFIG` to that path. This separates immutable operator policy
from mutable runtime state.

Operational logs, security audit metadata, conversation content, and secrets
are separate data classes. The AAIT audit implementation intentionally does
not retain tool argument values or tool result bodies.

Example audit record:

```json
{
  "event": "approval_required",
  "tenant_id": "customer-001",
  "tool_name": "aait.gmail.send",
  "action_hash": "...",
  "arg_keys": ["body", "subject", "to"]
}
```

---

# Docker deployment

## Docker guarantees added by this runtime

The repository Docker image now provides the following AAIT-specific behavior:

- `aait_runtime` is installed with the Hermes Python environment;
- `plugins/aait-runtime/plugin.yaml` is included in the image;
- `examples/aait/tenant.yaml` is included as an operator example only;
- `docs/aait-runtime.md` and the plugin README are retained in the image;
- `docker/SOUL.md` is explicitly retained despite the general Markdown ignore;
- image build fails if the AAIT package/plugin/example/docs are accidentally
  omitted;
- `/opt/data/aait` is created in persistent `HERMES_HOME`;
- AAIT runtime activation is opt-in through `AAIT_RUNTIME_ENABLED`;
- requested activation is fail-safe: if the plugin cannot be enabled, startup
  exits rather than continuing without policy enforcement;
- no customer policy, OAuth credential, provider API key, or other secret is
  baked into the image.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `AAIT_RUNTIME_ENABLED` | `0` | Explicitly enables AAIT policy/approval enforcement in the Docker entrypoint. |
| `AAIT_TENANT_CONFIG` | `/opt/data/aait/tenant.yaml` | Policy YAML read by the plugin. May point to a read-only secret mount. |
| `HERMES_HOME` | `/opt/data` | Persistent Hermes + AAIT runtime state. |
| `HERMES_UID` | image default `10000` | Optional host UID remap handled by the existing entrypoint. |
| `HERMES_GID` | image default group | Optional host GID remap handled by the existing entrypoint. |

`AAIT_RUNTIME_ENABLED` is a deployment control, not an application secret.
Provider keys and OAuth credentials should continue to use the existing Hermes
secret/config mechanisms or a future AAIT secrets broker.

## Build

From the repository root:

```bash
docker build --pull -t aait-hermes:dev .
```

The build includes a static AAIT packaging gate. A missing Python package,
plugin manifest, example policy, or runtime document fails the image build.
This gate does **not** replace connector/provider integration tests.

## First local smoke test

Create an isolated runtime directory and copy the example policy:

```bash
mkdir -p ./runtime-smoke/data
cp examples/aait/tenant.yaml ./runtime-smoke/tenant.yaml
```

Run the container with the tenant policy mounted read-only outside the mutable
runtime volume:

```bash
docker run --rm -it \
  -e AAIT_RUNTIME_ENABLED=1 \
  -e AAIT_TENANT_CONFIG=/run/secrets/aait-tenant.yaml \
  -v "$(pwd)/runtime-smoke/data:/opt/data" \
  -v "$(pwd)/runtime-smoke/tenant.yaml:/run/secrets/aait-tenant.yaml:ro" \
  aait-hermes:dev \
  bash
```

The entrypoint should report that the AAIT runtime was requested and that the
tenant policy is readable. Inside the container:

```bash
hermes plugins list
python -c 'import aait_runtime; print("aait_runtime import OK")'
```

Then launch Hermes and inspect:

```text
/aait status
```

Expected properties:

```text
Tenant: customer-001
Default mode: approval
Approval TTL: 900s
```

Do not treat the example tenant ID as production configuration.

## Persistent production-style run

A recommended production layout is:

```text
host
├── policy/
│   └── tenant.yaml        # operator-managed, read-only to container
└── hermes-data/           # persistent mutable runtime state
```

Example:

```bash
docker run -d \
  --name aait-customer-001 \
  --restart unless-stopped \
  -e AAIT_RUNTIME_ENABLED=1 \
  -e AAIT_TENANT_CONFIG=/run/secrets/aait-tenant.yaml \
  -v /srv/aait/customer-001/hermes-data:/opt/data \
  -v /srv/aait/customer-001/policy/tenant.yaml:/run/secrets/aait-tenant.yaml:ro \
  aait-hermes:<tested-version> \
  gateway
```

Only publish network ports that the selected Hermes surface actually requires.
Telegram long polling, for example, does not require exposing an inbound
Telegram webhook port.

## Missing tenant policy behavior

If AAIT is requested but `AAIT_TENANT_CONFIG` is absent or unreadable, the
entrypoint emits a warning and continues into the plugin's **fail-closed**
default policy. Unknown tool calls therefore require approval rather than being
silently permitted.

For a managed customer deployment, treat the warning as a provisioning failure
and repair the mount before accepting traffic.

---

## Validation gate before merge or production promotion

Do not promote solely because the image builds.

### Python regression suite

```bash
pytest -q \
  tests/test_aait_policy.py \
  tests/test_aait_approvals.py \
  tests/test_aait_runtime.py
```

### Docker build

```bash
docker build --pull -t aait-hermes:pr-test .
```

### Container smoke

Validate all of the following manually or from a host-side script:

1. image starts normally with `AAIT_RUNTIME_ENABLED=0`;
2. enabling AAIT persists `aait-runtime` in Hermes config;
3. `/aait status` resolves the mounted tenant policy;
4. `automatic` action executes without approval;
5. `approval` action returns an approval ID;
6. `/aait approve <id>` permits only the exact retry once;
7. mutating any argument after approval produces a fresh approval requirement;
8. `forbidden` action never dispatches;
9. container restart preserves approval/audit state under `/opt/data/aait`;
10. audit JSONL contains metadata and argument names, but not argument values;
11. an unreadable/missing tenant policy does not create an allow-all state;
12. normal non-AAIT Hermes container usage remains unchanged when AAIT is off.

### Security/adversarial gate before customer rollout

Before attaching real Gmail/Calendar write connectors, add and pass tests for:

- prompt injection attempting to bypass policy;
- cross-tenant approval reuse;
- cross-session approval reuse;
- replay of consumed approval IDs;
- duplicate tool dispatch/idempotency;
- provider timeout/failover during write preparation;
- malicious connector arguments containing secret-like values;
- expired Google/OAuth credentials;
- abrupt container restart between approval and execution.

---

## Upgrade and rollback policy

Commercial deployments should pin an AAIT-tested image revision. Never deploy
upstream `main` directly to customers.

Recommended promotion path:

```text
Nous/Hermes upstream
        |
        v
AAIT integration branch
        |
        v
AAIT regression + container smoke
        |
        v
immutable tested image tag/digest
        |
        v
staging customer
        |
        v
production customers
```

Keep the mutable state volume separate from the image so rollback is an image
change, not a customer-data migration. Back up `HERMES_HOME/aait` and any
future AAIT-owned workflow/memory stores independently from application source.

For irreversible connectors, use idempotency keys so a retry or provider
failover cannot send the same email, booking, payment, or external mutation
more than once.

---

## Data ownership direction

Hermes may continue to maintain engine/session state, but the commercial
product should treat these AAIT-controlled stores as authoritative over time:

- tenant configuration;
- approvals and audit history;
- connector credentials/tokens via a secrets broker;
- workflow definitions;
- schedules;
- long-lived customer memory;
- usage and billing records.

This keeps a future Hermes replacement from becoming a customer-data migration.

---

## Downstream strategy

Keep the downstream delta thin:

```text
Nous/Hermes upstream
        |
        v
AAIT tested engine revision
        |
        +--> aait_runtime package
        +--> aait-runtime plugin
        +--> AAIT connectors
        +--> AAIT skills/workflows
        +--> AAIT evals
```

Replace an upstream component only when a measurable commercial constraint
requires it: security, reliability, latency, maintainability, capability, or
cost. Do not rewrite the general agent loop merely to own more code.

---

## Next milestones

1. implement Gmail and Google Calendar behind stable `aait.*` connector names;
2. render approval requests as Telegram buttons while retaining `/aait` fallback;
3. add connector idempotency keys for all irreversible writes;
4. add per-tenant model budgets and provider health/failover telemetry;
5. move schedules/workflows to an AAIT-owned store;
6. add an AAIT secrets broker and credential rotation path;
7. connect MissedCallZero lead intake to the same policy boundary;
8. build adversarial prompt-injection and cross-tenant isolation evals.
