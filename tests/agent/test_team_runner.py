import json

import pytest

from agent.team_runner import build_team_tasks, describe_team


def test_build_team_tasks_from_config_applies_budget_and_policy():
    cfg = {
        "cost_policy": {"purpose_budgets": {"code": 0.3}},
        "agents": {"default_policy": {"deny_toolsets": ["web"]}},
        "teams": {
            "builders": {
                "toolsets": ["file", "terminal", "web"],
                "members": [
                    {"name": "impl", "purpose": "code", "instructions": "Implement only.", "policy": {"allow_toolsets": ["file", "terminal"]}},
                    {"profile": "reviewer", "purpose": "review", "budget_usd": 0.1},
                ],
            }
        },
    }
    tasks = build_team_tasks(cfg, "builders", "Implement feature")
    assert len(tasks) == 2
    assert tasks[0].name == "impl"
    assert tasks[0].purpose == "code"
    assert tasks[0].budget_usd == 0.3
    assert tasks[0].toolsets == ["file", "terminal", "web"]
    assert tasks[0].policy["deny_toolsets"] == ["web"]
    assert tasks[0].policy["allow_toolsets"] == ["file", "terminal"]
    assert "Implement only." in tasks[0].context
    assert tasks[1].name == "reviewer"
    assert tasks[1].budget_usd == 0.1


def test_build_team_tasks_rejects_unknown_or_empty_team():
    with pytest.raises(ValueError, match="Unknown team"):
        build_team_tasks({"teams": {}}, "missing", "prompt")
    with pytest.raises(ValueError, match="no members"):
        build_team_tasks({"teams": {"empty": {"members": []}}}, "empty", "prompt")
    with pytest.raises(ValueError, match="prompt"):
        build_team_tasks({"teams": {"x": {"members": [{}]}}}, "x", "")


def test_describe_team_returns_json_summary():
    cfg = {"teams": {"solo": {"members": [{"name": "one", "purpose": "plan"}]}}}
    payload = json.loads(describe_team(cfg, "solo"))
    assert payload["team"] == "solo"
    assert payload["members"][0]["name"] == "one"
    assert payload["members"][0]["purpose"] == "plan"
