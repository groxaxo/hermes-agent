from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatchcase
from typing import Any, Iterable, Mapping


class ActionMode(str, Enum):
    """How AAIT should treat a proposed tool action."""

    AUTOMATIC = "automatic"
    APPROVAL = "approval"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True)
class PolicyRule:
    pattern: str
    mode: ActionMode
    description: str = ""


@dataclass(frozen=True)
class PolicyDecision:
    mode: ActionMode
    action_name: str
    matched_pattern: str | None = None
    description: str = ""


_OPERATION_KEYS = ("operation", "action", "method", "verb")


def resolve_action_name(tool_name: str, args: Mapping[str, Any] | None = None) -> str:
    """Resolve a stable policy name from a Hermes tool call.

    AAIT connectors should expose explicit tool names such as
    ``aait.gmail.send``.  For generic dispatcher tools we also inspect a small
    set of conventional operation keys, producing e.g. ``google.gmail_send``.
    The raw operation is only accepted when it is a short simple identifier.
    """

    base = (tool_name or "unknown").strip() or "unknown"
    if not isinstance(args, Mapping):
        return base

    for key in _OPERATION_KEYS:
        value = args.get(key)
        if not isinstance(value, str):
            continue
        op = value.strip().lower().replace(" ", "_")
        if op and len(op) <= 96 and all(ch.isalnum() or ch in "._:-/" for ch in op):
            return f"{base}.{op}"
    return base


@dataclass(frozen=True)
class TenantPolicy:
    """Ordered, fail-closed policy for one commercial tenant."""

    tenant_id: str = "local"
    default_mode: ActionMode = ActionMode.APPROVAL
    approval_ttl_seconds: int = 900
    rules: tuple[PolicyRule, ...] = field(default_factory=tuple)

    def decide(self, tool_name: str, args: Mapping[str, Any] | None = None) -> PolicyDecision:
        action_name = resolve_action_name(tool_name, args)
        for rule in self.rules:
            if fnmatchcase(action_name, rule.pattern) or fnmatchcase(tool_name, rule.pattern):
                return PolicyDecision(
                    mode=rule.mode,
                    action_name=action_name,
                    matched_pattern=rule.pattern,
                    description=rule.description,
                )
        return PolicyDecision(mode=self.default_mode, action_name=action_name)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "TenantPolicy":
        data = data or {}
        raw_rules = data.get("rules", [])
        rules: list[PolicyRule] = []
        if isinstance(raw_rules, Iterable) and not isinstance(raw_rules, (str, bytes, Mapping)):
            for item in raw_rules:
                if not isinstance(item, Mapping):
                    continue
                pattern = str(item.get("match", "")).strip()
                if not pattern:
                    continue
                try:
                    mode = ActionMode(str(item.get("mode", "approval")).strip().lower())
                except ValueError as exc:
                    raise ValueError(f"Invalid AAIT policy mode for {pattern!r}") from exc
                rules.append(
                    PolicyRule(
                        pattern=pattern,
                        mode=mode,
                        description=str(item.get("description", "") or ""),
                    )
                )

        try:
            default_mode = ActionMode(str(data.get("default_mode", "approval")).strip().lower())
        except ValueError as exc:
            raise ValueError("Invalid AAIT default_mode") from exc

        ttl = int(data.get("approval_ttl_seconds", 900))
        if ttl < 30 or ttl > 86400:
            raise ValueError("approval_ttl_seconds must be between 30 and 86400")

        return cls(
            tenant_id=str(data.get("tenant_id", "local") or "local"),
            default_mode=default_mode,
            approval_ttl_seconds=ttl,
            rules=tuple(rules),
        )
