from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


def _restrict_mode(path: Path, mode: int) -> None:
    """Apply private POSIX permissions without breaking non-POSIX installs."""

    if os.name == "posix":
        path.chmod(mode)


def action_digest(tenant_id: str, tool_name: str, args: Mapping[str, Any] | None) -> str:
    """Hash the exact proposed action without persisting its sensitive values."""

    payload = {
        "tenant_id": tenant_id,
        "tool_name": tool_name,
        "args": args if isinstance(args, Mapping) else {},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApprovalRecord:
    id: str
    tenant_id: str
    session_id: str
    tool_name: str
    action_hash: str
    arg_keys: tuple[str, ...]
    status: str
    created_at: float
    expires_at: float
    approved_at: float | None = None
    consumed_at: float | None = None


class ApprovalStore:
    """SQLite-backed exact-action, single-use approvals.

    Only the SHA-256 digest and argument *keys* are persisted. Email bodies,
    contact data, calendar descriptions and other argument values are never
    stored in the approval database.

    On POSIX systems the state directory is restricted to ``0700`` and the
    database to ``0600``. This provides defense in depth for bind-mounted
    customer state even when the host/container default umask is permissive.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _restrict_mode(self.path.parent, 0o700)
        self._init_db()
        _restrict_mode(self.path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        if self.path.exists():
            _restrict_mode(self.path, 0o600)
        conn = sqlite3.connect(str(self.path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    action_hash TEXT NOT NULL,
                    arg_keys_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    approved_at REAL,
                    consumed_at REAL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_aait_approvals_lookup "
                "ON approvals (tenant_id, session_id, action_hash, status, expires_at)"
            )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ApprovalRecord:
        return ApprovalRecord(
            id=row["id"],
            tenant_id=row["tenant_id"],
            session_id=row["session_id"],
            tool_name=row["tool_name"],
            action_hash=row["action_hash"],
            arg_keys=tuple(json.loads(row["arg_keys_json"])),
            status=row["status"],
            created_at=float(row["created_at"]),
            expires_at=float(row["expires_at"]),
            approved_at=row["approved_at"],
            consumed_at=row["consumed_at"],
        )

    def request(
        self,
        *,
        tenant_id: str,
        session_id: str,
        tool_name: str,
        action_hash: str,
        arg_keys: tuple[str, ...],
        ttl_seconds: int,
    ) -> ApprovalRecord:
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE approvals SET status='expired' "
                "WHERE status IN ('pending','approved') AND expires_at <= ?",
                (now,),
            )
            row = conn.execute(
                """
                SELECT * FROM approvals
                WHERE tenant_id=? AND session_id=? AND action_hash=?
                  AND status IN ('pending','approved') AND expires_at > ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (tenant_id, session_id, action_hash, now),
            ).fetchone()
            if row is not None:
                return self._row_to_record(row)

            approval_id = f"apr_{secrets.token_hex(6)}"
            expires_at = now + ttl_seconds
            conn.execute(
                """
                INSERT INTO approvals
                (id, tenant_id, session_id, tool_name, action_hash, arg_keys_json,
                 status, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    approval_id,
                    tenant_id,
                    session_id,
                    tool_name,
                    action_hash,
                    json.dumps(sorted(arg_keys)),
                    now,
                    expires_at,
                ),
            )
            row = conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            assert row is not None
            return self._row_to_record(row)

    def approve(self, approval_id: str) -> ApprovalRecord | None:
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE approvals SET status='expired' "
                "WHERE id=? AND status IN ('pending','approved') AND expires_at <= ?",
                (approval_id, now),
            )
            conn.execute(
                "UPDATE approvals SET status='approved', approved_at=? "
                "WHERE id=? AND status='pending' AND expires_at > ?",
                (now, approval_id, now),
            )
            row = conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            return self._row_to_record(row) if row is not None else None

    def reject(self, approval_id: str) -> ApprovalRecord | None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE approvals SET status='rejected' "
                "WHERE id=? AND status IN ('pending','approved')",
                (approval_id,),
            )
            row = conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            return self._row_to_record(row) if row is not None else None

    def consume_if_approved(
        self,
        *,
        tenant_id: str,
        session_id: str,
        action_hash: str,
    ) -> ApprovalRecord | None:
        """Atomically consume one exact matching approval, once."""

        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM approvals
                WHERE tenant_id=? AND session_id=? AND action_hash=?
                  AND status='approved' AND expires_at > ?
                ORDER BY approved_at DESC LIMIT 1
                """,
                (tenant_id, session_id, action_hash, now),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE approvals SET status='consumed', consumed_at=? "
                "WHERE id=? AND status='approved'",
                (now, row["id"]),
            )
            updated = conn.execute("SELECT * FROM approvals WHERE id=?", (row["id"],)).fetchone()
            return self._row_to_record(updated) if updated is not None else None

    def list_recent(self, limit: int = 10) -> list[ApprovalRecord]:
        limit = max(1, min(int(limit), 100))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM approvals ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]
