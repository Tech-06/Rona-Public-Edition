import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_install_sh_has_valid_syntax():
    # Fed on stdin with LF endings: a Windows checkout has CRLF (which bash
    # rejects) and a WSL `bash` on PATH can't read a Windows drive path.
    script = (REPO_ROOT / "install.sh").read_text(encoding="utf-8").replace(chr(13) + chr(10), chr(10))
    result = subprocess.run(
        ["bash", "-n"], input=script.encode("utf-8"), capture_output=True
    )
    assert result.returncode == 0, result.stderr.decode()


def test_install_sh_probes_versioned_pythons_first():
    text = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    assert "python3.13 python3.12 python3.11 python3 python" in text
    assert "deadsnakes" in text and "uv python install 3.12" in text
