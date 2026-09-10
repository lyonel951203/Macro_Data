from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from bs4 import UnicodeDammit

from ..config import source_policy
from ..errors import ParserRowCountError
from ..http import FetchResult, PoliteHttpClient


@dataclass(frozen=True)
class SourceInventoryEntry:
    source: str
    dataset: str
    url: str
    earliest_period: str | None
    latest_period: str | None
    frequency: str
    format: str
    archive_available: bool
    release_timestamp_available: bool
    historical_revision_available: bool
    estimated_count: int | None
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BaseSource(ABC):
    source = ""
    country = ""
    parser_version = "v1"
    expected_min_rows = 1

    def __init__(
        self,
        *,
        allow_network: bool = False,
        config_path: str | Path | None = None,
        client: PoliteHttpClient | None = None,
    ) -> None:
        self.policy = source_policy(self.source, config_path)
        self.client = client or PoliteHttpClient(
            source=self.source,
            policy=self.policy,
            allow_network=allow_network,
        )

    def close(self) -> None:
        self.client.close()

    def fetch(
        self,
        url: str,
        *,
        refresh: bool = False,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        return self.client.fetch(url, refresh=refresh, headers=headers)

    def validate_row_count(self, rows: list[dict[str, Any]], expected_min_rows: int | None = None) -> None:
        minimum = self.expected_min_rows if expected_min_rows is None else expected_min_rows
        if len(rows) < minimum:
            raise ParserRowCountError(
                f"{self.source} parser returned {len(rows)} rows; expected at least {minimum}"
            )

    @abstractmethod
    def inventory(self) -> list[SourceInventoryEntry]:
        raise NotImplementedError


def decode_content(content: bytes) -> str:
    decoded = UnicodeDammit(content, ["utf-8", "gb18030", "gbk"])
    if decoded.unicode_markup is None:
        raise UnicodeError("unable to decode response as UTF-8/GB18030/GBK")
    return decoded.unicode_markup
