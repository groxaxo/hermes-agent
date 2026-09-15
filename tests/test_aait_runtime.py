import json

from aait_runtime.audit import AuditLogger
from aait_runtime.providers import ModelTier, ProviderRoute, ProviderRouter


def test_audit_omits_argument_values(tmp_path):
    logger = AuditLogger(tmp_path / "audit")
    secret_body = "customer-confidential-body"
    logger.write(
        event="approval_required",
        tenant_id="tenant-a",
        tool_name="aait.gmail.send",
        action_name="aait.gmail.send",
        action_hash="abc123",
        args={"to": "john@example.com", "body": secret_body},
        session_id="s1",
    )

    path = next((tmp_path / "audit").glob("*.jsonl"))
    raw = path.read_text(encoding="utf-8")
    assert secret_body not in raw
    assert "john@example.com" not in raw
    record = json.loads(raw)
    assert record["arg_keys"] == ["body", "to"]


def test_provider_router_prefers_priority_and_supports_failover():
    router = ProviderRouter(
        [
            ProviderRoute("bedrock", "nova-lite", ModelTier.STANDARD, priority=20),
            ProviderRoute("openai", "luna", ModelTier.STANDARD, priority=10),
            ProviderRoute("openai", "terra", ModelTier.ADVANCED, priority=10),
        ]
    )

    assert router.choose(ModelTier.STANDARD).provider == "openai"
    assert (
        router.choose(ModelTier.STANDARD, unavailable_providers={"openai"}).provider
        == "bedrock"
    )
