"""Regression tests for fork-specific installer defaults."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_install_sh_defaults_to_groxaxo_repo() -> None:
    text = (REPO_ROOT / "scripts" / "install.sh").read_text()

    assert 'REPO_OWNER="${HERMES_REPO_OWNER:-groxaxo}"' in text
    assert 'REPO_NAME="${HERMES_REPO_NAME:-hermes-agent}"' in text
    assert 'https://raw.githubusercontent.com/groxaxo/hermes-agent/main/scripts/install.sh' in text


def test_install_ps1_defaults_to_groxaxo_repo() -> None:
    text = (REPO_ROOT / "scripts" / "install.ps1").read_text()

    assert '{ "groxaxo" }' in text
    assert '{ "hermes-agent" }' in text
    assert "https://raw.githubusercontent.com/groxaxo/hermes-agent/main/scripts/install.ps1" in text


def test_install_cmd_bootstraps_groxaxo_repo() -> None:
    text = (REPO_ROOT / "scripts" / "install.cmd").read_text()

    assert "https://raw.githubusercontent.com/groxaxo/hermes-agent/main/scripts/install.cmd" in text
    assert "https://raw.githubusercontent.com/groxaxo/hermes-agent/main/scripts/install.ps1" in text
