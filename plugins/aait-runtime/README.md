# AAIT Runtime plugin

This plugin turns Hermes into a replaceable execution engine beneath an
Auckland Automate IT-owned policy boundary.

It deliberately does **not** fork or patch `run_agent.py`, `model_tools.py`, or
the gateway. It uses the supported plugin hooks instead.

## What is enforced now

- per-tenant ordered tool policy (`automatic`, `approval`, `forbidden`)
- fail-closed default when the plugin is enabled without a tenant policy
- exact-action SHA-256 approvals tied to tenant + session + tool + arguments
- single-use approval consumption with expiry
- SQLite approval state for restart safety
- metadata-only JSONL audit log (argument values and tool result bodies omitted)
- `/aait` status, approval, rejection and reload commands in CLI/gateway sessions

## Enable

The plugin is standalone and therefore opt-in:

```bash
hermes plugins enable aait-runtime
```

Copy `examples/aait/tenant.yaml` to:

```text
~/.hermes/aait/tenant.yaml
```

or set `AAIT_TENANT_CONFIG` to another YAML path.

Restart Hermes (or force plugin rediscovery) after first enabling it. Policy
changes can then be applied with:

```text
/aait reload
```

## Approval flow

When an action matches an `approval` rule, Hermes receives a blocking tool
result like:

```text
AAIT approval required for 'aait.gmail.send'.
Approval ID: apr_abc123...
```

The user approves it:

```text
/aait approve apr_abc123...
```

The exact same tool call may then be retried once. Any change to recipient,
body, time, amount, target, or another argument changes the action hash and
requires a new approval.

## State

```text
~/.hermes/aait/
├── tenant.yaml
├── approvals.sqlite3
└── audit/
    └── YYYY-MM-DD.jsonl
```

The approval DB stores tool name, argument **keys**, status and an action hash.
It does not persist the argument values. The audit log follows the same rule.

## Intended next layer

AAIT connectors should use stable action names such as:

```text
aait.gmail.search
aait.gmail.draft
aait.gmail.send
aait.calendar.read
aait.calendar.create
aait.calendar.cancel
aait.missedcallzero.lead.create
```

so policy stays independent of whichever agent engine performs the reasoning.
See `docs/aait-runtime.md`.
