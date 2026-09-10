# %%
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import duckdb
import pandas as pd

root = next(p for p in [Path.cwd(), *Path.cwd().parents]
            if (p / "data/exports/cn_pit_month_end_2005_20260731_values.csv").exists())
prefix = root / "data/exports/cn_pit_month_end_2005_20260731"
out = root / "reports/v2/pit_csv_inspection"
values = pd.read_csv(str(prefix) + "_values.csv")
periods = pd.read_parquet(str(prefix) + "_periods.parquet")
metadata = pd.read_csv(str(prefix) + "_metadata.csv")
dates = pd.to_datetime(values.as_of_month_end)
cutoff = pd.Timestamp(values.as_of_month_end.iloc[-1] + " 23:59:59", tz="Asia/Shanghai")
assert values.as_of_month_end.tolist() == periods.as_of_month_end.astype(str).tolist()
assert list(values.columns) == list(periods.columns)
assert set(values.columns[1:]) == set(metadata.canonical_series_id)
assert values.iloc[:, 1:].notna().equals(periods.iloc[:, 1:].notna())
with duckdb.connect(str(root / "macro_pit_v2.duckdb"), read_only=True) as con:
    observations = con.execute("""
        SELECT canonical_series_id, source, period, available_at, pit_grade
        FROM observation_vintage WHERE country = 'CN'
    """).df()
strict = observations[
    observations.pit_grade.isin(["A", "B"]) & (observations.available_at <= cutoff)
].copy()
print(f"CSV: {len(values)} month ends, {len(metadata)} indicators; cutoff {cutoff}")
print(f"Read-only CN database rows: {len(observations)}; eligible strict rows: {len(strict)}")

# %%
records = []
for spec in metadata.itertuples():
    name = spec.canonical_series_id
    mask = values[name].notna()
    first = values[name].first_valid_index()
    last = values[name].last_valid_index()
    db = observations[observations.canonical_series_id.eq(name)]
    eligible = strict[strict.canonical_series_id.eq(name)]
    chosen = periods.loc[mask, name]
    source_end_months = chosen.map(
        lambda p: pd.Period(p, freq=spec.frequency).asfreq("M", how="end").ordinal
    )
    ages = dates.loc[mask].dt.to_period("M").map(lambda p: p.ordinal) - source_end_months
    assert ages.ge(0).all(), name
    assert set(chosen).issubset(set(eligible.period)), name
    records.append({
        "indicator": name, "name": spec.series_name, "source": spec.source,
        "frequency": spec.frequency,
        "first_nonnull_as_of": values.loc[first, "as_of_month_end"],
        "first_selected_source_period": periods.loc[first, name],
        "last_nonnull_as_of": values.loc[last, "as_of_month_end"],
        "latest_selected_source_period": periods.loc[last, name],
        "nonnull_snapshot_months": int(mask.sum()),
        "missing_snapshot_months": int((~mask).sum()),
        "missing_pct": round(float((~mask).mean()) * 100, 2),
        "null_months_after_first": int(values.loc[first:, name].isna().sum()),
        "distinct_selected_source_periods": int(chosen.nunique()),
        "strict_first_period_by_cutoff": eligible.period.min(),
        "strict_last_period_by_cutoff": eligible.period.max(),
        "strict_periods_by_cutoff": int(eligible.period.nunique()),
        "db_all_grades_first_period": db.period.min(),
        "db_all_grades_last_period": db.period.max(),
        "db_all_grades_periods": int(db.period.nunique()),
        "max_source_age_months": int(ages.max()),
        "latest_source_age_months": int(ages.iloc[-1]),
    })
history = pd.DataFrame(records).sort_values(["source", "first_nonnull_as_of", "indicator"])
assert len(history) == len(metadata) and history.indicator.is_unique
history.to_csv(out / "field_history.csv", index=False, encoding="utf-8-sig")
print(history[["name", "first_nonnull_as_of", "first_selected_source_period",
               "strict_periods_by_cutoff", "max_source_age_months"]].to_string(index=False))

# %%
# Price series publish monthly: enumerate missing source months, not empty snapshot cells.
gap_rows = []
price_summary = []
for name in ["CN_CPI_YOY", "CN_PPI_YOY"]:
    observed = set(strict.loc[strict.canonical_series_id.eq(name), "period"])
    expected = pd.period_range("2005-01", "2026-06", freq="M")
    missing = [p for p in expected if str(p) not in observed]
    price_summary.append({"indicator": name, "expected_source_months": len(expected),
                          "observed_source_months": len(set(map(str, expected)) & observed),
                          "missing_source_months": len(missing)})
    runs = []
    for period in missing:
        if runs and period.ordinal == runs[-1][-1].ordinal + 1:
            runs[-1].append(period)
        else:
            runs.append([period])
    for run in runs:
        gap_rows.append({"indicator": name, "missing_start": str(run[0]),
                         "missing_end": str(run[-1]), "missing_months": len(run)})
gaps = pd.DataFrame(gap_rows)
gaps.to_csv(out / "price_missing_ranges.csv", index=False, encoding="utf-8-sig")

# The existing coverage catalogue includes configured fields absent from the export.
# Cross-check absence against the current database, rather than trusting its old counts.
catalogue = pd.read_csv(root / "reports/v2/cn_coverage.csv")
absent = catalogue.loc[
    ~catalogue.canonical_series_id.isin(observations.canonical_series_id),
    ["canonical_series_id", "source", "frequency"],
].copy()
absent.to_csv(out / "unpopulated_catalogue_fields.csv", index=False, encoding="utf-8-sig")
summary = {
    "inspected_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
    "cutoff": str(cutoff), "indicator_count": len(history),
    "first_visible_2021_or_later": int(history.first_nonnull_as_of.ge("2021-01-01").sum()),
    "missing_pct": round(float(values.iloc[:, 1:].isna().to_numpy().mean()) * 100, 2),
    "cn_db_rows": len(observations), "price_coverage": price_summary,
    "unpopulated_catalogue_fields": len(absent),
    "input_sha256": {
        suffix: hashlib.sha256(Path(str(prefix) + suffix).read_bytes()).hexdigest()
        for suffix in ["_values.csv", "_periods.parquet", "_metadata.csv"]
    },
}
(out / "field_history_summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
lines = [
    "# PIT 字段历史覆盖检查", "",
    f"范围：当前 2005-01 至 2026-07 月末 CSV 的全部 {len(history)} 个指标；主库以只读方式核对。", "",
    "首次有值是本 CSV 的月末日期，首条数据期是该单元格对应的统计月份/季度；两者都不代表官方指标创设日期。",
    "已入库期数仅统计截至 2026-07-31 23:59:59（上海时间）可用的 A/B 记录，按原始数据期去重。",
    "该期数包含起始月末以前的历史数据，也可能包含从未被月末最新值选中的数据期；不等于非空快照月数。", "",
    "| 字段 | 名称 | 来源 | CSV 首次有值 | 首条数据期 | 截止日 A/B 已入库期数 |",
    "| --- | --- | --- | --- | --- | ---: |",
]
for r in history.itertuples():
    lines.append(f"| {r.indicator} | {r.name} | {r.source} | {r.first_nonnull_as_of} | "
                 f"{r.first_selected_source_period} | {r.strict_periods_by_cutoff} |")
cpi, ppi = price_summary
gdp = history.set_index("indicator").loc["CN_GDP_YOY"]
real_ids = ["CN_INDUSTRIAL_VALUE_ADDED_YOY", "CN_RETAIL_SALES_YOY",
            "CN_SERVICE_PRODUCTION_YOY", "CN_FAI_YTD_YOY",
            "CN_INFRA_INVESTMENT_YTD_YOY", "CN_MANUFACTURING_INVESTMENT_YTD_YOY",
            "CN_REAL_ESTATE_INVESTMENT_YTD_YOY", "CN_URBAN_SURVEYED_UNEMPLOYMENT"]
real = history[history.indicator.isin(real_ids)]
real_text = "；".join(f"{r['name']} {r.strict_periods_by_cutoff} 个月（{r.strict_first_period_by_cutoff} 起）"
                      for _, r in real.iterrows())
pboc = history[history.source.eq("PBOC")]
pboc_text = "；".join(f"{r['name']} {r.strict_periods_by_cutoff} 个月"
                      for _, r in pboc.iterrows())
strict_absent = catalogue.loc[~catalogue.canonical_series_id.isin(strict.canonical_series_id),
                              ["canonical_series_id", "source", "frequency"]].copy()
strict_absent.to_csv(out / "strict_unpopulated_catalogue_fields.csv", index=False, encoding="utf-8-sig")
lines += [
    "", "主要发现：", "",
    f"- {summary['first_visible_2021_or_later']}/{len(history)} 个字段首次有值在 2021 年以后；全表指标单元格空值占 {summary['missing_pct']}%。",
    f"- CPI/PPI 虽从 2005 年出现，但在 2005-01 至 2026-06 的 258 个原始月份中仅有 {cpi['observed_source_months']}/{ppi['observed_source_months']} 个月，分别缺 {cpi['missing_source_months']}/{ppi['missing_source_months']} 个月。",
    f"- 实体经济严格 A/B 数据仍稀疏：{real_text}。最早日期提前不等于中间月份已经补齐。",
    f"- PBOC 严格 A/B 覆盖：{pboc_text}。此处仅统计截止日前可用的官方记录。",
    "- SAFE 早期历史存在于主库：外储始于 1999-12，其余六项始于 2010-01；早期 C/D 记录无法进入严格 A/B 快照，仍缺原始发布证据。",
    f"- PMI 的真实月份和月末选中月份分别见 strict_periods_by_cutoff 与 distinct_selected_source_periods 两列；月末仅取当时最新期，二者差额不能直接判作漏抓。GDP 在 {gdp.strict_first_period_by_cutoff} 至 {gdp.strict_last_period_by_cutoff} 间已入库 {gdp.strict_periods_by_cutoff} 个季度。",
    "- OECD 首次出现在 2005-01 是导出窗口限制；首条快照分别采用 2004-10 CPI 和 2004-08 工业生产指数，主库更早历史已存在。",
    "- 财政部分月份缺失需结合发布口径判断，不能将累计指标的每个自然月都机械认定为必发月份。",
    f"- 现有覆盖目录有 {len(absent)} 个字段在所有等级中均未入库；另有 {len(strict_absent)} 个字段在截止日前没有严格 A/B 记录，不在当前 {len(history)} 列中。两种缺口分别列出，不能混用。", "",
    "后续优先处理 NBS 已有候选正文入库及综合稿漏解析，再补 PBOC 历史和 SAFE 原始发布时间证据；回测需同时检查数据期和陈旧程度。", "",
    "完整 CSV：field_history.csv；价格缺口：price_missing_ranges.csv；空缺目录：unpopulated_catalogue_fields.csv。",
    "复核代码：field_history_review.ipynb / field_history_review.py。该复核脚本不修改原始 CSV 或主库，也不运行全库验收。",
]
(out / "field_history.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
print(gaps.sort_values("missing_months", ascending=False).head(6).to_string(index=False))
