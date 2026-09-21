from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import polars as pl
import yaml


DEFAULT_SERIES_REGISTRY = (
    Path(__file__).resolve().parents[2] / "config" / "series_registry.yml"
)


@lru_cache(maxsize=8)
def inactive_series_ids(
    registry_path: str | Path = DEFAULT_SERIES_REGISTRY,
) -> frozenset[str]:
    """Return canonical series explicitly retired from user-facing outputs."""
    path = Path(registry_path)
    if not path.is_file():
        return frozenset()
    registry = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return frozenset(
        str(series_id)
        for series_id, spec in registry.items()
        if isinstance(spec, dict) and spec.get("active", True) is False
    )


def exclude_inactive_series(
    frame: pl.DataFrame,
    *,
    column: str = "canonical_series_id",
    registry_path: str | Path = DEFAULT_SERIES_REGISTRY,
) -> pl.DataFrame:
    """Hide retired fields while leaving append-only database rows intact."""
    inactive = inactive_series_ids(registry_path)
    if frame.is_empty() or not inactive or column not in frame.columns:
        return frame
    return frame.filter(~pl.col(column).is_in(sorted(inactive)))
