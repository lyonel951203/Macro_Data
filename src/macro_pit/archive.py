from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .timeutils import SHANGHAI, ensure_aware


@dataclass(frozen=True)
class RawArtifact:
    source: str
    url: str
    path: str
    sha256: str
    content_type: str
    retrieved_at: datetime
    size: int


class RawArchive:
    def __init__(self, root: str | Path = "data/raw") -> None:
        self.root = Path(root)

    def store(
        self,
        *,
        source: str,
        url: str,
        content: bytes,
        content_type: str | None,
        retrieved_at: datetime,
        extension: str | None = None,
    ) -> RawArtifact:
        retrieved_utc = ensure_aware(retrieved_at)
        local_date = retrieved_utc.astimezone(SHANGHAI)
        digest = hashlib.sha256(content).hexdigest()
        ext = extension or _extension(url, content_type)
        directory = self.root / source.lower() / f"{local_date.year:04d}" / f"{local_date.month:02d}" / f"{local_date.day:02d}"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{digest}.{ext}"
        if not target.exists():
            temporary = target.with_suffix(target.suffix + ".tmp")
            temporary.write_bytes(content)
            os.replace(temporary, target)
        return RawArtifact(
            source=source.upper(),
            url=url,
            path=target.as_posix(),
            sha256=digest,
            content_type=content_type or "application/octet-stream",
            retrieved_at=retrieved_utc,
            size=len(content),
        )


class UrlCache:
    """Small URL-to-raw-file index used for cache-first and conditional GETs."""

    def __init__(self, root: str | Path = "data/http_cache") -> None:
        self.root = Path(root)

    def _path(self, source: str, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.root / source.lower() / f"{digest}.json"

    def get(self, source: str, url: str) -> dict[str, Any] | None:
        path = self._path(source, url)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def put(self, source: str, url: str, values: dict[str, Any]) -> None:
        path = self._path(source, url)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)


def _extension(url: str, content_type: str | None) -> str:
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    mapping = {
        "text/html": "html",
        "application/json": "json",
        "text/json": "json",
        "text/csv": "csv",
        "application/pdf": "pdf",
        "application/vnd.ms-excel": "xls",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "application/vnd.sdmx.structure+xml": "xml",
        "application/vnd.sdmx.genericdata+xml": "xml",
        "text/plain": "txt",
    }
    if media_type in mapping:
        return mapping[media_type]
    suffix = Path(urlparse(url).path).suffix.lower().lstrip(".")
    return suffix if suffix in {"html", "htm", "json", "csv", "pdf", "xls", "xlsx", "txt"} else "bin"
