# Auckland Automate IT runtime architecture

## Goal

Hermes is an agent engine, not the product boundary. Auckland Automate IT owns
the controls that must remain stable across engine and model changes:

```text
Customer / Telegram / API
          |
          v
+------------------------------+
| AAIT commercial boundary     |
|                              |
| tenant config                |
| policy + approvals           |
| audit                        |
| provider tiers               |
| connector contracts          |
| memory/scheduler ownership   |
+---------------+--------------+
                |
                v
        Hermes agent engine
                |
                v
       skills / tools / MCP
```

The first implementation ships as `plugins/aait-runtime` and uses Hermes's
supported lifecycle hooks. It does not modify the core conversation loop.

## Security model

Every tool call is classified by an ordered tenant policy:

- `automatic`: may execute without an additional prompt
- `approval`: exact action must be approved once before dispatch
- `forbidden`: never executes

The tenant default is `approval`. When the plugin is enabled and
`tenant.yaml` is missing, it therefore fails closed rather than silently
running tools.

### Exact-action approval

The approval digest is SHA-256 over canonical JSON containing:

```text
tenant_id + tool_name + full arguments
```

Only the digest and argument names are persisted. Argument values are not
written to the approval database or audit log.

An approval is:

1. tenant scoped
2. session scoped
3. bound to the exact action digest
4. time limited
5. atomically consumed once

Changing an email recipient/body, calendar time, filesystem target, payment
amount, or any other argument invalidates the approval.

## Stable AAIT connector namespace

New customer integrations should be presented to the policy layer through
stable names independent of upstream implementation details:

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

The connector implementation may use Google APIs, an MCP server, another
service, or later move outside the Hermes process. Customer policy does not
change.

## Provider abstraction

Product-facing configuration uses logical quality tiers:

```text
standard
advanced
maximum
```

Example mapping:

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
```

Customer workflows should never encode a vendor model name. `ProviderRouter`
is the stable AAIT contract; Hermes's native provider stack remains the
execution implementation until there is a concrete reason to replace it.

## Data ownership

Hermes may maintain session state for the engine, but the commercial product
should treat these AAIT-controlled stores as authoritative:

- tenant configuration
- approvals and audit history
- connector credentials/tokens (future secrets broker)
- workflow definitions
- schedules
- long-lived customer memory
- usage/billing records

This prevents an engine migration from becoming a customer-data migration.

## Logging policy

Operational logs, security audit logs, conversation content, and secrets are
different data classes.

The AAIT audit implementation currently records metadata only:

```json
{
  "event": "approval_required",
  "tenant_id": "customer-001",
  "tool_name": "aait.gmail.send",
  "action_hash": "...",
  "arg_keys": ["body", "subject", "to"]
}
```

It does not record the email body, recipient value, calendar description, tool
result, or secret values.

## Deployment policy

For commercial deployments:

1. pin an AAIT-tested Hermes revision/image; never deploy upstream `main`
2. run the AAIT regression suite before promoting an upstream update
3. keep customer configuration outside the image
4. use one tenant identity and isolated credentials per customer
5. prefer a client-owned or dedicated Ubuntu VPS for 24/7 service
6. back up AAIT state independently of Hermes source code
7. use idempotency keys inside connectors for irreversible actions

## Upgrade strategy

Keep the downstream delta thin:

```text
Nous/Hermes upstream
        |
        v
AAIT tested engine revision
        |
        +--> aait_runtime package
        +--> aait-runtime plugin
        +--> AAIT skills/connectors
        +--> AAIT evals
```

Only replace an upstream component when a measurable commercial constraint
requires it (security, reliability, latency, maintainability, or cost). Do not
rewrite the general agent loop merely to own more code.

## Next milestones

1. wrap Gmail and Google Calendar behind `aait.*` connector names
2. render approval requests as Telegram buttons while preserving slash fallback
3. add idempotency keys to all write connectors
4. add per-tenant model usage budgets and provider failover telemetry
5. move schedules/workflows to an AAIT-owned store
6. connect MissedCallZero lead intake to the same connector/policy boundary
7. build adversarial evals for prompt injection and cross-tenant isolation
