from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import duckdb
import yaml
from bs4 import BeautifulSoup

from .archive import RawArchive, RawArtifact
from .config import source_policy
from .db import insert_observations
from .errors import DataContractError
from .pipeline import SOURCE_CLASSES, _parse
from .sources.base import decode_content


@dataclass
class OfflineResult:
    source: str
    files: int = 0
    inserted: int = 0
    revisions: int = 0
    metadata_updates: int = 0
    unchanged: int = 0


def archive_manual_files(
    *,
    source_name: str,
    files: list[str | Path],
    raw_root: str | Path = "data/raw",
    config_path: str | Path | None = None,
) -> list[dict[str, str]]:
    """Copy manually downloaded official files into the immutable SHA raw layer."""
    source_key = source_name.upper()
    policy = source_policy(source_key, config_path)
    archive = RawArchive(raw_root)
    items: list[dict[str, str]] = []
    for file in files:
        path = Path(file)
        content = path.read_bytes()
        url = infer_official_url(source_key, content, policy)
        _validate_official_url(url, policy)
        artifact = archive.store(
            source=source_key,
            url=url,
            content=content,
            content_type=_content_type(path.suffix),
            retrieved_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
            extension=path.suffix.lstrip(".").lower() or None,
        )
        items.append({"path": artifact.path, "url": artifact.url})
    return items


def load_raw_manifest(path: str | Path) -> list[dict[str, str]]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    items = payload.get("items", [])
    if not items:
        raise ValueError("raw manifest requires a non-empty 'items' list")
    result = []
    for item in items:
        if not item.get("path"):
            raise ValueError("every raw manifest item requires path")
        result.append({"path": str(item["path"]), "url": str(item.get("url") or "")})
    return result


def ingest_raw_manifest(
    conn: duckdb.DuckDBPyConnection,
    *,
    source_name: str,
    items: list[dict[str, str]],
    config_path: str | Path | None = None,
) -> OfflineResult:
    source_key = source_name.upper()
    if source_key not in {"NBS", "PBOC", "CUSTOMS", "MOF", "SAFE"}:
        raise ValueError(f"unsupported source: {source_name}")
    source = SOURCE_CLASSES[source_key](allow_network=False, config_path=config_path)
    result = OfflineResult(source=source_key)
    try:
        for item in items:
            path = Path(item["path"])
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if path.stem.lower() != digest:
                raise DataContractError(
                    f"raw filename/hash mismatch: {path.name}; expected {digest}{path.suffix.lower()}"
                )
            url = item.get("url") or infer_official_url(source_key, content, source.policy)
            _validate_official_url(url, source.policy)
            artifact = RawArtifact(
                source=source_key,
                url=url,
                path=path.as_posix(),
                sha256=digest,
                content_type=_content_type(path.suffix),
                retrieved_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
                size=len(content),
            )
            rows = _parse(source, content, artifact)
            stats = insert_observations(conn, rows)
            result.files += 1
            result.inserted += stats.inserted
            result.revisions += stats.revisions
            result.metadata_updates += stats.metadata_updates
            result.unchanged += stats.unchanged
    finally:
        source.close()
    return result


def infer_official_url(source: str, content: bytes, policy: dict) -> str:
    if source not in {"PBOC", "MOF", "SAFE", "CUSTOMS"}:
        raise DataContractError(f"{source} raw manifest must provide the original official URL")
    soup = BeautifulSoup(decode_content(content), "lxml")
    for name in ("Url", "url", "URL"):
        node = soup.find("meta", attrs={"name": name})
        if node and node.get("content"):
            return urljoin(str(policy["base_url"]), str(node["content"]))
    canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
    if canonical and canonical.get("href"):
        return urljoin(str(policy["base_url"]), str(canonical["href"]))
    raise DataContractError(f"cannot infer official URL for {source}; add it explicitly to the raw manifest")


def _validate_official_url(url: str, policy: dict) -> None:
    parsed = urlparse(url)
    allowed = {str(host).lower() for host in policy.get("allowed_hosts", [])}
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in allowed:
        raise DataContractError(f"raw source URL is outside configured official hosts: {url}")


def _content_type(suffix: str) -> str:
    return {
        ".html": "text/html",
        ".htm": "text/html",
        ".json": "application/json",
        ".csv": "text/csv",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
    }.get(suffix.lower(), "application/octet-stream")
