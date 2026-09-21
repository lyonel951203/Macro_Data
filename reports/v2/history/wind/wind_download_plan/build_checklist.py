"""Build a Wind download checklist from the local registry and frozen coverage."""
from pathlib import Path
from datetime import datetime
import json
import pandas as pd
import yaml

root = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "config/series_registry.yml").exists())
out = root / "reports/v2/history/wind/wind_download_plan"
out.mkdir(parents=True, exist_ok=True)
for source, target in [
    (root / "reports/v2/cn_coverage.csv", out / "coverage_snapshot.csv"),
    (root / "reports/v2/pit_csv_inspection/field_history.csv", out / "field_history_snapshot.csv"),
]:
    if not target.exists():
        target.write_bytes(source.read_bytes())
coverage = pd.read_csv(out / "coverage_snapshot.csv").set_index("canonical_series_id")
history = pd.read_csv(out / "field_history_snapshot.csv").set_index("indicator")
registry = yaml.safe_load((root / "config/series_registry.yml").read_text(encoding="utf-8"))
names = history["name"].to_dict()
names.update({
    "CN_CORE_CPI_YOY": "核心CPI同比", "CN_PMI_NEW_EXPORT_ORDERS": "制造业PMI新出口订单指数",
    "CN_M0_STOCK": "M0余额", "CN_M1_STOCK": "M1余额", "CN_M2_STOCK": "M2余额",
})
for currency, label in [("CNY", "人民币"), ("USD", "美元")]:
    for field, name in [("EXPORT", "出口金额"), ("IMPORT", "进口金额"), ("TRADE_BALANCE", "贸易差额")]:
        names[f"CN_{field}_{currency}"] = f"{name}（{label}，当月）"
    for field, name in [("EXPORT", "出口"), ("IMPORT", "进口")]:
        names[f"CN_{field}_{currency}_YOY"] = f"{name}金额当月同比（{label}口径）"

records = []
for key, spec in registry.items():
    if spec["country"] != "CN" or spec["source"] == "OECD" or key == "CN_HOME_SALES_YTD_YOY":
        continue
    source = spec["source"]
    if source == "PBOC":
        priority = "P2" if key in {"CN_M0_STOCK", "CN_M1_STOCK", "CN_M2_STOCK"} else "P0"
        reason = "现有同比/信贷/社融各仅3个近期月份；余额补充字段尚未入库，历史自动抓取受限"
        caveat = "保留统计口径与修订说明；M1新旧口径、社融统计范围须区分"
    elif source == "CUSTOMS":
        priority = "P0" if "USD" in key else "P2"
        reason = "尚无数据入库，官方自动访问受阻；优先美元口径五项"
        caveat = "当月值/当月同比；不要以累计值代替；1—2月合并披露保留原样，币种分开"
    elif source == "NBS":
        priority = "P1"
        reason = "历史收录不完整或起点偏晚；部分字段尚未入库，官方旧稿仍在分批补齐"
        caveat = "保留原频率、口径及缺失；同比增长率与上年同月=100指数须区分"
    elif source == "MOF":
        priority = "P2"
        reason = "已有较长官方历史；Wind主要用于更早年份和内部缺口核对"
        caveat = "累计同比；保留1—2月合并披露及历史名称变化，不补造单独1月"
    else:
        priority = "P3"
        reason = "当前值历史已基本完整，主要缺原始发布时间/版本证据；单纯Wind时序增益有限"
        caveat = "可选对照；月末余额与当月流量区分，美元单位保留，不把数据期当发布时间"
    if key == "CN_GDP_YOY":
        caveat = "当季、不变价同比；不要用累计同比或季调环比代替；修订值无法仅靠日期滞后恢复原值"
    elif key.startswith("CN_PMI_"):
        caveat = "指数点、原月频；制造业分项须对应制造业，不混入非制造业分项"
    elif "YTD" in key:
        caveat += "；目标为年内累计口径，非当月增量"
    elif key in {"CN_INDUSTRIAL_VALUE_ADDED_YOY", "CN_SERVICE_PRODUCTION_YOY", "CN_RETAIL_SALES_YOY"}:
        caveat += "；目标为当月同比，不把年内累计同比填成当月同比"
    if key in {"CN_M1_YOY", "CN_M1_STOCK"}:
        caveat += "；如可选，请同时导出原口径、新口径及回溯说明"
    c = coverage.loc[key]
    h = history.loc[key] if key in history.index else None
    records.append({
        "priority": priority, "canonical_series_id": key, "download_search_name": names[key],
        "original_source": source, "frequency": spec["frequency"], "target_unit": spec["unit"],
        "requested_start": "2005-Q1" if spec["frequency"] == "Q" else "2005-01",
        "requested_end": "最新已公布；不足2005年的指标从首期开始",
        "current_db_first_period_all_grades": c.earliest_valid_period,
        "current_db_last_period_all_grades": c.latest_period,
        "current_db_distinct_periods_all_grades": int(c.observed_periods),
        "strict_periods_by_20260731": 0 if h is None else int(h.strict_periods_by_cutoff),
        "download_reason": reason, "definition_notes": caveat,
        "wind_code": "", "wind_unit": "", "wind_definition": "", "exported_at": "",
    })
checklist = pd.DataFrame(records).sort_values(["priority", "original_source", "canonical_series_id"])
assert len(checklist) == 60 and checklist.canonical_series_id.is_unique
assert checklist.download_search_name.notna().all()
checklist.to_csv(out / "wind_download_checklist.csv", index=False, encoding="utf-8-sig")
checklist[checklist.priority.eq("P0")].to_csv(out / "wind_first_batch_15.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(columns=["wind_code", "period", "value"]).to_csv(out / "values_long_template.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(columns=["wind_code", "wind_name", "canonical_series_id", "original_source", "unit", "frequency", "seasonal_adjustment", "definition", "exported_at"]).to_csv(out / "series_metadata_template.csv", index=False, encoding="utf-8-sig")
summary = {"priority_counts": checklist.groupby("priority").size().to_dict(),
           "source_counts": checklist.groupby("original_source").size().to_dict(),
           "total": len(checklist), "reference": "13:17 batch4 coverage; batch5 in progress at plan creation",
           "excluded": ["OECD supplements already have edition history", "CN_HOME_SALES_YTD_YOY is ambiguous; use separate area/value targets"]}
(out / "checklist_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False))
