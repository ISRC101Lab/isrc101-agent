import pytest

from isrc101_agent.tools.git_ops import GitOps


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "config/.env.local",
        "secrets/private.key",
        "certs/server.pem",
        "keys/id_rsa",
    ],
)
def test_sensitive_path_detection(tmp_path, path):
    ops = GitOps(str(tmp_path))

    assert ops._is_sensitive_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "src/main.py",
        "web/app.js",
        "tests/test_utils.py",
        "README.md",
    ],
)
def test_non_sensitive_path_allowed(tmp_path, path):
    ops = GitOps(str(tmp_path))

    assert ops._is_sensitive_path(path) is False
