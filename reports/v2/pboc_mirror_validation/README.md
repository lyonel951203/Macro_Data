# PBOC政府转载自动更新验证（2026-09-17）

## 结果

- 每日任务来源：PBOC_MIRROR
- 真实运行状态：SUCCESS
- 目录：上海、吉林、青岛三个政府转载目录
- 发现5篇，选中3篇，HTTP成功3篇，解析错误0
- 本轮新增20条、2条数值修订、18条元数据版本、10条不变
- 全量测试：251项通过

2026年8月十项核心指标已经按政府转载日期写入PIT_B。上海转载页发布日期为
2026-09-15，日期级证据按保守规则从北京时间2026-09-16 00:00可见；青岛转载页
提供2026-09-16的冗余证据。央行官网仍为BLOCKED_POLICY，没有绕过robots策略。

## 贷款字段修复

旧解析器会先匹配社融段落中的“对实体经济发放的人民币贷款”，已改为排除该分项。
离线重放2026年5—7月三篇央行官方原稿后，正式查询结果为：

| period | field | value | selected grade |
|---|---|---:|---|
| 2026-07 | CN_RMB_LOAN_BAL_YOY | 5.1 | PIT_A |
| 2026-07 | CN_NEW_RMB_LOANS_YTD | 10.38 | PIT_A |
| 2026-08 | CN_RMB_LOAN_BAL_YOY | 4.9 | PIT_B |
| 2026-08 | CN_NEW_RMB_LOANS_YTD | 10.44 | PIT_B |

## 可检查文件

- reports/v2/daily_web_update/latest.json
- reports/v2/daily_web_update/latest.md
- reports/v2/pboc_mirror_validation/cn_20260917_selected_long.csv
- reports/v2/pboc_mirror_validation/cn_20260917_provenance.csv
- reports/v2/pboc_mirror_validation/cn_20260917_query.json
