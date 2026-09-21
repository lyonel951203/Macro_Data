"""Compare this batch's frozen before snapshot with the regenerated exports."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

root = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "macro_pit_v2.duckdb").exists())
out = root / "reports/v2/nbs_gap_batch4"
name = "cn_pit_month_end_2005_20260731"
before = pd.read_csv(out / "before" / (name + "_values.csv"))
after = pd.read_csv(root / "data/exports" / (name + "_values.csv"))
old_periods = pd.read_parquet(out / "before" / (name + "_periods.parquet"))
new_periods = pd.read_parquet(root / "data/exports" / (name + "_periods.parquet"))
expected = json.loads((root / "config/history/nbs/nbs_gap_batch4_expected.json").read_text(encoding="utf-8"))
assert before.columns.tolist() == after.columns.tolist()
assert before.as_of_month_end.tolist() == after.as_of_month_end.tolist()
assert len(after) == 259
changed = []
for field in after.columns[1:]:
    same_values = np.isclose(before[field], after[field], equal_nan=True, rtol=1e-12, atol=1e-12)
    same_periods = old_periods[field].fillna("").eq(new_periods[field].fillna(""))
    for i in np.flatnonzero(~same_values | ~same_periods):
        changed.append({"indicator": field, "as_of_month_end": after.loc[i, "as_of_month_end"],
                        "old_value": before.loc[i, field], "new_value": after.loc[i, field],
                        "old_period": old_periods.loc[i, field], "new_period": new_periods.loc[i, field]})
changes = pd.DataFrame(changed)
assert set(changes.indicator) == {r["canonical_series_id"] for r in expected.values()}
for r in expected.values():
    # These releases all occur before the next same-series release's month end.
    first_month_end = str(pd.Timestamp(r["available_at"]).tz_localize(None).to_period("M").end_time.date())
    i = after.index[after.as_of_month_end.eq(first_month_end)][0]
    assert new_periods.loc[i, r["canonical_series_id"]] == r["period"]
    assert after.loc[i, r["canonical_series_id"]] == r["value"]
for r in changes.itertuples():
    matching = [x for x in expected.values() if x["canonical_series_id"] == r.indicator and x["period"] == r.new_period]
    assert len(matching) == 1
    snapshot_at = pd.Timestamp(r.as_of_month_end + " 23:59:59", tz="Asia/Shanghai")
    assert snapshot_at >= pd.Timestamp(matching[0]["available_at"])
changes.to_csv(out / "export_changes.csv", index=False, encoding="utf-8-sig")
result = {"result": "PASS", "changed_cells": len(changes),
          "changed_indicators": changes.groupby("indicator").size().to_dict(),
          "first_month_end_checks": len(expected),
          "null_cells_before": int(before.iloc[:, 1:].isna().to_numpy().sum()),
          "null_cells_after": int(after.iloc[:, 1:].isna().to_numpy().sum())}
(out / "export_comparison.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result))
