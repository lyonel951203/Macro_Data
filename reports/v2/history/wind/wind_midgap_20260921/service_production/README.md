# 服务业生产指数 Wind 中段补缺

核查日期：2026-09-21。Wind 指标为 `M5767203`（中国:服务业生产指数:当月同比，%，国家统计局），原始回执分为2017—2021和2022—2026两个窗口。

- Wind 返回99期；与库内最新 NBS A 级记录重叠57期，57/57数值完全一致。
- 选取库内缺失且月份不为1月或2月的39期，以 `WIND/PIT_D` 写入 batch13；0隔离、0重复、0修订。
- Wind 返回的2017-02、2018-02、2019-02三值属于1—2月合并口径，已写入 `held_january_february.csv`，未进入单月字段。Wind 对2020年以后也没有在该代码下返回1月、2月单月值。
- 覆盖由57/114增至96/114；剩余18期恰为2018—2026各年1月和2月。它们不是抓取失败，而是单月序列与合并发布口径的结构性边界。
- `release_at` 保持为空，研究侧车按服务业规则（期末后16天，次日00:00可用）生成经验可得日。严格A/B快照及原严格导出不变。
- 主库、复合Parquet长表的39条 Wind 记录完全一致；2017-04、2022-04、2025-12三个代表期的发布前/发布时边界检查通过。

证据文件：`official_overlap.csv`、`held_january_february.csv`、`mapping_review.csv`、`ingestion_result.json`、`summary.json`。原始回执位于上级目录，入库批次为 `data/manual_import/wind_mcp/batch13_service_production_safe_gaps.json`。
