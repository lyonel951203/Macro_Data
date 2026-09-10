"""Independently check reviewed economy cells, then optionally append corrections."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import shutil

from lxml import html
import pandas as pd

from macro_pit.archive import RawArtifact
from macro_pit.db import OBSERVATION_COLUMNS, get_connection, insert_observations
from macro_pit.pit import get_snapshot
from macro_pit.sources.cn_nbs import NBSSource
from macro_pit.timeutils import SHANGHAI, ensure_aware

OUT = Path("reports/v2/nbs_economy_batch1")


def compact(text):
    return re.sub(r"\s+", "", text)


def validate(*, ingest=False):
    expected = json.loads(Path("config/nbs_economy_review_values.json").read_text(encoding="utf-8"))
    inventory = pd.read_csv(OUT / "cached_economy_inventory.csv")
    raw_map = json.loads((OUT / "artifacts.json").read_text(encoding="utf-8"))
    sample = json.loads(Path("data/history_backfill/nbs_economy_sample_batch1_state.json").read_text(encoding="utf-8"))
    per_hash = {row.periods: row.raw_sha256 for row in inventory.itertuples()}
    per_hash.update({v["period"]: v["artifact"]["sha256"] for v in sample["items"].values()})
    labels = {"CN_INDUSTRIAL_VALUE_ADDED_YOY": "规模以上工业增加值", "CN_RETAIL_SALES_YOY": "社会消费品零售总额",
              "CN_CPI_YOY": "居民消费价格", "CN_PPI_YOY": "工业.*出厂价格"}
    body_quotes = {("2022-11", "CN_SERVICE_PRODUCTION_YOY"): "11月份，全国服务业生产指数同比下降1.9%",
                   ("2024-06", "CN_INFRA_INVESTMENT_YTD_YOY"): "分领域看，基础设施投资增长5.4%"}
    evidence, records = [], []
    source = NBSSource(allow_network=False)
    try:
        for period, specifications in expected.items():
            artifact = dict(raw_map[per_hash[period]])
            artifact["retrieved_at"] = ensure_aware(artifact["retrieved_at"])
            artifact = RawArtifact(**artifact)
            content = Path(artifact.path).read_bytes()
            assert hashlib.sha256(content).hexdigest() == artifact.sha256
            tree = html.fromstring(content, parser=html.HTMLParser(encoding="utf-8"))
            title = compact(tree.findtext('.//title'))
            headers = tree.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " detail-title-des ")]')
            assert len(headers) == 1
            stamp, = re.findall(r"20\d\d/\d\d/\d\d\s+\d\d:\d\d(?::\d\d)?", headers[0].text_content())
            stamp = " ".join(stamp.split())
            fmt = "%Y/%m/%d %H:%M:%S" if stamp.count(":") == 2 else "%Y/%m/%d %H:%M"
            release = datetime.strptime(stamp, fmt).replace(tzinfo=SHANGHAI)
            # All selected articles concern the preceding calendar month.
            assert str(pd.Period(release.date(), freq="M")-1) == period
            month = int(period[-2:])
            bodies = tree.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " txt-content ")]')
            assert len(bodies) == 1
            body = bodies[0]
            body_text = compact(body.text_content())
            parsed = {(r["canonical_series_id"], r["period"]): r for r in source.parse(content, artifact)}
            if period.startswith("2010"):
                candidate = next(x for x in sample["items"].values() if x["period"] == period)
                search_raw = Path(candidate["index_raw_file"])
                search_data = json.loads(search_raw.read_text(encoding="utf-8"))
                docs = [x["data"] for x in search_data["resultDocs"] if x.get("data",{}).get("url") == artifact.url]
                assert len(docs) == 1 and compact(docs[0]["titleO"]) in title
                assert docs[0]["docDate"] == release.date().isoformat()
            for canonical, value in specifications.items():
                row = parsed[(canonical, period)]
                assert row["value"] == value, (period, canonical, row["value"], value)
                assert row["release_at"] == release and row["available_at"] == release
                assert row["pit_grade"] == "A" and row["unit"] == "pct_yoy"
                matches = []
                if (period, canonical) in body_quotes:
                    quote = body_quotes[(period, canonical)]
                    assert quote in body_text
                    matches = [quote]
                    method = "manually_reviewed_body_sentence"
                else:
                    for table in body.xpath('.//table'):
                        table_rows = [[compact(''.join(c.itertext())) for c in tr.xpath('./th|./td')]
                                      for tr in table.xpath('.//tr')]
                        eligible = any(len(c)==3 and c[1]==f"{month}月" and
                                       c[2].replace("—", "-")==f"1-{month}月" for c in table_rows[:8])
                        if not eligible:
                            continue
                        for cells in table_rows:
                            if len(cells)==6 and cells[0]=="":
                                cells=cells[1:]
                            if len(cells)!=5:
                                continue
                            name = re.sub(r"^[一二三四五六七八九十]+、", "", cells[0])
                            name = re.sub(r"（亿元）$", "", name)
                            if re.fullmatch(labels[canonical], name):
                                assert float(cells[2]) == value, (period, canonical, cells)
                                matches.append(" | ".join(cells))
                    assert matches, (period, canonical, "independent table cell absent")
                    method = "manual_expected_value_lxml_monthly_yoy_cell"
                evidence.append(dict(canonical_series_id=canonical, period=period, value=value,
                    release_at=release.isoformat(), available_at=release.isoformat(), pit_grade="A",
                    timestamp_evidence=stamp, value_evidence=matches[0], method=method,
                    url=artifact.url, raw_file=artifact.path, raw_sha256=artifact.sha256, result="PASS"))
                records.append(row)
    finally:
        source.close()
    assert len(records) == 30
    with get_connection(":memory:") as conn:
        first = insert_observations(conn, records)
        replay = insert_observations(conn, records)
        assert first.inserted == 30 and replay.inserted == 0 and replay.unchanged == 30
        for row in records:
            for delta, should_exist in [(-1, False), (0, True)]:
                frame = get_snapshot(conn, (row["available_at"]+timedelta(seconds=delta)).isoformat(), "CN")
                found = [x for x in frame.to_dicts() if x["canonical_series_id"]==row["canonical_series_id"]
                         and x["period"]==row["period"] and x["value"]==row["value"]]
                assert bool(found) == should_exist
    pd.DataFrame(evidence).to_csv(OUT / "validated_samples.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(records).to_parquet(OUT / "validated_observations.parquet", index=False)
    # Every replay difference must be either explicitly reviewed or a later
    # repeat of an already covered PMI/PPI value; no unexplained removals allowed.
    changes = pd.read_csv(OUT / "parser_change_audit.csv")
    reviewed_keys = {(r["raw_sha256"],r["canonical_series_id"],r["period"]) for r in records}
    before = pd.read_parquet(OUT / "before_nbs_observations.parquet")
    corrections = changes[changes.kind.eq("correction")].copy()
    assert len(corrections) == 13 and corrections.changed_fields.eq("value").all()
    assert all((r.raw_sha256, r.canonical_series_id, r.period) in reviewed_keys
               for r in corrections.itertuples())
    new_keys = {(r["canonical_series_id"], r["period"]) for r in records} - set(
        zip(before.canonical_series_id, before.period))
    assert len(new_keys) == 17
    corrections["reason"] = "parser_correction_monthly_vs_cumulative_or_wrong_month"
    corrections["official_statistical_revision"] = False
    corrections["original_rows_retained"] = True
    corrections.to_csv(OUT / "parser_correction_ledger.csv", index=False, encoding="utf-8-sig")
    # Preserve the original vintage numbers in a disposable copy and prove that
    # the corrected observations win snapshot selection before touching main.
    with get_connection(":memory:") as conn:
        conn.register("baseline", before[OBSERVATION_COLUMNS])
        conn.execute("INSERT INTO observation_vintage SELECT * FROM baseline")
        simulated = insert_observations(conn, records)
        assert simulated.inserted == 30
        assert conn.execute("SELECT count(*) FROM observation_vintage").fetchone()[0] == len(before)+30
        assert conn.execute("SELECT count(*) FROM (SELECT * FROM baseline EXCEPT ALL SELECT * FROM observation_vintage)").fetchone()[0] == 0
        for row in records:
            frame = get_snapshot(conn, row["available_at"].isoformat(), "CN")
            chosen = [x for x in frame.to_dicts() if x["canonical_series_id"]==row["canonical_series_id"]
                      and x["period"]==row["period"]]
            assert len(chosen)==1 and chosen[0]["value"]==row["value"]
    excluded=[]
    for row in changes.itertuples():
        if (row.raw_sha256,row.canonical_series_id,row.period) in reviewed_keys:
            continue
        same = before[before.canonical_series_id.eq(row.canonical_series_id) & before.period.eq(row.period)
                      & before.value.eq(row.after_value)]
        assert row.kind=="addition" and len(same), row
        excluded.append(dict(raw_sha256=row.raw_sha256, canonical_series_id=row.canonical_series_id,
                             period=row.period, value=row.after_value, reason="already_covered_value_not_ingested"))
    pd.DataFrame(excluded).to_csv(OUT / "excluded_repeated_values.csv", index=False, encoding="utf-8-sig")
    summary = dict(reviewed_articles=len(expected), reviewed_records=len(records),
                   corrected_parser_records=13, new_series_periods=17, excluded_repeat_values=len(excluded),
                   independent_value_and_timestamp="PASS", sha256="PASS", release_boundary_checks=60,
                   baseline_preservation="PASS", corrected_snapshot_checks=30,
                   simulated_insert_stats=asdict(simulated),
                   idempotency="PASS", review_time=datetime.now(SHANGHAI).isoformat())
    if ingest:
        if Path("data/history_backfill/nbs_price_batch.lock").exists():
            raise RuntimeError("Another NBS batch holds the write lock")
        backup = OUT / "before"
        backup.mkdir(exist_ok=True)
        for p in Path("data/exports").glob("cn_pit_month_end_2005_20260731*"):
            if not (backup/p.name).exists():
                shutil.copyfile(p, backup/p.name)
        with get_connection("macro_pit_v2.duckdb") as conn:
            before_count = conn.execute("SELECT count(*) FROM observation_vintage").fetchone()[0]
            result = insert_observations(conn, records)
            conn.register("baseline", before[OBSERVATION_COLUMNS])
            assert conn.execute("SELECT count(*) FROM (SELECT * FROM baseline EXCEPT ALL SELECT * FROM observation_vintage WHERE source='NBS')").fetchone()[0] == 0
            for row in records:
                frame = get_snapshot(conn, row["available_at"].isoformat(), "CN")
                selected = [r for r in frame.to_dicts() if r["canonical_series_id"]==row["canonical_series_id"]
                            and r["period"]==row["period"]]
                assert len(selected)==1 and selected[0]["value"]==row["value"]
            after_count = conn.execute("SELECT count(*) FROM observation_vintage").fetchone()[0]
        result_data = dict(before_rows=before_count, after_rows=after_count, stats=asdict(result),
                           verified_current_snapshots=True, **summary)
        target = OUT / ("ingestion_replay.json" if (OUT / "ingestion_result.json").exists() else "ingestion_result.json")
        target.write_text(json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["ingestion"] = result_data
    (OUT / "validation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ingest", action="store_true")
    validate(ingest=p.parse_args().ingest)
