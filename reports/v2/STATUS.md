# Macro PIT v2 status

## 当前状态（2026-09-09，Asia/Shanghai）

工作目录：`E:\Macro_Data`；主库：`macro_pit_v2.duckdb`。以下以最上方批次为当前状态；后面的 Wind、NBS 价格批次及 9 月 4 日段落均保留为历史快照。

### 最近修复：PBOC 断点替换失败与续跑（2026-09-09 16:54）

- 16:38，PBOC 完成检索页下载后在替换 `state.json` 时遇到 Windows `WinError 5`，最终保存再次失败并留下死进程锁。已为断点写入增加独立临时文件、完整落盘和最多 8 次短间隔替换尝试；持续失败保留恢复文件，退出时仍清理锁。具体占用进程未确定，未改变文件权限。
- 25 项测试通过；核对全部 263 份归档原稿的大小与 SHA-256，恢复遗留临时文件中的 1 个检索页和 2 个新链接。旧结果、请求计数、队列顺序、原 9/16 08:51 截止时间均保留。
- 已单独恢复 PBOC **PID 21584**；16:53:50 成功下载并保存新正文《货币增速仍在合理区间》，HTTP 200，正式断点推进到 **266/338 个链接、189 篇正文、75 个目录页**，旧错误清除。NBS 继续运行；SAFE 保持本轮原文归档完成待审。
- [修复证据、断点恢复与验证](pboc_checkpoint_recovery_20260909/README.md)；当前状态以 [实时监控](source_monitor/latest.md) 为准。

### 最近修复：NBS 空检索词错误与断点恢复（2026-09-09 16:30）

- 16:05，2014 年“经济运行”第 9 页在请求词非空的情况下返回 `code=201/无搜索词`，错误响应被缓存，导致 NBS 退出。已增加同页限次刷新重试、持久化失败次数及错误证据；连续 3 次失败仍停止，不跳页或将错误视为空结果。限速和 HTTP 熔断保留。
- 33 项测试通过；311 份归档重放通过，独立核验 486 条、0 不匹配、0 失败。相同第 9 页实测恢复 HTTP 200、20 条结果，生产断点在验证阶段未改动。
- 16:28 从原断点恢复隐藏进程 **PID 25796**；16:29 已获取第 10 页，继续第 11 页，监控旧错误清除。当前 66/154 个检索窗口，363 篇正文；重启后的 7 天期限为 9/16 16:28。PBOC 持续运行，SAFE 本轮原文队列已完成待审，未因本次修复重启。
- [故障证据、修复与验证](nbs_search_recovery_20260909/README.md)；当前进度仍以 [实时监控](source_monitor/latest.md) 为准。

### 最近完成：B02 货币信贷首批历史入库（2026-09-09 13:08）

- 两篇财政部转载核验后新增 **14 条 PIT_B、7 字段、0 修订、0 元数据覆盖**。M0/M1/M2 同比、人民币存贷款余额同比及新增存贷款累计，首次非空月末均从 **2026-06-30 前移到 2010-01-31**，首个数据期为 2009-12；同时补入 2010-03，每字段真实严格数据期 2 → 4，历史尚不连续。
- 转载日期 2010-01-18、2010-04-12，保守分别从次日零点可用；未假定央行原发时间。原文、单位、归档哈希、28 次可用边界、重复入库与主库回读均通过。旧通用解析器存在“第一季度”误判为年末等问题，本批使用封存稿件专用核验流程。
- 严格宽表仍为 **259 × 47**；本批解释 **1379 格**变化。原 CSV 另有 **201 格**落后于入库前主库，已独立对账并刷新，不算本批新增。空值率：旧 CSV 63.21%，入库前主库对应 63.00%，本批后 **51.67%**。主库 **769,574 条**，中国 **8,840 条**；本批其他来源记录数不变。
- 统计局写库任务在提交期间暂停，旧导出基线已封存并交接新基线；央行和外汇局原稿下载持续。任务状态以实时监控为准，下载任务显示的新增数不包含这次独立审核批次。
- [本批结果、原文证据与对账](pboc_reprints/b02_money_credit/README.md)；[最新 47 字段起点](pit_csv_inspection/first_points.csv)。下一步继续寻找 2005—2009 货币信贷原稿、补外储及社融证据，并完善通用旧稿解析；34 字段计划仍在进行。

### 多来源并行拉取与实时监控（2026-09-09）

- **11:34 央行新源验证后接入**：按用户要求先停全部后台，再单独测试。财政部历史正文及官方检索可访问，2010 年检索两页共 12 条、发现正文成功下载；2005 年单词查询为空，空模板已适配且不冒充历史齐全。21 项离线测试通过。央行新增 **10 篇正文种子 + 132 个年度关键词检索窗口**，从 2005 年搜索到 2026 年；旧 4 条结果、受阻站点和请求计数保留。中国政府网旧样本实测 404，本轮未接入。独立配置 `config/pboc_reprint_pull.json`，新源仅归档、不入库；见 [接入与验证](pboc_reprints/README.md)。恢复后以实时监控为准。

- **10:59 已取消请求数量上限并恢复**：NBS/PBOC/SAFE 每日和每轮请求数量均改为不限，保留原有限速、robots、HTTP 熔断及请求计数。NBS PID 12224、SAFE PID 16568 已从断点运行，SAFE 新正文 HTTP 200、累计 42 篇；PBOC 已结束且受阻的种子不自动重试。39 项测试和 311 份 NBS 归档回放通过。7 天运行期限及队列范围保留，当前 NBS 截止 9/16 10:58、SAFE 截止 9/16 08:51。详见 [变更与验证](source_monitor/UNLIMITED_REQUESTS_20260909.md)，实时状态以监控为准；下面 09:02 按每日额度估算的排期已失效。

- **09:12 日志核查**：NBS 是项目单次额度等待；SAFE 连续 HTTP 200、正常下载；PBOC 原站 robots 明确禁止，而湖南转载是 **TLS `SSL: BAD_ECPOINT` 导致 robots 读取失败**，两者原因不同。财政部 robots 的 404 未阻断正文，两篇转载已归档。详见 [日志诊断](source_monitor/LOG_DIAGNOSIS_20260909.md)。

- 各来源使用独立拉取任务及一个隐藏监控进程，各自限速、保存断点；当日请求合并统计旧账本和新账本，独立写入避免跨来源账本竞争。调整代码后通过启动器从原断点恢复。
- **实时查看：[多来源监控 latest.md](source_monitor/latest.md)**，每 10 秒自动刷新；双击项目根目录 `monitor_progress.cmd` 每 5 秒在终端查看。单次命令：`python scripts/monitor_source_progress.py`；结构化输出加 `--json`。
- 监控同时检查进程存活、心跳、完成/待拉队列、正文与目录归档数、待审数、本任务入库数、当日合计请求、截止点、错误和受阻站点，区分“额度等待、来源受阻、进程退出、原稿队列完成”。
- PBOC/SAFE 本轮 **仅归档与写独立事件日志，不写主库**；统计来源与实际托管站点分别记录。央行原站及湖南转载入口已记录 robots 限制，任务尝试其余明确列出的政府转载；PBOC 初始仅 4 个种子，不代表全部历史已建立队列。SAFE 初始 66 个 URL，历史目录发现新正文后队列增加。
- 12 项针对性测试通过；已验证 SAFE 早期正文实际归档与监控刷新。配置 `config/source_pull_tasks.json`；启动器 `scripts/start_source_workers.py`；[运行、停启和文件说明](source_monitor/README.md)。旧排期是 08:35 的估算快照，新增来源的实际运行情况以上述实时监控为准。

### 最新排期估算（2026-09-09 09:02，第二版）

- [多来源新版时间表与估算依据](source_monitor/TIMELINE_20260909_v2.md)：**NBS 首轮原稿 9/12—9/16；SAFE 首轮原稿 9/16—9/23，中心情景约 9/19**。SAFE 的估计仅基于 3 页目录，置信度低，后续新增正文会改变队列规模。
- PBOC 当前 4 个种子已于 08:56 处理结束：2 篇归档、2 个入口受限，进程已退出；**央行历史全量尚无可扩展队列，暂不估完成日**。不能把种子完成当作央行数据拉全。
- 09:02 快照：NBS 206 篇正文；SAFE 9 篇正文、3 页目录；PBOC 2 篇转载。后台本轮新增严格观测仍为 0。优先事项是旧格式适配和央行来源拓展；这些开发尚未自动启动。
- 原稿完成与 PIT 验收分开：撤回上一版固定的 9/17—9/18 可用 PIT 验收日期，改为解析通过后的条件节点；34 项完成日期仍未知，9/23 仅作建议评审检查点。
- NBS **9/15 21:45** 到期；SAFE **9/16 08:51** 到期且普通重启不会自动延长已保存的截止时间。超过这些时点的预计完成日期以安排续跑/延期为条件，**当前并未配置自动续期**。本次只更新估算，未改请求预算或后台进程。

<!-- PIT_HISTORY_AUTORUN:start -->
### 后台长任务：从 2005 年向后逐年补齐
- 状态 `RUNNING`；进程 25796；更新时间 2026-09-10T14:53:54.918527+08:00。
- 当前步骤：2024-01-01 至 2024-12-31：国民经济；已完成年度检索窗口 135/154。
- 已处理正文 951 篇；本任务累计新增严格记录 318 条；待审正文 931 篇。
- 自动执行范围：NBS 17 个目标字段的发现与已核格式补缺；未知格式/口径隔离待审。PBOC 10 项、SAFE 7 项仍需适配，不能标成全自动完成。
- 检索从 2005 到 2026-07，逐年连续推进；每日和每轮请求数量不限，来源限速与熔断保留。此进程最长运行 7 天，关机/休眠时不推进，重启后可从断点启动。
- 进度以 `data/history_backfill/pit_history_autorun.json` 为准；已插入记录/待审原稿见 `reports/v2/pit_history_autorun/`。候选数与非空格不代表真实历史完整度。
- 最近导出：2026-09-10T08:45:30.485534+08:00；运行说明见 [README](pit_history_autorun/README.md)。
<!-- PIT_HISTORY_AUTORUN:end -->

### 最近完成：34 字段回溯 B01 首轮起点（2026-09-08 19:31）

- 三篇官方原稿归档，追加 **12 条 PIT_A、0 修订、0 元数据覆盖**。B01 三项主任务及同稿七项 PMI，共 **10 个字段**的首次非空月末前移；任务状态 `ANCHOR_ADDED`，首年与后续历史未完成。
- **综合 PMI：2021-09-30 → 2018-01-31**，最早数据期 2018-01，真实月份 59 → 60；另外七项 PMI 同样前移，仍在 B03/B04 继续回溯 2005/2007 起点。
- **服务业：2022-04-30 → 2017-04-30**，最早单月数据 2017-03，真实月份 33 → 34。**失业率：2022-04-30 → 2018-04-30**，原始数据期从 2018-01 开始，真实月份 34 → 37；1/2/3 月同用 2018-04-17 10:00 的真实发布时间，4 月末宽表选中 3 月。
- 主库 **769,290 条**；中国 **8,556 条、52 序列**；NBS **1,081 条**。严格宽表 **259 × 47**，空值率 **66.99% → 63.21%**；460 格新增非空逐格核验通过，**实际只新增 12 条原始记录**。服务业/失业率/PMI 已覆盖区间内最长缺口仍分别为 **59 / 47 / 43 个月**。
- **127 项测试通过**；290 份旧归档回放，1,056 条有效记录不变；12 条原值/单位/范围/时间/SHA、24 次可用边界、重复入库及主库快照检查通过，三个 notebook 已执行。全量验收仍 FAIL：来源 4/5、历史深度 18/25、A/B 占比 59.6%。
- [本批结果及复核入口](pit_34_backfill/b01/README.md)、[34 项实际执行进度](pit_34_backfill/execution_progress.csv)、[首年待补期](pit_34_backfill/b01/first_year_period_review.csv)、[最新 47 字段起点](pit_csv_inspection/first_points.csv)。15 条同稿额外解析候选暂存待审，未计入成果。
- 本批已结束，无后台任务。**下一批 B02：货币信贷七项 + 外汇储备**，尚未启动；B01 首年及边界复查保留。Wind 暂不处理。

### 执行中的总计划：34 个晚起点字段向 2005 年或最早可核验时间回溯（2026-09-08）

- 按最新要求，**优先处理当前首次非空在 2021 年及以后的 34 项**：NBS 17、PBOC 10、SAFE 7。名单已冻结，起点前移后仍跟踪首年和后续缺期；其余 13 项的补缺队列保留并后移。
- **18 项以 2005 年为回溯目标**：货币信贷 7、制造业 PMI 及分项 6、GDP 1、房地产 3、外储 1。另 **16 项需核制度起点/口径**，包括三项投资、非制造业/综合 PMI、服务业、失业率、社融三项及外汇流量六项。2005 是争取目标，不是已证实能全部达成；实际可用时间不会早于发布。
- 六批主任务（共 34 项，不重复计数）：**B01** 综合 PMI/服务业/失业率 3 项；**B02** 货币信贷+外储 8 项；**B03** 制造业 PMI/GDP/房地产 10 项；**B04** 投资/非制造业 PMI 4 项；**B05** 外汇流量 6 项；**B06** 社融 3 项。B01 的 PMI 同稿可顺带核其他七项，仍继续回溯其各自早期历史。
- 2018-01 PMI、2017-03 服务业单月附表和 2018 年失业率首稿已在 B01 归档核验；2010 年一季度逐月涉外收支及 2015 年社融存量仍是待归档候选。特别注意：2010 代客结售汇排除银行自身，不直接接入现银行总额；2017-03 初次发布的 1—2 月服务业累计不当单月值。
- 每项按“找源 → raw 核验 → 解析验证 → 起点前移 → 首年复核 → 后续逐年补缺”推进，分别记录最早数据期、实际发布时间、宽表首次非空、真实期数和最大缺口/来源陈旧度。无法找到更早稿件不等于证明不存在；旧口径代理和 C/D 回溯表不用于伪造原字段达标。
- [完整计划与验收标准](pit_34_backfill/PLAN.md)、[34 项任务表](pit_34_backfill/TASKS.md)、[逐字段任务 CSV](pit_34_backfill/tasks.csv)、[官方证据](pit_34_backfill/source_evidence.json)。规格：`config/pit34_backfill_plan.json`；五个窄搜窗口：`config/nbs_pit34_discovery_jobs.json`；离线校验：`scripts/plan_pit_34_backfill.py`。
- 总计划状态 **IN_PROGRESS**，B01 起点批次已完成，当前数值以上方最新批次为准。规划基线保留为 259 × 47、空值率 66.99%、主库 769,278 条、中国 8,544 条；34 项冻结名单不因起点前移而减少。实际状态保存于 `pit_34_backfill/execution_state.json`，下一执行入口 B02。

### 最近完成：2005 年早期工业与社零首批（2026-09-08T16:51）

- **工业、社零最早严格数据期均为 2005-01，原起点为 2010-02。** 本批 11 篇归档已完成核验，追加 **11 条 PIT_A，无修订或覆盖旧记录**。工业新增 5 个月，社零新增 6 个月。
- 严格真实月份：工业 **36 → 41**，社零 **36 → 42**；CSV 首次非空分别为 **2005-02-28 / 2005-03-31**。工业 2005-02 原稿只有累计 16.9%，仍标缺；社零 2005-01/02 均使用原稿实际时间 2005-03-14 13:19，未倒填日期。
- 主库 **769,278 条**；中国 **8,544 条、52 个序列**；NBS **1,069 条、21 个序列**。未处理 Wind，其他来源观测数未变。
- 严格 CSV 已重导出，259 行 × 47 字段，空值率 **67.99% → 66.99%**；121 格变化，新增非空 121 格，全部匹配已核验记录。工业/社零最大来源陈旧度仍为 136 个月，历史尚不连续。
- **118 项测试通过**；280 份旧归档、1,045 条有效记录保持一致，13 条之前已更正的旧版本原样保留；11 条独立原值/时间/SHA 核验、22 次可用边界及重复入库检查通过，三个 notebook 已执行。全量验收仍为 FAIL。
- 已改为从 2005 年向后逐年补缺。下一步：2005 年下半年工业/社零、12 月价格、早期制造业 PMI；五个搜索窗口保存于 `config/nbs_early_2005_next_search_jobs.json`，尚未启动。近期综合稿 9 篇队列暂后移。
- [47 字段目标及当前起点](nbs_early_2005/history_plan.md)、[制度起点/历史口径约束](nbs_early_2005/history_constraints.md)、[各年真实期数](nbs_early_2005/yearly_raw_period_coverage.csv)。服务业、失业率、综合 PMI 等按实际公开起点回溯；旧城镇投资不直接拼接现代口径。
- 本批已结束，无本批后台任务。结果：`data/history_backfill/nbs_early_2005_run.json`；[本批说明与复核入口](nbs_early_2005/README.md)。

### 最近完成：NBS 综合稿第二批（2026-09-08，16:16）

- 固定清单 20 篇全部下载并核验，另核验三篇旧归档的商品房销售数据。**追加 206 条 PIT_A，全部为新指标月份，无修订或覆盖旧记录。** 20 篇新稿各补 10 个字段，共 200 条；旧归档补 6 条。核验的 40 条 CPI/PPI 已有同月同值记录，未重复入库。
- **主库 769,267 条；中国 8,533 条、52 个序列；NBS 1,058 条、21 个序列。** 本批继续官方数据补充，未处理 Wind。
- 截至 2026-07-31 可用的严格 A/B 原始月份：工业/社零各 **16 → 36**；服务业、固定资产投资、房地产投资各 **13 → 33**；基建、制造业投资、失业率各 **14 → 34**；商品房销售面积/销售额各 **10 → 33**。CPI/PPI 仍为 81/85 个月。
- 工业/社零最早数据期仍为 2010-02；服务业、投资和失业率的起点从 2022-05 推进到 **2022-03**；商品房销售两项从 2024-04 推进到 **2022-03**，对应首次非空月末 2022-04-30。名称衔接依据见 [官方定义复核](nbs_economy_batch2/sales_definition_mapping.md)；2010 年城镇固定资产投资仍未混入现代口径。
- 已修复季度/年度稿引用往年季度导致的数据期误判，优先使用明确的附表年月标题；补齐服务业、房地产等表格读取和成对表述的失业率识别。失业率取当月水平，累计投资/销售取累计同比，保留真实历史发布时间，未加经验 PIT 标签。
- **严格 CSV 已重导出，仍为 259 行 × 47 字段。** 空值率 **68.50% → 67.99%**；313 格变化（296 格数值改变、313 格来源数据期改变），新增非空 62 格，全部与已核验记录匹配。工业/社零沿用旧值最陈旧仍达 **136 个月**，早期大段历史仍缺失。
- 近期 12 字段 × 54 个月的 648 个参考格中，严格已覆盖 **235 → 441**；另有 87 格已找到候选但未归档正文、100 格须核对 1—2 月发布结构、20 格未找到综合稿候选。上一批的 6 个旧销售缺项已补齐。[完整缺月表](nbs_economy_batch2/recent_indicator_month_gaps.csv)。
- 从本地目录另找到 5 个仅含“经济运行”的标题，发现和解析规则已扩展；候选总数 **293 → 298**，综合稿候选 52 篇。下一批 [9 篇清单](nbs_economy_batch2/next_20_candidates.csv)已保存到 `config/nbs_economy_batch3_candidates.json`，对应 87 个待核验指标月份，状态 `READY_NOT_STARTED`，未启动下载。
- 验证：**108 项测试通过**；23 篇/246 条指标独立核对数值、历史时间和 SHA256；206 条新增完成 412 次发布前一秒/当时检查、重复入库检查及实际主库快照检查。260 份旧归档回放，839 条有效记录不变，13 条旧错误版本按上一批更正清单保留。三个 notebook 共 12 个代码单元执行通过。
- 全量验收仍为 **FAIL**：必需官方来源 4/5，可验证 A/B 占中国记录 59.5%；raw 可追溯率 100%、重复 vintage 0。包含 D 的核心字段/历史深度统计不代表严格 PIT 覆盖完成。
- 项目下载客户端本批 20 次正文请求及 1 次 robots 检查，NBS 当日账本 114；另通过网页工具核对官方定义。原稿下载于 16:13 完成，本批已结束、无后台任务。结果：`data/history_backfill/nbs_economy_batch2_run.json`；断点：`nbs_economy_batch2_download_state.json`。
- 查看：[本批说明](nbs_economy_batch2/README.md)、[逐字段覆盖变化](nbs_economy_batch2/field_coverage_changes.csv)、[全部字段起点](pit_csv_inspection/field_history.md)、[复核 notebook](nbs_economy_batch2/review.ipynb)。只读核验入口：`python scripts/review_nbs_economy_batch2.py`；显式 `--ingest` 才追加主库。导出/验收入口：`scripts/finalize_nbs_economy_batch2.py`，不联网。

### 历史快照：官方 NBS 综合稿首批完成（2026-09-08，15:15 后）

- 按用户要求先补官方数据，本轮未处理 Wind。检查原有 15 篇相关归档（14 篇综合稿、1 篇答记者问），下载并核验 2010 年 2、4、11 月三篇综合稿；本批结束，下一批尚未启动。
- **追加 30 条 PIT_A：17 个新指标月份、13 条解析更正。** 更正包括把累计 CPI/PPI 或其他月份增速误当当月值的情况；例如 2022-11 社零 -0.1% → -5.9%、2024-09 PPI -2.0% → -2.8%。原记录全部保留，严格快照选择更正版本；通用入库统计的 `revisions=13` 不是官方统计修订，见 [解析更正清单](nbs_economy_batch1/parser_correction_ledger.csv)。
- **主库 769,061 条；中国 8,327 条、52 个序列；NBS 852 条、21 个序列。** 本批全部依据原值、口径和页面可见历史发布时间入库，不使用迁移 URL 年份或经验滞后来补 PIT。
- **严格 CSV 已刷新，259 行 × 47 字段，截止 2026-07-31。** 原始可用月份：工业/社零各 **11 → 16**，CPI **78 → 81**，PPI **82 → 85**，基建投资 **13 → 14**。工业/社零最早数据期 **2022-05 → 2010-02**，首次非空月末 **2022-06-30 → 2010-03-31**。2010 年城镇固定资产投资未映射到现代不含农户口径。
- 空值率 **70.91% → 68.50%**；443 个数值单元格改变，其中新增非空 294 个，来源数据期改变 418 格，全部可由本批核验记录解释。工业/社零各 197 个非空月末只有 16 个真实数据月，沿用旧值最陈旧达 **138 个月**，不能据此认为历史补齐。CPI/PPI 在 2005-01 至 2026-06 仍缺 177/173 个月。
- 目录发现规则由“国民经济运行”扩为“国民经济”；离线重查 91 个目录归档后，候选 **253 → 293 个 URL**。排除答记者问、署名解读和统计公报后得到 47 篇综合稿候选。[近期缺月表](nbs_economy_batch1/recent_indicator_month_gaps.csv)覆盖 12 个字段 × 54 个月：235 格已有严格记录，247 格有候选但无正文，100 格须核对 1—2 月发布结构，60 格未发现综合稿候选，6 格待核对旧商品房销售定义。
- 下一批 [20 篇官方候选](nbs_economy_batch1/next_20_candidates.csv)已保存到 `config/nbs_economy_batch2_candidates.json`，状态 `READY_NOT_STARTED`；优先补 2022 年至 2025 年实体经济缺月。候选日期只作查验提示，必须再核对正文数值、月度/累计口径和历史发布时间，不能直接入库。
- 验证：**100 项测试通过**；260 份原始文件离线回放，原有 822 条中 809 条不变、13 条更正，无记录消失或解析异常；30 条独立数值/时间/SHA 核验、60 次发布边界检查、重复入库及原记录保留检查通过。另有 15 条已覆盖 PMI/PPI 重述值未重复入库。三个 notebook 共 12 个代码单元执行通过。
- 全量验收仍为 **FAIL**：必需官方来源 4/5，A/B 占中国记录 58.5%；raw 可追溯率 100%，重复 vintage 0，19 个来源/序列内部覆盖低于 95%。核心指标 16/16、历史深度 26/25 包含 D 等级，不能理解为严格 PIT 覆盖完成。
- 本批新增 3 次官方正文请求及 1 次 robots 检查，当日 NBS 请求账本为 93。下载断点 `nbs_economy_sample_batch1_state.json` 已完成；当前没有本批后台任务。
- 查看：[本批说明](nbs_economy_batch1/README.md)、[逐字段起点与月份数](pit_csv_inspection/field_history.md)、[复核 notebook](nbs_economy_batch1/review.ipynb)、[完整结果](nbs_economy_batch1/final_result.json)。离线核验：`python scripts/validate_nbs_economy_batch.py`；显式 `--ingest` 才写主库。`scripts/finalize_nbs_economy_batch.py` 刷新导出、审计、缺月表与 notebook，不联网。

### 历史快照：Wind 首批，18 项已检查、8 项部分入库（2026-09-08，第五批 NBS 完成后）

- 收到 `data/manual_import/wind/数据.xlsx`：436 个日期、18 个指标、7,848 个数值单元格。原件已另存 SHA256 归档，首次归档时间为 **14:10:31 Asia/Shanghai**，导出时间未知；原文件不变。清单与证据见 [接入说明](wind_batch1/README.md)。
- **新增 1,958 条 WIND / PIT_D，8 个指标，无修订、无覆盖。** 海关美元出口/进口/差额及进出口同比各 260 个月（2005-01 至 2026-08）；M2 同比 259 个月（2005-01 至 2026-07），M1 同比 258 个月（2020-01 的零待核对）；社融存量同比 141 期（2005-12 至 2026-07），早期仅年末/季末记录，2016 年起连续月度。
- 内嵌配置确认空值填 0，共 2,515 个零，不能区分真实零与填充值；s2—s11 共 10 项经过人民币转美元，其中 s7—s9 还从季度转为月度，s5 改过数量级。变换项和歧义零未写入主库；2005 年前记录也只留存原件。共 5,890 个单元格未接入，排除原因可能重叠，不等于全是坏数据。
- 入库来源保持 `WIND`，原始发布机构另保存在接入元数据；不冒充 CUSTOMS/PBOC 官方原稿。`release_at` 为空，真实可用时间从首次归档起算；未添加经验 PIT 标签，未实现估计可用日期视图。海关金额由亿美元乘 0.1 转为项目的 `bn_usd`。
- **主库 769,031 条；中国 8,297 条、52 个序列。** 其中 WIND 1,958 条/8 个指标，NBS 822 条/21 个指标；本节已包含后台第五批新增的 25 条 PIT_A。
- **严格宽表仍为 259 行 × 47 指标。** 已核对 Wind 入库前后严格查询结果及四个导出文件 SHA 完全相同。最新严格导出对应第五批 NBS：截至 2026-07-31，CPI 78 个、PPI 82 个原始月份，空值率仍为 70.91%。不要用当前值历史 CSV 冒充严格 as_of 面板。
- 全量验收仍为 **FAIL**：必需官方来源 4/5，可验证 A/B 占中国记录 58.3%；核心指标 16/16、历史深度 26/25 是现有验收程序包含 D 的数值覆盖统计，不能解读为严格 PIT 覆盖完成。技术审计 raw 可追溯率 100%、重复 0，19 个来源/序列内部覆盖低于 95%。本批审计另存 `wind_batch1/audit/` 和 `acceptance.txt`，之前批次报告保留为时间快照。
- 验证：新增 Wind 测试 **8/8 通过**；复核 notebook 4 个代码单元执行通过，独立逐格核对 **1,958/1,958**，内存库重复入库为 0 新增；strict/loose 排除 D、first_seen 前一秒不可见及当时可见均通过。260 个海关月份金额恒等式最大差 0.01 亿美元，在本轮舍入容差内。
- 下一批优先 [剩余七项](wind_batch1/next_download_7.csv)：M0 同比、人民币存贷款余额同比、新增人民币存贷款累计、社融增量累计、社融存量。原始代码见 [十项重导清单](wind_batch1/reexport_10.csv)；金融统计新增贷款总量不能用社融人民币贷款分项替代，余额也不能直接当同比。关闭换汇、填零、插值和变频，保留原始单位/频率。
- 用户查看入口：[当前值宽表](wind_batch1/wind_current_history_values.csv)、[逐字段起止与变换](wind_batch1/field_profile.csv)、[复核 notebook](wind_batch1/review.ipynb)。只读重检入口：`python scripts/review_wind_batch.py`；显式 `--ingest` 才追加主库。HTML 打包因本机缺少 Node/npm 未完成，说明与 CSV/notebook 已交付；详情保存在 `wind_batch1/report_delivery.json`。

### 历史快照：第五批，25 篇价格稿自动复核入库（已完成）

本批处理第四批列出的 25 个缺失价格数据期（CPI 11、PPI 14）；单进程按 75—105 秒间隔运行，全部完成或遇阻即退出，不跨日等待。只有归档搜索标题、正文首段数值、页面可见历史发布时间一致，且解析器、发布边界及重复入库验证通过，才写入主库。随后自动导出 CSV、运行全量验收、刷新逐字段检查与 notebook。下列段落由任务自动刷新；`COMPLETE` 仅表示本批完成，不代表历史数据完整。

<!-- nbs-price-batch5:start -->
- 状态：`COMPLETE`；PID：13060；更新时间：2026-09-08T14:14:47.495394+08:00。
- 固定队列 25 篇；已通过独立正文核对 25 篇。
- 阶段：`exported_and_checked`；结果：`data/history_backfill/nbs_gap_batch5_run.json`。
- 本批入库：新增 25、修订 0、未变 0。
- 主库 767073 条；中国 6339 条、47 序列；严格宽表 259 行 × 47 指标。
- 全量验收：FAIL；报告：`reports/v2/nbs_gap_batch5/review.html`。
- 截止日前原始月份：CPI 78、PPI 82；CSV 空值率 70.91%。
<!-- nbs-price-batch5:end -->

- 启动/恢复入口：`python scripts/run_nbs_price_batch_once.py --manifest config/nbs_gap_batch5_validation.json --batch nbs_gap_batch5 --allow-network --status-marker nbs-price-batch5`。运行时持有 `data/history_backfill/nbs_price_batch.lock`，不要重复启动；遇服务器阻断先复核原因，不自动重试。
- 持久化结果：`data/history_backfill/nbs_gap_batch5_run.json`；正文断点：`nbs_gap_batch5_validation_state.json`；核对证据：`config/nbs_gap_batch5_expected.json`；报告目录：`reports/v2/nbs_gap_batch5/`。
- 日志：`logs/nbs_gap_batch5.stdout.log`、`logs/nbs_gap_batch5.stderr.log`。进程关闭后查看结果 JSON 和本段状态；导出失败时保留原入库结果，恢复不会重复计数。

### 启动第五批前的入库快照（2026-09-08 13:17，第四批）

- 本批 9 篇已完成正文验证并新增入库 9 条 PIT_A，无修订、无覆盖：CPI 2021-06/07；PPI 2021-04/05/06/07 和 2024-12；GDP 2021-Q3/Q4。
- 当前主库 **767,048 条**；中国 **6,314 条、47 个序列**；NBS **797 条、21 个序列**。MOF/PBOC/SAFE/OECD 本批未新增。
- 严格月末宽表已于 **13:16** 重导出，仍为 259 行 × 47 个指标。按 2026-07-31 截止日前可用的原始数据期统计：CPI **65 → 67 个月**，PPI **63 → 68 个月**，GDP **18 → 20 个季度**。GDP 原始起点 **2022-Q1 → 2021-Q3**，CSV 首次有值 **2022-04-30 → 2021-10-31**。
- 导出前后对照：仅 CPI/PPI/GDP 合计 **13 个单元格**变化，9 条新记录的首个月末可见性均通过；空值单元格 **8,638 → 8,632**，空值率 **70.96% → 70.91%**。非空值中的历史陈旧问题仍需逐月补齐。
- 修复 GDP 旧标题中的“（GDP）”识别，以及 PPI“出厂价格和购进价格同比均下降”的解析；GDP 分派依据标题，避免正文相关链接误触发。完整测试 **67/67 通过**；修复后离线回放 **223 份原始文件、788 条既有 NBS 记录**，数值、数据期、发布时间等均一致。新批次另通过 SHA256、独立正文/表格值、18 个发布边界及重复入库检查。
- 原 43 个失败项复核：**3 个已修复入库**；5 个为年度“三新”经济稿，5 个为年度 GDP 修订/最终核实稿，不对应当前季度同比目标；30 个 HTTP 404 未重试。原始失败日志保留，处理结果见 `reports/v2/nbs_gap_batch4/existing_queue_resolution.csv`。
- 最新全量验收仍为 **FAIL**：必需来源 4/5、核心指标 14/16、历史深度 19/25、可验证 A/B **76.3%**；18 个序列内部覆盖低于 95%。raw 可追溯率 100%、重复 0；美国 RTDSM 通过。
- 已发现旧稿候选仍为 **332 篇，其中 19 篇已入库**；本批六篇待补价格稿已完成。另已列出 **25 个尚未入库的 2020—2021 价格数据期候选**（CPI 11、PPI 14），见 `reports/v2/nbs_gap_batch4/next_price_candidates.csv`；仍须下载正文并核对。
- 本批下载与验证均已退出，断点 `data/history_backfill/nbs_gap_batch4_validation_state.json` 为 **COMPLETE / pending 0**。本批使用 6 篇网络正文及 3 篇缓存；请求账本由 55 增至 63（含 1 次本机沙箱连接拒绝及 1 次 robots 检查），未遇服务器 403/429，未启动下一批网络任务。
- 复核入口：`reports/v2/nbs_gap_batch4/review.html`、`review.ipynb`（5 个代码单元执行通过）、`validated_samples.csv`、`cached_regression.json`、`export_changes.csv`、`final_result.json`。原导出已保存在该目录 `before/`。逐字段起点、覆盖及两个检查 notebook 已同步刷新至 `reports/v2/pit_csv_inspection/`。

### 后台窄搜第三批

本批按“不长时间值守”的偏好在后台运行；以下专用段落由批次退出时自动刷新。下方数据库和宽表数字仍对应 10:56 的已入库快照。

后台编排验证：完整测试 62/62 通过，包含批次上限、遇阻停止、结果持久化和状态段落刷新。

<!-- nbs-gap-batch3:start -->
- 后台批次状态：`FINISHED`；结束时间：2026-09-08T11:31:00.933079+08:00。
- 最新合并候选：332 篇。此次只发现候选，主库 observation 和严格宽表未新增。
- 批次结果：`data/history_backfill/nbs_gap_search_batch3_run.json`；`FINISHED` 仅表示本批次结束，不表示历史覆盖完整。
- `economy_indicators_2010`：1/1 页；COMPLETE；下一页 2。
- `economy_running_2010`：1/2 页；PAUSED；下一页 2。
- `cpi_2020_2021`：4/6 页；PAUSED；下一页 5。
- `ppi_2020_2021`：4/4 页；COMPLETE；下一页 5。
<!-- nbs-gap-batch3:end -->

### 历史入库快照（2026-09-08 10:56；最新见文首第四批）

- 主库共 767,039 条；中国 6,305 条、47 个已填充序列。
- MOF：195/195 个候选稿处理成功，`COMPLETE`，待处理 0；已入库 1,125 条、7 个序列，数据期 2008-08 至 2026-07。
- NBS：已入库 788 条、21 个序列，全部为 PIT_A；CPI/PPI 的最早数据期均为 2005-01，各序列起点不同。2020 年以前的 NBS 记录共 9 条；另外新补 2021 年 CPI/PPI 的 4 条记录，历史仍不连续。
- 最近一次完整测试：60/60 通过（含搜索重复页检测及日期窗口共用客户端的请求审计测试）。两批共 13 篇真实旧稿另经正文数值、数据期、发布时间、SHA256、26 个发布边界及重复入库检查。
- 最近全量验收（10:56 Asia/Shanghai）：`OVERALL: FAIL`。必需来源 4/5、必需核心指标 14/16、历史深度 19/25、可验证 A/B 记录 76.2%；美国 RTDSM 仍通过。技术审计 raw 可追溯率 100%、重复 0，但 18 个已填充序列的内部月份/季度覆盖低于 95%，仍需补齐。
- 严格月末宽表已于本轮重导出：259 行、47 个指标列，已反映随后 MOF/NBS 数据及本轮旧稿；values、来源数据期和 metadata 同步更新。不能把稀疏历史下的最新已知值误读为逐月回填。
- 用户要求低 token 消耗、不长时间值守；使用有限后台批次，完成后退出并保留断点。

### NBS 现有发布目录回填：已处理完

- `sj/zxfb/` 首页加 `index_1` 至 `index_66` 共 67 个索引页，目录发布日期约覆盖 2021-09 至 2026-08，不能据此回填至 2005 年。
- 253 个候选稿均已处理：210 个成功、43 个失败，队列 `COMPLETE`、待处理 0；其中新增入库 608 条。
- `COMPLETE` 表示队列已处理完，不表示所有稿件解析成功。43 个失败项保留在断点和日志中，后续需逐项复核。
- 断点：`data/history_backfill/nbs_release_2005_state.json`；日志：`logs/nbs_history_backfill.jsonl`。

### NBS 旧发布稿搜索：已补完 PPI 最后一页，CPI 需窄搜

广泛搜索批次于 **2026-09-08 10:17:29 +08:00** 补完 PPI 第 15 页并正常退出，持久化状态为 `PAUSED`。该断点累计处理 41 个结果页，得到候选记录 282 条、当时按 URL 去重后为 278 篇。随后第二批增加下述 4 页窄搜，**第二批结束时合并候选为 290 篇**，推断数据期为 **2005-01 至 2021-08**；第三批最新结果见文首后台段落。这不代表逐月完整覆盖。

| 搜索词 | 已完成页 / 总页 | 候选记录数（跨词去重前） | 状态 |
| --- | ---: | ---: | --- |
| 居民消费价格 | 已处理 26 页 | 171 | 第 26 页重复第 1 页；needs_narrowing |
| 工业品出厂价格 | 15 / 15 | 111 | 本词队列处理完，仍需月份缺口复查 |
| 工业生产者出厂价格 | 0 / 未知 | 0 | 未开始 |
| 采购经理指数 | 0 / 未知 | 0 | 未开始 |
| 国民经济运行 | 0 / 未知 | 0 | 未开始 |
| 国民经济主要指标 | 0 / 未知 | 0 | 未开始 |
| 国内生产总值 | 0 / 未知 | 0 | 未开始 |

- 搜索入口已验证：NBS 官方搜索页引用的 `POST https://api.so-gov.cn/query/s`，`siteCode=bm36000002`；采用仅标题、按日期倒序、发布日期 2005-01-01 至 2020-02-29，每页 20 条。
- 第二批结束时，290 篇合并候选中有 13 篇已验证入库、277 篇未完成；第四批结束时为 **332 篇候选、19 篇已入库、313 篇待筛选/验证**。候选仅保留 `www.stats.gov.cn/sj/zxfb/` 发布稿链接，排除社交平台和解读路径；官方发布路径中仍可能出现不属于目标价格指标的收入等稿件，需要按题目和正文筛选。
- 离线复核全部 41 页发现 CPI 第 26 页的 URL/日期列表与第 1 页相同，虽然 API 响应的整体 SHA 不同。已保存重复页证据、备份并修正断点：`complete=false, needs_narrowing=true`。新搜索器按结果文档指纹检测循环，不再把重复页计为新增候选；续跑会跳过需窄搜的词，其他词仍可继续。全部其他词完成后，若仍有窄搜项则返回 `PARTIAL`。
- 后台脚本每次最多新增 20 个搜索页，间隔 75–105 秒，保留单线程、缓存优先、robots 检查、请求预算及 403/429 停机机制；达到批次上限后退出。
- 当前 NBS 来源预算为每进程 300 次、每天 400 次请求；这是此前有限发布稿队列的配置，不等于本搜索脚本每批 20 页的上限，robots 请求也消耗预算。

续跑与复核入口（均相对项目根目录）：

- 搜索断点：`data/history_backfill/nbs_legacy_search_state.json`。
- 候选清单：`data/discovery/nbs_legacy/nbs_candidates.parquet`、`nbs_candidate_urls.txt`。
- 运行日志：`logs/nbs_legacy_search.stdout.log`。
- 广泛搜索后台脚本：`scripts/run_nbs_legacy_search_once.ps1`；命令入口：`discover-nbs-legacy`，可用 `--max-network-pages 1` 限制新增一页。窄搜入口见下一节。
- 搜索词：`config/nbs_legacy_search_terms.txt`；实现：`src/macro_pit/nbs_search.py`。
- 续跑前核对已有进程和当日预算，避免重复启动。两批搜索和正文下载均已退出；没有启动跨日等待任务。

### NBS 窄搜补缺：新增 12 个候选、5 条入库记录

- 本轮增加 4 个搜索页，合并候选从 278 增至 290。其中 11 篇是 CPI/PPI 价格稿，1 篇是居民收入和消费支出稿，后者未加入价格正文队列。
- CPI 2005 年一季度：1/1 页，新增 2005-01 原稿；正文核对同比 1.9%、发布时间 2005-02-22 09:11，已入库 PIT_A。2005 年 CPI 候选现为 11/12 月，仅缺 12 月。
- CPI 2010 数据年对应发布日期窗口（2010-02-01 至 2011-02-28）：1/1 页、3 个搜索结果、2 个已知候选，未新增。2010 年 2–12 月仍缺候选，不能将该窗口搜索结束理解为数据齐全；下一步尝试综合国民经济发布稿。
- 发布日期 2020-03-01 至 2021-09-30：CPI 完成 1/6 页、候选月份为 2021-05 至 2021-08；PPI 完成 1/4 页、候选月份为 2021-03 至 2021-08。各自状态 `PAUSED`、下一页均为 2；2020 年缺口尚未补齐。
- 本轮另外入库 CPI 2021-05（1.3%）、2021-08（0.8%）；PPI 2021-03（4.4%）、2021-08（9.5%），全部为 PIT_A。5 条合计新增，无修订。
- 断点：`data/history_backfill/nbs_cpi_2005_q1_search_state.json`、`nbs_cpi_2010_search_state.json`、`nbs_cpi_2020_2021_search_state.json`、`nbs_ppi_2020_2021_search_state.json`；正文断点：`nbs_gap_validation_state.json`，`COMPLETE`，待处理 0。
- 搜索续跑：`python scripts/run_nbs_gap_search_once.py --max-pages-per-job 3 --allow-network`。按 `config/nbs_gap_search_jobs.json` 逐窗执行、共用一个客户端保留跨窗口限速及 robots 缓存；已完成窗口跳过，此配置下一批最多新增 6 个搜索页，完成后退出。
- 本轮报告目录：`reports/v2/nbs_gap_probe_20260908/`；其中 `search_summary.json`、`new_candidates.csv`、`gap_coverage.json` 保留搜索证据，`validated_samples.csv` 保留正文、数值和发布时间证据。
- 完整报告：`reports/v2/nbs_gap_probe_20260908/review.html`；可复跑 notebook：`review.ipynb`，全部代码单元执行通过；验收：`acceptance.txt`；完整结果：`final_result.json`。严格宽表已于 10:56 重导出，仍为 259 行、47 指标，并验证 2005-01 CPI 从 2005-02 月末可见，以及 2021-08 CPI/PPI 从 2021-09 月末可见。
- 本轮 NBS 请求账本增加 12 次（4 个搜索页、5 篇正文及 3 次 robots 检查），当日合计 46 次；无 403/429。全部下载进程已退出，搜索和正文断点均已保存。
- 新候选中另有 6 篇价格稿尚未下载正文，已保存为 `config/nbs_gap_remaining_price_urls.txt` 和报告目录的 `remaining_price_candidates.parquet`；收入稿已排除。

### 已完成的代码改动及待验证范围

- HTTP 客户端新增表单 POST，缓存键包含请求参数，保留原始响应归档及请求审计。
- 旧稿搜索增加断点、候选去重及官方发布稿 URL 过滤；实现位于 `src/macro_pit/http.py`、`src/macro_pit/nbs_search.py`、`src/macro_pit/cli.py`。
- NBS 解析器已有的 CPI“总水平”和 PPI“工业品出厂价格”等规则已通过本轮真实旧稿验证；PMI 旧表述及 12 月跨年规则此前单元测试通过，仍需相应真实旧稿抽验。本轮未改变数值解析规则。
- 严格 PIT 必须从正文验证原始值和真实发布日期/时间；迁移 URL 中的 `202302`、`202303` 不能充当历史发布时间。C/D 数据不进入严格 A/B 宽表。
- NBS `data.stats.gov.cn` 历史接口此前返回 403，仍不重试；PBOC robots 禁止路径仍需使用手工保存文件的离线入口。

### 已完成的旧稿首批验证（2026-09-08，10:33 快照）

- 8 篇：2005-02 CPI 3.9%、2005-01 PPI 5.8%；2010-01 CPI 1.5%、PPI 4.3%；2015-01 CPI 0.8%、2015-02 PPI -4.8%；2019-01 CPI 1.7%、PPI 0.1%。全部根据正文与历史页面时间验证为 PIT_A，新增 8 条，无修订。
- 原始正文下载断点：`data/history_backfill/nbs_legacy_validation_state.json`，`COMPLETE`，待处理 0。
- 人工核对的预期值与证据片段：`config/nbs_legacy_review_expected.json`；离线复核入口：`scripts/validate_nbs_legacy_batch.py`（默认不写主库；显式 `--ingest` 才入库）。
- 候选按年/按月缺口：`reports/v2/nbs_legacy/candidate_year_coverage.csv`、`candidate_missing_months.csv`。2005-01 CPI、2010 年大部分月份、PPI 2011–2014、2020-02 至 2021-08 等仍缺候选；候选存在也不代表正文已验证。
- 搜索重复页证据：`reports/v2/nbs_legacy/search_pagination_audit.json`；离线复核脚本：`scripts/audit_nbs_search_pages.py`。
- 原有 43 个失败项已分类：30 个 HTTP 404、7 个零行解析、5 个数据期提取失败、1 个 GDP 季度识别失败。清单：`reports/v2/nbs_legacy/existing_queue_failures.csv`；本轮未自动重试。
- 本轮报告：`reports/v2/nbs_legacy/review.html`；可复跑检查：`review.ipynb`，代码单元已执行通过；逐篇证据：`validated_samples.csv`；验收：`acceptance.txt`；完整结果：`final_result.json`。
- 导出：`data/exports/cn_pit_month_end_2005_20260731_values.parquet` 及同前缀 periods/metadata 文件。另存 `reports/v2/nbs_legacy/price_panel_source_age.csv`，标示 CPI/PPI 每个月末使用的数据期及其距月末的月数。
- 当日 NBS 预算账本为 34 次，本轮增加 13 次（含 1 次沙箱套接字拒绝与 robots 请求）。沙箱拒绝没有访问到服务端；获准出站后搜索/正文请求完成，本轮未遇到服务端 403/429。

### 下一步

1. 按 `config/nbs_economy_batch3_candidates.json` 核验下一批 9 篇综合稿，优先补 2023-03、2024-12、2025-04/07/09/11、2026-03/04/06 的实体经济缺月。清单已准备，未开始下载；每篇须先验证原值、统计口径与历史发布时间，不能把候选字段数当作已确认增量。
2. 继续 2010 年其余综合稿及价格历史：首批 2、4、11 月已验证，不能重复计为增量。2010“国民经济运行”搜索仍剩 1 页，2020—2021 CPI 搜索仍剩 2 页；本批仅重查本地目录、下载三篇样本，没有续跑搜索。
3. 补查 PPI 2011—2014、2005 年 12 月 CPI/PPI 对应的次年发布稿，以及近期尚未找到综合稿候选的月份；逐项核对 1—2 月单月与累计发布结构。6 个旧商品房销售缺项已在第二批补齐。候选数、原始月份数与非空快照格数分开统计。
4. 既有 404 先查官方链接和来源，避免盲目重试；年度综合稿若附有明确 12 月列可逐项核验，不把全年增速当季度或当月增速。后续再补 PBOC 历史、SAFE 原始发布时间证据和海关官方缺口；Wind 按用户当前要求暂不继续处理。
5. 每批入库后刷新覆盖、严格宽表及 `pit_csv_inspection`，同时核对来源数据期、版本和陈旧程度；保留解析更正清单，不能仅以起点提前或非空率衡量完成度。

## 历史快照：2026-09-04 16:55 Asia/Shanghai

以下数字、任务状态、测试和验收结果仅对应当时快照，不代表 2026-09-08 当前状态。

- Database: `macro_pit_v2.duckdb`
- Observation rows: 765,834
- Raw references verified: 100%
- Duplicate vintage rows: 0
- China: 47 populated series, 5,100 rows
- China historical-depth gate: 15/25 series
- China required sources: 4/5; Customs remains missing
- China required core series: 14/16; export/import remain missing
- China verifiable PIT A+B rows: 70.6%
- US RTDSM: 15 populated series; 1,500/1,500 sampled workbook cells match
- OECD global extension: optional and non-blocking
- Automated tests: 51 passed
- Technical audit: one populated series below 95% internal period coverage; HTTP/parser failures remain recorded
- Strict China + US acceptance: `OVERALL: FAIL`

### China history progress

- MOF: 195 release candidates from 2008-08 to 2026-07; 78 completed, 117 pending. The normalized database currently contains 78 periods from 2019-07 to 2026-07 across seven fiscal series. No live MOF worker was detected at 2026-09-04 16:27; the persisted `WAITING_NEXT_DAY` state requires an explicit resume after migration.
- SAFE: 1,415 PIT_D long-history rows plus 84 annual-consolidation PIT_C rows. Foreign-exchange-reserve observation periods are continuous for all 320 months from 1999-12 to 2026-07 when B/C/D evidence is combined. Strict snapshots still use only A/B.
- NBS: current domestic-source coverage is unchanged. A single `data.stats.gov.cn` history probe returned HTTP 403 on 2026-09-04; the circuit stopped immediately and the endpoint must not be retried.
- PBOC: three strict periods remain populated. Both the statistics catalogue and financial-statistics list are disallowed by robots.txt. Two browser-saved pages pass the new manual archive and offline-ingest workflow with 20 unchanged rows.
- OECD China supplement: CPI has 2,373 edition vintages over 402 observation periods from 1993-01 to 2026-06; industrial production has 316 valid edition vintages from 1999-01 to 2026-05. Both are PIT_B and do not replace required NBS series.
- Customs: no observations. WAF/TLS failures remain unresolved; use browser-saved official files and offline ingestion rather than automated retries.

### Data-quality repairs

- SAFE annual reserve pages for 2018-2024 are parsed as PIT_C because their page dates prove when the whole consolidation became available, not each month's original release time.
- An OECD China retail result was removed because values contradicted its declared index unit. One zero industrial-index sentinel was also removed.
- Raw OECD files and crawl logs were retained. The pre-repair database backup is `data/backups/macro_pit_v2_pre_oecd_cn_repair_20260904.duckdb` with SHA256 `7F47A5ED9D3F804508E0B1120525DEAFE8DC946E11B18B53E415FEB294D9AB8E`.
- The strict month-end wide panel was regenerated with 259 rows and 37 indicator columns. Every 2005 month now has two non-null edition-backed indicators: OECD China CPI and industrial production.

### 2026-09-04 request safety evidence

Daily ledger at this cutoff:

```text
MOF 41
NBS 2
OECD 7
PBOC 1
SAFE 10
```

- NBS HTTP 403: stopped with no retry.
- PBOC robots.txt disallow: stopped with no page request.
- OECD China GDP in the STES revisions dataset returned HTTP 404; this is treated as an unavailable series, not a transient error.
- SAFE used one index page and seven annual pages, then all parsing and ingestion ran offline.
- No HTTP 429 occurred.

No proxy rotation, browser fingerprint spoofing, CAPTCHA bypass, or concurrent requests were used.

### Migration handoff

Read `MIGRATION_README.md` before copying the project. Its migration-time MOF snapshot is 78 completed / 117 pending; use the current section above and `data/history_backfill/mof_2005_state.json` for the post-migration progress.
