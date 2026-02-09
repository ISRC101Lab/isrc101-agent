import shlex
import subprocess
import sys
from unittest.mock import patch

from isrc101_agent.tools.shell import ShellExecutor


def test_blocked_command_basic(tmp_path):
    executor = ShellExecutor(project_root=str(tmp_path))

    result = executor.execute("rm -rf /")

    assert result.startswith("Blocked:")


def test_blocked_command_bypass_base64(tmp_path):
    executor = ShellExecutor(project_root=str(tmp_path))

    # base64("rm -rf /tmp/test")
    result = executor.execute("echo cm0gLXJmIC90bXAvdGVzdA== | base64 -d")

    assert result.startswith("Blocked:")
    assert "base64-decoded payload" in result


def test_blocked_command_bypass_variable(tmp_path):
    executor = ShellExecutor(project_root=str(tmp_path))

    result = executor.execute("a=r b=m c=-rf d=/tmp/test; $a$b $c $d")

    assert result.startswith("Blocked:")
    assert "variable expansion" in result


def test_safe_command_allowed(tmp_path):
    (tmp_path / "sample.txt").write_text("content", encoding="utf-8")
    executor = ShellExecutor(project_root=str(tmp_path))

    echo_output = executor.execute("echo hello")
    ls_output = executor.execute("ls")

    assert echo_output.strip() == "hello"
    assert "sample.txt" in ls_output
    assert not echo_output.startswith("Blocked:")
    assert not ls_output.startswith("Blocked:")


def test_timeout_handling(tmp_path):
    executor = ShellExecutor(project_root=str(tmp_path), timeout=1)

    with patch(
        "isrc101_agent.tools.shell.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="bash -c sleep 5", timeout=1),
    ):
        result = executor.execute("sleep 5")

    assert result == "Timed out after 1s"


def test_output_truncation(tmp_path):
    executor = ShellExecutor(project_root=str(tmp_path))
    py = shlex.quote(sys.executable)

    result = executor.execute(f"{py} -c \"print(\\\"a\\\" * 9001)\"")

    assert "...(truncated)..." in result
    assert len(result) < 9001
