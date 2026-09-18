"""Verify the PIT_work export against the strict panel.

Checks:
1. Shape: same rows/columns as the strict panel (259 x 47 + key column).
2. Consistency: every cell whose provenance is work_A/work_B must have the
   SAME value as the strict panel (official evidence cells never altered).
   Cells labeled work_wind/work_wind_revision/work_web_revision/work_safe_d may legitimately differ from strict:
   the work rule is "freshest visible period wins", so a fresher Wind/SAFE
   terminal value can replace a stale official value (strict keeps the stale
   official one). Those divergences are reported, not asserted away.
3. Fill stats: how many previously-blank cells are now filled, by origin.
4. Provenance distribution per series.
"""

from __future__ import annotations

import io
from pathlib import Path

import polars as pl

EXPORT_DIR = Path(r"E:\Macro_Data\data\exports")
STRICT = EXPORT_DIR / "cn_pit_month_end_2005_20260731_values.csv"
WORK = EXPORT_DIR / "cn_pit_work_month_end_2005_20260731_values.csv"
PROV = EXPORT_DIR / "cn_pit_work_month_end_2005_20260731_provenance.csv"
STRICT_PERIODS = EXPORT_DIR / "cn_pit_month_end_2005_20260731_periods.csv"
OUT = Path(r"E:\Macro_Data\reports\v2\pit_work_step3_work_mode")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    strict = pl.read_csv(STRICT)
    work = pl.read_csv(WORK)
    prov = pl.read_csv(PROV)
    # Columns with long leading all-null runs are inferred as String on read;
    # cast numeric-looking cells to Float64 for comparison.
    for frame_name, frame in (("strict", strict), ("work", work)):
        cast_exprs = [
            pl.col(c).cast(pl.Float64, strict=False)
            for c in frame.columns
            if c != "as_of_month_end" and frame[c].dtype == pl.String
        ]
        if cast_exprs:
            frame = frame.with_columns(cast_exprs)
            if frame_name == "strict":
                strict = frame
            else:
                work = frame

    buf = io.StringIO()
    buf.write("# PIT_work 第3步：work 模式导出验收\n\n")
    buf.write(f"strict 形状: {strict.shape}; work 形状: {work.shape}; provenance 形状: {prov.shape}\n\n")

    assert strict.shape == work.shape == prov.shape, "shape mismatch"
    series = [c for c in strict.columns if c != "as_of_month_end"]

    mismatches = []
    filled = 0
    upgraded = 0
    origin_counts: dict[str, int] = {}
    per_series_fill: dict[str, int] = {}
    per_series_upgrade: dict[str, int] = {}
    for col in series:
        s = strict[col]
        w = work[col]
        p = prov[col]
        for i in range(strict.height):
            sv, wv, pv = s[i], w[i], p[i]
            if pv in ("work_A", "work_B"):
                # Official-evidence cells must match strict exactly.
                if sv is None or wv is None or abs(wv - sv) > 1e-9:
                    mismatches.append((col, strict["as_of_month_end"][i], sv, wv, pv))
            elif pv in ("work_wind", "work_wind_revision", "work_web_revision", "work_safe_d"):
                if sv is None:
                    filled += 1
                    per_series_fill[col] = per_series_fill.get(col, 0) + 1
                elif wv is None or abs(wv - sv) > 1e-9:
                    # Fresher terminal value replacing a stale official value.
                    upgraded += 1
                    per_series_upgrade[col] = per_series_upgrade.get(col, 0) + 1
            if pv is not None:
                origin_counts[pv] = origin_counts.get(pv, 0) + 1

    buf.write(f"## 一致性\n\nprov 为 work_A/work_B 的格子与严格表不一致的数量：**{len(mismatches)}**（必须为 0）\n\n")
    if mismatches:
        for m in mismatches[:20]:
            buf.write(f"- {m}\n")
        buf.write("\n")
    buf.write(f"prov 为 work_wind/work_wind_revision/work_web_revision/work_safe_d 且**更新了严格表陈旧值**的格子：**{upgraded}**"
              "（设计内行为：work 规则为最新可见期优先，严格表保留陈旧官方值）\n\n")

    total_cells = strict.height * len(series)
    strict_filled = sum(strict[col].drop_nulls().len() for col in series)
    work_filled = sum(work[col].drop_nulls().len() for col in series)
    buf.write("## 覆盖\n\n")
    buf.write(f"- 总格子数：{total_cells}\n")
    buf.write(f"- 严格表非空：{strict_filled}（{strict_filled / total_cells:.1%}）\n")
    buf.write(f"- work 表非空：{work_filled}（{work_filled / total_cells:.1%}）\n")
    buf.write(f"- 本模式新增填充：**{filled}** 格\n\n")

    buf.write("## 来源标签分布（全表）\n\n| 标签 | 格数 |\n|---|---:|\n")
    for k in sorted(origin_counts):
        buf.write(f"| {k} | {origin_counts[k]} |\n")
    buf.write("\n## 各序列新增填充格数（严格表原本为空）\n\n| 序列 | 新增格数 |\n|---|---:|\n")
    for k in sorted(per_series_fill, key=per_series_fill.get, reverse=True):
        buf.write(f"| {k} | {per_series_fill[k]} |\n")
    if not per_series_fill:
        buf.write("| （无新增） | 0 |\n")
    buf.write("\n## 各序列升级格数（Wind/SAFE 终值替换陈旧官方值）\n\n| 序列 | 升级格数 |\n|---|---:|\n")
    for k in sorted(per_series_upgrade, key=per_series_upgrade.get, reverse=True):
        buf.write(f"| {k} | {per_series_upgrade[k]} |\n")
    if not per_series_upgrade:
        buf.write("| （无升级） | 0 |\n")

    (OUT / "README.md").write_text(buf.getvalue(), encoding="utf-8")
    print(f"mismatches={len(mismatches)} filled={filled} upgraded={upgraded} origins={origin_counts}")


if __name__ == "__main__":
    main()
