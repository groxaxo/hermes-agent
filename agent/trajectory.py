"""Trajectory saving utilities and static helpers.

_convert_to_trajectory_format stays as an AIAgent method (batch_runner.py
calls agent._convert_to_trajectory_format). Only the static helpers and
the file-write logic live here.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List

from agent.redact import redact_sensitive_text

logger = logging.getLogger(__name__)


def redact_trajectory_entry(obj: Any) -> Any:
    """Recursively redact sensitive strings throughout a trajectory entry.

    Walks the full object tree so that secrets in nested dicts, lists, or
    unexpected fields (e.g. "query", "metadata", tool arguments) are masked
    before the entry is persisted to disk.

    Uses ``force=True`` because trajectory files are durable on-disk
    artefacts — they must never contain raw secrets regardless of the
    user's global redaction preference.
    """
    if isinstance(obj, str):
        return redact_sensitive_text(obj, force=True)
    if isinstance(obj, list):
        return [redact_trajectory_entry(item) for item in obj]
    if isinstance(obj, dict):
        return {k: redact_trajectory_entry(v) for k, v in obj.items()}
    return obj


def convert_scratchpad_to_think(content: str) -> str:
    """Convert <REASONING_SCRATCHPAD> tags to <think> tags."""
    if not content or "<REASONING_SCRATCHPAD>" not in content:
        return content
    return content.replace("<REASONING_SCRATCHPAD>", "<think>").replace("</REASONING_SCRATCHPAD>", "</think>")


def has_incomplete_scratchpad(content: str) -> bool:
    """Check if content has an opening <REASONING_SCRATCHPAD> without a closing tag."""
    if not content:
        return False
    return "<REASONING_SCRATCHPAD>" in content and "</REASONING_SCRATCHPAD>" not in content


def save_trajectory(trajectory: List[Dict[str, Any]], model: str,
                    completed: bool, filename: str = None):
    """Append a trajectory entry to a JSONL file.

    Args:
        trajectory: The ShareGPT-format conversation list.
        model: Model name for metadata.
        completed: Whether the conversation completed successfully.
        filename: Override output filename. Defaults to trajectory_samples.jsonl
                  or failed_trajectories.jsonl based on ``completed``.
    """
    if filename is None:
        filename = "trajectory_samples.jsonl" if completed else "failed_trajectories.jsonl"

    entry = {
        "conversations": trajectory,
        "timestamp": datetime.now().isoformat(),
        "model": model,
        "completed": completed,
    }

    try:
        with open(filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(redact_trajectory_entry(entry), ensure_ascii=False) + "\n")
        logger.info("Trajectory saved to %s", filename)
    except Exception as e:
        logger.warning("Failed to save trajectory: %s", e)
