"""Refresh per-field history priorities and raw-period coverage, without downloads."""
from pathlib import Path
import pandas as pd
import duckdb

OUT = Path("reports/v2/nbs_early_2005")


def build():
    history = pd.read_csv("reports/v2/pit_csv_inspection/field_history.csv")
    rows = []
    for r in history.itertuples():
        goal = "2005 起逐年查原稿"
        priority = 2
        notes = "按原发布机构历史月报和政府转载核对数值及时间；不能给回溯值倒填 PIT"
        if r.indicator in ["CN_CPI_YOY", "CN_PPI_YOY", "CN_INDUSTRIAL_VALUE_ADDED_YOY", "CN_RETAIL_SALES_YOY"]:
            priority = 1
            notes = "先补 2005 年缺月，再逐年推进；工业 2005-02 现有稿仅累计，须另找单月证据"
        if "OECD" in r.source:
            priority = 4
            goal = "已早于 2005；核对内部缺口"
            notes = "保持 OECD 来源和现有时间证据，不当成 NBS 原始首发"
        if r.indicator == "CN_FAI_YTD_YOY":
            goal = "2011 起现口径；2005 起旧口径另序列"
            notes = "旧城镇投资与不含农户投资范围不同；不得直接拼接"
        if r.indicator in ["CN_INFRA_INVESTMENT_YTD_YOY", "CN_MANUFACTURING_INVESTMENT_YTD_YOY"]:
            goal = "尽早；先核对旧投资统计范围"
            notes = "检查城镇/不含农户、行业范围与基建是否含电力；在确认一致前不作数值拼接"
        if r.indicator in ["CN_NEW_HOME_SALES_AREA_YTD_YOY", "CN_NEW_HOME_SALES_VALUE_YTD_YOY", "CN_REAL_ESTATE_INVESTMENT_YTD_YOY"]:
            notes = "查 2005 年房地产专项稿；商品房销售旧名称及累计口径须逐年确认"
        if r.indicator == "CN_SERVICE_PRODUCTION_YOY":
            goal = "2017-03 起正式发布；首期数据期待核对"
            notes = "不存在 2005 年同定义的公开月度序列；区分首期累计与单月"
        if r.indicator == "CN_URBAN_SURVEYED_UNEMPLOYMENT":
            goal = "2018-04 起定期发布；首稿含哪些月份待核对"
            notes = "不得与登记失业率或 31 大城市调查失业率混用"
        if r.indicator.startswith("CN_PMI_"):
            goal = "2005 制造业调查起；逐项查实际首发"
            notes = "调查建立时间不是每个分项公开时间；历史季调重估不能倒填可用日期"
        if r.indicator == "CN_PMI_NONMANUFACTURING":
            goal = "2007 非制造业调查起；实际首发待核对"
        if r.indicator == "CN_PMI_COMPOSITE":
            goal = "2018-01 正式发布起"
        if "TSF" in r.indicator:
            goal = "实际公开发布起；2005 回溯值另保留"
            notes = "增量/存量、累计/当月、后补统计范围分别核对；历史数据期不能替代实际发布时点"
        if r.source == "SAFE":
            notes = "现有 C/D 历史需补实际发布证据；旧月表或年报可以保留其较晚真实可用时间"
        rows.append(dict(indicator=r.indicator, name=r.name, source=r.source, priority=priority,
                         current_strict_first_period=r.strict_first_period_by_cutoff,
                         current_strict_periods=r.strict_periods_by_cutoff, current_first_as_of=r.first_nonnull_as_of,
                         history_goal=goal, handling=notes))
    plan = pd.DataFrame(rows).sort_values(["priority", "source", "indicator"])
    assert len(plan) == len(history) == 47 and not plan.indicator.duplicated().any()
    plan.to_csv(OUT / "history_backfill_priorities.csv", index=False, encoding="utf-8-sig")
    with duckdb.connect("macro_pit_v2.duckdb", read_only=True) as conn:
        periods = conn.sql("""SELECT DISTINCT canonical_series_id AS indicator, period
          FROM observation_vintage WHERE country='CN' AND pit_grade IN ('A','B')
          AND available_at <= TIMESTAMPTZ '2026-07-31 23:59:59+08'
          AND period >= '2005-01'""").df()
    periods["year"] = periods.period.str[:4].astype(int)
    counts = periods.groupby(["indicator", "year"]).period.nunique().rename("strict_original_periods")
    grid = pd.MultiIndex.from_product([history.indicator, range(2005,2027)], names=["indicator", "year"])
    annual = counts.reindex(grid, fill_value=0).reset_index().merge(history[["indicator", "name", "frequency"]], on="indicator")
    annual.to_csv(OUT / "yearly_raw_period_coverage.csv", index=False, encoding="utf-8-sig")
    notes = ["# 自 2005 年起的逐字段回溯顺序", "", "这是 47 个当前严格 CSV 字段的目标清单，目标日期不是已入库或已证实连续覆盖的承诺。", "",
             "年度表统计真实 A/B 数据期个数，季度字段按季度计数，未统计宽表沿用旧值形成的格数。2026 年仅计算截止 7 月 31 日已公开的记录。", "",
             "详细制度证据见 [口径约束](history_constraints.md)。全年 0 期可能是尚未采集、该口径未发布或归档证据不足，不能一概视为抓取遗漏。", "",
             "| 字段 | 当前最早数据期 | 真实期数 | 回溯目标 |", "|---|---|---:|---|"]
    for r in plan.itertuples():
        notes.append(f"| {r.name} | {r.current_strict_first_period} | {r.current_strict_periods} | {r.history_goal} |")
    (OUT / "history_plan.md").write_text("\n".join(notes)+"\n", encoding="utf-8")
    print(f"History priorities: {len(plan)} fields; annual coverage: {len(annual)} field-years")
    return plan


if __name__ == "__main__":
    build()
