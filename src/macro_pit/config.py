from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_sources_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else project_root() / "config" / "sources.yml"
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def source_policy(source: str, path: str | Path | None = None) -> dict[str, Any]:
    config = load_sources_config(path)
    result = deepcopy(config.get("network", {}))
    result.update(config.get("defaults", {}))
    source_values = config.get("sources", {}).get(source.upper())
    if source_values is None:
        raise KeyError(f"source not configured: {source}")
    result.update(source_values)
    return result

