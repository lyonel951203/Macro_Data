# CN / US / GLB 复合 PIT 长表使用说明

## 已生成文件

- `data/exports/all_pit_long_from_2005-01-01.parquet`：推荐查询文件。
- `data/exports/all_pit_long_from_2005-01-01.csv`：便于人工检查，但文件较大。
- `data/exports/all_pit_long_from_2005-01-01_export.json`：导出元数据。

复合长表从 2005-01-01 开始；2026-09-21 按当前字段范围重新生成后，共 238,642 条版本事件。CN 50 个当前可用字段，US 18 个字段，GLB 54 个字段。五个海关美元口径字段已停用，既不进入新长表，也不会从旧长表查询中返回；底层数据库记录仅作历史留存。本次仍包含综合 PMI、调查失业率和服务业生产指数的 Wind D 级中段补缺，详情见历史补缺核查。

## 三类日期的含义

- `period_end`：宏观值所属月份或季度的期末日期。
- `valid_from`：这个版本从何时开始对历史观察者可见，包含该时点。
- `valid_to`：这个版本何时被下一版本取代，不包含该时点；为空表示目前仍有效。

因此，站在信息截止时点 T，可见记录的条件是：

    valid_from <= T AND (valid_to IS NULL OR T < valid_to)

长表已经把 A、B、Wind、备用来源以及有日期的历史修订整合为版本有效区间。查询时不要再重新套一次来源优先级。

普通 Wind PIT_D 是严格的缺口补充：同一中国字段期只要数据库中存在任一 PIT_A/PIT_B，普通 Wind 行就完全不进入长表，即使其虚拟可得日更早。有明确日期的 Wind 修订快照仍作为独立修订事件处理。财政七项已增加 104 个无 A/B 的 Wind 事件；其余 1,045 个与 A/B 重叠的 Wind 字段期不进入长表。财政经验日期按规则表分别采用月末后第 16 或第 18 天估计披露，并从次日 00:00 起可用。

外汇储备是一个单字段例外：`CN_FX_RESERVE_USD` 在没有任何 A/B 的字段期可使用 SAFE 历史汇编 PIT_D，标记为 `SAFE_ESTIMATED_D`。估计发布日期为统计月末后第 7 天，`valid_from` 为次日 00:00（北京时间，即月末后第 8 天）；一旦同字段期存在 A/B，该经验 D 完全不进入长表。当前共有 140 个此类事件，覆盖 2005-01 至 2016-10，且与 A/B 重叠数为 0。

## 按固定时点分别输出 CN、US、GLB 宽表

下面示例输出站在 2026-07-31 月末可见的月频宽表：

    $T = '2026-07-31'
    foreach ($scope in 'CN', 'US', 'GLB') {
        python -m macro_pit query-wide `
          --as-of $T `
          --scope $scope `
          --frequency M `
          --start-date 2005-01-01 `
          --long-parquet data\exports\all_pit_long_from_2005-01-01.parquet `
          --output-prefix "data\exports\${scope}_M_asof_20260731"
    }

季度输出把 `--frequency M` 改成 `--frequency Q`。

`--as-of 2026-07-31` 按北京时间当天 23:59:59.999999 处理。输出表的索引仍是各宏观数据的 `period_end`，不会把所有记录都改成 2026-07-31，也不会向未来月份填值。

## 直接提取截止 T 的复合长表

    from datetime import datetime
    from zoneinfo import ZoneInfo
    import polars as pl

    src = r"E:\Macro_Data\data\exports\all_pit_long_from_2005-01-01.parquet"
    out = r"E:\Macro_Data\data\exports\all_visible_asof_20260731.parquet"

    df = pl.read_parquet(src)
    t = datetime(2026, 7, 31, 23, 59, 59, 999999,
                 tzinfo=ZoneInfo("Asia/Shanghai"))

    visible = (
        df.filter(
            (pl.col("valid_from") <= t)
            & (pl.col("valid_to").is_null() | (t < pl.col("valid_to")))
        )
        .with_columns(
            pl.when(pl.col("country") == "CN").then(pl.lit("CN"))
            .when(pl.col("country") == "US").then(pl.lit("US"))
            .otherwise(pl.lit("GLB"))
            .alias("scope")
        )
        .sort(["scope", "country", "canonical_series_id", "period_end"])
    )
    visible.write_parquet(out)

这里的 `scope` 是查询维度：country 为 CN 时属于 CN，country 为 US 时属于 US，其余国家归入 GLB。原始复合长表保留具体 `country`，没有额外固化 `scope` 列。

## 从截止 T 的长表转为一张复合宽表

    wide = (
        visible.pivot(
            index=["country", "period_end"],
            on="canonical_series_id",
            values="value",
            aggregate_function="first",
        )
        .sort(["country", "period_end"])
    )
    wide.write_parquet(
        r"E:\Macro_Data\data\exports\all_wide_asof_20260731.parquet"
    )

GLB 含多个国家，因此复合宽表使用 `country + period_end` 作为索引最稳妥。若只查询 CN 或 US，则可仅用 `period_end` 作为索引。

## 重新生成复合事件长表

    python -m macro_pit --db-path macro_pit_v2.duckdb export-long --scope ALL --start-date 2005-01-01

数据库有新增或修订事件后，先重新执行这条命令，再用新的长表查询任意截止时点。
