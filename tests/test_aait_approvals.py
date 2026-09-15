from aait_runtime.approvals import ApprovalStore, action_digest


def test_approval_is_exact_and_single_use(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.sqlite3")
    original = {"to": "john@example.com", "body": "hello"}
    changed = {"to": "john@example.com", "body": "changed"}

    original_hash = action_digest("tenant-a", "aait.gmail.send", original)
    changed_hash = action_digest("tenant-a", "aait.gmail.send", changed)
    assert original_hash != changed_hash

    request = store.request(
        tenant_id="tenant-a",
        session_id="session-1",
        tool_name="aait.gmail.send",
        action_hash=original_hash,
        arg_keys=tuple(original.keys()),
        ttl_seconds=900,
    )
    assert request.status == "pending"
    assert request.arg_keys == ("body", "to")

    approved = store.approve(request.id)
    assert approved is not None
    assert approved.status == "approved"

    # Changed arguments cannot reuse the approval.
    assert (
        store.consume_if_approved(
            tenant_id="tenant-a",
            session_id="session-1",
            action_hash=changed_hash,
        )
        is None
    )

    consumed = store.consume_if_approved(
        tenant_id="tenant-a",
        session_id="session-1",
        action_hash=original_hash,
    )
    assert consumed is not None
    assert consumed.status == "consumed"

    # Exact approval is consumed once.
    assert (
        store.consume_if_approved(
            tenant_id="tenant-a",
            session_id="session-1",
            action_hash=original_hash,
        )
        is None
    )


def test_approval_is_session_scoped(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.sqlite3")
    digest = action_digest("tenant-a", "aait.calendar.create", {"when": "10:00"})
    request = store.request(
        tenant_id="tenant-a",
        session_id="session-1",
        tool_name="aait.calendar.create",
        action_hash=digest,
        arg_keys=("when",),
        ttl_seconds=900,
    )
    store.approve(request.id)

    assert (
        store.consume_if_approved(
            tenant_id="tenant-a",
            session_id="session-2",
            action_hash=digest,
        )
        is None
    )
