"""Offline candidate gap inventory and a small, stratified raw-review manifest."""
from pathlib import Path
import argparse
import json
import pandas as pd

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--coverage-only", action="store_true")
args = parser.parse_args()

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/v2/nbs_legacy"
OUT.mkdir(parents=True, exist_ok=True)
frame = pd.read_parquet(ROOT / "data/discovery/nbs_legacy/nbs_candidates.parquet")
frame["family"] = frame.title.map(
    lambda title: "CPI" if "居民消费价格" in title else
    "PPI" if "工业品出厂价格" in title or "工业生产者出厂价格" in title else "OTHER"
)
records = []
for family in ["CPI", "PPI"]:
    counts = frame.loc[frame.family.eq(family)].groupby("period").url.nunique()
    for period in pd.period_range("2005-01", "2021-08", freq="M").astype(str):
        records.append({"family": family, "period": period,
                        "candidate_urls": int(counts.get(period, 0)),
                        "body_verified": False})
gaps = pd.DataFrame(records)
verified = set()
for review_path in (ROOT / "reports/v2").glob("nbs_*/validated_samples.csv"):
    for row in pd.read_csv(review_path).itertuples():
        if row.result == "PASS" and row.canonical_series_id in {"CN_CPI_YOY", "CN_PPI_YOY"}:
            verified.add((row.canonical_series_id.split("_")[1], row.period))
gaps["body_verified"] = [(row.family, row.period) in verified for row in gaps.itertuples()]
gaps.to_csv(OUT / "candidate_month_coverage.csv", index=False, encoding="utf-8-sig")
gaps[gaps.candidate_urls.eq(0)].to_csv(OUT / "candidate_missing_months.csv", index=False, encoding="utf-8-sig")
summary = gaps.assign(year=gaps.period.str[:4], present=gaps.candidate_urls.gt(0)).groupby(
    ["family", "year"], as_index=False
).agg(expected_months=("period", "count"), candidate_months=("present", "sum"))
summary.to_csv(OUT / "candidate_year_coverage.csv", index=False, encoding="utf-8-sig")
if args.coverage_only:
    print(json.dumps({"candidates": len(frame), "verified_price_periods": len(verified), "coverage": str(OUT)}))
    raise SystemExit(0)
samples, missing = [], []
for year in ["2005", "2010", "2015", "2019"]:
    for family in ["CPI", "PPI"]:
        options = frame[frame.period.str.startswith(year, na=False) & frame.family.eq(family)].sort_values(["period", "url"])
        if options.empty:
            missing.append({"year": year, "family": family})
        else:
            samples.append(options.iloc[0].to_dict())
manifest = {"purpose": "Download raw only; require body review before offline ingestion.",
            "missing_sample_strata": missing, "items": samples}
target = ROOT / "config/nbs_legacy_validation_batch.json"
target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"candidates": len(frame), "samples": len(samples), "missing_strata": missing,
                  "coverage": str(OUT), "manifest": str(target)}, ensure_ascii=False))
