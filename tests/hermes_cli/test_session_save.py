"""Tests for the /save current-session export helpers."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from hermes_cli.session_export import (
    SAVE_FORMATS,
    default_save_filename,
    normalize_save_format,
    render_session_for_save,
)
from hermes_cli.session_export_md import redact_session_for_messaging


SESSION = {
    "id": "20260814_abc123",
    "title": "Test Session",
    "model": "test-model",
    "started_at": 1755100000,
    "messages": [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
        {"role": "tool", "content": "tool output"},
    ],
}


class TestNormalizeSaveFormat:
    def test_default_is_json(self):
        assert normalize_save_format(None) == "json"
        assert normalize_save_format("") == "json"

    def test_aliases(self):
        assert normalize_save_format("markdown") == "md"
        assert normalize_save_format("MD") == "md"
        assert normalize_save_format("HTML") == "html"
        assert normalize_save_format("snapshot") == "json"

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            normalize_save_format("pdf")

    def test_all_declared_formats_normalize_to_themselves(self):
        for fmt in SAVE_FORMATS:
            assert normalize_save_format(fmt) == fmt


class TestRenderSessionForSave:
    def test_json_round_trips(self):
        out = render_session_for_save(SESSION, "json")
        data = json.loads(out)
        assert data["id"] == SESSION["id"]
        assert len(data["messages"]) == 3

    def test_markdown_contains_messages(self):
        out = render_session_for_save(SESSION, "md")
        assert "Hello" in out
        assert "Hi there" in out

    def test_html_is_standalone_document(self):
        out = render_session_for_save(SESSION, "html")
        assert out.lstrip().lower().startswith("<!doctype html")
        assert "Hello" in out

    def test_html_survives_none_title_and_model(self):
        # Async title generation may not have run yet — None title/model is
        # the default state for a fresh session (PR #62268 regression).
        session = {**SESSION, "title": None, "model": None}
        out = render_session_for_save(session, "html")
        assert "<title>None</title>" not in out

    def test_unknown_format_raises(self):
        with pytest.raises(ValueError):
            render_session_for_save(SESSION, "pdf")


class TestDefaultSaveFilename:
    def test_basic(self):
        assert default_save_filename("abc-123", "md") == "hermes_session_abc-123.md"

    def test_hostile_session_id_sanitized(self):
        name = default_save_filename("../../etc/passwd", "json")
        assert "/" not in name
        assert ".." not in name.replace("etcpasswd", "")

    def test_empty_session_id(self):
        assert default_save_filename("", "html") == "hermes_session_session.html"


class TestMessagingExportProjection:
    def test_redacts_secrets_and_omits_tool_records_without_mutating_source(self):
        session = {
            **SESSION,
            "system_prompt": "hidden system token sk-proj-abcdefghijklmnopqrstuvwxyz123456",
            "model_config": {"api_key": "sk-proj-abcdefghijklmnopqrstuvwxyz123456"},
            "cwd": "/private/home/alice/project",
            "messages": [
                {"role": "user", "content": "Use sk-proj-abcdefghijklmnopqrstuvwxyz123456"},
                {"role": "assistant", "content": "Done", "tool_calls": [{"arguments": {"token": "secret"}}]},
                {"role": "tool", "name": "shell", "content": "API_KEY=super-secret-value"},
            ],
            "segments": [{"messages": [{"role": "user", "content": "segment secret sk-proj-abcdefghijklmnopqrstuvwxyz123456"}]}],
        }

        projected = redact_session_for_messaging(session)

        assert "segments" not in projected
        assert "system_prompt" not in projected
        assert "model_config" not in projected
        assert "cwd" not in projected
        assert all(message["role"] != "tool" for message in projected["messages"])
        assert all("tool_calls" not in message for message in projected["messages"])
        rendered = "\n".join(render_session_for_save(projected, fmt) for fmt in SAVE_FORMATS)
        assert "sk-proj-abcdefghijklmnopqrstuvwxyz123456" not in rendered
        assert "API_KEY=super-secret-value" not in rendered
        assert session["messages"][1]["tool_calls"]
        assert session["messages"][2]["role"] == "tool"

    @pytest.mark.asyncio
    async def test_gateway_save_always_sends_safe_projection(self):
        from gateway.config import Platform
        from gateway.platforms.event import MessageEvent
        from gateway.session import SessionSource
        from gateway.slash_commands_session import GatewaySessionCommandsMixin

        raw = {
            "id": "session-1",
            "system_prompt": "hidden system instruction",
            "model_config": {"api_key": "sk-proj-abcdefghijklmnopqrstuvwxyz123456"},
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "using sk-proj-abcdefghijklmnopqrstuvwxyz123456"},
                {"role": "tool", "content": "private tool result"},
            ],
        }
        captured = {}

        async def send_document(**kwargs):
            captured["body"] = Path(kwargs["file_path"]).read_text(encoding="utf-8")

        class Handler(GatewaySessionCommandsMixin):
            async_session_store = SimpleNamespace(
                get_or_create_session=AsyncMock(return_value=SimpleNamespace(session_id="session-1")))
            _session_db = SimpleNamespace(export_session=AsyncMock(return_value=raw))

            @staticmethod
            def get_adapter(_platform):
                return SimpleNamespace(send_document=send_document)

        event = MessageEvent(
            text="/save json",
            source=SessionSource(platform=Platform.TELEGRAM, chat_id="chat-1", user_id="user-1"),
        )
        result = await Handler()._handle_save_command(event)

        assert result == "Export complete."
        assert "hello" in captured["body"]
        assert "sk-proj-abcdefghijklmnopqrstuvwxyz123456" not in captured["body"]
        assert "private tool result" not in captured["body"]
        assert "hidden system instruction" not in captured["body"]
        assert "model_config" not in captured["body"]
