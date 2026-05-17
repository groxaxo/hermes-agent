"""Invariant tests for the durable async-task registry (Phase 2).

NOTE: hermes_state.DEFAULT_DB_PATH is captured at import time, so all
SessionDB() instances within an xdist worker share one DB file. Tests
therefore use UUID-prefixed task IDs and filter list/sweep assertions
to their own rows so state leakage across tests in the same worker
doesn't cause false failures.
"""

from __future__ import annotations

import time
import uuid

import pytest

from agent import async_tasks


def _prefix() -> str:
    return f"test_{uuid.uuid4().hex[:12]}_"


def test_register_then_get_returns_running_row():
    tid = _prefix() + "single"
    ok = async_tasks.register(
        tid,
        type=async_tasks.TYPE_DELEGATE,
        goal="do a thing",
        requester="cli",
    )
    assert ok is True
    row = async_tasks.get(tid)
    assert row is not None
    assert row["task_id"] == tid
    assert row["type"] == async_tasks.TYPE_DELEGATE
    assert row["status"] == async_tasks.STATUS_RUNNING
    assert row["goal"] == "do a thing"
    assert row["started_at"] is not None
    assert row["finished_at"] is None


def test_register_is_idempotent():
    tid = _prefix() + "dup"
    assert async_tasks.register(tid, type=async_tasks.TYPE_BACKGROUND, goal="A")
    assert async_tasks.register(tid, type=async_tasks.TYPE_BACKGROUND, goal="B")
    assert async_tasks.get(tid)["goal"] == "A"


def test_heartbeat_updates_last_heartbeat_at():
    tid = _prefix() + "hb"
    async_tasks.register(tid, type=async_tasks.TYPE_DELEGATE)
    first = async_tasks.get(tid)["last_heartbeat_at"]
    time.sleep(0.01)
    async_tasks.heartbeat(tid)
    second = async_tasks.get(tid)["last_heartbeat_at"]
    assert second >= first


def test_complete_sets_terminal_fields():
    tid = _prefix() + "c"
    async_tasks.register(tid, type=async_tasks.TYPE_DELEGATE)
    async_tasks.complete(
        tid,
        result_summary="done",
        output_preview="done preview",
        cost_usd=0.01,
        input_tokens=100,
        output_tokens=50,
        api_calls=3,
    )
    row = async_tasks.get(tid)
    assert row["status"] == async_tasks.STATUS_COMPLETED
    assert row["finished_at"] is not None
    assert row["result_summary"] == "done"
    assert row["output_preview"] == "done preview"
    assert row["error"] is None
    assert row["input_tokens"] == 100
    assert row["output_tokens"] == 50
    assert row["api_calls"] == 3


def test_fail_records_error_and_supports_cancelled_status():
    pre = _prefix()
    tid1, tid2 = pre + "f1", pre + "f2"

    async_tasks.register(tid1, type=async_tasks.TYPE_DELEGATE)
    async_tasks.fail(tid1, error="boom")
    row = async_tasks.get(tid1)
    assert row["status"] == async_tasks.STATUS_FAILED
    assert row["error"] == "boom"
    assert row["finished_at"] is not None

    async_tasks.register(tid2, type=async_tasks.TYPE_DELEGATE)
    async_tasks.fail(tid2, error="user stop", status=async_tasks.STATUS_CANCELLED)
    assert async_tasks.get(tid2)["status"] == async_tasks.STATUS_CANCELLED


def test_fail_with_invalid_status_falls_back_to_failed():
    tid = _prefix() + "f3"
    async_tasks.register(tid, type=async_tasks.TYPE_DELEGATE)
    async_tasks.fail(tid, error="x", status="bogus-status")
    assert async_tasks.get(tid)["status"] == async_tasks.STATUS_FAILED


def test_list_tasks_filters_and_limit_and_order():
    pre = _prefix()
    a, b, c = pre + "a", pre + "b", pre + "c"

    async_tasks.register(a, type=async_tasks.TYPE_DELEGATE)
    time.sleep(0.005)
    async_tasks.register(b, type=async_tasks.TYPE_BACKGROUND)
    time.sleep(0.005)
    async_tasks.register(c, type=async_tasks.TYPE_DELEGATE, parent_task_id=a)
    async_tasks.complete(a, result_summary="ok")

    # Filter to our test's rows since the worker-shared DB may contain others.
    ours = [r for r in async_tasks.list_tasks(limit=10_000)
            if r["task_id"].startswith(pre)]
    assert [r["task_id"] for r in ours] == [c, b, a]

    # parent_task_id is exact-match, so no prefix filtering needed.
    children = async_tasks.list_tasks(parent_task_id=a)
    assert [r["task_id"] for r in children] == [c]

    bg_ours = [r for r in async_tasks.list_tasks(
        type=async_tasks.TYPE_BACKGROUND, limit=10_000)
        if r["task_id"].startswith(pre)]
    assert [r["task_id"] for r in bg_ours] == [b]

    done_ours = [r for r in async_tasks.list_tasks(
        status=async_tasks.STATUS_COMPLETED, limit=10_000)
        if r["task_id"].startswith(pre)]
    assert [r["task_id"] for r in done_ours] == [a]

    # Limit clamp.
    assert len(async_tasks.list_tasks(limit=1)) == 1


def test_mark_stale_running_as_orphaned_uses_pid_alive_callable():
    pre = _prefix()
    o1, o2 = pre + "o1", pre + "o2"
    async_tasks.register(o1, type=async_tasks.TYPE_DELEGATE)
    async_tasks.register(o2, type=async_tasks.TYPE_CRON)
    async_tasks.complete(o2, result_summary="finished")  # terminal — must NOT be touched

    async_tasks.mark_stale_running_as_orphaned(pid_alive=lambda _p: False)
    assert async_tasks.get(o1)["status"] == async_tasks.STATUS_ORPHANED
    assert async_tasks.get(o2)["status"] == async_tasks.STATUS_COMPLETED

    # Idempotent: re-running doesn't flip terminal rows back.
    async_tasks.mark_stale_running_as_orphaned(pid_alive=lambda _p: False)
    assert async_tasks.get(o1)["status"] == async_tasks.STATUS_ORPHANED


def test_mark_stale_uses_max_age_seconds_even_if_pid_alive():
    tid = _prefix() + "age"
    async_tasks.register(tid, type=async_tasks.TYPE_DELEGATE)
    # Force heartbeat into the past so age-based eviction triggers.
    from hermes_state import SessionDB
    db = SessionDB()
    try:
        def _w(conn):
            conn.execute(
                "UPDATE async_tasks SET last_heartbeat_at = ?, started_at = ? "
                "WHERE task_id = ?",
                (time.time() - 3600, time.time() - 3600, tid),
            )
        db._execute_write(_w)
    finally:
        db.close()

    async_tasks.mark_stale_running_as_orphaned(
        max_age_seconds=60, pid_alive=lambda _p: True,
    )
    assert async_tasks.get(tid)["status"] == async_tasks.STATUS_ORPHANED


def test_cleanup_old_removes_only_terminal_rows():
    pre = _prefix()
    keep, old = pre + "keep_running", pre + "old_done"
    async_tasks.register(keep, type=async_tasks.TYPE_DELEGATE)
    async_tasks.register(old, type=async_tasks.TYPE_DELEGATE)
    async_tasks.complete(old, result_summary="x")

    from hermes_state import SessionDB
    db = SessionDB()
    try:
        def _w(conn):
            conn.execute(
                "UPDATE async_tasks SET finished_at = ? WHERE task_id = ?",
                (time.time() - 86400, old),
            )
        db._execute_write(_w)
    finally:
        db.close()

    async_tasks.cleanup_old(max_age_seconds=3600)
    assert async_tasks.get(old) is None
    assert async_tasks.get(keep) is not None


def test_register_with_missing_args_returns_false():
    assert async_tasks.register("", type=async_tasks.TYPE_DELEGATE) is False
    assert async_tasks.register("x" + uuid.uuid4().hex, type="") is False


def test_get_unknown_task_returns_none():
    assert async_tasks.get("does-not-exist-" + uuid.uuid4().hex) is None
