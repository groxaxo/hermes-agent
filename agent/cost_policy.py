"""Purpose routing and budget policy helpers for autonomy workflows.

This module is intentionally side-effect free.  It does not mutate active model
clients or interrupt in-flight turns; callers use it at task boundaries
(delegate/background/cron/team spawn) to annotate work and choose safe defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional

VALID_PURPOSES = frozenset(
    {"general", "research", "code", "review", "test", "plan", "summarize", "execute"}
)

_PURPOSE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "research": ("research", "search", "investigate", "compare", "source", "paper", "web"),
    "code": ("implement", "code", "fix", "refactor", "function", "class", "bug", "patch"),
    "review": ("review", "audit", "critique", "inspect", "pr", "pull request"),
    "test": ("test", "pytest", "unit", "integration", "coverage", "verify"),
    "plan": ("plan", "design", "roadmap", "architecture", "proposal"),
    "summarize": ("summarize", "summary", "digest", "recap", "brief"),
    "execute": ("run", "execute", "deploy", "install", "terminal", "command"),
}


class BudgetMode(str, Enum):
    ALERT = "alert"
    PAUSE = "pause"
    DOWNGRADE = "downgrade"


@dataclass(frozen=True)
class BudgetDecision:
    ok: bool
    mode: BudgetMode
    reason: str = ""
    budget_usd: Optional[float] = None
    spent_usd: float = 0.0
    warning: bool = False


@dataclass(frozen=True)
class PurposeRoute:
    purpose: str
    provider: Optional[str] = None
    model: Optional[str] = None
    reasoning_effort: Optional[str] = None
    timeout_seconds: Optional[float] = None
    budget_usd: Optional[float] = None
    toolsets: Optional[list[str]] = None


def infer_purpose(text: str | None, *, default: str = "general") -> str:
    """Infer a coarse task purpose from natural language.

    The classifier is deliberately transparent and deterministic; it is used
    for routing metadata, not security decisions.
    """
    haystack = (text or "").strip().lower()
    if not haystack:
        return normalize_purpose(default)
    for purpose, keywords in _PURPOSE_KEYWORDS.items():
        if any(k in haystack for k in keywords):
            return purpose
    return normalize_purpose(default)


def normalize_purpose(value: str | None, *, default: str = "general") -> str:
    purpose = (value or default or "general").strip().lower().replace("-", "_")
    if purpose in ("coding", "debug", "debugging"):
        purpose = "code"
    if purpose in ("analysis", "analyze"):
        purpose = "research"
    if purpose not in VALID_PURPOSES:
        return default if default in VALID_PURPOSES else "general"
    return purpose


def _as_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def resolve_budget_usd(
    config: Mapping[str, Any] | None,
    *,
    purpose: str | None = None,
    explicit_budget_usd: Any = None,
    kind: str = "task",
) -> Optional[float]:
    """Resolve an effective budget for a task/subagent/cron boundary."""
    explicit = _as_float(explicit_budget_usd)
    if explicit is not None:
        return explicit
    cfg = _mapping(config)
    policy = _mapping(cfg.get("cost_policy"))
    purpose = normalize_purpose(purpose)
    purpose_budgets = _mapping(policy.get("purpose_budgets"))
    from_purpose = _as_float(purpose_budgets.get(purpose))
    if from_purpose is not None:
        return from_purpose
    kind_key = f"default_{kind}_budget_usd"
    from_kind = _as_float(policy.get(kind_key))
    if from_kind is not None:
        return from_kind
    return _as_float(policy.get("default_task_budget_usd"))


def resolve_purpose_route(
    config: Mapping[str, Any] | None,
    *,
    purpose: str | None,
    current_provider: str | None = None,
    current_model: str | None = None,
) -> PurposeRoute:
    """Resolve optional provider/model/tool defaults for *purpose*.

    Disabled routing returns a route that preserves the current provider/model.
    """
    cfg = _mapping(config)
    purpose = normalize_purpose(purpose)
    routing = _mapping(cfg.get("purpose_routing"))
    if not bool(routing.get("enabled", False)):
        return PurposeRoute(purpose=purpose, provider=current_provider, model=current_model)
    purposes = _mapping(routing.get("purposes"))
    entry = _mapping(purposes.get(purpose)) or _mapping(purposes.get("general"))
    toolsets = entry.get("toolsets")
    return PurposeRoute(
        purpose=purpose,
        provider=entry.get("provider") or current_provider,
        model=entry.get("model") or current_model,
        reasoning_effort=entry.get("reasoning_effort"),
        timeout_seconds=_as_float(entry.get("timeout_seconds")),
        budget_usd=_as_float(entry.get("budget_usd")),
        toolsets=list(toolsets) if isinstance(toolsets, list) else None,
    )


def budget_decision(
    *,
    spent_usd: Any,
    budget_usd: Any,
    mode: str | None = None,
    warning_threshold: float = 0.8,
) -> BudgetDecision:
    """Return a deterministic budget decision for completed spend."""
    spent = _as_float(spent_usd) or 0.0
    budget = _as_float(budget_usd)
    try:
        mode_enum = BudgetMode(mode or BudgetMode.ALERT.value)
    except ValueError:
        mode_enum = BudgetMode.ALERT
    if budget is None or budget == 0:
        return BudgetDecision(ok=True, mode=mode_enum, budget_usd=budget, spent_usd=spent)
    warning = spent >= budget * max(0.0, min(float(warning_threshold), 1.0))
    if spent <= budget:
        return BudgetDecision(ok=True, mode=mode_enum, budget_usd=budget, spent_usd=spent, warning=warning)
    return BudgetDecision(
        ok=False,
        mode=mode_enum,
        budget_usd=budget,
        spent_usd=spent,
        warning=True,
        reason=f"budget exceeded: spent ${spent:.4f} of ${budget:.4f}",
    )


def find_downgrade_model(config: Mapping[str, Any] | None, current_model: str | None) -> Optional[str]:
    """Return a configured downgrade model for *current_model*, if any."""
    if not current_model:
        return None
    tiers = _mapping(_mapping(config).get("cost_policy")).get("downgrade_tiers")
    tiers = _mapping(tiers)
    candidate = tiers.get(current_model)
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    if isinstance(candidate, list):
        for item in candidate:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return None
