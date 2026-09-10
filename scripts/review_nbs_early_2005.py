"""Independently validate manually reviewed historical quotes; opt in to append."""
import argparse
from dataclasses import asdict
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import runpy

from lxml import html
import pandas as pd

from macro_pit.archive import RawArtifact
from macro_pit.db import OBSERVATION_COLUMNS, get_connection, insert_observations
from macro_pit.errors import ParserRowCountError
from macro_pit.snapshot import get_snapshot
from macro_pit.sources.cn_nbs import NBSSource
from macro_pit.timeutils import SHANGHAI

OUT = Path("reports/v2/nbs_early_2005")


def compact(value):
    return re.sub(r"\s+", "", value).replace("％", "%")


def review(ingest=False):
    state = json.loads(Path("data/history_backfill/nbs_early_2005_download_state.json").read_text(encoding="utf-8"))
    specs = json.loads(Path("config/nbs_early_2005_review_values.json").read_text(encoding="utf-8"))["items"]
    manifest = Path("config/nbs_early_2005_candidates.json")
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == state["manifest_sha256"]
    assert state["status"] == "COMPLETE" and len(specs) == len(state["items"])
    baseline = pd.read_parquet(OUT / "before_nbs_observations.parquet")
    baseline_keys = set(zip(baseline.canonical_series_id, baseline.period))
    rows = []; evidence = []; excluded = []
    source = NBSSource(allow_network=False)
    try:
        for spec in specs:
            item = state["items"][spec["url"]]
            details = item["artifact"].copy()
            details["retrieved_at"] = datetime.fromisoformat(details["retrieved_at"])
            artifact = RawArtifact(**details)
            content = Path(artifact.path).read_bytes()
            assert len(content) == artifact.size
            assert hashlib.sha256(content).hexdigest() == artifact.sha256
            doc = html.fromstring(content.decode("utf-8"))
            title = compact(doc.xpath("string(//title)"))
            assert compact(item["title"]) in title
            bodies = doc.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " txt-content ")]')
            assert bodies
            text = compact("".join(bodies[0].itertext()))
            full = compact("".join(doc.itertext()))
            timestamp = spec["release_at"]
            release = datetime.fromisoformat(timestamp).replace(tzinfo=SHANGHAI)
            visible = release.strftime("%Y/%m/%d%H:%M")
            assert visible in full
            search = json.loads(Path(item["index_raw_file"]).read_text(encoding="utf-8"))
            docs = [x["data"] for x in search["resultDocs"] if x.get("data", {}).get("url") == spec["url"]]
            assert len(docs) == 1 and docs[0]["docDate"] == release.date().isoformat()
            if not spec["values"]:
                assert spec["exclusion_reason"] == "YTD_only_no_explicit_monthly_value"
                assert compact(spec["quote"]) in text
                try:
                    source.parse(content, artifact)
                except ParserRowCountError:
                    pass
                else:
                    raise AssertionError("YTD-only article unexpectedly produced monthly observations")
                excluded.append(dict(url=artifact.url, raw_file=artifact.path, raw_sha256=artifact.sha256,
                                     reason=spec["exclusion_reason"], quote=spec["quote"], result="PASS"))
                continue
            parsed = {(r["canonical_series_id"], r["period"]): r for r in source.parse(content, artifact)}
            expected_keys = {(v["canonical_series_id"], v["period"]) for v in spec["values"]}
            assert set(parsed) == expected_keys, (title, set(parsed), expected_keys)
            for expected in spec["values"]:
                key = (expected["canonical_series_id"], expected["period"])
                quote = compact(expected["quote"])
                assert quote in text and f"{abs(expected['value']):g}%" in quote
                row = parsed[key]
                assert row["value"] == expected["value"], (key, row["value"], expected["value"])
                assert row["release_at"] == release and row["available_at"] == release
                assert row["pit_grade"] == "A" and row["unit"] == "pct_yoy" and row["seasonal_adjustment"] == "NSA"
                assert key not in baseline_keys
                rows.append(row)
                evidence.append(dict(**expected, release_at=release.isoformat(), pit_grade="A", url=artifact.url,
                                     raw_file=artifact.path, raw_sha256=artifact.sha256, timestamp_evidence=visible,
                                     method="manual_expected_value_and_lxml_exact_body_quote", result="PASS"))
    finally:
        source.close()
    assert len(rows) == 11 and len({(r["canonical_series_id"],r["period"]) for r in rows}) == 11
    assert len(excluded) == 1
    with get_connection(":memory:") as conn:
        first = insert_observations(conn, rows)
        repeat = insert_observations(conn, rows)
        assert first.inserted == len(rows) and first.revisions == 0
        assert repeat.inserted == 0 and repeat.unchanged == len(rows)
        for row in rows:
            for seconds, visible in [(-1, False), (0, True)]:
                frame = get_snapshot(conn, (row["available_at"]+timedelta(seconds=seconds)).isoformat(), "CN")
                matching = [r for r in frame.to_dicts() if r["canonical_series_id"] == row["canonical_series_id"] and r["period"] == row["period"]]
                assert bool(matching) == visible
    pd.DataFrame(rows).to_parquet(OUT / "validated_observations.parquet", index=False)
    pd.DataFrame(evidence).to_csv(OUT / "validated_samples.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(excluded).to_csv(OUT / "excluded_articles.csv", index=False, encoding="utf-8-sig")
    result = dict(status="PASS", articles=len(specs), excluded_ytd_only_articles=len(excluded), new_series_periods=len(rows), release_boundary_checks=2*len(rows),
                  sha256="PASS", independent_body_and_time="PASS", idempotency="PASS", at=datetime.now(SHANGHAI).isoformat())
    if ingest:
        regression = json.loads((OUT / "regression_result.json").read_text(encoding="utf-8"))
        assert regression["status"] == "PASS"
        tests = json.loads((OUT / "test_results.json").read_text(encoding="utf-8"))
        assert tests["status"] == "PASS"
        assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest for path,digest in tests["sha256"].items())
        if Path("data/history_backfill/nbs_price_batch.lock").exists():
            raise RuntimeError("Another NBS batch holds the shared lock")
        with get_connection("macro_pit_v2.duckdb") as conn:
            count_before = conn.sql("SELECT count(*) FROM observation_vintage").fetchone()[0]
            stats = insert_observations(conn, rows)
            conn.register("frozen", baseline[OBSERVATION_COLUMNS])
            assert conn.sql("SELECT count(*) FROM (SELECT * FROM frozen EXCEPT ALL SELECT * FROM observation_vintage WHERE source='NBS')").fetchone()[0] == 0
            for row in rows:
                frame = get_snapshot(conn, row["available_at"].isoformat(), "CN")
                matches = [r for r in frame.to_dicts() if r["canonical_series_id"] == row["canonical_series_id"] and r["period"] == row["period"]]
                assert len(matches) == 1 and matches[0]["value"] == row["value"]
            count_after = conn.sql("SELECT count(*) FROM observation_vintage").fetchone()[0]
        ingestion = dict(before_rows=count_before, after_rows=count_after, stats=asdict(stats), baseline_preserved=True, **result)
        target = OUT / ("ingestion_replay.json" if (OUT / "ingestion_result.json").exists() else "ingestion_result.json")
        target.write_text(json.dumps(ingestion, ensure_ascii=False, indent=2), encoding="utf-8")
        result["ingestion"] = ingestion
    (OUT / "validation_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ingest", action="store_true")
    p.add_argument("--regress", action="store_true")
    args = p.parse_args()
    if args.regress:
        checker = runpy.run_path("scripts/regress_nbs_economy_batch2.py")["check"]
        checker.__globals__["OUT"] = OUT
        checker()
    else:
        review(args.ingest)
