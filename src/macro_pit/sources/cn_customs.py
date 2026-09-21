from __future__ import annotations

import math
import re

from ..archive import RawArtifact
from .base import BaseSource, SourceInventoryEntry
from .cn_common import extract_period_from_title, extract_release_evidence, html_text, make_observation, signed_percent


class CustomsSource(BaseSource):
    source = "CUSTOMS"
    country = "CN"
    parser_version = "customs_release_v2"

    def inventory(self) -> list[SourceInventoryEntry]:
        return [
            SourceInventoryEntry(
                source=self.source,
                dataset="海关统计月度进出口总值及国别表",
                url="http://www.customs.gov.cn/customs/302249/zfxxgk/2799825/302274/index.html",
                earliest_period=None,
                latest_period=None,
                frequency="M",
                format="html/xls",
                archive_available=True,
                release_timestamp_available=True,
                historical_revision_available=True,
                estimated_count=None,
                evidence="起止期与附件格式必须由限速 discovery 从官方索引确认",
            )
        ]

    def parse_release(self, content: bytes, artifact: RawArtifact) -> list[dict]:
        soup, text = html_text(content)
        english_rows = self._parse_english_usd_summary(soup, text, artifact)
        if english_rows is not None:
            self.validate_row_count(english_rows, expected_min_rows=5)
            return english_rows

        year, month = extract_period_from_title(soup, text)
        release = extract_release_evidence(soup, text, artifact.retrieved_at)
        rows: list[dict] = []

        for currency_label, currency_id, unit in (
            ("亿元", "CNY", "bn_cny"),
            ("亿美元", "USD", "bn_usd"),
        ):
            for label, canonical in (("出口", "EXPORT"), ("进口", "IMPORT")):
                pattern = rf"(?<!进){label}(?:总值|金额|额)?\s*(?:为|达)?\s*(?P<amount>[\d,.]+)\s*{currency_label}[^。；]{{0,80}}?同比(?P<direction>增长|下降)(?P<yoy>[\d.]+)[%％]"
                match = re.search(pattern, text)
                if not match:
                    continue
                rows.append(
                    make_observation(
                        source=self.source,
                        canonical_series_id=f"CN_{canonical}_{currency_id}",
                        source_series_id=f"{canonical}_{currency_id}",
                        series_name=f"{label}{currency_id}金额",
                        unit=unit,
                        year=year,
                        month=month,
                        # 亿 units are 0.1 billion units in the canonical table.
                        value=float(match.group("amount").replace(",", "")) * 0.1,
                        artifact=artifact,
                        release=release,
                        parser_version=self.parser_version,
                    )
                )
                rows.append(
                    make_observation(
                        source=self.source,
                        canonical_series_id=f"CN_{canonical}_{currency_id}_YOY",
                        source_series_id=f"{canonical}_{currency_id}_YOY",
                        series_name=f"{label}{currency_id}同比",
                        unit="pct_yoy",
                        year=year,
                        month=month,
                        value=signed_percent(match.group("yoy"), match.group("direction")),
                        artifact=artifact,
                        release=release,
                        parser_version=self.parser_version,
                    )
                )

            balance = re.search(rf"贸易(?P<direction>顺差|逆差)\s*(?P<value>[\d,.]+)\s*{currency_label}", text)
            if balance:
                value = float(balance.group("value").replace(",", "")) * 0.1
                if balance.group("direction") == "逆差":
                    value = -value
                rows.append(
                    make_observation(
                        source=self.source,
                        canonical_series_id=f"CN_TRADE_BALANCE_{currency_id}",
                        source_series_id=f"TRADE_BALANCE_{currency_id}",
                        series_name=f"贸易差额{currency_id}",
                        unit=unit,
                        year=year,
                        month=month,
                        value=value,
                        artifact=artifact,
                        release=release,
                        parser_version=self.parser_version,
                    )
                )

        self.validate_row_count(rows)
        return rows

    def _parse_english_usd_summary(
        self,
        soup,
        text: str,
        artifact: RawArtifact,
    ) -> list[dict] | None:
        """Parse GACC's official English USD total-trade release table.

        The table exposes the current-month amount, year-to-date amount,
        month-on-month rate, current-month year-on-year rate and cumulative
        year-on-year rate. Only the current-month amount and current-month
        year-on-year rate are accepted here.
        """
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        marker = f"{title} {text[:500]}".lower()
        if not (
            ("total export & import values" in marker or "summary of imports and exports" in marker)
            and ("in usd" in marker or "usd 100 million" in marker or "us$" in marker)
        ):
            return None

        year, month = _english_period(title or text)
        release = extract_release_evidence(soup, text, artifact.retrieved_at)
        values: dict[str, list[float]] = {}
        for table in soup.find_all("table"):
            for tr in table.find_all("tr"):
                cells = [
                    " ".join(cell.get_text(" ", strip=True).split())
                    for cell in tr.find_all(["th", "td"], recursive=False)
                ]
                if len(cells) < 2:
                    continue
                label = re.sub(r"\s+", " ", cells[0]).strip().lower()
                key = _english_trade_row(label)
                if key is None:
                    continue
                numbers = [_number(cell) for cell in cells[1:]]
                values[key] = [value for value in numbers if value is not None]

        required = {"export", "import", "balance"}
        if not required.issubset(values):
            return None
        if len(values["export"]) < 4 or len(values["import"]) < 4:
            return None
        if not values["balance"]:
            return None

        export_amount = values["export"][0] * 0.1
        import_amount = values["import"][0] * 0.1
        balance_amount = values["balance"][0] * 0.1
        if not math.isclose(
            export_amount - import_amount,
            balance_amount,
            rel_tol=0.0,
            abs_tol=0.021,
        ):
            raise ValueError(
                "GACC USD table fails export-import=balance check: "
                f"{export_amount} - {import_amount} != {balance_amount}"
            )

        observations = (
            ("CN_EXPORT_USD", "EXPORT_USD", "出口USD金额", "bn_usd", export_amount),
            ("CN_IMPORT_USD", "IMPORT_USD", "进口USD金额", "bn_usd", import_amount),
            ("CN_TRADE_BALANCE_USD", "TRADE_BALANCE_USD", "贸易差额USD", "bn_usd", balance_amount),
            ("CN_EXPORT_USD_YOY", "EXPORT_USD_YOY", "出口USD同比", "pct_yoy", values["export"][3]),
            ("CN_IMPORT_USD_YOY", "IMPORT_USD_YOY", "进口USD同比", "pct_yoy", values["import"][3]),
        )
        return [
            make_observation(
                source=self.source,
                canonical_series_id=canonical,
                source_series_id=source_id,
                series_name=name,
                unit=unit,
                year=year,
                month=month,
                value=value,
                artifact=artifact,
                release=release,
                parser_version=self.parser_version,
            )
            for canonical, source_id, name, unit, value in observations
        ]


_ENGLISH_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("january", "jan"), ("february", "feb"), ("march", "mar"),
            ("april", "apr"), ("may",), ("june", "jun"),
            ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"),
            ("october", "oct"), ("november", "nov"), ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}


def _english_period(text: str) -> tuple[int, int]:
    normalized = " ".join(text.split()).lower()
    month_names = "|".join(sorted(_ENGLISH_MONTHS, key=len, reverse=True))
    match = re.search(rf"\b({month_names})\.?\s*,?\s*(20\d{{2}})\b", normalized)
    if match:
        return int(match.group(2)), _ENGLISH_MONTHS[match.group(1)]
    match = re.search(r"\b(0?[1-9]|1[0-2])\s*\.\s*(20\d{2})\b", normalized)
    if match:
        return int(match.group(2)), int(match.group(1))
    raise ValueError("English GACC monthly period not found in title")


def _english_trade_row(label: str) -> str | None:
    cleaned = label.replace("–", "-").replace("—", "-")
    if cleaned in {"total export", "exports", "export"}:
        return "export"
    if cleaned in {"total import", "imports", "import"}:
        return "import"
    if cleaned in {
        "export-import balance", "export - import balance", "trade balance",
    }:
        return "balance"
    return None


def _number(value: str) -> float | None:
    normalized = value.replace("−", "-").replace("–", "-").replace("—", "-")
    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", normalized)
    return float(match.group(0).replace(",", "")) if match else None


CustomsScraper = CustomsSource
