# Zoey Mini — native Hermes companion profile

Zoey is a fictional adult West Auckland woman with natural NZ English,
automatic language adaptation and four native /personality options:
spicy (default), sweet, chaos, and focus.

Install from the root of the groxaxo/hermes-agent fork using a modern
Hermes binary with distribution support:

    hermes profile install ./distributions/zoey --name zoey -y
    hermes -p zoey chat

The distribution contains only SOUL.md, config.yaml and its manifest.
No bot tokens, private memories, model weights, plugins, extra skills or
scheduled jobs are included. Configure the inference provider separately in
the private installed profile. When updating, Hermes normally preserves the
private config; changing personality definitions requires explicitly
reapplying the reviewed new config.

For the private standalone project, hardened Debian 13 KVM VM deployment
and API-only GPU connection, see:
https://github.com/groxaxo/hermes-wifey (owner access required).
The VM calls http://100.85.200.51:12434/v1; it has no passed-through GPUs.
