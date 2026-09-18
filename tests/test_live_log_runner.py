from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_with_live_log.py"


def test_live_log_runner_tees_output_and_preserves_exit_code(tmp_path):
    log = tmp_path / "launcher.log"
    result = subprocess.run(
        [
            sys.executable,
            "-u",
            str(RUNNER),
            "--log",
            str(log),
            "--",
            sys.executable,
            "-u",
            "-c",
            "import sys; print('live-line', flush=True); sys.exit(7)",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    saved = log.read_text(encoding="utf-8")
    assert result.returncode == 7
    assert "live-line" in result.stdout
    assert "live-line" in saved
    assert "START" in result.stdout and "START" in saved
    assert "EXIT code=7" in result.stdout and "EXIT code=7" in saved
