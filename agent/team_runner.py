"""Team fanout helpers built on existing delegate_task batch semantics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from agent.cost_policy import infer_purpose, normalize_purpose, resolve_budget_usd
from agent.policy import merge_policies


@dataclass(frozen=True)
class TeamMemberTask:
    name: str
    goal: str
    context: str
    toolsets: Optional[list[str]] = None
    role: str = "leaf"
    purpose: str = "general"
    budget_usd: Optional[float] = None
    policy: Optional[dict[str, Any]] = None

    def as_delegate_task(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "goal": self.goal,
            "context": self.context,
            "role": self.role,
            "purpose": self.purpose,
        }
        if self.toolsets:
            data["toolsets"] = self.toolsets
        if self.budget_usd is not None:
            data["budget_usd"] = self.budget_usd
        if self.policy:
            data["policy"] = self.policy
        return data


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def get_team_config(config: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    teams = _mapping(config.get("teams"))
    team = teams.get(name)
    if not isinstance(team, Mapping):
        raise ValueError(f"Unknown team '{name}'. Configure teams.{name} in config.yaml.")
    return team


def build_team_tasks(
    config: Mapping[str, Any],
    team_name: str,
    prompt: str,
) -> list[TeamMemberTask]:
    """Build delegate_task batch specs for a configured team."""
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("Team prompt is required.")
    team = get_team_config(config, team_name)
    members = team.get("members")
    if not isinstance(members, list) or not members:
        raise ValueError(f"Team '{team_name}' has no members.")
    default_policy = _mapping(_mapping(config.get("agents")).get("default_policy"))
    team_policy = _mapping(team.get("policy"))
    tasks: list[TeamMemberTask] = []
    for idx, raw in enumerate(members, 1):
        member = _mapping(raw)
        name = str(member.get("name") or member.get("profile") or f"member-{idx}")
        purpose = normalize_purpose(member.get("purpose") or infer_purpose(prompt))
        member_policy = merge_policies(default_policy, team_policy, _mapping(member.get("policy")))
        role = str(member.get("role") or "leaf")
        if role not in ("leaf", "orchestrator"):
            role = "leaf"
        budget = resolve_budget_usd(
            config,
            purpose=purpose,
            explicit_budget_usd=member.get("budget_usd") or team.get("budget_usd"),
            kind="subagent",
        )
        context_bits = [
            f"You are team member '{name}' in team '{team_name}'.",
            f"Focus area / purpose: {purpose}.",
        ]
        if member.get("profile"):
            context_bits.append(f"Configured profile hint: {member.get('profile')}.")
        if member.get("instructions"):
            context_bits.append(str(member.get("instructions")))
        context_bits.append("Return a concise final summary for synthesis by the parent agent.")
        tasks.append(
            TeamMemberTask(
                name=name,
                goal=f"[{team_name}/{name}] {prompt}",
                context="\n".join(context_bits),
                toolsets=list(member.get("toolsets") or team.get("toolsets") or []) or None,
                role=role,
                purpose=purpose,
                budget_usd=budget,
                policy={
                    "allow_toolsets": list(member_policy.allow_toolsets),
                    "deny_toolsets": list(member_policy.deny_toolsets),
                    "allow_tools": list(member_policy.allow_tools),
                    "deny_tools": list(member_policy.deny_tools),
                },
            )
        )
    return tasks


def run_team_delegate(config: Mapping[str, Any], team_name: str, prompt: str, *, parent_agent) -> str:
    """Run a configured team via delegate_task batch mode."""
    if parent_agent is None:
        raise ValueError("A live parent agent is required for team fanout.")
    from tools.delegate_tool import delegate_task

    specs = [task.as_delegate_task() for task in build_team_tasks(config, team_name, prompt)]
    return delegate_task(tasks=specs, parent_agent=parent_agent)


def describe_team(config: Mapping[str, Any], team_name: str) -> str:
    tasks = build_team_tasks(config, team_name, "<prompt>")
    payload = [
        {
            "name": t.name,
            "purpose": t.purpose,
            "toolsets": t.toolsets or [],
            "role": t.role,
            "budget_usd": t.budget_usd,
        }
        for t in tasks
    ]
    return json.dumps({"team": team_name, "members": payload}, ensure_ascii=False, indent=2)
