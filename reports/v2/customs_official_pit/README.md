# 海关总署官方外贸 PIT 接入

更新时间：2026-09-21（Asia/Shanghai）

## 当前状态：已停用

根据当前字段范围决定，以下五个美元口径外贸字段已从每日任务、周度
修订任务、PIT查询、复合长表和当前字段清单中移除。注册表将它们标为
`active: false`；数据库既有记录只作历史留存，不会被物理删除。本文其余
内容保留为已完成实现和访问故障的技术记录，不代表当前仍在运行。

WorkBuddy浏览器采集与离线入库交接：[WORKBUDDY_HANDOFF.md](WORKBUDDY_HANDOFF.md)

## 目标

原接入方案不调用 Wind 接口，曾计划由海关总署官方初步统计和月度公报维护以下五个中国月度字段：

| 字段 | 含义 | 单位 |
|---|---|---|
| `CN_EXPORT_USD` | 出口金额（美元） | `bn_usd` |
| `CN_EXPORT_USD_YOY` | 出口金额当月同比 | `pct_yoy` |
| `CN_IMPORT_USD` | 进口金额（美元） | `bn_usd` |
| `CN_IMPORT_USD_YOY` | 进口金额当月同比 | `pct_yoy` |
| `CN_TRADE_BALANCE_USD` | 贸易差额（美元，顺差为正） | `bn_usd` |

## 官方入口

- 初步统计：<https://english.customs.gov.cn/statics/report/preliminary.html>
- 月度公报：<https://english.customs.gov.cn/statics/report/monthly.html>
- 发布日历：<https://english.customs.gov.cn/Statics/fc662cee-21c3-474e-a7fb-4768bb1e295a.html>
- 格式样例：<https://english.customs.gov.cn/Statics/4733ad72-5ba7-4b60-bfbd-00e2f4eef77f.html>

海关月度公报目录明确说明，数据在初步发布后会继续核验，月报版本更准确。因此两个目录均保留，不能只保存一条“最终值”。

## PIT 与修订规则

1. 页面提供完整发布日期但无时分秒时记为 `PIT_B`，在上海时区次日 00:00 起可用。
2. 初步统计和月度公报若使用不同官方 URL，各自按页面发布日期形成版本；较晚披露的月报值仅在其可用日起生效。
3. 同一官方 URL 后来发生数值变化时，保留旧版；新版记为 `PIT_D / official_web_revision_first_seen`，从本地首次观测到变化的时间起生效。
4. `query-wide` 和复合 PIT 长表均识别上述官方网页修订事件。后来的 `PIT_A/PIT_B` 仍可继续覆盖较早版本。
5. 金额原表单位 `USD 100 Million` 乘 0.1 转为 `bn_usd`；每页强制检查“出口－进口＝贸易差额”，容差仅覆盖原表一位小数舍入。
6. 目录只接受全国美元总值表，排除人民币、国别、贸易方式等相似标题，避免误提取。

## 自动运行

以下为停用前的设计。`CUSTOMS.enabled` 当前在每日与周度配置中均为
`false`，计划任务不会再访问海关站点。

- 每日中国任务：`config/daily_web_update.yml`
- 每周修订核查：`config/weekly_web_revision.yml`
- 目录清单：`config/customs_english_index_urls.txt`
- 每日首次启动不跳过既有候选；发现的历史链接按有界批次逐日消化。
- 候选逐页隔离，单页格式变化会留下错误和重试状态，不中止其他页面。
- 失败按 1、3、7 天退避，404 冷却 30 天。
- Wind 明确排除在无人值守任务之外。

手工 dry-run：

```powershell
py -3.11 scripts/run_daily_web_update.py --config config/daily_web_update.yml --sources CUSTOMS --dry-run
```

## 当前实测状态

2026-09-21 使用独立临时库进行了真实联网验证。海关 CDN 向本机提供的 TLS 证书链无法通过 Python、Windows PowerShell 或 Windows Schannel 严格验证，因此 robots.txt 也无法安全读取。程序按 fail-closed 原则没有关闭证书校验、没有绕过 robots，也没有写主库。

该状态记为 `BLOCKED_TRANSPORT`：每日仍会探测，其他来源继续运行，整批任务不会因这个已知外部故障标成失败；证书恢复后会自动进入发现、回补和入库。验证回执见 [validation_20260921.md](validation_20260921.md) 和 [validation_20260921.json](validation_20260921.json)。

截至本报告时间：**本次新增 CUSTOMS 主库记录为 0，历史回补尚未开始。** 代码已经覆盖初步值、月报修订和同页静默修订，但 2005 年以来官网可访问年份范围必须在 TLS 恢复后由归档结果确认；不能把搜索引擎缓存当作主库官方原稿。

## 验证

- 海关解析、目录发现、每日调度、PIT 宽表和复合长表定向测试：67 项通过。
- 全项目最终回归：283 项全部通过。
