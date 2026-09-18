"""Durable text replacement with bounded Windows sharing-conflict retries."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import time


def atomic_write_text(path: str | Path, content: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent,
        prefix=path.name + ".", suffix=".tmp", delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    for attempt in range(8):
        try:
            os.replace(temporary, path)
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == 7:
                # Preserve both the old checkpoint and complete recovery file.
                raise
            time.sleep(min(0.05 * 2**attempt, 1.0))
