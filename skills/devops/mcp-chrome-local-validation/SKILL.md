---
name: mcp-chrome-local-validation
description: "Safely validate groxaxo/mcp-chrome-patched on the user's Ubuntu workstation through its allowlisted GitHub-controlled local test bridge. Use for test, typecheck, build, regression, and hardware-local verification requests without GitHub Actions or arbitrary remote shell execution."
version: 1.0.0
metadata:
  hermes:
    tags: [mcp-chrome, testing, local-runner, github, vitest, jest, typecheck, build, devops]
---

# MCP Chrome Local Validation

Use this skill when the user asks Hermes to run, verify, reproduce, or diagnose tests for `groxaxo/mcp-chrome-patched` on the local Ubuntu workstation.

## Architecture

Keep the responsibilities separated:

1. **Hermes orchestrates**: select the smallest sufficient target, submit the request, read the result, diagnose failures, and recommend the next action.
2. **GLM-5.3 Max is the preferred reasoning profile** for diagnosis and planning when available.
3. **OpenCode is an optional implementation subagent** for code edits or repository investigation; it is not the authority that decides whether a test passed.
4. **The deterministic local-test bridge executes** only fixed allowlisted targets from `tools/local-test-bridge/targets.json` in isolated detached worktrees.

Do not replace the bridge with an LLM-generated shell command. Do not use GitHub Actions.

## Command Queue

Repository: `groxaxo/mcp-chrome-patched`

Queue issue: `#28` (`[Local Test Bridge] Ubuntu runner command queue`)

Submit exactly one JSON request under this marker:

````markdown
<!-- local-test-bridge:v1 -->
```json
{
  "requestId": "hermes-<date>-<short-purpose>-<unique-suffix>",
  "target": "extension:test:model-picker",
  "ref": "main",
  "timeoutSeconds": 900
}
```
````

Rules:

- `requestId` must be unique. Never reuse it for a rerun.
- Prefer a full 40-character commit SHA for release or merge verification.
- Use `main` only when the user explicitly wants current-head validation.
- Never place commands, shell fragments, environment variables, tokens, or secrets in the request.
- Accept results only from the bridge's result marker and matching `requestId`.
- One failing target does not justify running every target automatically; diagnose first.

## Allowlisted Targets

Choose the narrowest sufficient target:

| Target | Use when |
|---|---|
| `bridge:selftest` | Validate the command protocol and allowlist itself |
| `extension:test:model-picker` | Model registry, combobox, accessibility, or picker persistence changes |
| `extension:test:agent-state` | Request reducer, reconciliation, SSE, retry, or transport changes |
| `extension:test` | Full extension regression suite |
| `extension:typecheck` | Vue/TypeScript contract changes |
| `extension:build` | WXT/MV3 build and extension artifact invariants |
| `native:test` | Native-server Jest regressions |
| `native:typecheck` | Native TypeScript contracts |
| `native:build` | Native-host build output |
| `shared:build` | Shared package/API contract changes |
| `repo:test` | Combined native and extension test command |
| `repo:typecheck` | Workspace-wide typecheck |
| `repo:build` | Monorepo build excluding the special WASM target |

For a cross-layer change, use this default progression:

1. focused target,
2. affected package typecheck,
3. affected package build,
4. full regression target only after focused validation passes.

## Result Handling

The bridge updates one result comment with:

- `PASS`, `FAIL`, `TIMEOUT`, or `ABORTED`,
- resolved commit SHA,
- host identity,
- duration and exit code,
- failing step,
- bounded log tail,
- local full-log path.

When reading a result:

1. Confirm `requestId`, target, and resolved SHA match the request.
2. Treat a SHA mismatch as an invalid result, not a pass.
3. Distinguish assertion failures, type errors, build errors, dependency/install failures, and infrastructure timeouts.
4. Quote only the smallest load-bearing error excerpt.
5. Explain whether the failure is new, pre-existing, flaky, or infrastructural only when evidence supports that classification.
6. For `TIMEOUT`, do not simply increase the timeout. First determine whether the process made progress or wedged.
7. Never claim local validation succeeded until the bridge reports `PASS` for the intended SHA.

## Failure Workflow

For a product-code failure:

1. Identify the first causal error, not the last cascade message.
2. Inspect the exact tested commit.
3. Use OpenCode with GLM-5.3 Max only when code investigation or editing is required.
4. Request the smallest focused rerun with a new `requestId`.
5. Expand to typecheck/build/full regression after the focused target passes.

For an infrastructure failure:

- Check the bridge service and queue before changing product code.
- Do not edit product files to mask missing dependencies, an offline Git fetch, a dead runner, or a wedged external process.
- Preserve the distinction between `FAIL`, `TIMEOUT`, and `ABORTED`.

## Security Invariants

- Exact GitHub author allowlist.
- Exact target allowlist.
- No arbitrary command field.
- No `shell: true` execution.
- No GitHub Actions.
- No exposed inbound terminal or SSH service.
- No secrets in issue comments or result logs.
- Test subprocesses do not receive the GitHub bridge token.
- Requested commit SHAs must be reachable from a fetched remote branch.
- Untrusted third-party refs require review before local execution because repository test code runs as the local Linux user.

## Recommended Agent Routing

Use **Hermes + GLM-5.3 Max** as the default controller for this workflow because the job is multi-step orchestration: choose tests, monitor the queue, interpret evidence, and decide the next validation layer.

Delegate to **OpenCode + GLM-5.3 Max** when the task becomes repository implementation work requiring code navigation, edits, or targeted debugging. Return execution authority to the deterministic bridge for the final pass/fail result.

The preferred stack is therefore:

```text
Hermes orchestration
  -> OpenCode implementation/review when needed
  -> allowlisted local-test bridge execution
  -> Hermes evidence-based verdict
```
