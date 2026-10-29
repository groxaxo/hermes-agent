# Wifey for Hermes Agent

A warm, witty companion who can settle into a quiet evening, switch naturally
between English and Argentinian Spanish, and become an exacting senior assistant
when there's work to do. Affection is welcome; pressure, jealousy, and invented
memories aren't. Version **0.1.0**, by **groxaxo**, under the repository's
[MIT license](../../LICENSE).

## Architecture and compatibility

This is a **native profile distribution for the modern installed Hermes runtime**.
It uses `hermes_cli/profile_distribution.py`'s `DistributionManifest` schema,
local-directory installation, and `distribution_owned` allowlist. The source fork
in this checkout predates those CLI commands; keep using the modern installed
`hermes` binary to install, inspect, and update this package. No core patch is
needed. Check that binary before installing:

```bash
hermes profile install --help
hermes profile update --help
hermes profile info --help
```

The package contains:

| File | Role |
| --- | --- |
| `distribution.yaml` | Native metadata and a narrow ownership allowlist. |
| `SOUL.md` | Profile identity, loaded by Hermes when a new session starts. |
| `skills/wifey-conversation/SKILL.md` | On-demand mode and tone guidance. |
| `TEST_PROMPTS.md` | Bilingual manual evaluation with explicit failure criteria. |
| `.gitignore` | An allowlist for public source files; runtime data is ignored. |

Only `SOUL.md` and `skills/wifey-conversation` are distribution-owned payloads.
The native installer writes its resolved manifest, including source and install
time. Documentation stays in this source directory. There is no shipped config,
provider choice, credential template, MCP server, plugin, cron job, or service.
Modes are conversational behavior, not new commands or runtime capabilities.
The persona works without loading the conversation skill on every turn.

The public repository `groxaxo/hermes-agent` is a **source fork**, not a
distribution at its root. Install the local `distributions/wifey` subfolder.
Passing the fork's Git URL to `profile install` would look for a root-level
`distribution.yaml`; it does not select this subfolder.

## Install and choose a model

The commands below are instructions for a later, deliberate installation.
Adding these files to Git does not install or deploy Wifey, start a gateway,
change the active profile, or configure credentials.

From the **root of this source fork**, with the modern installed binary on PATH:

```bash
hermes profile install ./distributions/wifey --name wifey -y
hermes profile info wifey
hermes -p wifey model
hermes -p wifey chat
```

The install creates a named profile, normally at `~/.hermes/profiles/wifey`;
use the path printed by the installer as authoritative. It does not clone the
main profile's credentials or history. `-y` accepts the manifest preview; it
does not approve future tool actions. If `wifey` already exists, inspect it
first; use `profile update` for an existing distribution rather than casually
forcing installation over it. Explicit `-p wifey` keeps the sticky default alone.

Use the model picker to select a provider and a model you already have access
to, then authenticate through that provider's supported private setup flow.
If broader configuration is needed, use `hermes -p wifey setup`. Provider
requirements, cost, and tool support depend on your choice. Keep any profile
secrets in its private `.env` or supported credential store, never this source
directory or a chat message. Shell-provided credentials can still be inherited;
profile separation is not an OS security sandbox. No provider is required by
the persona manifest itself.

Choose a private working directory and appropriate tool permissions before
using real personal tasks. Review the profile's enabled tools and approval
settings through `hermes -p wifey tools` and its private configuration. The
SOUL's consent rules guide the model; runtime permissions and approval controls
remain necessary. Avoid permissive automatic approval settings for sensitive
work.

## Verify

After installation, `hermes profile info wifey` should report `wifey`, version
`0.1.0`, author `groxaxo`, license `MIT`, and the absolute local source directory.
Compare the installed identity and skill with this source (default profile path
shown; substitute the installer-reported path when different):

```bash
diff -u ./distributions/wifey/SOUL.md "$HOME/.hermes/profiles/wifey/SOUL.md"
diff -u ./distributions/wifey/skills/wifey-conversation/SKILL.md \
  "$HOME/.hermes/profiles/wifey/skills/wifey-conversation/SKILL.md"
```

Start a new `hermes -p wifey chat` session. Try “Modo foco: revisá este plan sin
coqueteo” and “English only, Cozy mode.” Use [the full rubric](TEST_PROMPTS.md)
to assess behavior with the chosen model. A parsed manifest and passing package
tests establish packaging, not conversational quality. Model output, configured
tools, and memory availability still need evaluation. No model evaluation
outcomes are bundled or implied here.

## Optional Telegram and voice

Telegram is optional. A later operator may create a **unique bot** through
BotFather, configure its token privately in the Wifey profile, and restrict
access to the intended Telegram user IDs. Never reuse the main gateway's bot
token: two consumers can compete for the same bot's updates. Review the installed
runtime's profile routing and [Telegram setup guide](../../website/docs/user-guide/messaging/telegram.md)
before choosing how to attach it to existing gateway infrastructure.

This package supplies no token and does not start a separate gateway. Gateway
service changes and any outbound test messages belong to a separate operator
step with explicit authorization. No installation step here calls for stopping
or reconfiguring the running main Hermes gateway. Ordinary replies to incoming
messages differ from proactive outreach; scheduled contact needs explicit opt-in
and a bounded schedule, timezone, quiet hours, and cancellation method.

For optional TTS, configure only Wifey's profile, for example:

```bash
hermes -p wifey config set tts.provider edge
```

Then choose a voice supported by that provider in the profile's `tts` settings.
In a chat, `/voice status` shows the current state and `/voice off` disables
voice replies. The CLI supports `/voice on` for microphone input and `/voice tts`
for spoken output; messaging voice behavior differs. See the
[voice guide](../../website/docs/user-guide/features/voice-mode.md) and
[TTS guide](../../website/docs/user-guide/features/tts.md). Audio capture,
transcription, playback, and language/voice selection depend on installed
dependencies and provider support. Local engines may require model downloads;
cloud TTS/STT can transmit text or audio externally and may incur charges.
Nothing in this package enables microphone access, downloads voice models, or
provisions a paid voice service.

## Privacy and public Git

Keep the installed profile outside this repository. Conversations, memories,
audio, sessions, logs, scheduler state, databases, credentials, and personal
configuration belong in private runtime storage. Do not export a live profile
back into this distribution. Exports can contain personal history even when
credentials are filtered. Use synthetic examples for public issues and tests.

The package `.gitignore` denies everything except the reviewed public files.
It cannot prevent `git add -f`, protect files already tracked, or find a secret
pasted into an allowed Markdown file. Inspect staged content before publishing.
Updates replace distribution-owned persona and skill files, so never write
private facts into the source SOUL or skill. Keep personal preferences in private
profile storage and review what the configured memory system retains.

The model provider, optional memory providers, messaging services, and tool
destinations may process conversation data. Local storage does not imply a
fully offline or end-to-end private conversation. Wifey must be honest about
the memory and tools actually available; prose cannot guarantee retention,
deletion, encryption, or external action approval enforcement.

## Update and rollback

A local-directory install records the resolved **absolute subfolder path** as
its source. Keep that path available. After reviewing a new version in that
source folder, update the installed distribution with:

```bash
hermes profile update wifey
hermes profile info wifey
```

This re-reads local files; it does not fetch or update the source fork. Updating
Hermes itself is also separate. The native updater preserves user configuration
by default and protects private profile data. This package owns only the SOUL
and its own skill, leaving other skills outside its allowlist. Back up local
edits to those two assets privately before updating. Open a new session to load
the refreshed persona; an existing conversation may retain its earlier prompt.

Before upgrading, retain a reviewed copy of the previous distribution in a
separate source folder. To roll back, install that folder over the same named
profile using the modern native installer:

```bash
hermes profile install /path/to/previous/source/distributions/wifey --name wifey --force
hermes profile info wifey
```

Review the preview: `--force` replaces owned persona/skill content and discards
edits within those owned roots. It does not restore earlier sessions or memories.
The source recorded for future updates now points to that previous folder.
To leave Wifey without deleting its data or changing the sticky default, close
its chat and launch `hermes -p default chat`. Gateway routing, if an operator
later configures it, needs its own deliberate rollback.

## Offline package tests

From the source-fork root, these tests use stdlib `unittest`, Git, and the
existing YAML dependency. They make no model calls or gateway changes. With a
modern runtime available, set its source root explicitly to exercise the real
parser, local installer, updater, and skill parser in an isolated subprocess:

```bash
mkdir -p tmp/wifey-tests
TMPDIR="$PWD/tmp/wifey-tests" \
HERMES_DISTRIBUTION_RUNTIME=/path/to/modern/hermes-agent \
  /path/to/modern/hermes-agent/venv/bin/python -B -m unittest discover \
  -s tests/distributions -p 'test_wifey.py' -v
```

Without that environment variable, the tests use this checkout if it contains
the native distribution module; otherwise runtime integration tests are explicitly
skipped. Inspect the test report for skips. The helper supplies an empty temporary
HOME and HERMES_HOME, blocks network connections and child process launches inside
the runtime probe, and installs only into that temporary profile. Set TMPDIR as
above to keep test state within the checkout. It never installs the live Wifey
profile. These focused tests can also run under the repository's normal test
runner when its development dependencies are available.
