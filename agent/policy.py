"""Additive toolset policy helpers for subagents and teams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class ToolsetPolicy:
    allow_toolsets: tuple[str, ...] = ()
    deny_toolsets: tuple[str, ...] = ()
    allow_tools: tuple[str, ...] = ()
    deny_tools: tuple[str, ...] = ()

    @classmethod
    def from_config(cls, cfg: Mapping | None) -> "ToolsetPolicy":
        cfg = cfg if isinstance(cfg, Mapping) else {}
        return cls(
            allow_toolsets=_tuple(cfg.get("allow_toolsets")),
            deny_toolsets=_tuple(cfg.get("deny_toolsets")),
            allow_tools=_tuple(cfg.get("allow_tools")),
            deny_tools=_tuple(cfg.get("deny_tools")),
        )


def _tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(str(v) for v in value if str(v).strip())
    return ()


def merge_policies(*policies: ToolsetPolicy | Mapping | None) -> ToolsetPolicy:
    allow_toolsets: list[str] = []
    deny_toolsets: list[str] = []
    allow_tools: list[str] = []
    deny_tools: list[str] = []
    for policy in policies:
        if policy is None:
            continue
        if not isinstance(policy, ToolsetPolicy):
            policy = ToolsetPolicy.from_config(policy)
        allow_toolsets.extend(policy.allow_toolsets)
        deny_toolsets.extend(policy.deny_toolsets)
        allow_tools.extend(policy.allow_tools)
        deny_tools.extend(policy.deny_tools)
    return ToolsetPolicy(
        allow_toolsets=_dedupe(allow_toolsets),
        deny_toolsets=_dedupe(deny_toolsets),
        allow_tools=_dedupe(allow_tools),
        deny_tools=_dedupe(deny_tools),
    )


def _dedupe(items: Sequence[str]) -> tuple[str, ...]:
    out: list[str] = []
    for item in items:
        if item not in out:
            out.append(item)
    return tuple(out)


def apply_toolset_policy(toolsets: Sequence[str], policy: ToolsetPolicy | Mapping | None) -> list[str]:
    """Apply allow/deny toolset constraints with deny taking precedence."""
    if not isinstance(policy, ToolsetPolicy):
        policy = ToolsetPolicy.from_config(policy)
    selected = list(toolsets or [])
    if policy.allow_toolsets:
        allow = set(policy.allow_toolsets)
        selected = [t for t in selected if t in allow]
    if policy.deny_toolsets:
        deny = set(policy.deny_toolsets)
        selected = [t for t in selected if t not in deny]
    return selected


def is_tool_allowed(tool_name: str, policy: ToolsetPolicy | Mapping | None) -> bool:
    """Check direct tool allow/deny rules. Deny always wins."""
    if not isinstance(policy, ToolsetPolicy):
        policy = ToolsetPolicy.from_config(policy)
    if tool_name in policy.deny_tools:
        return False
    if policy.allow_tools and tool_name not in policy.allow_tools:
        return False
    return True
