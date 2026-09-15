from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from aait_runtime.approvals import ApprovalStore, action_digest
from aait_runtime.audit import AuditLogger
from aait_runtime.policy import ActionMode, TenantPolicy
from hermes_constants import get_hermes_home


@dataclass
class _RuntimeState:
    config_path: Path
    policy: TenantPolicy
    approvals: ApprovalStore
    audit: AuditLogger


_state: Optional[_RuntimeState] = None
_state_lock = threading.Lock()


def _config_path() -> Path:
    override = os.getenv("AAIT_TENANT_CONFIG", "").strip()
    if override:
        return Path(override).expanduser()
    return get_hermes_home() / "aait" / "tenant.yaml"


def _load_policy(path: Path) -> TenantPolicy:
    if not path.exists():
        # The plugin itself is opt-in.  Once enabled, missing tenant policy is
        # intentionally fail-closed: every tool needs explicit approval until
        # the operator installs a policy file.
        return TenantPolicy()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"AAIT tenant config must be a YAML mapping: {path}")
    policy_data = data.get("policy", data)
    if not isinstance(policy_data, dict):
        raise ValueError("AAIT policy section must be a YAML mapping")
    merged = dict(policy_data)
    merged.setdefault("tenant_id", data.get("tenant_id", "local"))
    return TenantPolicy.from_mapping(merged)


def _ensure_state(force: bool = False) -> _RuntimeState:
    global _state
    with _state_lock:
        if _state is not None and not force:
            return _state
        path = _config_path()
        home = get_hermes_home() / "aait"
        policy = _load_policy(path)
        _state = _RuntimeState(
            config_path=path,
            policy=policy,
            approvals=ApprovalStore(home / "approvals.sqlite3"),
            audit=AuditLogger(home / "audit"),
        )
        return _state


def _audit(
    state: _RuntimeState,
    *,
    event: str,
    tool_name: str,
    args: Dict[str, Any],
    session_id: str,
    task_id: str,
    tool_call_id: str,
    action_name: str,
    digest: str,
    approval_id: str = "",
    status: str = "",
    matched_policy: str = "",
) -> None:
    state.audit.write(
        event=event,
        tenant_id=state.policy.tenant_id,
        tool_name=tool_name,
        action_name=action_name,
        action_hash=digest,
        args=args,
        session_id=session_id,
        task_id=task_id,
        tool_call_id=tool_call_id,
        approval_id=approval_id,
        status=status,
        matched_policy=matched_policy,
    )


def _on_pre_tool_call(
    tool_name: str = "",
    args: Optional[Dict[str, Any]] = None,
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    **_: Any,
):
    """Enforce tenant policy before Hermes dispatches a tool."""

    safe_args: Dict[str, Any] = args if isinstance(args, dict) else {}
    try:
        state = _ensure_state()
        decision = state.policy.decide(tool_name, safe_args)
    except Exception as exc:
        return {
            "action": "block",
            "message": f"AAIT policy could not be loaded; failing closed: {exc}",
        }

    digest = action_digest(state.policy.tenant_id, tool_name, safe_args)
    matched = decision.matched_pattern or "<default>"

    if decision.mode == ActionMode.AUTOMATIC:
        _audit(
            state,
            event="tool_allowed",
            tool_name=tool_name,
            args=safe_args,
            session_id=session_id,
            task_id=task_id,
            tool_call_id=tool_call_id,
            action_name=decision.action_name,
            digest=digest,
            status="automatic",
            matched_policy=matched,
        )
        return None

    if decision.mode == ActionMode.FORBIDDEN:
        _audit(
            state,
            event="tool_blocked",
            tool_name=tool_name,
            args=safe_args,
            session_id=session_id,
            task_id=task_id,
            tool_call_id=tool_call_id,
            action_name=decision.action_name,
            digest=digest,
            status="forbidden",
            matched_policy=matched,
        )
        return {
            "action": "block",
            "message": (
                f"AAIT policy forbids '{decision.action_name}' for tenant "
                f"'{state.policy.tenant_id}'."
            ),
        }

    consumed = state.approvals.consume_if_approved(
        tenant_id=state.policy.tenant_id,
        session_id=session_id or "default",
        action_hash=digest,
    )
    if consumed is not None:
        _audit(
            state,
            event="approval_consumed",
            tool_name=tool_name,
            args=safe_args,
            session_id=session_id,
            task_id=task_id,
            tool_call_id=tool_call_id,
            action_name=decision.action_name,
            digest=digest,
            approval_id=consumed.id,
            status="approved_once",
            matched_policy=matched,
        )
        return None

    approval = state.approvals.request(
        tenant_id=state.policy.tenant_id,
        session_id=session_id or "default",
        tool_name=tool_name,
        action_hash=digest,
        arg_keys=tuple(sorted(safe_args.keys())),
        ttl_seconds=state.policy.approval_ttl_seconds,
    )
    _audit(
        state,
        event="approval_required",
        tool_name=tool_name,
        args=safe_args,
        session_id=session_id,
        task_id=task_id,
        tool_call_id=tool_call_id,
        action_name=decision.action_name,
        digest=digest,
        approval_id=approval.id,
        status=approval.status,
        matched_policy=matched,
    )
    return {
        "action": "block",
        "message": (
            f"AAIT approval required for '{decision.action_name}'. "
            f"Approval ID: {approval.id}. A user can approve this exact action with "
            f"`/aait approve {approval.id}` and then retry it. Approval expires in "
            f"{state.policy.approval_ttl_seconds // 60} minute(s) and is single-use."
        ),
    }


def _on_post_tool_call(
    tool_name: str = "",
    args: Optional[Dict[str, Any]] = None,
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    **_: Any,
) -> None:
    """Record completion metadata without retaining tool result contents."""

    safe_args: Dict[str, Any] = args if isinstance(args, dict) else {}
    try:
        state = _ensure_state()
        decision = state.policy.decide(tool_name, safe_args)
        digest = action_digest(state.policy.tenant_id, tool_name, safe_args)
        _audit(
            state,
            event="tool_completed",
            tool_name=tool_name,
            args=safe_args,
            session_id=session_id,
            task_id=task_id,
            tool_call_id=tool_call_id,
            action_name=decision.action_name,
            digest=digest,
            status="completed",
            matched_policy=decision.matched_pattern or "<default>",
        )
    except Exception:
        # Audit failure must not turn a successfully completed tool into a
        # second user-visible failure.  Pre-tool policy remains fail-closed.
        return


def _format_status(state: _RuntimeState) -> str:
    configured = state.config_path.exists()
    return (
        "AAIT Runtime\n"
        f"Tenant: {state.policy.tenant_id}\n"
        f"Policy: {state.config_path} ({'loaded' if configured else 'missing; fail-closed defaults'})\n"
        f"Default mode: {state.policy.default_mode.value}\n"
        f"Rules: {len(state.policy.rules)}\n"
        f"Approval TTL: {state.policy.approval_ttl_seconds}s\n"
        f"State: {get_hermes_home() / 'aait'}"
    )


def _handle_slash(raw_args: str) -> str:
    global _state
    argv = raw_args.strip().split()
    cmd = argv[0].lower() if argv else "status"

    if cmd in ("help", "-h", "--help"):
        return (
            "/aait status\n"
            "/aait approvals\n"
            "/aait approve <approval-id>\n"
            "/aait reject <approval-id>\n"
            "/aait reload\n\n"
            "Approvals are bound to the exact hashed action and are consumed once."
        )

    try:
        state = _ensure_state(force=(cmd == "reload"))
    except Exception as exc:
        return f"AAIT runtime error: {exc}"

    if cmd in ("status", "reload"):
        return _format_status(state)

    if cmd == "approvals":
        rows = state.approvals.list_recent(10)
        if not rows:
            return "No AAIT approvals recorded."
        lines = ["Recent AAIT approvals:"]
        for row in rows:
            lines.append(
                f"- {row.id} [{row.status}] {row.tool_name} "
                f"keys={','.join(row.arg_keys) or '-'}"
            )
        return "\n".join(lines)

    if cmd in ("approve", "reject"):
        if len(argv) != 2:
            return f"Usage: /aait {cmd} <approval-id>"
        approval_id = argv[1]
        record = (
            state.approvals.approve(approval_id)
            if cmd == "approve"
            else state.approvals.reject(approval_id)
        )
        if record is None:
            return f"Unknown AAIT approval: {approval_id}"
        if cmd == "approve" and record.status != "approved":
            return f"Approval {approval_id} is {record.status}; it cannot be approved."
        return (
            f"AAIT approval {approval_id} {record.status}. "
            + ("Retry the exact action to execute it once." if record.status == "approved" else "")
        )

    return "Unknown AAIT command. Run `/aait help`."


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_command(
        "aait",
        handler=_handle_slash,
        description="AAIT tenant policy, approvals, audit and runtime status.",
        args_hint="[status|approvals|approve|reject|reload]",
    )
