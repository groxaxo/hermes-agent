"""Auckland Automate IT commercial runtime boundaries for Hermes.

This package intentionally sits beside Hermes core.  It contains the stable
contracts and enforcement primitives that AAIT owns (tenant policy, approvals,
audit, provider routing, connectors) while Hermes remains a replaceable agent
engine.
"""

from .approvals import ApprovalRecord, ApprovalStore, action_digest
from .policy import ActionMode, PolicyDecision, PolicyRule, TenantPolicy
from .providers import ModelTier, ProviderRoute, ProviderRouter

__all__ = [
    "ActionMode",
    "ApprovalRecord",
    "ApprovalStore",
    "ModelTier",
    "PolicyDecision",
    "PolicyRule",
    "ProviderRoute",
    "ProviderRouter",
    "TenantPolicy",
    "action_digest",
]
