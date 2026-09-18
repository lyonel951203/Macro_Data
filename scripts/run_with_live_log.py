"""Stream a child process to the console and an append-only UTF-8 log."""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys


def _stamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write(stream, line: str) -> None:
    stream.write(line)
    stream.flush()


def run_command(command: list[str], log_path: Path) -> int:
    if not command:
        raise ValueError("a child command is required")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    start_line = f"[{_stamp()}] START {' '.join(command)}\n"
    with log_path.open("a", encoding="utf-8", buffering=1) as log:
        _write(sys.stdout, start_line)
        _write(log, start_line)
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=environment,
        )
        try:
            assert process.stdout is not None
            for line in process.stdout:
                _write(sys.stdout, line)
                _write(log, line)
            return_code = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            try:
                return_code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                return_code = process.wait()
            return_code = return_code or 130
        end_line = f"[{_stamp()}] EXIT code={return_code}\n"
        _write(sys.stdout, end_line)
        _write(log, end_line)
        return return_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Show unbuffered child output while appending the same text to a log."
    )
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    return run_command(command, args.log)


if __name__ == "__main__":
    raise SystemExit(main())
