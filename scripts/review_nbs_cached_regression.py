"""Read-only replay of existing NBS observations against their archived releases."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

import duckdb
import pandas as pd

from macro_pit.archive import RawArtifact, UrlCache
from macro_pit.sources.cn_common import html_text
from macro_pit.sources.cn_nbs import NBSSource
from macro_pit.timeutils import SHANGHAI


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    out = root / "reports/v2/nbs_gap_batch4"
    out.mkdir(parents=True, exist_ok=True)
    with duckdb.connect("macro_pit_v2.duckdb", read_only=True) as con:
        stored = con.execute("SELECT * FROM observation_vintage WHERE source='NBS'").df()
    compared = 0
    errors = []
    fields = ["canonical_series_id", "period", "value", "release_at", "available_at", "pit_grade", "unit"]
    source = NBSSource(allow_network=False)
    try:
        for (raw_file, raw_hash), group in stored.groupby(["raw_file", "raw_sha256"]):
            content = Path(raw_file).read_bytes()
            assert hashlib.sha256(content).hexdigest() == raw_hash, raw_file
            first = group.iloc[0]
            artifact = RawArtifact("NBS", first.source_url, raw_file, raw_hash,
                                   "text/html", first.retrieved_at.to_pydatetime(), len(content))
            try:
                parsed = source.parse(content, artifact)
                actual = {tuple(row[key] for key in fields) for row in parsed}
                for row in group.to_dict("records"):
                    if tuple(row[key] for key in fields) not in actual:
                        errors.append({"raw_file": raw_file, "indicator": row["canonical_series_id"],
                                       "period": row["period"], "error": "stored observation changed or missing"})
                    compared += 1
            except Exception as exc:
                errors.append({"raw_file": raw_file, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        source.close()
    result = {"at": datetime.now(SHANGHAI).isoformat(), "stored_rows": len(stored),
              "replayed_raw_files": stored.raw_file.nunique(), "compared_rows": compared,
              "errors": errors, "result": "PASS" if not errors and compared == len(stored) else "FAIL"}
    (out / "cached_regression.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if result["result"] != "PASS":
        raise RuntimeError("Existing NBS observations did not reproduce")

    # Classify the historical failure queue without replacing its original audit.
    failures = pd.read_csv("reports/v2/nbs_legacy/existing_queue_failures.csv")
    repairs = set(json.loads(Path("config/nbs_gap_batch4_expected.json").read_text(encoding="utf-8")))
    records = []
    for item in failures.itertuples():
        title = ""
        if item.error_type == "HTTPStatusError":
            category = "http_404_not_retried"
        else:
            cache = UrlCache().get("NBS", item.url)
            soup, _ = html_text(Path(cache["raw_file"]).read_bytes())
            title = soup.title.get_text(strip=True) if soup.title else ""
            if item.url in repairs:
                category = "repaired_and_ingested" if item.url in set(stored.source_url) else "parser_fixed_pending_verified_ingestion"
            elif "三新" in title:
                category = "annual_new_economy_not_target_series"
            elif "国内生产总值" in title and ("最终核实" in title or "修订" in title):
                category = "annual_gdp_revision_not_quarterly_yoy"
            else:
                category = "needs_review"
        records.append({"url": item.url, "title": title, "original_error": item.error_type,
                        "review_category": category})
    classified = pd.DataFrame(records)
    classified.to_csv(out / "existing_queue_resolution.csv", index=False, encoding="utf-8-sig")
    print(classified.review_category.value_counts().to_json(force_ascii=False), flush=True)


if __name__ == "__main__":
    main()
