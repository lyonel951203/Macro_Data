"""Write the completed batch handoff from validated results; no ingestion."""
from datetime import datetime
import json
from pathlib import Path
import pandas as pd
from macro_pit.timeutils import SHANGHAI

OUT=Path("reports/v2/nbs_economy_batch2")


def write_report():
    result=json.loads((OUT/"final_result.json").read_text(encoding="utf-8"))
    assert result['status']=='COMPLETE'
    fields=pd.read_csv(OUT/"field_coverage_changes.csv")
    tests=json.loads((OUT/"test_results.json").read_text(encoding="utf-8"))
    state=json.loads(Path('data/history_backfill/nbs_economy_batch2_download_state.json').read_text(encoding='utf-8'))
    assert state['status']=='COMPLETE' and state['pending']==0 and tests['failed']==0
    by_id=fields.set_index('indicator')
    industry=by_id.loc['CN_INDUSTRIAL_VALUE_ADDED_YOY']
    sales=by_id.loc['CN_NEW_HOME_SALES_AREA_YTD_YOY']
    gaps=result['next_plan']['gap_status_counts']
    lines=["# NBS 综合稿第二批完成", "", f"更新时间：{result['at']}。20 篇官方综合稿全部下载并通过正文核验，另核对三篇旧归档的商品房销售值。本批追加 **206 条 PIT_A，全部为新的指标月份**，无解析更正或覆盖旧记录。", "",
           f"主库 {result['database_rows']:,} 条，中国 {result['china_rows']:,} 条、{result['china_series']} 个序列；NBS {result['nbs_rows']:,} 条。其余来源的观测数量不变，本批未处理 Wind。", "",
           "## 真实覆盖增量", "", "以下按截至 2026-07-31 23:59:59 上海时间可用的 A/B 原始数据期去重，不使用非空快照格数代替月份数。", "",
           "| 指标 | 补前月份数 | 补后月份数 | 补后最早数据期 |", "| --- | ---: | ---: | --- |"]
    for row in fields.itertuples():
        lines.append(f"| {row.name_after} | {row.strict_periods_by_cutoff_before} | {row.strict_periods_by_cutoff_after} | {row.strict_first_period_by_cutoff_after} |")
    lines += ["", "本批新下载稿覆盖 2022-03/06/07/08/09/10/12，2023-05 至 12，2024-03/05/11，2025-03/06，每篇补入 10 个实体经济字段，共 200 条。另补 2022-05、2022-11、2023-04 三篇原有归档的销售面积与销售额累计同比，共 6 条。", "",
              "同时核对的 40 条 CPI/PPI 已有同指标、同月、同值记录，未重复入库；CPI/PPI 严格覆盖仍为 81/85 个月。解析到的其他已覆盖重述值另列排除清单。", "",
              "## 本批修复的解析遗漏", "",
              "- 用附表中明确的年月标题识别季度、年度稿的数据期，防止正文引用的往年季度或发布日期被误认成统计期。",
              "- 从附表读取服务业当月同比、房地产累计同比；失业率读当月水平列，不能读同比百分点变化或累计平均值。",
              "- 2022 年 6 月失业率由全国口径的 4 月句子及紧接的 5、6 月成对表述确认，6 月为 5.5%，不取季度平均或户籍分组值。",
              "- 2022—2023 年旧商品房销售名称已按官方指标解释确认属于新建商品房。映射范围、原值累计口径和文档证据见 [名称衔接说明](sales_definition_mapping.md)。2010 年城镇固定资产投资仍不混入现代不含农户口径。", "",
              "## 严格 CSV 与剩余缺口", "",
              f"已刷新 259 个自然月末 × 47 字段的 [严格 CSV](../../../data/exports/cn_pit_month_end_2005_20260731_values.csv)、来源数据期和元数据。空值率 {result['before_missing_pct']:.2f}% → {result['after_missing_pct']:.2f}%；{result['changed_export_cells']} 格变化，其中数值改变 {result['changed_value_cells']} 格，来源数据期改变 {result['changed_period_cells']} 格，新增非空 {result['newly_nonnull_cells']} 格。所有变化逐格匹配本批已核验记录，其余字段保持一致。", "",
              f"工业、社零的最早数据期仍为 2010-02，中间缺月大量存在；工业旧值的最大陈旧程度从 {industry.max_source_age_months_before} 降到 {industry.max_source_age_months_after} 个月，仍不能作为连续历史序列使用。商品房销售两项最早数据期由 {sales.strict_first_period_by_cutoff_before} 推进到 {sales.strict_first_period_by_cutoff_after}。请联合 [字段起点与月份数](../pit_csv_inspection/field_history.md)、[来源数据期年龄](panel_source_age.csv) 查看。", "",
              "近期缺月表覆盖 2022-01 至 2026-06 的 12 个 NBS 月度字段，共 648 个参考格：", "",
              f"- 已有严格记录：235 → {gaps.get('covered_strict',0)} 格。",
              f"- 有官方候选、未归档对应正文：{gaps.get('candidate_exists_article_not_archived',0)} 格。",
              f"- 1—2 月发布结构须逐项核对：{gaps.get('jan_feb_publication_structure_needs_review',0)} 格，不自动拆成单月。",
              f"- 尚未发现综合稿候选：{gaps.get('combined_release_candidate_not_discovered',0)} 格。", "",
              f"下一批保留 {result['next_plan']['next_queue']} 篇候选，见 [候选清单](next_20_candidates.csv) 和 `config/nbs_economy_batch3_candidates.json`；仅准备清单，未启动后续下载。", "",
              "## 验证", "",
              f"- {tests['passed']} 项测试通过。",
              "- 23 篇稿件、246 条指标记录均通过独立 lxml 表格或限定正文核对、复核预期值、SHA256、页面历史发布时间与解析器结果比较。",
              "- 对 206 条新增记录完成 412 次发布前一秒/发布时刻检查，内存重复入库 0 新增；实际主库逐条验证 PIT 版本选择，原 852 条 NBS 记录全部保留。",
              "- 260 份旧归档回放：839 条有效记录的数值、时间、单位、频率和等级不变；13 条旧错误版本按第一批更正清单明确识别，未误记成本批更正。只发现本批已核验的 6 个旧销售缺项。",
              "- 批次复核、字段历史、CSV 三个 notebook 共 12 个代码单元执行通过。",
              "- 全库 raw 可追溯率 100%、重复 vintage 0；[全量验收](acceptance.txt)仍为 FAIL。必需官方来源尚未齐全，可验证 A/B 占比也未达标；包含 D 的历史深度统计不能代表严格 PIT 完成。", "",
              "复跑入口（设置 `PYTHONPATH=src`，从仓库根目录运行）：", "", "```text", "python scripts/review_nbs_economy_batch2.py", "python scripts/regress_nbs_economy_batch2.py", "```", "",
              "上述入口不联网、不写主库，会刷新核验产物；显式 `--ingest` 才追加主库。导出及验收入口为 `scripts/finalize_nbs_economy_batch2.py`，说明生成入口为 `scripts/report_nbs_economy_batch2.py`。原始下载断点已完成，当前无本批后台任务。", "",
              "证据入口：[逐条核验](validated_samples.csv)、[字段覆盖变化](field_coverage_changes.csv)、[CSV 差异](export_changes.csv)、[近期缺月](recent_indicator_month_gaps.csv)、[复核 notebook](review.ipynb)、[完整结果](final_result.json)。"]
    (OUT/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    task=dict(batch='nbs_economy_batch2',status='COMPLETE',completed_at=datetime.now(SHANGHAI).isoformat(),
              downloaded_articles=20,reviewed_articles=23,verified_records=246,new_series_periods=206,
              revisions=0,background_task_running=False,next_batch_started=False,
              result_path=(OUT/'final_result.json').as_posix(),next_manifest='config/nbs_economy_batch3_candidates.json')
    Path('data/history_backfill/nbs_economy_batch2_run.json').write_text(json.dumps(task,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(task,ensure_ascii=False,indent=2))
    return task


if __name__=='__main__': write_report()
