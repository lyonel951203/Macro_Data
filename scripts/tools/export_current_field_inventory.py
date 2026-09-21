
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import yaml


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "macro_pit_v2.duckdb"
OUT_DIR = ROOT / "reports" / "v2" / "current_field_inventory"
DAILY_CONFIG = ROOT / "config" / "daily_web_update.yml"
GLOBAL_CONFIG = ROOT / "config" / "daily_global_update.yml"
SERIES_REGISTRY = ROOT / "config" / "series_registry.yml"
SHANGHAI = ZoneInfo("Asia/Shanghai")
BT = chr(96)

ENGLISH_NAMES = {
    "CN_BANK_FX_NET_SETTLEMENT_USD": "Bank FX Net Settlement (USD)",
    "CN_BANK_FX_SALES_USD": "Bank FX Sales (USD)",
    "CN_BANK_FX_SETTLEMENT_USD": "Bank FX Settlement (USD)",
    "CN_CPI_YOY": "Consumer Price Index YoY",
    "CN_CGB_YTM_10Y": "China 10-Year Government Bond Yield to Maturity",
    "CN_CGB_TERM_SPREAD_10Y_1Y": "China Government Bond Term Spread (10Y minus 1Y)",
    "CN_AAA_CP_NOTE_CREDIT_SPREAD_3Y": "China AAA CP and Note Credit Spread (3Y minus 3Y CGB)",
    "CN_CROSS_BORDER_NET_RECEIPTS_USD": "Cross-Border Net Receipts (USD)",
    "CN_CROSS_BORDER_PAYMENTS_USD": "Cross-Border Payments (USD)",
    "CN_CROSS_BORDER_RECEIPTS_USD": "Cross-Border Receipts (USD)",
    "CN_EXPORT_USD": "Export Value (USD, Monthly)",
    "CN_EXPORT_USD_YOY": "Export Value YoY (USD)",
    "CN_FAI_YTD_YOY": "Fixed Asset Investment YTD YoY",
    "CN_FX_RESERVE_USD": "Foreign Exchange Reserves (USD)",
    "CN_GDP_YOY": "Real GDP YoY",
    "CN_GENERAL_BUDGET_EXPENDITURE_YTD_YOY": "General Public Budget Expenditure YTD YoY",
    "CN_GENERAL_BUDGET_REVENUE_YTD_YOY": "General Public Budget Revenue YTD YoY",
    "CN_GOV_FUND_EXPENDITURE_YTD_YOY": "Government Fund Budget Expenditure YTD YoY",
    "CN_GOV_FUND_REVENUE_YTD_YOY": "Government Fund Budget Revenue YTD YoY",
    "CN_IMPORT_USD": "Import Value (USD, Monthly)",
    "CN_IMPORT_USD_YOY": "Import Value YoY (USD)",
    "CN_INDUSTRIAL_VALUE_ADDED_YOY": "Industrial Value Added YoY",
    "CN_INFRA_INVESTMENT_YTD_YOY": "Infrastructure Investment YTD YoY",
    "CN_LAND_SALE_REVENUE_YTD_YOY": "Land-Use Rights Sale Revenue YTD YoY",
    "CN_M0_YOY": "M0 YoY",
    "CN_M1_YOY": "M1 YoY",
    "CN_M2_YOY": "M2 YoY",
    "CN_MANUFACTURING_INVESTMENT_YTD_YOY": "Manufacturing Investment YTD YoY",
    "CN_NEW_HOME_SALES_AREA_YTD_YOY": "Commodity Housing Sales Area YTD YoY",
    "CN_NEW_HOME_SALES_VALUE_YTD_YOY": "Commodity Housing Sales Value YTD YoY",
    "CN_NEW_RMB_DEPOSITS_YTD": "New RMB Deposits YTD",
    "CN_NEW_RMB_LOANS_YTD": "New RMB Loans YTD",
    "CN_NONTAX_REVENUE_YTD_YOY": "Nontax Revenue YTD YoY",
    "CN_OECD_CPI_INDEX": "OECD China Consumer Price Index",
    "CN_OECD_INDUSTRIAL_PRODUCTION": "OECD China Industrial Production Index",
    "CN_PMI_COMPOSITE": "Composite PMI Output Index",
    "CN_PMI_EMPLOYMENT": "Manufacturing PMI Employment",
    "CN_PMI_MANUFACTURING": "Manufacturing PMI",
    "CN_PMI_NEW_ORDERS": "Manufacturing PMI New Orders",
    "CN_PMI_NONMANUFACTURING": "Non-Manufacturing Business Activity Index",
    "CN_PMI_PRODUCTION": "Manufacturing PMI Production",
    "CN_PMI_RAW_MATERIAL_INVENTORY": "Manufacturing PMI Raw Material Inventory",
    "CN_PMI_SUPPLIER_DELIVERY": "Manufacturing PMI Supplier Delivery Time",
    "CN_PPI_YOY": "Producer Price Index YoY",
    "CN_REAL_ESTATE_INVESTMENT_YTD_YOY": "Real Estate Development Investment YTD YoY",
    "CN_RETAIL_SALES_YOY": "Retail Sales YoY",
    "CN_RMB_DEPOSIT_BAL_YOY": "RMB Deposit Balance YoY",
    "CN_RMB_LOAN_BAL_YOY": "RMB Loan Balance YoY",
    "CN_SERVICE_PRODUCTION_YOY": "Service Production Index YoY",
    "CN_TAX_REVENUE_YTD_YOY": "Tax Revenue YTD YoY",
    "CN_TRADE_BALANCE_USD": "Trade Balance (USD, Monthly)",
    "CN_TSF_FLOW_YTD": "Total Social Financing Flow YTD",
    "CN_TSF_STOCK": "Total Social Financing Stock",
    "CN_TSF_STOCK_YOY": "Total Social Financing Stock YoY",
    "CN_URBAN_SURVEYED_UNEMPLOYMENT": "Urban Surveyed Unemployment Rate",
}

CHINESE_NAMES = {
    "CN_BANK_FX_NET_SETTLEMENT_USD": "银行结售汇差额（当月，美元）",
    "CN_BANK_FX_SALES_USD": "银行售汇额（当月，美元）",
    "CN_BANK_FX_SETTLEMENT_USD": "银行结汇额（当月，美元）",
    "CN_CPI_YOY": "居民消费价格指数同比",
    "CN_CGB_YTM_10Y": "10年期国债到期收益率",
    "CN_CGB_TERM_SPREAD_10Y_1Y": "国债期限利差（10年减1年）",
    "CN_AAA_CP_NOTE_CREDIT_SPREAD_3Y": "AAA级短融中票信用利差（3年减3年国债）",
    "CN_CROSS_BORDER_NET_RECEIPTS_USD": "银行代客涉外收付款差额（当月，美元）",
    "CN_CROSS_BORDER_PAYMENTS_USD": "银行代客对外付款（当月，美元）",
    "CN_CROSS_BORDER_RECEIPTS_USD": "银行代客涉外收入（当月，美元）",
    "CN_EXPORT_USD": "出口金额（当月，美元）",
    "CN_EXPORT_USD_YOY": "出口金额同比（美元口径）",
    "CN_FAI_YTD_YOY": "固定资产投资累计同比",
    "CN_FX_RESERVE_USD": "外汇储备余额（美元）",
    "CN_GDP_YOY": "国内生产总值实际同比",
    "CN_GENERAL_BUDGET_EXPENDITURE_YTD_YOY": "一般公共预算支出累计同比",
    "CN_GENERAL_BUDGET_REVENUE_YTD_YOY": "一般公共预算收入累计同比",
    "CN_GOV_FUND_EXPENDITURE_YTD_YOY": "政府性基金预算支出累计同比",
    "CN_GOV_FUND_REVENUE_YTD_YOY": "政府性基金预算收入累计同比",
    "CN_IMPORT_USD": "进口金额（当月，美元）",
    "CN_IMPORT_USD_YOY": "进口金额同比（美元口径）",
    "CN_INDUSTRIAL_VALUE_ADDED_YOY": "规模以上工业增加值同比",
    "CN_INFRA_INVESTMENT_YTD_YOY": "基础设施投资累计同比",
    "CN_LAND_SALE_REVENUE_YTD_YOY": "国有土地使用权出让收入累计同比",
    "CN_M0_YOY": "流通中货币M0同比",
    "CN_M1_YOY": "狭义货币M1同比",
    "CN_M2_YOY": "广义货币M2同比",
    "CN_MANUFACTURING_INVESTMENT_YTD_YOY": "制造业投资累计同比",
    "CN_NEW_HOME_SALES_AREA_YTD_YOY": "商品房销售面积累计同比",
    "CN_NEW_HOME_SALES_VALUE_YTD_YOY": "商品房销售额累计同比",
    "CN_NEW_RMB_DEPOSITS_YTD": "新增人民币存款累计值",
    "CN_NEW_RMB_LOANS_YTD": "新增人民币贷款累计值",
    "CN_NONTAX_REVENUE_YTD_YOY": "非税收入累计同比",
    "CN_OECD_CPI_INDEX": "OECD中国居民消费价格指数",
    "CN_OECD_INDUSTRIAL_PRODUCTION": "OECD中国工业生产指数",
    "CN_PMI_COMPOSITE": "综合PMI产出指数",
    "CN_PMI_EMPLOYMENT": "制造业PMI从业人员指数",
    "CN_PMI_MANUFACTURING": "制造业采购经理指数",
    "CN_PMI_NEW_ORDERS": "制造业PMI新订单指数",
    "CN_PMI_NONMANUFACTURING": "非制造业商务活动指数",
    "CN_PMI_PRODUCTION": "制造业PMI生产指数",
    "CN_PMI_RAW_MATERIAL_INVENTORY": "制造业PMI原材料库存指数",
    "CN_PMI_SUPPLIER_DELIVERY": "制造业PMI供应商配送时间指数",
    "CN_PPI_YOY": "工业生产者出厂价格指数同比",
    "CN_REAL_ESTATE_INVESTMENT_YTD_YOY": "房地产开发投资累计同比",
    "CN_RETAIL_SALES_YOY": "社会消费品零售总额同比",
    "CN_RMB_DEPOSIT_BAL_YOY": "人民币存款余额同比",
    "CN_RMB_LOAN_BAL_YOY": "人民币贷款余额同比",
    "CN_SERVICE_PRODUCTION_YOY": "服务业生产指数同比",
    "CN_TAX_REVENUE_YTD_YOY": "税收收入累计同比",
    "CN_TRADE_BALANCE_USD": "贸易差额（当月，美元）",
    "CN_TSF_FLOW_YTD": "社会融资规模增量累计值",
    "CN_TSF_STOCK": "社会融资规模存量",
    "CN_TSF_STOCK_YOY": "社会融资规模存量同比",
    "CN_URBAN_SURVEYED_UNEMPLOYMENT": "全国城镇调查失业率",
}

FREQUENCY_NAMES = {"M": "月度", "Q": "季度"}
UNIT_NAMES = {
    "pct_yoy": "百分比（同比）",
    "pct": "百分比",
    "pct_points": "百分点",
    "index": "指数点",
    "bn_usd": "十亿美元",
    "tn_cny_ytd": "万亿元人民币（年初累计）",
    "tn_cny": "万亿元人民币",
}
SOURCE_NAMES = {
    "NBS": "国家统计局",
    "PBOC": "中国人民银行",
    "MOF": "财政部",
    "SAFE": "国家外汇管理局",
    "OECD": "经济合作与发展组织",
    "CHINABOND": "中国债券信息网",
    "WIND": "Wind",
}
UPDATE_METHODS = {
    "NBS": "每日22:00：NBS官方目录自动抓取、解析并幂等入库；历史可能含Wind D，官方A/B优先。",
    "PBOC": "每日22:00：PBOC官方目录自动尝试；robots阻止时记录失败；历史可能含Wind D。",
    "MOF": "每日22:00：MOF官方目录只向前更新并复查最新3篇；停止历史补齐。",
    "SAFE": "每日22:00：SAFE官方目录自动抓取、解析并幂等入库。",
    "OECD": "每日22:00：OECD官方SDMX修订API完整重取；按EDITION生成PIT_B。",
    "CHINABOND": "每日00:00：中债官方收益率曲线复查最近75天，按月末最后交易日幂等追加PIT_A。",
    "WIND": "不自动更新：只保留既有Wind手工导入记录；每日任务不调用Wind接口。",
}
SOURCE_ORDER = ["NBS", "PBOC", "MOF", "SAFE", "OECD", "CHINABOND", "WIND"]


def main() -> None:
    now = datetime.now(SHANGHAI)
    registry = yaml.safe_load(SERIES_REGISTRY.read_text(encoding="utf-8")) or {}
    inactive_fields = {
        str(field) for field, spec in registry.items()
        if isinstance(spec, dict) and spec.get("active", True) is False
    }
    active_english_names = {
        field: name for field, name in ENGLISH_NAMES.items()
        if field not in inactive_fields
    }
    active_chinese_names = {
        field: name for field, name in CHINESE_NAMES.items()
        if field not in inactive_fields
    }
    config = yaml.safe_load(DAILY_CONFIG.read_text(encoding="utf-8"))
    enabled = {
        key for key, value in config["sources"].items()
        if value.get("enabled", True)
    }
    assert enabled == {
        "NBS", "PBOC", "PBOC_MIRROR", "MOF", "SAFE",
        "EASTMONEY_MACRO", "SINA_MACRO", "OECD",
    }
    global_config = yaml.safe_load(GLOBAL_CONFIG.read_text(encoding="utf-8"))
    assert global_config["sources"]["CHINABOND"]["enabled"] is True
    enabled.add("CHINABOND")

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    visible_rows = conn.execute(
        """
        select canonical_series_id, min(period), max(period), count(distinct period)
        from observation_vintage
        where country = 'CN' and available_at <= ?
        group by canonical_series_id
        order by canonical_series_id
        """,
        [now],
    ).fetchall()
    visible_rows = [row for row in visible_rows if row[0] not in inactive_fields]
    all_latest = {
        field: latest for field, latest in conn.execute(
            """
            select canonical_series_id, max(period)
            from observation_vintage
            where country = 'CN'
            group by canonical_series_id
            """
        ).fetchall() if field not in inactive_fields
    }
    attributes = {
        row[0]: row[1:]
        for row in conn.execute(
            """
            select canonical_series_id,
                   any_value(frequency), count(distinct frequency),
                   any_value(unit), count(distinct unit)
            from observation_vintage
            where country = 'CN'
            group by canonical_series_id
            """
        ).fetchall() if row[0] not in inactive_fields
    }
    source_rows = [row for row in conn.execute(
        """
        select canonical_series_id, source
        from observation_vintage
        where country = 'CN'
        group by canonical_series_id, source
        order by canonical_series_id, source
        """
    ).fetchall() if row[0] not in inactive_fields]
    sources_by_field: dict[str, list[str]] = {}
    for field, source in source_rows:
        sources_by_field.setdefault(field, []).append(source)

    latest_sources = {}
    for field, _, latest, _ in visible_rows:
        latest_sources[field] = [
            item[0] for item in conn.execute(
                """
                select distinct source
                from observation_vintage
                where country = 'CN'
                  and canonical_series_id = ?
                  and period = ?
                  and available_at <= ?
                order by source
                """,
                [field, latest, now],
            ).fetchall()
        ]
    conn.close()

    field_ids = {row[0] for row in visible_rows}
    assert len(visible_rows) == 50
    assert field_ids == set(active_english_names) == set(active_chinese_names)
    assert all(value[1] == 1 and value[3] == 1 for value in attributes.values())

    rows = []
    group_counts = Counter()
    for field, first_period, visible_last_period, period_count in visible_rows:
        frequency, _, unit, _ = attributes[field]
        sources = sources_by_field[field]
        primary = next(
            (source for source in SOURCE_ORDER if source in sources),
            None,
        )
        assert primary is not None
        group_counts[primary] += 1
        rows.append(
            {
                "field_code": field,
                "english_name": active_english_names[field],
                "chinese_name": active_chinese_names[field],
                "frequency": frequency,
                "frequency_cn": FREQUENCY_NAMES[frequency],
                "unit": unit,
                "unit_cn": UNIT_NAMES[unit],
                "record_sources": ",".join(sources),
                "start_period": first_period,
                "end_period_visible_at_generated_time": visible_last_period,
                "database_latest_period": all_latest[field],
                "latest_period_sources": ",".join(latest_sources[field]),
                "visible_distinct_periods": period_count,
                "update_owner": primary,
                "update_method": UPDATE_METHODS[primary],
                "automatic_daily_update": primary != "WIND",
            }
        )

    assert dict(group_counts) == {
        "NBS": 21,
        "PBOC": 10,
        "MOF": 7,
        "SAFE": 7,
        "OECD": 2,
        "CHINABOND": 3,
    }
    assert len({row["field_code"] for row in rows}) == 50
    assert all(row["start_period"] and row["end_period_visible_at_generated_time"] for row in rows)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "all_active_fields_bilingual_coverage_update.csv"
    headers = list(rows[0])
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    md_lines = [
        "# 当前50个宏观字段：英文、中文、覆盖时间与更新方式",
        "",
        f"生成时间：{now.isoformat()}。",
        "",
        "开始时间和结束时间均指字段的原始数据期，不是宽表观察日期。结束时间只统计生成时点已经满足PIT可见条件的记录；库内最晚数据期另列，可能包含尚未到可用日的保守版本。",
        "",
        "中国官方网页任务在Asia/Shanghai 22:00维护NBS、PBOC、MOF、SAFE和OECD；00:00全球任务维护ChinaBond 3个市场字段。海关美元出口、进口、差额及进出口同比5项已停用，不进入每日/周度任务、PIT查询和当前字段清单；既有底层记录仅为历史留存。",
        "",
    ]
    md_lines.extend([
        "## Reviewed PIT_D fallback coverage",
        "",
        "The 22:00 task also polls EASTMONEY_MACRO (11 fields) and SINA_MACRO "
        "(16 fields), covering 19 unique automatic fields. These sources do not "
        "own fields: they remain PIT_D and are selected only after A, B and Wind.",
        "",
    ])

    for source in SOURCE_ORDER:
        selected = [row for row in rows if row["update_owner"] == source]
        if not selected:
            continue
        md_lines.extend([
            f"## {source} / {SOURCE_NAMES[source]}（{len(selected)}项）",
            "",
            UPDATE_METHODS[source],
            "",
            "| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 库内最晚期 | 当前入库来源 |",
            "|---|---|---|---|---:|---:|---:|---|",
        ])
        for row in selected:
            md_lines.append(
                f"| {BT}{row['field_code']}{BT} | {row['english_name']} | "
                f"{row['chinese_name']} | {row['frequency_cn']} | "
                f"{row['start_period']} | {row['end_period_visible_at_generated_time']} | "
                f"{row['database_latest_period']} | {row['record_sources']} |"
            )
        md_lines.append("")

    future_difference = [
        {
            "field_code": row["field_code"],
            "visible_end": row["end_period_visible_at_generated_time"],
            "database_end": row["database_latest_period"],
        }
        for row in rows
        if row["end_period_visible_at_generated_time"] != row["database_latest_period"]
    ]
    md_lines.extend([
        "## 数据质量核对",
        "",
        "- 当前可用中国字段数：50；字段代码唯一，无空的开始或结束时间。",
        "- 更新责任分组：NBS 21、PBOC 10、MOF 7、SAFE 7、OECD 2、ChinaBond 3。",
        f"- 生成时尚未达到PIT可见日、因此库内末期与当前可见末期不同的字段：{len(future_difference)}项。",
        "- 混合来源字段保留Wind历史底座；同一期存在官方A/B记录时，工作PIT表优先使用官方记录。",
        "",
        "## Sources receipt",
        "",
        f"- 数据库：{BT}macro_pit_v2.duckdb{BT}，只读聚合50个当前可用CN字段；5个停用海关字段不计入。",
        f"- 自动更新配置：{BT}config/daily_web_update.yml{BT}、{BT}config/daily_global_update.yml{BT}。",
        f"- 中文口径参考：{BT}scripts/export_current_pit_chinese.py{BT}及当前字段代码。",
        f"- 本清单生成器：{BT}scripts/tools/export_current_field_inventory.py{BT}。",
    ])
    md_path = OUT_DIR / "README.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    quality = {
        "generated_at": now.isoformat(),
        "database": str(DB_PATH),
        "field_count": len(rows),
        "unique_field_codes": len({row["field_code"] for row in rows}),
        "all_names_mapped": field_ids == set(active_english_names) == set(active_chinese_names),
        "inactive_fields": sorted(inactive_fields),
        "all_start_end_non_null": all(
            row["start_period"] and row["end_period_visible_at_generated_time"]
            for row in rows
        ),
        "automatic_daily_fields": sum(row["automatic_daily_update"] for row in rows),
        "manual_fields": sum(not row["automatic_daily_update"] for row in rows),
        "update_owner_counts": dict(group_counts),
        "future_visibility_differences": future_difference,
        "daily_enabled_sources": sorted(enabled),
    }
    quality_path = OUT_DIR / "quality_summary.json"
    quality_path.write_text(
        json.dumps(quality, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(md_path)
    print(csv_path)
    print(quality_path)
    print(json.dumps(quality, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
