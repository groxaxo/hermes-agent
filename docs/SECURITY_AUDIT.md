# Security Audit — Telemetry & Data-Leak Analysis

**Scope:** hermes-agent codebase (full repository scan)  
**Focus:** Third-party telemetry SDKs, credential leakage in logs/on-disk artefacts,
outbound HTTP, web server authentication surfaces, gateway platform adapters  
**Result:** 1 Medium, 1 Low/Informational finding. Both remediated.

---

## Executive Summary

No third-party analytics or telemetry SDKs are present in the codebase. All
log handlers apply a comprehensive regex-based redaction filter before any
output is written. The one confirmed data-leak vulnerability was a medium-severity
issue where three separate code paths wrote trajectory/training-data JSONL files
to disk without first passing the content through the redaction engine. These paths
have been patched. A secondary low-severity finding about unauthenticated plugin
API routes was reviewed and accepted as intentional by design (localhost-only server).

---

## Scope & Methodology

| Area | Approach |
|------|----------|
| Third-party telemetry | Grep for SDK package names (mixpanel, amplitude, sentry, posthog, segment) across all Python and `package.json` dependencies |
| Outbound HTTP | Grep for `requests.get`, `httpx`, `aiohttp`, `urllib`, `curl` patterns across Python files |
| Log handling | Trace formatter chain from `hermes_logging.py` to handlers; read `agent/redact.py` in full |
| On-disk secrets | Trace all `open(..., "w")` / `json.dumps` / JSONL write paths in `agent/trajectory.py`, `batch_runner.py`, `run_agent.py` |
| Web server auth | Read all 60+ endpoints in `hermes_cli/web_server.py`; check CORS config, token middleware, WebSocket auth |
| Gateway adapters | Spot-check `hermes_cli/auth.py`, `hermes_cli/dingtalk_auth.py`, `hermes_cli/skills_hub.py`, `hermes_cli/banner.py` |

---

## Non-Findings (Confirmed Clean)

### No third-party analytics SDK
Search for `mixpanel`, `amplitude`, `sentry`, `posthog`, `segment` in all Python
source and `pyproject.toml` / `package.json` dependencies returned zero matches.
Hermes-agent does not phone home.

### Log redaction is comprehensive
`hermes_logging.py` applies `RedactingFormatter` (from `agent/redact.py`) to all
log handlers: rotating file handler (`agent.log`), error file handler
(`errors.log`), and the gateway handler. The formatter wraps every log record
before it is written.

`agent/redact.py` covers 15+ secret categories via regex:
- OpenAI / Anthropic / Google / Perplexity / Fal / HuggingFace / Replicate vendor-prefix keys
- GitHub classic and fine-grained PATs
- Slack `xoxb-` / `xoxp-` tokens
- ENV-variable assignment patterns (`KEY=value`)
- JSON key-value secret fields
- Authorization and X-API-Key headers
- Telegram bot tokens
- PEM private keys
- Database connection strings with userinfo
- JWTs
- URL query-string secrets (`?key=…`)
- URL userinfo (`user:pass@host`)
- Multipart/form-data bodies

### Update check sends no user data
`hermes_cli/banner.py` checks for a new version by running `git ls-remote` /
`git fetch` against the project's own GitHub repository. No user identity,
API keys, or conversation content is transmitted. Results are cached for 6 hours.

### Auth token fingerprinting uses one-way hash
`hermes_cli/auth.py` `_token_fingerprint()` hashes tokens with SHA-256 before
any logging. Raw token values never appear in log output.

### Skills Hub only calls GitHub API with user's own token
`hermes_cli/skills_hub.py` makes outbound requests only to `api.github.com`
using the user's own GitHub PAT. No third-party SaaS endpoints are involved.

### Web server authentication is robust
`hermes_cli/web_server.py` protects the dashboard with multiple defence-in-depth layers:

| Control | Implementation |
|---------|----------------|
| Session token entropy | `secrets.token_urlsafe(32)` — 256-bit ephemeral token per process |
| CORS | Restricted to `localhost` and `127.0.0.1` only |
| DNS rebinding protection | `host_header_middleware` validates `Host` header on every request |
| Constant-time comparison | `hmac.compare_digest` used in `_require_token()` |
| `/api/env/reveal` rate limit | 5 requests / 30 seconds |
| WebSocket authentication | All `/api/pty` and `/api/tui` WebSocket endpoints require the session token via query param |

---

## Findings

### MEDIUM-001 — Trajectory JSONL files written without redaction (FIXED)

**Severity:** Medium  
**Status:** Fixed in this audit  
**CWE:** CWE-312 (Cleartext Storage of Sensitive Information)

#### Description

Three separate write paths persisted conversation history to disk in JSONL or
JSON format without applying the redaction engine. A user who had run a shell
command that echoed a secret (e.g. `echo $OPENAI_API_KEY`) would have that
secret captured verbatim in the output file.

The feature is opt-in (`save_trajectories=False` is the default), but once
enabled the on-disk files were not protected.

#### Affected paths

| File | Scenario |
|------|----------|
| `agent/trajectory.py` `save_trajectory()` | All `save_trajectories=True` runs write `trajectory_samples.jsonl` / `failed_trajectories.jsonl` to CWD |
| `batch_runner.py` lines ~461–475 | Batch mode writes `batch_N.jsonl` files via a direct `json.dumps()` call that bypasses `save_trajectory()` |
| `run_agent.py` `save_sample` path | `--save_sample` flag writes `sample_<uuid>.json` to CWD via a direct `json.dumps()` call |

#### Root cause

The `save_trajectory()` helper in `agent/trajectory.py` was the intended
single-exit point for trajectory writes, but `batch_runner.py` and
`run_agent.py` both wrote JSONL directly without calling it. None of the
three paths applied `redact_sensitive_text()` before serialisation.

Additionally, `redact_sensitive_text()` has a global disable gate
(`_REDACT_ENABLED` snapshotted from `HERMES_REDACT_SECRETS` at import time).
Even calling it naively would have been wrong — trajectory files are durable
artefacts that must be protected regardless of the user's run-time redaction
preference.

#### Fix

**`agent/trajectory.py`** — Added `redact_trajectory_entry(obj)`, a
recursive helper that walks the full object tree (dicts, lists, strings) and
calls `redact_sensitive_text(s, force=True)` on every string value.
`force=True` bypasses `_REDACT_ENABLED` so protection is unconditional.
Applied `redact_trajectory_entry(entry)` inside `save_trajectory()` before
`json.dumps()`.

```python
def redact_trajectory_entry(obj: Any) -> Any:
    if isinstance(obj, str):
        return redact_sensitive_text(obj, force=True)
    if isinstance(obj, list):
        return [redact_trajectory_entry(item) for item in obj]
    if isinstance(obj, dict):
        return {k: redact_trajectory_entry(v) for k, v in obj.items()}
    return obj
```

**`batch_runner.py`** — Added `from agent.trajectory import redact_trajectory_entry`
import. Wrapped `trajectory_entry` with `redact_trajectory_entry()` before the
direct `json.dumps()` write.

**`run_agent.py`** — Added `redact_trajectory_entry` to the existing
`from agent.trajectory import …` block. Applied `redact_trajectory_entry(entry)`
before the `json.dumps()` write in the `save_sample` path.

**`.gitignore`** — Added entries to prevent trajectory output files from ever
being accidentally committed:
```
trajectory_samples.jsonl
failed_trajectories.jsonl
sample_*.json
batch_*.jsonl
```

#### Verification

12 new tests in `tests/agent/test_trajectory_redaction.py` cover:
- Recursive redaction of nested dicts/lists
- Plain string, list, and dict inputs
- OpenAI `sk-proj-` and GitHub PAT patterns
- ENV-assignment patterns in tool output
- `force=True` honoured even when `_REDACT_ENABLED=False`
- `save_trajectory()` integration: redacted output, valid JSONL structure,
  append mode, and the disabled-flag case

All 12 tests pass.

---

### LOW-001 / INFO — Plugin API routes exempt from authentication middleware (ACCEPTED)

**Severity:** Low / Informational  
**Status:** Accepted by design — no code change  
**CWE:** CWE-306 (Missing Authentication for Critical Function) — mitigated by network binding

#### Description

The authentication middleware in `hermes_cli/web_server.py` (line 228) exempts
all paths beginning with `/api/plugins/` from the session-token check:

```python
not path.startswith("/api/plugins/")
```

A request to any plugin-registered route therefore does not require the
`Authorization: Bearer <token>` header.

#### Assessment

This is intentional and self-documented. `plugins/kanban/dashboard/plugin_api.py`
lines 18–22 carry an explicit warning:

> "Plugin API routes are intentionally unauthenticated. The server is expected
> to be bound to localhost only. Do not expose with --host 0.0.0.0 unless you
> add your own authentication layer."

The server's CORS policy and DNS-rebinding `Host` header check together mean
that a cross-origin attacker (e.g. a malicious website) cannot reach these
routes from a browser. The risk surface is limited to processes already running
on the same machine.

#### Recommendation (accepted, no code change)

The existing warning in `plugin_api.py` is adequate. If in future a plugin
requires sensitive operations, it should either:
1. Opt back in to authentication by inspecting the `Authorization` header
   directly, or
2. The exemption list should be scoped per-plugin rather than a blanket prefix.

---

## Recommendations Summary

| # | Priority | Recommendation | Status |
|---|----------|----------------|--------|
| 1 | Medium | Apply recursive `redact_trajectory_entry(force=True)` to all on-disk trajectory writes | **Fixed** |
| 2 | Medium | Add trajectory output file patterns to `.gitignore` | **Fixed** |
| 3 | Low | Scope plugin API auth exemption per-plugin rather than blanket prefix | Accepted (future) |
| 4 | Info | Consider a developer-visible warning at `save_trajectories=True` startup that trajectories are redacted but the user should treat output files as sensitive | Open |
