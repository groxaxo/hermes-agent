"""Durable async-task registry (Phase 2 of autonomy roadmap).

A thin module on top of ``SessionDB`` that tracks long-running work spawned
outside the foreground conversation:

* ``type='delegate'``   — subagent spawned by ``delegate_task``
* ``type='background'`` — ``/background`` gateway command
* ``type='cron'``       — scheduled job execution

Rows survive process crashes. A startup sweep (see
``mark_stale_running_as_orphaned``) can mark stale ``running`` rows as
``orphaned`` so the user sees them surface in ``/tasks`` after a crash.

Design notes
------------
* Every public function is best-effort: failures are logged but never raised
  to the caller. The registry must NEVER take down the actual work it's
  tracking.
* All writes go through ``SessionDB._execute_write`` (BEGIN IMMEDIATE +
  jittered retry) so the gateway, CLI, cron tick, and subagent threads can
  all hit the same row concurrently without convoying.
* The module instantiates a fresh ``SessionDB`` per call. That matches the
  existing pattern in ``hermes_cli/web_server.py``, ``gateway/mirror.py``,
  and ``hermes_cli/goals.py`` — SQLite connections are cheap with WAL.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

from hermes_state import SessionDB

logger = logging.getLogger(__name__)

# Status vocabulary (kept here so callers don't reinvent strings).
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_ORPHANED = "orphaned"
STATUS_EXPIRED = "expired"
STATUS_CANCELLED = "cancelled"

TERMINAL_STATUSES = frozenset(
    {STATUS_COMPLETED, STATUS_FAILED, STATUS_ORPHANED, STATUS_EXPIRED, STATUS_CANCELLED}
)

# Type vocabulary.
TYPE_DELEGATE = "delegate"
TYPE_BACKGROUND = "background"
TYPE_CRON = "cron"


def _truncate(s: Optional[str], limit: int) -> Optional[str]:
    if s is None:
        return None
    if not isinstance(s, str):
        s = str(s)
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def register(
    task_id: str,
    *,
    type: str,
    goal: Optional[str] = None,
    parent_task_id: Optional[str] = None,
    requester: Optional[str] = None,
    session_id: Optional[str] = None,
    cron_job_id: Optional[str] = None,
    process_id: Optional[int] = None,
    db: Optional[SessionDB] = None,
) -> bool:
    """Insert a new ``running`` task row.

    Idempotent: ``ON CONFLICT(task_id) DO NOTHING`` so duplicate calls (e.g.
    after a retry) don't blow up.  Returns ``True`` on success/no-op,
    ``False`` only if the registry write actually failed.
    """
    if not task_id or not type:
        return False
    now = time.time()
    pid = process_id if process_id is not None else os.getpid()
    own_db = db is None
    if own_db:
        try:
            db = SessionDB()
        except Exception as exc:
            logger.debug("async_tasks.register: SessionDB() failed: %s", exc)
            return False
    try:
        def _insert(conn):
            conn.execute(
                """
                INSERT INTO async_tasks (
                    task_id, parent_task_id, type, status, requester,
                    session_id, goal, started_at, last_heartbeat_at,
                    process_id, cron_job_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO NOTHING
                """,
                (
                    task_id,
                    parent_task_id,
                    type,
                    STATUS_RUNNING,
                    requester,
                    session_id,
                    _truncate(goal, 4000),
                    now,
                    now,
                    pid,
                    cron_job_id,
                ),
            )

        db._execute_write(_insert)
        return True
    except Exception as exc:
        logger.debug("async_tasks.register(%s) failed: %s", task_id, exc)
        return False
    finally:
        if own_db and db is not None:
            try:
                db.close()
            except Exception:
                pass


def heartbeat(task_id: str, *, db: Optional[SessionDB] = None) -> None:
    """Update ``last_heartbeat_at`` so stale-detection can age out a row."""
    if not task_id:
        return
    own_db = db is None
    if own_db:
        try:
            db = SessionDB()
        except Exception:
            return
    try:
        now = time.time()

        def _update(conn):
            conn.execute(
                "UPDATE async_tasks SET last_heartbeat_at = ? WHERE task_id = ?",
                (now, task_id),
            )

        db._execute_write(_update)
    except Exception as exc:
        logger.debug("async_tasks.heartbeat(%s) failed: %s", task_id, exc)
    finally:
        if own_db and db is not None:
            try:
                db.close()
            except Exception:
                pass


def complete(
    task_id: str,
    *,
    result_summary: Optional[str] = None,
    output_preview: Optional[str] = None,
    cost_usd: Optional[float] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    api_calls: int = 0,
    db: Optional[SessionDB] = None,
) -> None:
    """Mark a task ``completed`` with optional cost / token metrics."""
    _finish(
        task_id,
        STATUS_COMPLETED,
        result_summary=result_summary,
        output_preview=output_preview,
        cost_usd=cost_usd,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        api_calls=api_calls,
        error=None,
        db=db,
    )


def fail(
    task_id: str,
    *,
    error: Optional[str] = None,
    result_summary: Optional[str] = None,
    cost_usd: Optional[float] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    api_calls: int = 0,
    status: str = STATUS_FAILED,
    db: Optional[SessionDB] = None,
) -> None:
    """Mark a task as terminally not-successful.

    *status* lets callers distinguish ``failed`` / ``cancelled`` / ``expired``
    without spawning N near-duplicate helpers.
    """
    if status not in TERMINAL_STATUSES:
        status = STATUS_FAILED
    _finish(
        task_id,
        status,
        result_summary=result_summary,
        output_preview=None,
        cost_usd=cost_usd,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        api_calls=api_calls,
        error=error,
        db=db,
    )


def _finish(
    task_id: str,
    status: str,
    *,
    result_summary: Optional[str],
    output_preview: Optional[str],
    cost_usd: Optional[float],
    input_tokens: int,
    output_tokens: int,
    api_calls: int,
    error: Optional[str],
    db: Optional[SessionDB],
) -> None:
    if not task_id:
        return
    own_db = db is None
    if own_db:
        try:
            db = SessionDB()
        except Exception as exc:
            logger.debug("async_tasks._finish: SessionDB() failed: %s", exc)
            return
    try:
        now = time.time()

        def _update(conn):
            conn.execute(
                """
                UPDATE async_tasks
                   SET status = ?,
                       finished_at = ?,
                       last_heartbeat_at = ?,
                       result_summary = COALESCE(?, result_summary),
                       output_preview = COALESCE(?, output_preview),
                       error = COALESCE(?, error),
                       cost_usd = COALESCE(?, cost_usd),
                       input_tokens = ?,
                       output_tokens = ?,
                       api_calls = ?
                 WHERE task_id = ?
                """,
                (
                    status,
                    now,
                    now,
                    _truncate(result_summary, 4000),
                    _truncate(output_preview, 4000),
                    _truncate(error, 4000),
                    float(cost_usd) if cost_usd is not None else None,
                    int(input_tokens or 0),
                    int(output_tokens or 0),
                    int(api_calls or 0),
                    task_id,
                ),
            )

        db._execute_write(_update)
    except Exception as exc:
        logger.debug("async_tasks._finish(%s, %s) failed: %s", task_id, status, exc)
    finally:
        if own_db and db is not None:
            try:
                db.close()
            except Exception:
                pass


def get(task_id: str, *, db: Optional[SessionDB] = None) -> Optional[Dict[str, Any]]:
    """Fetch a single task row as a plain dict, or ``None`` if not found."""
    if not task_id:
        return None
    own_db = db is None
    if own_db:
        try:
            db = SessionDB()
        except Exception:
            return None
    try:
        cur = db._conn.execute(
            "SELECT * FROM async_tasks WHERE task_id = ?", (task_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None
    except Exception as exc:
        logger.debug("async_tasks.get(%s) failed: %s", task_id, exc)
        return None
    finally:
        if own_db and db is not None:
            try:
                db.close()
            except Exception:
                pass


def list_tasks(
    *,
    status: Optional[str] = None,
    type: Optional[str] = None,
    parent_task_id: Optional[str] = None,
    limit: int = 50,
    include_finished: bool = True,
    db: Optional[SessionDB] = None,
) -> List[Dict[str, Any]]:
    """Return up to *limit* matching rows, newest first.

    With no filters, returns the *limit* most-recently-started tasks across
    all types and statuses.
    """
    own_db = db is None
    if own_db:
        try:
            db = SessionDB()
        except Exception:
            return []
    try:
        clauses: List[str] = []
        params: List[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if type:
            clauses.append("type = ?")
            params.append(type)
        if parent_task_id:
            clauses.append("parent_task_id = ?")
            params.append(parent_task_id)
        if not include_finished and not status:
            clauses.append("status = ?")
            params.append(STATUS_RUNNING)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(max(1, int(limit)))
        cur = db._conn.execute(
            f"SELECT * FROM async_tasks {where} "
            f"ORDER BY started_at DESC LIMIT ?",
            tuple(params),
        )
        return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.debug("async_tasks.list_tasks failed: %s", exc)
        return []
    finally:
        if own_db and db is not None:
            try:
                db.close()
            except Exception:
                pass


def mark_stale_running_as_orphaned(
    *,
    max_age_seconds: Optional[float] = None,
    pid_alive: Optional[callable] = None,
    db: Optional[SessionDB] = None,
) -> int:
    """Startup-recovery sweep.

    Marks ``running`` rows that came from a previous process generation as
    ``orphaned``. Two heuristics:

    * Any row whose ``process_id`` points at a PID that is NOT currently
      alive — the owning process is gone, so the task can never finish.
    * If *max_age_seconds* is given, any row whose ``last_heartbeat_at``
      (or ``started_at`` fallback) is older than the cutoff is also marked
      orphaned, regardless of PID. This catches hung processes that never
      cleared their row.

    *pid_alive* is a callable taking a PID and returning whether it's alive;
    callers can inject a mock in tests. Defaults to ``os.kill(pid, 0)``.

    Returns the number of rows transitioned.
    """
    if pid_alive is None:
        pid_alive = _default_pid_alive
    own_db = db is None
    if own_db:
        try:
            db = SessionDB()
        except Exception:
            return 0
    try:
        # Read first (no write lock needed) — then update only the matching
        # IDs in one write transaction.
        cur = db._conn.execute(
            "SELECT task_id, process_id, last_heartbeat_at, started_at "
            "FROM async_tasks WHERE status = ?",
            (STATUS_RUNNING,),
        )
        now = time.time()
        to_orphan: List[str] = []
        for row in cur.fetchall():
            tid = row["task_id"]
            pid = row["process_id"]
            last_hb = row["last_heartbeat_at"] or row["started_at"] or 0
            stale_by_age = (
                max_age_seconds is not None
                and (now - float(last_hb)) > float(max_age_seconds)
            )
            stale_by_pid = pid is None or not _safe_pid_alive(pid_alive, int(pid))
            if stale_by_age or stale_by_pid:
                to_orphan.append(tid)

        if not to_orphan:
            return 0

        def _update(conn):
            conn.executemany(
                "UPDATE async_tasks "
                "SET status = ?, finished_at = ?, "
                "    error = COALESCE(error, ?) "
                "WHERE task_id = ? AND status = ?",
                [
                    (STATUS_ORPHANED, now, "Process exited without finishing task", t, STATUS_RUNNING)
                    for t in to_orphan
                ],
            )

        db._execute_write(_update)
        return len(to_orphan)
    except Exception as exc:
        logger.debug("async_tasks.mark_stale_running_as_orphaned failed: %s", exc)
        return 0
    finally:
        if own_db and db is not None:
            try:
                db.close()
            except Exception:
                pass


def cleanup_old(
    *,
    max_age_seconds: float,
    db: Optional[SessionDB] = None,
) -> int:
    """Delete terminal rows older than *max_age_seconds*. Running rows stay."""
    if max_age_seconds <= 0:
        return 0
    own_db = db is None
    if own_db:
        try:
            db = SessionDB()
        except Exception:
            return 0
    try:
        cutoff = time.time() - max_age_seconds
        deleted = [0]

        def _delete(conn):
            cur = conn.execute(
                "DELETE FROM async_tasks "
                "WHERE status != ? AND COALESCE(finished_at, started_at) < ?",
                (STATUS_RUNNING, cutoff),
            )
            deleted[0] = cur.rowcount or 0

        db._execute_write(_delete)
        return deleted[0]
    except Exception as exc:
        logger.debug("async_tasks.cleanup_old failed: %s", exc)
        return 0
    finally:
        if own_db and db is not None:
            try:
                db.close()
            except Exception:
                pass


def _default_pid_alive(pid: int) -> bool:
    """Return True if *pid* corresponds to a live process on this host."""
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by someone else — still alive.
        return True
    except OSError:
        return False


def _safe_pid_alive(fn, pid: int) -> bool:
    try:
        return bool(fn(pid))
    except Exception:
        # Conservative: if the probe blew up, assume alive to avoid orphaning
        # legitimately-running tasks.
        return True
