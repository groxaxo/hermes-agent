"""Terminal lifecycle preflight must distinguish Python source from shell script operands."""
import pytest


from cron.lifecycle_guard import (
    _iter_referenced_shell_scripts,
    contains_gateway_lifecycle_command_or_referenced_script as check,
)
from tools.terminal_tool_guards import gateway_lifecycle_block


def test_quoted_python_heredoc_reads_large_log_without_executing_it(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.process_registry._is_supervised_gateway_process", lambda: True)
    log = tmp_path / "errors.log"
    log.write_text("ordinary log entry\n" * 70000)
    assert log.stat().st_size > 1024 * 1024
    command = (
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        f"p=Path({str(log)!r});lines=p.read_text(errors='replace').splitlines()\n"
        "print(len(lines))\n"
        "PY"
    )
    assert list(_iter_referenced_shell_scripts(command)) == []
    assert check(command) is False
    assert gateway_lifecycle_block(
        command=command, env=None, env_type="local", cwd=str(tmp_path),
        workdir=None, session_key="test",
    ) is None


def test_double_quoted_python_heredoc_reads_large_log(tmp_path):
    log = tmp_path / "errors.log"
    log.write_text("ordinary log entry\n" * 70000)
    assert log.stat().st_size > 1024 * 1024
    command = (
        'python3 - <<"PY"\n'
        'from pathlib import Path\n'
        f"p=Path({str(log)!r});lines=p.read_text(errors='replace').splitlines()\n"
        'print(len(lines))\nPY'
    )
    assert list(_iter_referenced_shell_scripts(command)) == []
    assert check(command) is False


def test_absolute_python3_heredoc_reads_large_log(tmp_path):
    log = tmp_path / "errors.log"
    log.write_text("ordinary log entry\n" * 70000)
    assert log.stat().st_size > 1024 * 1024
    command = (
        "/usr/bin/python3 - <<'PY'\n"
        "from pathlib import Path\n"
        f"p=Path({str(log)!r});lines=p.read_text(errors='replace').splitlines()\n"
        "print(len(lines))\nPY"
    )
    assert log not in list(_iter_referenced_shell_scripts(command))
    assert check(command) is False


def test_python_heredoc_prints_last_line_from_large_log(tmp_path):
    log = tmp_path / "errors.log"
    log.write_text("ordinary log entry\n" * 70000)
    assert log.stat().st_size > 1024 * 1024
    command = (
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        f"p=Path({str(log)!r});lines=p.read_text(errors='replace').splitlines()\n"
        "print(lines[-1])\nPY"
    )
    assert list(_iter_referenced_shell_scripts(command)) == []
    assert check(command) is False


def test_multiline_python_subprocess_cannot_hide_lifecycle_script(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.process_registry._is_supervised_gateway_process", lambda: True)
    script = tmp_path / "hermes_review_restart.sh"
    script.write_text("systemctl restart hermes-gateway\n")
    command = (
        "python3 - <<'PY'\n"
        "import subprocess\n"
        "subprocess.run([\n"
        "    'bash',\n"
        f"    {str(script)!r}\n"
        "])\n"
        "PY"
    )
    # This exercises only the guard; the heredoc and lifecycle script are never executed.
    assert check(command, cwd=str(tmp_path)) is True
    assert gateway_lifecycle_block(
        command=command, env=None, env_type="local", cwd=str(tmp_path),
        workdir=None, session_key="test",
    ) is not None


@pytest.mark.parametrize("opener", ["python3 - <<'PY'", 'python3 - <<"PY"',
                                   "/usr/bin/python3 - <<'PY'"])
def test_variant_heredocs_still_scan_executable_python_body(tmp_path, opener):
    script = tmp_path / "restart.sh"
    script.write_text("systemctl restart hermes-gateway\n")
    bodies = (
        f"import subprocess\nsubprocess.run([\n 'bash',\n {str(script)!r}\n])",
        f"from pathlib import Path\np=Path({str(script)!r})\nimport os\nos.system('bash ' + str(p))",
        f"from pathlib import Path\nPath=lambda x: x\nprint({str(script)!r})",
    )
    for body in bodies:
        command = f"{opener}\n{body}\nPY"
        assert check(command, cwd=str(tmp_path)), (opener, body)


def test_last_line_expression_with_unknown_call_stays_scanned(tmp_path):
    script = tmp_path / "restart.sh"
    script.write_text("systemctl restart hermes-gateway\n")
    command = (
        "python3 - <<'PY'\nfrom pathlib import Path\n"
        f"lines=Path({str(script)!r}).read_text(errors='replace').splitlines()\n"
        "print(lines[-1]);import subprocess\n"
        f"subprocess.run(['bash', {str(script)!r}])\nPY"
    )
    assert check(command, cwd=str(tmp_path))


def test_quoted_heredoc_does_not_hide_executed_lifecycle_calls(tmp_path):
    script = tmp_path / "restart.sh"
    script.write_text("systemctl restart hermes-gateway\n")
    commands = (
        "python3 -c 'import os; os.system(\"hermes gateway restart\")'",
        "launchctl submit -l other.job -- /bin/true",
        "bash <<'SH'\nsource restart.sh\nSH",
        f"python3 - <<'PY'\nprint('safe')\nPY\nbash {script}",
        f"python3 - <<'PY'\nfrom pathlib import Path\np=Path({str(script)!r})\nimport subprocess\nsubprocess.run([\n 'bash',\n {str(script)!r}\n])\nPY",
        f"python3 - <<'PY'\nfrom pathlib import Path\nPath=lambda x: x\nprint({str(script)!r})\nPY",
    )
    for command in commands:
        assert check(command, cwd=str(tmp_path)), command
