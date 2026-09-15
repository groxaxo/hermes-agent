# Auckland Automate IT commercial runtime

## Purpose

Hermes is the current **agent engine**. Auckland Automate IT (AAIT) owns the
commercial control boundary that must remain stable if the underlying model,
connector implementation, deployment method, or even the agent engine changes.

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
Hermes plugin hooks and deliberately avoids patching `run_agent.py`,
`model_tools.py`, gateway dispatch, or the core agent/tool loop.

---

## Security invariants

Every tool call is classified by an ordered per-tenant policy:

| Mode | Meaning |
| --- | --- |
| `automatic` | Tool may execute without an additional approval step. |
| `approval` | The exact proposed action must be approved once before dispatch. |
| `forbidden` | Tool must never execute. |

The tenant default is `approval`.

If AAIT is enabled and no policy is available, unmatched actions remain
approval-gated. Managed production deployments should go further and set
`AAIT_REQUIRE_TENANT_CONFIG=1`, which makes a missing or unreadable policy a
container-startup error.

A **present but malformed** policy is always treated as a startup validation
failure in the Docker path. The container must not accept traffic with a policy
file it cannot parse.

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

The approval record is never a blanket or time-window permission grant.

---

## Stable AAIT connector namespace

Commercial integrations should be exposed to policy through stable AAIT action
names rather than upstream-specific implementation names:

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
internal service, or future out-of-process connector service. Customer policy
should not need to change when that implementation changes.

> **Current scope:** this PR establishes the connector contract and policy
> boundary. Production Gmail, Calendar, Drive, and MissedCallZero connector
> implementations are follow-up milestones; this document does not imply they
> already exist.

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
vendor. `ProviderRouter` is the AAIT-owned routing contract; Hermes can continue
using its native provider stack as the execution implementation until a
measurable commercial reason exists to replace it.

---

## Runtime state and file permissions

AAIT mutable state lives beneath `HERMES_HOME/aait` only when AAIT is enabled:

```text
/opt/data/aait/
├── approvals.sqlite3
└── audit/
    └── YYYY-MM-DD.jsonl
```

The Docker bootstrap restricts the AAIT state directory to `0700`. The approval
store additionally restricts `approvals.sqlite3` to `0600` on POSIX systems.
This is defense in depth for persistent/bind-mounted customer state and does not
replace correct host ownership or encrypted storage where required.

For production Docker deployments, mount tenant policy separately and read-only:

```text
/run/secrets/aait-tenant.yaml
```

This keeps operator policy distinct from mutable approvals/audit state. No
customer policy, OAuth token, model API key, or connector credential is baked
into the image.

Operational logs, security audit metadata, conversation content, and secrets
remain separate data classes. AAIT audit records intentionally omit tool
argument values and tool result bodies.

---

# Docker deployment contract

## Image behavior

The repository Docker image guarantees:

- `aait_runtime` is installed in the Hermes Python environment;
- `plugins/aait-runtime/plugin.yaml` is included in the image;
- the plugin README, runtime document, example tenant policy, and
  `docker/SOUL.md` are retained despite the general Markdown ignore;
- image build fails if required AAIT/operator assets are omitted;
- AAIT is disabled by default;
- stock mode does **not** create `/opt/data/aait`;
- AAIT-enabled mode creates `/opt/data/aait` privately and verifies it is
  writable;
- plugin allow-list enablement is verified by real plugin discovery/load;
- `/aait` registration is required before startup continues;
- the selected tenant policy is parsed during startup;
- malformed policy aborts startup;
- production can require the policy mount with
  `AAIT_REQUIRE_TENANT_CONFIG=1`;
- no customer secrets are baked into the image.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `AAIT_RUNTIME_ENABLED` | `0` | Explicitly enables AAIT policy/approval enforcement. |
| `AAIT_REQUIRE_TENANT_CONFIG` | `0` | If truthy, missing/unreadable tenant policy aborts startup. Set to `1` for managed customer deployments. |
| `AAIT_TENANT_CONFIG` | `/run/secrets/aait-tenant.yaml` | Policy YAML read and validated at AAIT startup. |
| `HERMES_HOME` | `/opt/data` | Persistent Hermes + AAIT runtime state. |
| `HERMES_UID` | image default `10000` | Optional host UID remap handled by the existing entrypoint. |
| `HERMES_GID` | image default group | Optional host GID remap handled by the existing entrypoint. |

`AAIT_RUNTIME_ENABLED` and `AAIT_REQUIRE_TENANT_CONFIG` are deployment controls,
not secrets. Provider keys and OAuth credentials should use the existing Hermes
secret/config mechanisms until an AAIT secrets broker is implemented.

## Build

From the repository root:

```bash
docker build --pull -t aait-hermes:dev .
```

The build performs a static packaging gate for the AAIT Python package, plugin
manifest, plugin README, example policy, runtime document, and `docker/SOUL.md`.
This gate does **not** replace runtime connector/provider integration tests.

## Production-style run

Recommended host layout:

```text
/srv/aait/customer-001/
├── policy/
│   └── tenant.yaml
└── hermes-data/
```

Example:

```bash
docker run -d \
  --name aait-customer-001 \
  --restart unless-stopped \
  -e AAIT_RUNTIME_ENABLED=1 \
  -e AAIT_REQUIRE_TENANT_CONFIG=1 \
  -v /srv/aait/customer-001/hermes-data:/opt/data \
  -v /srv/aait/customer-001/policy/tenant.yaml:/run/secrets/aait-tenant.yaml:ro \
  aait-hermes:<tested-version> \
  gateway
```

Because `/run/secrets/aait-tenant.yaml` is the image default, the explicit
`AAIT_TENANT_CONFIG` variable is unnecessary in this standard layout. Set it
only when using a different read-only path.

Only publish network ports required by the selected Hermes surface. For
example, Telegram long polling does not require exposing an inbound Telegram
webhook port.

## Missing-policy modes

### Development / break-glass mode

With:

```text
AAIT_REQUIRE_TENANT_CONFIG=0
```

a missing policy is allowed to start, but unmatched actions remain in the
`approval` default. This is useful for local validation and recovery, not a
recommended steady-state managed-customer configuration.

### Managed production mode

With:

```text
AAIT_REQUIRE_TENANT_CONFIG=1
```

a missing or unreadable policy aborts startup before Hermes is launched. A
present but malformed policy also aborts startup because `/aait status` is
executed during entrypoint validation and forces policy parsing.

---

## Reproducible local validation

Run:

```bash
./scripts/validate_aait_docker.sh
```

The script deliberately makes **no model/provider API calls**. Container runtime
checks use `--network none` and validate:

1. Docker image build;
2. targeted AAIT pytest suite inside the built image;
3. AAIT-off stock behavior and absence of `/opt/data/aait`;
4. production-style AAIT activation using the default secret path;
5. persisted plugin enablement and actual plugin discovery/load;
6. `/aait` command registration;
7. mounted tenant-policy resolution;
8. `0700` AAIT state directory and `0600` approval database permissions on Linux;
9. optional missing-policy mode remains approval-gated;
10. strict production mode rejects a missing policy;
11. malformed tenant policy aborts startup.

After that gate passes, perform one real end-to-end tool smoke for each policy
state:

1. one `automatic` action;
2. one `approval` action, including an altered-arguments retry that must require
   a new approval;
3. one `forbidden` action that must never dispatch.

Also restart the container and verify approval/audit state persists under
`/opt/data/aait`.

### Security/adversarial gate before customer rollout

Before attaching real write-capable connectors, add and pass tests for:

- prompt injection attempting to bypass policy;
- cross-tenant approval reuse;
- cross-session approval reuse;
- replay of consumed approval IDs;
- duplicate tool dispatch/idempotency;
- provider timeout/failover during write preparation;
- malicious connector arguments containing secret-like values;
- expired OAuth credentials;
- abrupt container restart between approval and execution.

---

## Upgrade and rollback policy

Commercial deployments should pin an AAIT-tested immutable image tag/digest.
Never deploy upstream `main` directly to customers.

```text
Hermes upstream
      |
      v
AAIT integration branch
      |
      v
AAIT unit + Docker + adversarial validation
      |
      v
immutable image digest
      |
      v
staging tenant
      |
      v
production tenants
```

Keep mutable state outside the image so rollback is an image revision change,
not a customer-data migration. Back up `HERMES_HOME/aait` and future AAIT-owned
workflow/memory stores independently from application source.

For irreversible connectors, use idempotency keys so retry or provider failover
cannot send the same email, booking, payment, or other external mutation twice.

---

## Data ownership direction

Hermes may continue to maintain engine/session state, but the commercial product
should make these AAIT-controlled stores authoritative over time:

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
Hermes upstream
      |
      v
AAIT-tested engine revision
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
