from aait_runtime.policy import ActionMode, TenantPolicy, resolve_action_name


def test_policy_first_match_wins():
    policy = TenantPolicy.from_mapping(
        {
            "tenant_id": "t1",
            "default_mode": "approval",
            "rules": [
                {"match": "aait.gmail.search*", "mode": "automatic"},
                {"match": "aait.gmail.*", "mode": "forbidden"},
            ],
        }
    )

    assert policy.decide("aait.gmail.search").mode is ActionMode.AUTOMATIC
    assert policy.decide("aait.gmail.send").mode is ActionMode.FORBIDDEN
    assert policy.decide("unknown_tool").mode is ActionMode.APPROVAL


def test_operation_key_extends_generic_tool_name():
    assert resolve_action_name("google", {"operation": "gmail_send"}) == "google.gmail_send"


def test_policy_can_match_resolved_operation():
    policy = TenantPolicy.from_mapping(
        {
            "rules": [
                {"match": "google.gmail_send", "mode": "approval"},
                {"match": "google.*", "mode": "automatic"},
            ]
        }
    )
    decision = policy.decide("google", {"operation": "gmail_send"})
    assert decision.mode is ActionMode.APPROVAL
    assert decision.action_name == "google.gmail_send"


def test_invalid_ttl_fails_fast():
    try:
        TenantPolicy.from_mapping({"approval_ttl_seconds": 1})
    except ValueError as exc:
        assert "approval_ttl_seconds" in str(exc)
    else:
        raise AssertionError("expected invalid TTL to fail")
