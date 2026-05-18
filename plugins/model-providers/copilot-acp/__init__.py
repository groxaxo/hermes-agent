"""GitHub Copilot ACP provider profile.

copilot-acp uses an external ACP subprocess — NOT the standard
transport. api_mode="copilot_acp" is handled separately in run_agent.py.
The profile captures auth + endpoint metadata for registry migration.
"""

from typing import Any

from providers import register_provider
from providers.base import ProviderProfile


class CopilotACPProfile(ProviderProfile):
    """GitHub Copilot ACP — external process, no REST models endpoint."""

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        """Model listing is handled by the ACP subprocess."""
        return None

    def build_api_kwargs_extras(
        self,
        *,
        model: str | None = None,
        reasoning_config: dict | None = None,
        supports_reasoning: bool = False,
        **ctx: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Forward reasoning effort as a top-level kwarg for CopilotACPClient."""
        if not supports_reasoning or not reasoning_config:
            return {}, {}
        if reasoning_config.get("enabled") is False:
            return {}, {}
        effort = str(reasoning_config.get("effort") or "medium").strip().lower()
        # Clamp to ACP-supported range (clamping also done in the client, belt+suspenders)
        if effort == "minimal":
            effort = "low"
        elif effort == "xhigh":
            effort = "high"
        elif effort in ("none", ""):
            return {}, {}
        return {"reasoning_effort": effort}, {}


copilot_acp = CopilotACPProfile(
    name="copilot-acp",
    aliases=("github-copilot-acp", "copilot-acp-agent"),
    api_mode="chat_completions",  # ACP subprocess uses chat_completions routing
    env_vars=(),  # Managed by ACP subprocess
    base_url="acp://copilot",  # ACP internal scheme
    auth_type="external_process",
)

register_provider(copilot_acp)
