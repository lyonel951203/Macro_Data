# 第五批有限价格回填

固定范围：25 篇已发现、尚未入库的 2020—2021 CPI/PPI 原稿，CPI 11 篇、PPI 14 篇。

启动前完成：归档搜索证据校验；6 篇真实缓存稿自动复核与上批人工记录一致；12 个发布边界及重复入库检查；完整测试 80 项通过。此处的测试数字不表示这 25 篇已下载或已入库。

任务会依次执行：固定清单下载、搜索/正文/页面时间独立核对、解析器比对、完整批次发布边界与重复入库验证、入库、全量审计和验收、严格月末导出、导出差异验证、逐字段明细与 notebook 刷新。原始快照保存在 `before/`；不自动改变发布时间或放宽 A/B 条件。

运行状态以 [结果 JSON](../../../data/history_backfill/nbs_gap_batch5_run.json) 和 STATUS.md 文首第五批段落为准。失败会保留正文、核对证据和检查点；已入库后导出失败时，恢复保留原始入库计数。

完成后产物：`validated_samples.csv`、`ingestion_result.json`、`final_result.json`、`acceptance.txt`、`export_changes.csv`、`export_comparison.json`、`review.html`、`review.ipynb`。这些文件尚未生成时，不应把后台任务已启动理解为数据已补齐。
