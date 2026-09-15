from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class AuditLogger:
    """Append-only metadata audit log with privacy-safe defaults.

    Tool argument values and result bodies are intentionally never written.
    The action digest allows later correlation with an approval without
    retaining the underlying customer content.
    """

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(
        self,
        *,
        event: str,
        tenant_id: str,
        tool_name: str,
        action_name: str,
        action_hash: str,
        args: Mapping[str, Any] | None = None,
        session_id: str = "",
        task_id: str = "",
        tool_call_id: str = "",
        approval_id: str = "",
        status: str = "",
        matched_policy: str = "",
    ) -> None:
        now = datetime.now(timezone.utc)
        record = {
            "timestamp": now.isoformat(),
            "event": event,
            "tenant_id": tenant_id,
            "session_id": session_id,
            "task_id": task_id,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "action_name": action_name,
            "action_hash": action_hash,
            "arg_keys": sorted(args.keys()) if isinstance(args, Mapping) else [],
            "approval_id": approval_id or None,
            "status": status or None,
            "matched_policy": matched_policy or None,
        }
        path = self.directory / f"{now.date().isoformat()}.jsonl"
        line = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
