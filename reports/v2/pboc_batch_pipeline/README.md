# PBOC增量批处理

入口：scripts/pboc_batch_pipeline.py（PYTHONPATH包含src和scripts）。运行仅解析及只读核对主库，不自动把未审候选写入库。

- 输入是第13轮剩余167篇固定队列；包含成功但可能漏字段的稿，不能按文章已恢复就整篇退出。
- 每篇以原稿SHA及解析脚本SHA缓存，逐篇异常记录并继续；脚本或原稿变化时重解析，每次重新读取主库去重。
- candidates.json保留字段、月份、原句、完整段落、发布日期和原稿SHA；documents.json按错误路由分组。
- 年月缺失、过远发布时间、预测、全国口径不明确和跨稿冲突进入待审；字段已存在进入重复组。
- latest.json为本次耗时与候选指标，runs.jsonl追加历史。指标分别是文章数、候选行、唯一潜在缺期、实际提交数，不能互换。
- 现有审核批次输出verified_observations.parquet与independent_review.json；复用prepare_safe_monthly_commit、commit_safe_monthly_review集中试入和提交；最后check_reviewed_monthly_batch.py执行实际PIT边界检查。每批使用新的输出目录，禁止重复prepare覆盖基线。

首个批次已入库29条，见../archive_parse_round14/pboc_month_context。扫描日志inserted=0表示扫描不写库；实际提交以该批result.json/efficiency.json为准。

下一轮：优先审核剩19个潜在字段期，包括全国存贷款口径、2009-03 M2不同精度、2010-09货币分项与预测段中的实际句。随后扩展NO_SUPPORTED_GROWTH_PATTERN组的句式和其他目标字段；不无修改反复解析148篇。SAFE口径专题保持单独队列，不阻塞PBOC/NBS。
