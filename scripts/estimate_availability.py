"""Step 2 for PIT_work: assign estimated_available_at to PIT_D records.

Read-only against the main DB. Applies config/estimated_availability_rules_v1.csv
to CN PIT_D records (WIND terminal-value imports and SAFE official bulk loads).

Conventions (documented in the step report):
- estimated_release_date = period_end + lag_days (a DATE).
- available_same_day=false: estimated_available_at = estimated_release_date + 1
  day at 00:00 Asia/Shanghai (B-grade-style conservative convention for
  date-only releases).
- available_same_day=true (PMI only): estimated_available_at = period_end
  09:30 Asia/Shanghai (release time known).
- OECD series are eligible=false (bulk-load contamination, see step 1).
- Values remain terminal/latest values; vintage_status=latest_snapshot.

Outputs under reports/v2/pit_work_step2_estimated_availability/:
  - estimated_available_v1.csv  one row per D record with an estimate
  - README.md                   summary
"""

from __future__ import annotations

import io
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import duckdb
import polars as pl

DB_PATH = r"E:\Macro_Data\macro_pit_v2.duckdb"
RULES_PATH = r"E:\Macro_Data\config\estimated_availability_rules_v1.csv"
OUT_DIR = Path(r"E:\Macro_Data\reports\v2\pit_work_step2_estimated_availability")
PRE_REVISION_OVERRIDES = Path(
    r"E:\Macro_Data\data\derived\wind_pre_revision_overrides.csv"
)
RULE_VERSION = "estimated_availability_rules_v1"
CN_TZ = timezone(timedelta(hours=8))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rules = {
        row["canonical_series_id"]: row
        for row in pl.read_csv(RULES_PATH).iter_rows(named=True)
    }
    overrides: dict[tuple[str, str, str], dict] = {}
    if PRE_REVISION_OVERRIDES.is_file():
        for row in pl.read_csv(PRE_REVISION_OVERRIDES).iter_rows(named=True):
            overrides[(
                row["canonical_series_id"], row["source"], row["period"]
            )] = row

    conn = duckdb.connect(DB_PATH, read_only=True)
    df = conn.execute(
        """
        SELECT canonical_series_id, source, frequency, unit, period, period_end,
               value, first_seen_at, release_date_source
        FROM observation_vintage
        WHERE country = 'CN' AND pit_grade = 'D'
        ORDER BY canonical_series_id, period
        """
    ).pl()
    conn.close()

    recs = []
    skipped: dict[str, int] = {}
    for row in df.iter_rows(named=True):
        sid = row["canonical_series_id"]
        marker = str(row.get("release_date_source") or "")
        if marker.startswith("wind_revision_snapshot_"):
            skipped["DOCUMENTED_WIND_REVISIONS"] = (
                skipped.get("DOCUMENTED_WIND_REVISIONS", 0) + 1
            )
            continue
        rule = rules.get(sid)
        if rule is None or rule["eligible"] is not True:
            skipped[sid] = skipped.get(sid, 0) + 1
            continue
        period_end: date = row["period_end"]
        est_release = period_end + timedelta(days=int(rule["lag_days"]))
        if rule["available_same_day"] is True:
            est_avail = datetime.combine(period_end, time(9, 30), tzinfo=CN_TZ)
        else:
            est_avail = datetime.combine(
                est_release + timedelta(days=1), time(0, 0), tzinfo=CN_TZ
            )
        value = row["value"]
        vintage_status = "latest_snapshot"
        override = overrides.get((sid, row["source"], row["period"]))
        if override is not None:
            revision_at = datetime.fromisoformat(str(override["revision_at"]))
            if est_avail < revision_at:
                value = float(override["pre_revision_value"])
                vintage_status = "pre_revision_snapshot"
        recs.append(
            {
                "canonical_series_id": sid,
                "source": row["source"],
                "period": row["period"],
                "period_end": period_end,
                "value": value,
                "estimated_release_date": est_release,
                "estimated_available_at": est_avail.isoformat(),
                "availability_method": "estimated",
                "availability_rule_version": RULE_VERSION,
                "rule_confidence": rule["confidence"],
                "vintage_status": vintage_status,
            }
        )

    out = pl.DataFrame(recs)
    out.write_csv(OUT_DIR / "estimated_available_v1.csv")

    per_series = (
        out.group_by(["canonical_series_id", "source", "rule_confidence"])
        .agg(
            pl.len().alias("n_records"),
            pl.col("period").min().alias("first_period"),
            pl.col("period").max().alias("last_period"),
        )
        .sort("canonical_series_id")
    )

    buf = io.StringIO()
    buf.write("# PIT_work 第2步：PIT_D 记录的估计可用日期\n\n")
    buf.write(
        "规则版本 `estimated_availability_rules_v1`（config/estimated_availability_rules_v1.csv）。\n"
        "口径：estimated_release_date = period_end + 规则滞后天数；非 PMI 序列自估计发布日次日 00:00（Asia/Shanghai）可用"
        "（沿用 B 级日期保守惯例）；PMI 序列当月末 09:30 可用。\n"
        "数值为终值，vintage_status=latest_snapshot；估计日期不写入主库，仅供 work 模式导出使用。\n\n"
    )
    buf.write(f"已赋估计日期的 D 记录：**{out.height}** 条\n\n")
    buf.write("| 序列 | 来源 | 置信度 | 记录数 | 首期 | 末期 |\n|---|---|---|---:|---|---|\n")
    for r in per_series.iter_rows(named=True):
        buf.write(
            f"| {r['canonical_series_id']} | {r['source']} | {r['rule_confidence']} "
            f"| {r['n_records']} | {r['first_period']} | {r['last_period']} |\n"
        )
    if skipped:
        buf.write("\n## 未赋估计日期的 D 记录\n\n")
        for sid, n in sorted(skipped.items()):
            buf.write(f"- {sid}: {n} 条（规则 eligible=false 或无规则）\n")
    buf.write(
        "\n## 边界\n\n"
        "- SAFE 的 D 记录来自官方批量表（终值），与 WIND 记录同样只进 work 模式；是否纳入由导出开关控制。\n"
        "- 海关 5 项与央行序列置信度 low（无本地校准样本或样本少），下游使用时建议做滞后敏感性测试。\n"
        "- OECD 两序列已排除。\n"
        "- 带 `wind_revision_snapshot_*` 标记的 Wind 修订事件不使用估计日期；work 模式直接使用其有据修订日。\n"
    )
    (OUT_DIR / "README.md").write_text(buf.getvalue(), encoding="utf-8")
    print(f"estimated={out.height} skipped={sum(skipped.values())}")


if __name__ == "__main__":
    main()
