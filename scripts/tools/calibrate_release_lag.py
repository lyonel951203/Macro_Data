"""Step 1 for PIT_work: empirical release-lag calibration.

Read-only against the main DB. For every CN series with PIT_A/PIT_B records,
take the EARLIEST release per (series, period) - the first time a data period
became visible - and measure the lag from period_end to the release date
(Asia/Shanghai). Outputs per-series distribution stats used to build the
estimated_available_at rule table.

Outputs (under reports/v2/pit_work_step1_lag/):
  - lag_by_period.csv      one row per (series, period): first release timing
  - lag_stats_by_series.csv  per-series distribution summary
  - README.md              human-readable summary
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import duckdb
import polars as pl

DB_PATH = r"E:\Macro_Data\macro_pit_v2.duckdb"
OUT_DIR = Path(r"E:\Macro_Data\reports\v2\pit_work_step1_lag")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(DB_PATH, read_only=True)

    df = conn.execute(
        """
        WITH first_release AS (
            SELECT
                canonical_series_id,
                source,
                frequency,
                period,
                period_end,
                MIN(release_at) AS first_release_at,
                min_by(pit_grade, release_at) AS first_grade
            FROM observation_vintage
            WHERE country = 'CN'
              AND pit_grade IN ('A', 'B')
              AND release_at IS NOT NULL
            GROUP BY canonical_series_id, source, frequency, period, period_end
        )
        SELECT
            canonical_series_id,
            source,
            frequency,
            period,
            period_end,
            CAST(timezone('Asia/Shanghai', first_release_at) AS DATE) AS first_release_date,
            first_grade,
            date_diff('day', period_end,
                      CAST(timezone('Asia/Shanghai', first_release_at) AS DATE)) AS lag_days,
            day(CAST(timezone('Asia/Shanghai', first_release_at) AS DATE)) AS release_day_of_month
        FROM first_release
        ORDER BY canonical_series_id, period
        """
    ).pl()
    conn.close()

    if df.is_empty():
        sys.exit("no A/B records found")

    df.write_csv(OUT_DIR / "lag_by_period.csv")

    stats = (
        df.group_by("canonical_series_id")
        .agg(
            pl.first("source"),
            pl.first("frequency"),
            pl.len().alias("n_periods"),
            pl.col("lag_days").min().alias("lag_min"),
            pl.col("lag_days").quantile(0.10, "nearest").alias("lag_p10"),
            pl.col("lag_days").median().alias("lag_median"),
            pl.col("lag_days").quantile(0.90, "nearest").alias("lag_p90"),
            pl.col("lag_days").max().alias("lag_max"),
            pl.col("lag_days").std().alias("lag_std"),
            pl.col("release_day_of_month").median().alias("release_dom_median"),
            pl.col("period").min().alias("first_period"),
            pl.col("period").max().alias("last_period"),
        )
        .sort("canonical_series_id")
    )
    stats.write_csv(OUT_DIR / "lag_stats_by_series.csv")

    # Markdown summary
    buf = io.StringIO()
    buf.write("# PIT_work 第1步：实际发布滞后实证分布\n\n")
    buf.write(
        "口径：主库中国 A/B 记录，每个（序列 × 数据期）取最早一次 release_at，"
        "换算 Asia/Shanghai 日期后计算 滞后天数 = 发布日 - 数据期末日。"
        "衡量的是\"数据期首次可见\"的时点，不含后续修订版本。\n\n"
    )
    buf.write(f"覆盖序列数：{stats.height}；首次发布样本总数：{df.height}\n\n")
    buf.write("| 序列 | 来源 | 频率 | 样本期数 | 滞后中位(天) | P10 | P90 | 最小 | 最大 | 发布日中位 |\n")
    buf.write("|---|---|---|---:|---:|---:|---:|---:|---:|---:|\n")
    for row in stats.iter_rows(named=True):
        buf.write(
            f"| {row['canonical_series_id']} | {row['source']} | {row['frequency']} "
            f"| {row['n_periods']} | {row['lag_median']:.0f} | {row['lag_p10']:.0f} "
            f"| {row['lag_p90']:.0f} | {row['lag_min']} | {row['lag_max']} "
            f"| {row['release_dom_median']:.0f} |\n"
        )
    buf.write(
        "\n说明：lag_std 大或 P90 明显偏离中位数的序列，经验规则需要分时期或显式例外，"
        "不能一刀切。负滞后（PMI 月末当天发布）属正常。\n"
    )
    (OUT_DIR / "README.md").write_text(buf.getvalue(), encoding="utf-8")

    print(f"series={stats.height} samples={df.height}")
    print(f"outputs in {OUT_DIR}")


if __name__ == "__main__":
    main()
