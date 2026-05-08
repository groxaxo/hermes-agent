"""Tests for trajectory redaction in agent/trajectory.py.

Verifies that secrets present in conversation content, tool arguments, or
metadata fields are stripped by redact_trajectory_entry() and that
save_trajectory() never writes raw credentials to disk.
"""

import json
import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.trajectory import redact_trajectory_entry, save_trajectory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _force_redaction_on(monkeypatch):
    """Force redaction regardless of env-var snapshot in agent.redact."""
    monkeypatch.delenv("HERMES_REDACT_SECRETS", raising=False)
    monkeypatch.setattr("agent.redact._REDACT_ENABLED", True)


# ---------------------------------------------------------------------------
# Unit tests for redact_trajectory_entry()
# ---------------------------------------------------------------------------


class TestRedactTrajectoryEntry:
    def test_plain_string_is_redacted(self):
        secret = "sk-proj-abc123def456ghi789jkl012"
        result = redact_trajectory_entry(secret)
        assert "abc123def456" not in result

    def test_list_items_are_redacted(self):
        data = ["hello", "key: sk-proj-abc123def456ghi789jkl012", "world"]
        result = redact_trajectory_entry(data)
        assert isinstance(result, list)
        assert "abc123def456" not in result[1]
        assert result[0] == "hello"
        assert result[2] == "world"

    def test_dict_values_are_redacted(self):
        data = {"content": "my key is sk-proj-abc123def456ghi789jkl012", "role": "user"}
        result = redact_trajectory_entry(data)
        assert "abc123def456" not in result["content"]
        assert result["role"] == "user"

    def test_nested_structure_is_fully_redacted(self):
        """Secrets buried deep in nested dicts/lists must all be masked."""
        secret_key = "sk-proj-abc123def456ghi789jkl012"
        data = {
            "conversations": [
                {
                    "from": "tool",
                    "value": f"Output: {secret_key}",
                },
                {
                    "from": "human",
                    "value": "What is your API key?",
                },
            ],
            "metadata": {
                "tool_args": {"api_key": secret_key},
            },
        }
        result = redact_trajectory_entry(data)
        result_str = json.dumps(result)
        assert "abc123def456" not in result_str

    def test_non_string_primitives_pass_through(self):
        data = {"count": 42, "ok": True, "nothing": None}
        result = redact_trajectory_entry(data)
        assert result == {"count": 42, "ok": True, "nothing": None}

    def test_env_assignment_in_tool_output(self):
        """Tool outputs that echo environment variables are redacted."""
        text = "OPENAI_API_KEY=sk-proj-abc123def456ghi789jkl012 was set"
        result = redact_trajectory_entry(text)
        assert "abc123def456" not in result

    def test_github_pat_in_assistant_message(self):
        token = "ghp_" + "a" * 20
        data = {"from": "assistant", "value": f"Using token {token}"}
        result = redact_trajectory_entry(data)
        assert "a" * 20 not in result["value"]

    def test_force_overrides_disabled_flag(self, monkeypatch):
        """redact_trajectory_entry uses force=True, so it ignores _REDACT_ENABLED=False."""
        monkeypatch.setattr("agent.redact._REDACT_ENABLED", False)
        secret = "sk-proj-abc123def456ghi789jkl012"
        result = redact_trajectory_entry(secret)
        # force=True path is exercised — secret must still be redacted
        assert "abc123def456" not in result


# ---------------------------------------------------------------------------
# Integration tests for save_trajectory()
# ---------------------------------------------------------------------------


class TestSaveTrajectoryRedaction:
    def _make_trajectory(self, secret: str):
        return [
            {"from": "human", "value": "Run a command"},
            {
                "from": "tool",
                "value": f"Executed: echo {secret}",
            },
            {"from": "assistant", "value": "Done."},
        ]

    def test_save_trajectory_redacts_openai_key(self, tmp_path):
        secret = "sk-proj-abc123def456ghi789jkl012"
        traj = self._make_trajectory(secret)
        out = tmp_path / "traj.jsonl"
        save_trajectory(traj, model="gpt-4o", completed=True, filename=str(out))
        content = out.read_text()
        assert "abc123def456" not in content

    def test_save_trajectory_writes_valid_jsonl(self, tmp_path):
        traj = [{"from": "human", "value": "Hello"}, {"from": "assistant", "value": "Hi"}]
        out = tmp_path / "traj.jsonl"
        save_trajectory(traj, model="gpt-4o", completed=True, filename=str(out))
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert "conversations" in entry
        assert entry["model"] == "gpt-4o"
        assert entry["completed"] is True

    def test_save_trajectory_appends_multiple_entries(self, tmp_path):
        traj = [{"from": "human", "value": "hi"}]
        out = tmp_path / "traj.jsonl"
        save_trajectory(traj, model="m", completed=True, filename=str(out))
        save_trajectory(traj, model="m", completed=True, filename=str(out))
        lines = [l for l in out.read_text().strip().split("\n") if l]
        assert len(lines) == 2

    def test_save_trajectory_redacts_with_disabled_flag(self, tmp_path, monkeypatch):
        """Even when global redaction is off, save_trajectory must still redact (force=True)."""
        monkeypatch.setattr("agent.redact._REDACT_ENABLED", False)
        secret = "sk-proj-abc123def456ghi789jkl012"
        traj = self._make_trajectory(secret)
        out = tmp_path / "traj.jsonl"
        save_trajectory(traj, model="test", completed=True, filename=str(out))
        assert "abc123def456" not in out.read_text()
