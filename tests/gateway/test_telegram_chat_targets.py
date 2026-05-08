"""Tests for Telegram chat target validation and coercion."""

from __future__ import annotations

import logging
import os
from unittest.mock import patch

import pytest

from gateway.config import Platform


def test_coerce_chat_id_accepts_numeric_ids_and_public_channels():
    from gateway.platforms.telegram import _coerce_chat_id

    assert _coerce_chat_id("12345") == 12345
    assert _coerce_chat_id("-10012345") == -10012345
    assert _coerce_chat_id("@public_channel") == "@public_channel"


def test_coerce_chat_id_rejects_bare_usernames():
    from gateway.platforms.telegram import _coerce_chat_id

    with pytest.raises(ValueError, match="Invalid Telegram chat_id"):
        _coerce_chat_id("grox4xo")


def test_invalid_telegram_home_channel_is_ignored(caplog):
    from gateway.config import load_gateway_config

    env = {
        "TELEGRAM_BOT_TOKEN": "fake-token",
        "TELEGRAM_HOME_CHANNEL": "grox4xo",
    }

    with patch.dict(os.environ, env, clear=False), caplog.at_level(logging.ERROR):
        config = load_gateway_config()

    assert Platform.TELEGRAM in config.platforms
    assert config.platforms[Platform.TELEGRAM].home_channel is None
    assert "Invalid TELEGRAM_HOME_CHANNEL" in caplog.text


def test_public_channel_home_channel_is_loaded():
    from gateway.config import load_gateway_config

    env = {
        "TELEGRAM_BOT_TOKEN": "fake-token",
        "TELEGRAM_HOME_CHANNEL": "@grox4xo",
        "TELEGRAM_HOME_CHANNEL_NAME": "Home Channel",
    }

    with patch.dict(os.environ, env, clear=False):
        config = load_gateway_config()

    home = config.platforms[Platform.TELEGRAM].home_channel
    assert home is not None
    assert home.chat_id == "@grox4xo"
    assert home.name == "Home Channel"
