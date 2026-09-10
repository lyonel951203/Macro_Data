"""Publish the completed local batch summary into STATUS.md."""
import json
from pathlib import Path
import pandas as pd

OUT = Path("reports/v2/nbs_early_2005")


def report():
    result = json.loads((OUT / "final_result.json").read_text(encoding="utf-8"))
    state = json.loads(Path("data/history_backfill/nbs_early_2005_download_state.json").read_text(encoding="utf-8"))
    tests = json.loads((OUT / "test_results.json").read_text(encoding="utf-8"))
    assert result["status"] == state["status"] == "COMPLETE" and tests["status"] == "PASS"
    assert not Path("data/history_backfill/nbs_price_batch.lock").exists()
    coverage = pd.read_csv(OUT / "field_coverage_changes.csv")
    samples = pd.read_csv(OUT / "validated_samples.csv")
    lines = ["# 2005 年早期工业与社零：首批完成", "",
             "工业和社零的严格原始数据起点均已从 2010-02 推进到 2005-01。11 篇旧稿已归档，10 篇提供 11 条新 PIT_A；另 1 篇仅有累计工业增速，排除并保留原稿。", "",
             "| 字段 | 真实月份数变化 | 最早数据期 | CSV 首次非空月末 |", "|---|---:|---|---|"]
    for r in coverage.itertuples():
        lines.append(f"| {r.name_after} | {r.strict_periods_by_cutoff_before} → {r.strict_periods_by_cutoff_after} | {r.strict_first_period_by_cutoff_after} | {r.first_nonnull_as_of_after} |")
    lines += ["", "本批工业覆盖 2005 年 1、3、4、5、6 月；社零覆盖 1—6 月。工业 2 月仍缺：1—2 月稿中的 16.9% 是累计同比，不能改成 2 月同比。社零 1 月 11.5% 和 2 月 15.8% 均来自 3 月 14 日的同一篇稿件，两期都从该日 13:19 起可用，未推定更早发布时间。", "",
              "工业 1 月保留原始同比 20.9%，未取春节因素调整后的日均增速 8.9%。4 月原稿漏写了增加值的末字，标题明确指标，正文仍按原样归档，核对值为 16%。各年工业统计范围变化见 [口径说明](history_constraints.md)。", "",
              f"主库 {result['database_rows']:,} 条；中国 {result['china_rows']:,} 条 / {result['china_series']} 序列；NBS {result['nbs_rows']:,} 条。严格 CSV 仍为 {result['wide_rows']} 行 × {result['wide_indicators']} 字段，空值率 {result['before_missing_pct']}% → {result['after_missing_pct']}%；新增非空 {result['newly_nonnull_cells']} 格。宽表会沿用旧值，工业/社零最大来源陈旧月数仍为 {int(coverage.max_source_age_months_after.max())}，不能据非空率认为历史完整。", "",
              "验证：118 项测试通过；280 份既有归档回放，1,045 条有效记录未变，13 条此前更正的旧版本仍保留。11 条新记录逐条核对正文、时间和 SHA256，通过 22 次发布边界检查及重复入库验证。导出每个变化格均匹配本批原值和数据期；三个 notebook 执行通过。", "",
              "全量验收仍为 FAIL，详见 acceptance.txt。本批未处理 Wind，其他来源观测数均未变。", "",
              "[逐条原稿证据](validated_samples.csv) · [被排除的累计稿](excluded_articles.csv) · [字段覆盖变化](field_coverage_changes.csv) · [复核 notebook](review.ipynb) · [47 字段回溯顺序](history_plan.md) · [各年真实数据期数](yearly_raw_period_coverage.csv)", "",
              "下一步从 2005 年下半年继续，同时查 2005 年 12 月 CPI/PPI 及早期制造业 PMI。五个窄搜索窗口已写入 config/nbs_early_2005_next_search_jobs.json，未启动。原近期综合稿 9 篇队列暂后移。", "",
              "只读复核：python scripts/review_nbs_early_2005.py；显式 --ingest 才追加数据库。离线导出：python scripts/finalize_nbs_early_2005.py。"]
    (OUT / "README.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    status = Path("reports/v2/STATUS.md")
    current = status.read_text(encoding="utf-8")
    heading = "### 当前任务：优先向 2005 年回溯" if "### 当前任务：优先向 2005 年回溯" in current else "### 当前：2005 年早期工业与社零首批完成"
    start = current.index(heading)
    end = current.index("### 最近完成：NBS 综合稿第二批", start)
    block = [f"### 当前：2005 年早期工业与社零首批完成（{result['at'][:16]}）", "",
             "- **工业、社零最早严格数据期均为 2005-01，原起点为 2010-02。** 本批 11 篇归档已完成核验，追加 **11 条 PIT_A，无修订或覆盖旧记录**。工业新增 5 个月，社零新增 6 个月。",
             "- 严格真实月份：工业 **36 → 41**，社零 **36 → 42**；CSV 首次非空分别为 **2005-02-28 / 2005-03-31**。工业 2005-02 原稿只有累计 16.9%，仍标缺；社零 2005-01/02 均使用原稿实际时间 2005-03-14 13:19，未倒填日期。",
             f"- 主库 **{result['database_rows']:,} 条**；中国 **{result['china_rows']:,} 条、52 个序列**；NBS **{result['nbs_rows']:,} 条、21 个序列**。未处理 Wind，其他来源观测数未变。",
             f"- 严格 CSV 已重导出，259 行 × 47 字段，空值率 **{result['before_missing_pct']}% → {result['after_missing_pct']}%**；{result['changed_cells']} 格变化，新增非空 {result['newly_nonnull_cells']} 格，全部匹配已核验记录。工业/社零最大来源陈旧度仍为 136 个月，历史尚不连续。",
             "- **118 项测试通过**；280 份旧归档、1,045 条有效记录保持一致，13 条之前已更正的旧版本原样保留；11 条独立原值/时间/SHA 核验、22 次可用边界及重复入库检查通过，三个 notebook 已执行。全量验收仍为 FAIL。",
             "- 已改为从 2005 年向后逐年补缺。下一步：2005 年下半年工业/社零、12 月价格、早期制造业 PMI；五个搜索窗口保存于 `config/nbs_early_2005_next_search_jobs.json`，尚未启动。近期综合稿 9 篇队列暂后移。",
             "- [47 字段目标及当前起点](nbs_early_2005/history_plan.md)、[制度起点/历史口径约束](nbs_early_2005/history_constraints.md)、[各年真实期数](nbs_early_2005/yearly_raw_period_coverage.csv)。服务业、失业率、综合 PMI 等按实际公开起点回溯；旧城镇投资不直接拼接现代口径。",
             "- 本批已结束，无本批后台任务。结果：`data/history_backfill/nbs_early_2005_run.json`；[本批说明与复核入口](nbs_early_2005/README.md)。", "", ""]
    status.write_text(current[:start]+"\n".join(block)+current[end:], encoding="utf-8")
    print("Updated early-history README and STATUS.md")


if __name__ == "__main__":
    report()
