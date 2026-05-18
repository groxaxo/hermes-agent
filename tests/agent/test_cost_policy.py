from agent.cost_policy import (
    BudgetMode,
    budget_decision,
    find_downgrade_model,
    infer_purpose,
    resolve_budget_usd,
    resolve_purpose_route,
)


def test_infer_purpose_is_deterministic():
    assert infer_purpose("Implement a fix for this bug") == "code"
    assert infer_purpose("Research and compare providers") == "research"
    assert infer_purpose("Summarize today's tasks") == "summarize"
    assert infer_purpose("") == "general"


def test_resolve_budget_prefers_explicit_then_purpose_then_kind_default():
    cfg = {
        "cost_policy": {
            "default_task_budget_usd": 1.0,
            "default_subagent_budget_usd": 0.5,
            "purpose_budgets": {"research": 0.25},
        }
    }
    assert resolve_budget_usd(cfg, purpose="research", explicit_budget_usd=2.0) == 2.0
    assert resolve_budget_usd(cfg, purpose="research", kind="subagent") == 0.25
    assert resolve_budget_usd(cfg, purpose="code", kind="subagent") == 0.5
    assert resolve_budget_usd(cfg, purpose="code", kind="task") == 1.0


def test_resolve_purpose_route_is_disabled_by_default():
    route = resolve_purpose_route({}, purpose="code", current_provider="p", current_model="m")
    assert route.purpose == "code"
    assert route.provider == "p"
    assert route.model == "m"


def test_resolve_purpose_route_reads_enabled_mapping():
    cfg = {
        "purpose_routing": {
            "enabled": True,
            "purposes": {
                "code": {
                    "provider": "fast",
                    "model": "fast-code",
                    "toolsets": ["file", "terminal"],
                    "budget_usd": 0.2,
                    "reasoning_effort": "low",
                }
            },
        }
    }
    route = resolve_purpose_route(cfg, purpose="code", current_provider="p", current_model="m")
    assert route.provider == "fast"
    assert route.model == "fast-code"
    assert route.toolsets == ["file", "terminal"]
    assert route.budget_usd == 0.2
    assert route.reasoning_effort == "low"


def test_budget_decision_warns_and_blocks_when_over_budget():
    under = budget_decision(spent_usd=0.8, budget_usd=1.0, mode="alert")
    assert under.ok is True
    assert under.warning is True
    over = budget_decision(spent_usd=1.2, budget_usd=1.0, mode="pause")
    assert over.ok is False
    assert over.mode == BudgetMode.PAUSE
    assert "budget exceeded" in over.reason


def test_find_downgrade_model_supports_string_and_list():
    cfg = {"cost_policy": {"downgrade_tiers": {"expensive": ["mid", "cheap"], "mid": "cheap"}}}
    assert find_downgrade_model(cfg, "expensive") == "mid"
    assert find_downgrade_model(cfg, "mid") == "cheap"
    assert find_downgrade_model(cfg, "unknown") is None
