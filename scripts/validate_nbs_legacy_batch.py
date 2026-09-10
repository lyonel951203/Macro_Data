"""Reproduce independent raw-review checks; ingest only a fully verified batch."""
import argparse
from dataclasses import asdict
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path

import pandas as pd
from macro_pit.archive import RawArtifact
from macro_pit.db import get_connection, insert_observations
from macro_pit.pit import get_snapshot
from macro_pit.sources.cn_common import html_text
from macro_pit.sources.cn_nbs import NBSSource
from macro_pit.timeutils import ensure_aware


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--ingest", action="store_true")
    parser.add_argument("--manifest", default="config/nbs_legacy_validation_batch.json")
    parser.add_argument("--state-path", default="data/history_backfill/nbs_legacy_validation_state.json")
    parser.add_argument("--expected", default="config/nbs_legacy_review_expected.json")
    parser.add_argument("--output-dir", default="reports/v2/nbs_legacy")
    args = parser.parse_args()
    os.chdir(Path(__file__).resolve().parents[1])
    state = json.loads(Path(args.state_path).read_text(encoding="utf-8"))
    expected_path = Path(args.expected)
    expected = {} if args.preview else json.loads(expected_path.read_text(encoding="utf-8"))
    source = NBSSource(allow_network=False)
    rows, evidence = [], []
    try:
        for url, item in state["items"].items():
            artifact = dict(item["artifact"])
            artifact["retrieved_at"] = ensure_aware(artifact["retrieved_at"])
            artifact = RawArtifact(**artifact)
            content = Path(artifact.path).read_bytes()
            if hashlib.sha256(content).hexdigest() != artifact.sha256:
                raise ValueError(f"Raw hash mismatch: {artifact.path}")
            soup, text = html_text(content)
            # Read the actual article body independently from whole-page parser matches.
            body = soup.select_one(".txt-content") or soup.select_one(".TRS_Editor") or soup.select_one(".trs_editor")
            body_text = " ".join(body.get_text(" ", strip=True).split()) if body else ""
            try:
                parsed = source.parse(content, artifact)
            except Exception as exc:
                if not args.preview:
                    raise
                parsed = [{"error": f"{type(exc).__name__}: {exc}"}]
            if args.preview:
                compact = [{key: row.get(key) for key in ["canonical_series_id", "period", "value", "release_at", "pit_grade", "error"]} for row in parsed]
                print(json.dumps({"url": url, "title": item["title"], "page_header": text[:230],
                                  "body": body_text[:350], "parsed": compact}, ensure_ascii=False, default=str))
                continue
            review = expected[url]
            if len(parsed) != 1:
                raise ValueError(f"Expected exactly one reviewed observation: {url}")
            row = parsed[0]
            for key in ["canonical_series_id", "period", "value", "pit_grade"]:
                if row[key] != review[key]:
                    raise ValueError(f"{url}: {key}: parsed {row[key]!r} != reviewed {review[key]!r}")
            if row["release_at"] != ensure_aware(review["release_at"]):
                raise ValueError(f"Official timestamp mismatch: {url}")
            if row["available_at"] != ensure_aware(review["available_at"]):
                raise ValueError(f"Availability mismatch: {url}")
            if review["body_evidence"].replace(" ", "") not in body_text.replace(" ", ""):
                raise ValueError(f"Reviewed value evidence absent from article body: {url}")
            if review["timestamp_evidence"] not in text:
                raise ValueError(f"Reviewed publication timestamp absent: {url}")
            rows.append(row)
            evidence.append({**review, "url": url, "raw_file": artifact.path,
                             "raw_sha256": artifact.sha256, "result": "PASS"})
    finally:
        source.close()
    if args.preview:
        return
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if len(rows) != len(manifest["items"]) or len(rows) != len(expected):
        raise ValueError("The complete reviewed batch must be downloaded and validated")
    memory = get_connection(":memory:")
    try:
        inserted = insert_observations(memory, rows)
        repeated = insert_observations(memory, rows)
        if inserted.inserted != len(rows) or repeated.inserted or repeated.unchanged != len(rows):
            raise ValueError("Batch idempotency check failed")
        for row in rows:
            for delta, should_exist in [(-1, False), (0, True)]:
                snapshot = get_snapshot(memory, (row["available_at"] + timedelta(seconds=delta)).isoformat(), country="CN")
                exists = any(r["raw_sha256"] == row["raw_sha256"] for r in snapshot.to_dicts())
                if exists != should_exist:
                    raise ValueError(f"Release boundary failure: {row['source_url']}")
    finally:
        memory.close()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(evidence).to_csv(output / "validated_samples.csv", index=False, encoding="utf-8-sig")
    summary = {"reviewed_samples": len(rows), "hash_value_period_timestamp_checks": "PASS",
               "release_boundary_checks": 2 * len(rows), "idempotency": "PASS"}
    if args.ingest:
        conn = get_connection("macro_pit_v2.duckdb")
        try:
            summary["ingestion"] = asdict(insert_observations(conn, rows))
        finally:
            conn.close()
        (output / "ingestion_result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output / "validation_result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
