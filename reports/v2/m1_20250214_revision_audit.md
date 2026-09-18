# CN_M1_YOY 2025-02-14 修订核查

核查日期：2026-09-17  
数据库：`E:\Macro_Data\macro_pit_v2.duckdb`  
字段：`CN_M1_YOY`（中国 M1 同比）

## 2026-09-17 修复结果

用户补充的 Wind 历史修正工作簿已校验并入库。数据库新增12条修订事件；估计可用日期侧表已改为修订日前使用旧值；中国全量 PIT 长表 CSV/Parquet 已重建。

边界验证：T=2025-02-13 返回旧口径值，T=2025-02-14 返回新口径值。原报告所述前视偏差已修复。

## 修复前结论

当前数据库**没有**把 2025-02-14 对2024年12期 M1 同比的回溯修订保存为一个有日期的版本事件。

数据库保存的是 Wind 于 2026-09-08 导入的一份最终值快照。2024年1—12月每期只有一行，均为 `vintage_no=0`、`revision_type=initial`、`pit_grade=D`。库内没有 `available_at/release_at/first_seen_at` 落在 2025-02-13 至 2025-02-16 的 `CN_M1_YOY` 记录，也没有 `wind_revision_snapshot_*` 标记。

因此，当前 as-of 查询会把修订后的最终值按估计的原始发布日期回填到修订日前，构成前视偏差。实测在 `T=2025-02-13`、`2025-02-14` 和 `2025-02-15` 时，系统返回完全相同的2024年12期修订后数值，没有在修订日发生版本切换。

## 当前库中的2024年 Wind 值

| 月份 | 当前值 | 行数 | vintage | 类型 | as-of 使用的估计可用日 |
|---|---:|---:|---:|---|---|
| 2024-01 | 3.3 | 1 | 0 | initial | 2024-02-13 |
| 2024-02 | 2.6 | 1 | 0 | initial | 2024-03-13 |
| 2024-03 | 2.3 | 1 | 0 | initial | 2024-04-13 |
| 2024-04 | 0.6 | 1 | 0 | initial | 2024-05-13 |
| 2024-05 | -0.8 | 1 | 0 | initial | 2024-06-13 |
| 2024-06 | -1.7 | 1 | 0 | initial | 2024-07-13 |
| 2024-07 | -2.6 | 1 | 0 | initial | 2024-08-13 |
| 2024-08 | -3.0 | 1 | 0 | initial | 2024-09-13 |
| 2024-09 | -3.3 | 1 | 0 | initial | 2024-10-13 |
| 2024-10 | -2.3 | 1 | 0 | initial | 2024-11-13 |
| 2024-11 | -0.7 | 1 | 0 | initial | 2024-12-13 |
| 2024-12 | 1.2 | 1 | 0 | initial | 2025-01-13 |

这12个值正是新口径回溯后的值，但侧表把它们当成各月原始可见值。

## 来源检查

- Wind 原始文件：`data/raw/wind/2026/09/08/7577d31e2117e3d46097149f6f6a0c0513a8118141c086c530ea265229419230.xlsx`
- 工作簿只有最终历史序列，没有“修正日期、修正前值、修正值”版本列。
- 当前 `data/raw/wind/修订` 目录只有 GDP 的历史修正工作簿，没有 M1 历史修正工作簿。
- 本地两篇后续 PBOC 官方报告正文包含2024年 M1 新口径回溯表，但它们是2026年归档的后续报告，不能单独证明2025-02-14之前的旧版本状态。
- 中国人民银行的2025年1月金融统计报告于2025-02-14发布，并列出2024年各月新口径回溯值；这是应当采用的修订事件证据。

## 影响

严重程度：**高**。置信度：**高**。

受影响的是任何 `as_of < 2025-02-14` 且读取2024年 `CN_M1_YOY` 的回测或特征构造。当前结果使用了当时尚未公布的新口径值，会产生宏观因子前视偏差。修订日之后的当前值本身正确，错误在于版本日期和修订前状态缺失。

## 修复要求

1. 归档2025-02-14发布的2025年1月金融统计报告，作为12期新口径值的官方修订事件证据。
2. 从2024年各月官方金融统计报告恢复旧口径的原始 M1 同比及实际发布日期。
3. 对每个月保留两个版本：旧值按原发布日期可见；新值从2025-02-14 00:00（Asia/Shanghai，日粒度约定）起可见。
4. 新版本应使用 `revision_type=revision`、递增的 `vintage_no` 和非空 `revision_delta`；官方报告可评为 PIT_A，若仅用 Wind 历史修正页则为 PIT_D。
5. 重建 `estimated_available_v1.csv` 时，不能再把最终快照中的新口径值锚定到2024年的估计发布日期。
6. 增加边界测试：2025-02-13应返回旧口径值，2025-02-14及以后应返回新口径值；12个月都必须发生切换。

## 复核查询

```sql
SELECT period, count(*) AS n, count(DISTINCT value) AS distinct_values,
       min(vintage_no), max(vintage_no),
       string_agg(DISTINCT revision_type, ',') AS revision_types
FROM observation_vintage
WHERE canonical_series_id = 'CN_M1_YOY'
  AND source = 'WIND'
  AND period BETWEEN '2024-01' AND '2024-12'
GROUP BY period
ORDER BY period;
```

```sql
SELECT source, period, value, release_at, available_at,
       vintage_no, revision_type, revision_delta, release_date_source
FROM observation_vintage
WHERE canonical_series_id = 'CN_M1_YOY'
  AND (
       CAST(release_at AS DATE) BETWEEN DATE '2025-02-13' AND DATE '2025-02-16'
    OR CAST(first_seen_at AS DATE) BETWEEN DATE '2025-02-13' AND DATE '2025-02-16'
    OR CAST(available_at AS DATE) BETWEEN DATE '2025-02-13' AND DATE '2025-02-16'
  );
```

第二条查询当前返回0行。

