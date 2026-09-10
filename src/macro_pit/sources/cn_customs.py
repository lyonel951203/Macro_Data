from __future__ import annotations

import re

from ..archive import RawArtifact
from .base import BaseSource, SourceInventoryEntry
from .cn_common import extract_period_from_title, extract_release_evidence, html_text, make_observation, signed_percent


class CustomsSource(BaseSource):
    source = "CUSTOMS"
    country = "CN"
    parser_version = "customs_release_v1"

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
                        value=float(match.group("amount").replace(",", "")),
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
                value = float(balance.group("value").replace(",", ""))
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


CustomsScraper = CustomsSource
