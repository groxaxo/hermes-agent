---
sidebar_position: 6
title: "Use MCP with Hermes"
description: "A practical guide to connecting MCP servers to Hermes Agent, filtering their tools, and using them safely in real workflows"
---

# Use MCP with Hermes

This guide shows how to actually use MCP with Hermes Agent in day-to-day workflows.

If the feature page explains what MCP is, this guide is about how to get value from it quickly and safely.

## When should you use MCP?

Use MCP when:
- a tool already exists in MCP form and you do not want to build a native Hermes tool
- you want Hermes to operate against a local or remote system through a clean RPC layer
- you want fine-grained per-server exposure control
- you want to connect Hermes to internal APIs, databases, or company systems without modifying Hermes core

Do not use MCP when:
- a built-in Hermes tool already solves the job well
- the server exposes a huge dangerous tool surface and you are not prepared to filter it
- you only need one very narrow integration and a native tool would be simpler and safer

## Mental model

Think of MCP as an adapter layer:

- Hermes remains the agent
- MCP servers contribute tools
- Hermes discovers those tools at startup or reload time
- the model can use them like normal tools
- you control how much of each server is visible

That last part matters. Good MCP usage is not just “connect everything.” It is “connect the right thing, with the smallest useful surface.”

## Step 1: install MCP support

If you installed Hermes with the standard install script, MCP support is already included (the installer runs `uv pip install -e ".[all]"`).

If you installed without extras and need to add MCP separately:

```bash
cd ~/.hermes/hermes-agent
uv pip install -e ".[mcp]"
```

For npm-based servers, make sure Node.js and `npx` are available.

For many Python MCP servers, `uvx` is a nice default.

## Step 2: add one server first

Start with a single, safe server.

Example: filesystem access to one project directory only.

```yaml
mcp_servers:
  project_fs:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/my-project"]
```

Then start Hermes:

```bash
hermes chat
```

Now ask something concrete:

```text
Inspect this project and summarize the repo layout.
```

## Step 3: verify MCP loaded

You can verify MCP in a few ways:

- Hermes banner/status should show MCP integration when configured
- ask Hermes what tools it has available
- use `/reload-mcp` after config changes
- check logs if the server failed to connect

A practical test prompt:

```text
Tell me which MCP-backed tools are available right now.
```

## Step 4: start filtering immediately

Do not wait until later if the server exposes a lot of tools.

### Example: whitelist only what you want

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "***"
    tools:
      include: [list_issues, create_issue, search_code]
```

This is usually the best default for sensitive systems.

## Default user Chrome: groxaxo/mcp-chrome-patched

Hermes' recommended MCP path for controlling your real signed-in Chrome session is [groxaxo/mcp-chrome-patched](https://github.com/groxaxo/mcp-chrome-patched). This is the user's own maintained fork/branch of the Chrome MCP bridge, with English documentation, Docker/native-server improvements, and a broader automation toolset than the older examples in this guide.

Install the native bridge and register its Chrome native messaging host:

```bash
npm install -g mcp-chrome-bridge
mcp-chrome-bridge register
mcp-chrome-bridge doctor
```

Then add the safe Hermes preset:

```bash
hermes mcp add chrome --preset chrome
```

That preset points to the bridge's shared local MCP endpoint:

```yaml
mcp_servers:
  chrome:
    url: "http://127.0.0.1:12306/mcp"
    connect_timeout: 20
    timeout: 120
    tools:
      include:
        - get_windows_and_tabs
        - chrome_switch_tab
        - chrome_navigate
        - chrome_screenshot
        - chrome_read_page
        - chrome_dismiss_cookie_banners
        - chrome_click_element
        - chrome_fill_or_select
        - chrome_request_element_selection
        - chrome_keyboard
        - chrome_get_web_content
        - extract_clean_content
        - chrome_handle_dialog
      resources: false
      prompts: false
```

The default preset intentionally does **not** expose high-risk browser tools such as arbitrary JavaScript, console/network capture, history, bookmark mutation, downloads/uploads, tab closing, broad `chrome_computer` control, or performance/GIF artifact capture.

If you intentionally want every tool from the patched bridge:

```bash
hermes mcp add chrome --preset chrome-full
```

If you cannot use HTTP MCP in your environment, use the stdio fallback:

```bash
hermes mcp add chrome --preset chrome-stdio
```

The stdio fallback uses the installed `mcp-chrome-stdio` binary and keeps the same safe allowlist.

:::warning Real-browser access
Patched Chrome MCP runs against your real Chrome profile. Exposed tools can interact with logged-in sites and read visible page content. Keep the safe preset unless you need more, and do not expose the local MCP endpoint outside your machine without the bridge's API key support and firewall controls.
:::

### Typical prompt

Once loaded, Hermes can use the MCP-prefixed Chrome tools directly. For example:

```text
Use the chrome MCP tools to list my current Chrome tabs, open the project dashboard, and summarize the visible errors without changing anything.
```

## WSL2: Hermes to Windows Chrome

This setup applies when:

- Hermes runs inside WSL2
- the browser you want to control is your normal signed-in Chrome on Windows
- `/browser connect` is awkward or unreliable from WSL

The patched Chrome native messaging host must be installed and registered on the same OS/user profile that runs Chrome. If Chrome runs on Windows, install `groxaxo/mcp-chrome-patched` on Windows, not only inside WSL.

Recommended same-machine pattern:

- Hermes runs in WSL
- Chrome, the extension, and the native bridge run on Windows
- Hermes connects to the bridge's MCP endpoint
- the bridge protects any non-local exposure with an API key and Windows Firewall rules

Mental model:

```text
Hermes (WSL) -> patched Chrome MCP endpoint -> Windows native host -> Windows Chrome
```

If WSL can reach the Windows bridge endpoint, add it directly:

```yaml
mcp_servers:
  chrome:
    url: "http://<windows-host-ip>:12306/mcp"
    headers:
      Authorization: "Bearer ${CHROME_MCP_API_KEY}"
    tools:
      include: [get_windows_and_tabs, chrome_read_page, chrome_screenshot]
      resources: false
      prompts: false
```

Store `CHROME_MCP_API_KEY` in `~/.hermes/.env`, not in `config.yaml`.

After saving the server:

```bash
hermes mcp test chrome
```

Then start a fresh Hermes session or run:

```text
/reload-mcp
```

### When `/browser connect` is the wrong tool

If Hermes runs in WSL and Chrome runs on Windows, `/browser connect` may fail even though Chrome is open and debuggable.

Common reasons:

- WSL cannot reach the same host-local endpoint Chrome exposes to Windows tools
- newer Chrome live-debugging flows are not the same as a classic `ws://localhost:9222`
- the browser is easier to attach to from a Windows-side helper such as `groxaxo/mcp-chrome-patched`

In those cases, keep `/browser connect` for same-environment setups and use MCP for WSL-to-Windows browser bridging.

### Known pitfalls

- Do not install the native host only inside WSL if the Chrome extension runs on Windows; native messaging registration is OS-local.
- Do not bind the MCP endpoint to `0.0.0.0` without an API key and firewall rule.
- Prefer the safe `chrome` preset or an explicit allowlist for WSL; full browser control over a network boundary is easy to overexpose.

### Example: blacklist dangerous actions

```yaml
mcp_servers:
  stripe:
    url: "https://mcp.stripe.com"
    headers:
      Authorization: "Bearer ***"
    tools:
      exclude: [delete_customer, refund_payment]
```

### Example: disable utility wrappers too

```yaml
mcp_servers:
  docs:
    url: "https://mcp.docs.example.com"
    tools:
      prompts: false
      resources: false
```

## What does filtering actually affect?

There are two categories of MCP-exposed functionality in Hermes:

1. Server-native MCP tools
- filtered with:
  - `tools.include`
  - `tools.exclude`

2. Hermes-added utility wrappers
- filtered with:
  - `tools.resources`
  - `tools.prompts`

### Utility wrappers you may see

Resources:
- `list_resources`
- `read_resource`

Prompts:
- `list_prompts`
- `get_prompt`

These wrappers only appear if:
- your config allows them, and
- the MCP server session actually supports those capabilities

So Hermes will not pretend a server has resources/prompts if it does not.

## Common patterns

### Pattern 1: local project assistant

Use MCP for a repo-local filesystem or git server when you want Hermes to reason over a bounded workspace.

```yaml
mcp_servers:
  fs:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/project"]

  git:
    command: "uvx"
    args: ["mcp-server-git", "--repository", "/home/user/project"]
```

Good prompts:

```text
Review the project structure and identify where configuration lives.
```

```text
Check the local git state and summarize what changed recently.
```

### Pattern 2: GitHub triage assistant

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "***"
    tools:
      include: [list_issues, create_issue, update_issue, search_code]
      prompts: false
      resources: false
```

Good prompts:

```text
List open issues about MCP, cluster them by theme, and draft a high-quality issue for the most common bug.
```

```text
Search the repo for uses of _discover_and_register_server and explain how MCP tools are registered.
```

### Pattern 3: internal API assistant

```yaml
mcp_servers:
  internal_api:
    url: "https://mcp.internal.example.com"
    headers:
      Authorization: "Bearer ***"
    tools:
      include: [list_customers, get_customer, list_invoices]
      resources: false
      prompts: false
```

Good prompts:

```text
Look up customer ACME Corp and summarize recent invoice activity.
```

This is the sort of place where a strict whitelist is far better than an exclude list.

### Pattern 4: documentation / knowledge servers

Some MCP servers expose prompts or resources that are more like shared knowledge assets than direct actions.

```yaml
mcp_servers:
  docs:
    url: "https://mcp.docs.example.com"
    tools:
      prompts: true
      resources: true
```

Good prompts:

```text
List available MCP resources from the docs server, then read the onboarding guide and summarize it.
```

```text
List prompts exposed by the docs server and tell me which ones would help with incident response.
```

## Tutorial: end-to-end setup with filtering

Here is a practical progression.

### Phase 1: add GitHub MCP with a tight whitelist

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "***"
    tools:
      include: [list_issues, create_issue, search_code]
      prompts: false
      resources: false
```

Start Hermes and ask:

```text
Search the codebase for references to MCP and summarize the main integration points.
```

### Phase 2: expand only when needed

If you later need issue updates too:

```yaml
tools:
  include: [list_issues, create_issue, update_issue, search_code]
```

Then reload:

```text
/reload-mcp
```

### Phase 3: add a second server with different policy

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "***"
    tools:
      include: [list_issues, create_issue, update_issue, search_code]
      prompts: false
      resources: false

  filesystem:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/project"]
```

Now Hermes can combine them:

```text
Inspect the local project files, then create a GitHub issue summarizing the bug you find.
```

That is where MCP gets powerful: multi-system workflows without changing Hermes core.

## Safe usage recommendations

### Prefer allowlists for dangerous systems

For anything financial, customer-facing, or destructive:
- use `tools.include`
- start with the smallest set possible

### Disable unused utilities

If you do not want the model browsing server-provided resources/prompts, turn them off:

```yaml
tools:
  resources: false
  prompts: false
```

### Keep servers scoped narrowly

Examples:
- filesystem server rooted to one project dir, not your whole home directory
- git server pointed at one repo
- internal API server with read-heavy tool exposure by default

### Reload after config changes

```text
/reload-mcp
```

Do this after changing:
- include/exclude lists
- enabled flags
- resources/prompts toggles
- auth headers / env

## Troubleshooting by symptom

### "The server connects but the tools I expected are missing"

Possible causes:
- filtered by `tools.include`
- excluded by `tools.exclude`
- utility wrappers disabled via `resources: false` or `prompts: false`
- server does not actually support resources/prompts

### "The server is configured but nothing loads"

Check:
- `enabled: false` was not left in config
- command/runtime exists (`npx`, `uvx`, etc.)
- HTTP endpoint is reachable
- auth env or headers are correct

### "Why do I see fewer tools than the MCP server advertises?"

Because Hermes now respects your per-server policy and capability-aware registration. That is expected, and usually desirable.

### "How do I remove an MCP server without deleting the config?"

Use:

```yaml
enabled: false
```

That keeps the config around but prevents connection and registration.

## Recommended first MCP setups

Good first servers for most users:
- filesystem
- git
- GitHub
- fetch / documentation MCP servers
- one narrow internal API

Not-great first servers:
- giant business systems with lots of destructive actions and no filtering
- anything you do not understand well enough to constrain

## Related docs

- [MCP (Model Context Protocol)](/docs/user-guide/features/mcp)
- [FAQ](/docs/reference/faq)
- [Slash Commands](/docs/reference/slash-commands)
