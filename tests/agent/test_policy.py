from agent.policy import ToolsetPolicy, apply_toolset_policy, is_tool_allowed, merge_policies


def test_apply_toolset_policy_allow_then_deny():
    policy = ToolsetPolicy(allow_toolsets=("file", "terminal"), deny_toolsets=("terminal",))
    assert apply_toolset_policy(["file", "web", "terminal"], policy) == ["file"]


def test_merge_policies_preserves_order_and_deny_wins_in_application():
    merged = merge_policies(
        {"allow_toolsets": ["file", "web"], "deny_tools": ["execute_code"]},
        {"deny_toolsets": ["web"], "allow_tools": ["read_file"]},
    )
    assert merged.allow_toolsets == ("file", "web")
    assert merged.deny_toolsets == ("web",)
    assert apply_toolset_policy(["file", "web"], merged) == ["file"]
    assert is_tool_allowed("execute_code", merged) is False
    assert is_tool_allowed("read_file", merged) is True
    assert is_tool_allowed("write_file", merged) is False


def test_policy_from_config_accepts_strings():
    policy = ToolsetPolicy.from_config({"allow_toolsets": "file", "deny_tools": "danger"})
    assert policy.allow_toolsets == ("file",)
    assert policy.deny_tools == ("danger",)
