
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
OUT_DIR = ROOT / "reports" / "v2" / "non_cn_field_inventory"
DAILY_CONFIG = ROOT / "config" / "daily_global_update.yml"
SHANGHAI = ZoneInfo("Asia/Shanghai")
SOURCE_TIMEZONES = {
    "OECD": ZoneInfo("Europe/Paris"),
    "RTDSM": ZoneInfo("America/New_York"),
    "USTREASURY": ZoneInfo("America/New_York"),
    "IMF": ZoneInfo("UTC"),
}
BT = chr(96)

COUNTRIES = {
    "GLB": ("Global", "全球", "GLB"),
    "AUS": ("Australia", "澳大利亚", "AU"),
    "BRA": ("Brazil", "巴西", "BR"),
    "CAN": ("Canada", "加拿大", "CA"),
    "DEU": ("Germany", "德国", "DE"),
    "FRA": ("France", "法国", "FR"),
    "GBR": ("United Kingdom", "英国", "UK"),
    "IND": ("India", "印度", "IN"),
    "ITA": ("Italy", "意大利", "IT"),
    "JPN": ("Japan", "日本", "JP"),
    "KOR": ("South Korea", "韩国", "KR"),
    "MEX": ("Mexico", "墨西哥", "MX"),
    "US": ("United States", "美国", "US"),
}
OECD_METRICS = {
    "CPI": ("Consumer Price Index", "居民消费价格指数"),
    "INDUSTRIAL_PRODUCTION": ("Industrial Production Index", "工业生产指数"),
    "REAL_GDP": ("Real GDP", "实际国内生产总值"),
    "RETAIL": ("Retail Trade Volume Index", "零售贸易量指数"),
    "UNEMPLOYMENT": ("Unemployment Rate", "失业率"),
}
SPECIAL_NAMES = {
    "GLB_IMF_ALL_COMMODITY_PRICE_INDEX": (
        "IMF Global Price Index of All Commodities",
        "IMF全球商品价格指数",
    ),
}
US_NAMES = {
    "US_CONSUMPTION": ("Nominal Personal Consumption Expenditures", "名义个人消费支出"),
    "US_CORE_CPI": ("Core Consumer Price Index", "核心居民消费价格指数"),
    "US_CPI": ("Consumer Price Index", "居民消费价格指数"),
    "US_EMPLOYMENT": ("Nonfarm Payroll Employment", "非农就业人数"),
    "US_GDI": ("Real Gross Domestic Income", "实际国内总收入"),
    "US_GDP_DEFLATOR": ("GDP Price Index", "GDP价格指数"),
    "US_HOUSING_STARTS": ("Housing Starts", "新屋开工"),
    "US_INDUSTRIAL_PRODUCTION": ("Industrial Production Index", "工业生产指数"),
    "US_LABOR_FORCE": ("Civilian Labor Force", "劳动力人口"),
    "US_MONEY_M1": ("M1 Money Stock", "M1货币存量"),
    "US_MONEY_M2": ("M2 Money Stock", "M2货币存量"),
    "US_NOMINAL_GDP": ("Nominal GDP", "名义国内生产总值"),
    "US_REAL_CONSUMPTION": ("Real Personal Consumption Expenditures", "实际个人消费支出"),
    "US_REAL_GDP": ("Real GDP", "实际国内生产总值"),
    "US_TREASURY_YIELD_2Y": ("2-Year Treasury Constant Maturity Rate", "2年期国债恒定到期收益率"),
    "US_TREASURY_YIELD_10Y": ("10-Year Treasury Constant Maturity Rate", "10年期国债恒定到期收益率"),
    "US_TREASURY_YIELD_30Y": ("30-Year Treasury Constant Maturity Rate", "30年期国债恒定到期收益率"),
    "US_UNEMPLOYMENT": ("Unemployment Rate", "失业率"),
}
FREQUENCY_NAMES = {"M": "月度", "Q": "季度"}
UNIT_NAMES = {
    "index": "指数点",
    "pct": "百分比",
    "national_currency": "本国货币口径",
    "bn_usd_sa_ar": "十亿美元，季调年率",
    "k_persons": "千人",
    "k_units_sa_ar": "千套，季调年率",
    "bn_usd_sa": "十亿美元，季调",
    "index_2016_100": "指数点，2016=100",
}
UPDATE_METHODS = {
    "USTREASURY": "每日00:00自动读取美国财政部官方Daily Treasury Par Yield Curve Rates XML；取每月最后交易日，发布日期次日00:00（America/New_York）可见，记为PIT_B。",
    "OECD": "每日00:00自动重取OECD官方SDMX revisions清单（oecd_core_part1/part2），按EDITION幂等追加PIT_B版本。",
    "RTDSM": "每日00:00自动重取费城联储RTDSM官方vintage工作簿（rtdsm_core.yml），幂等追加PIT_B版本。",
    "IMF": "每日00:00自动重取IMF官方商品价格工作簿；原始记录保持PIT_D，研究查询按40天保守估算可见。",
}


def names_for(field: str, country: str) -> tuple[str, str]:
    country_en, country_zh, prefix = COUNTRIES[country]
    if field in SPECIAL_NAMES:
        metric_en, metric_zh = SPECIAL_NAMES[field]
    elif country == "US":
        metric_en, metric_zh = US_NAMES[field]
    else:
        marker = prefix + "_"
        assert field.startswith(marker)
        suffix = field[len(marker):]
        metric_en, metric_zh = OECD_METRICS[suffix]
    return f"{country_en} {metric_en}", f"{country_zh}{metric_zh}"


def main() -> None:
    now = datetime.now(SHANGHAI)
    daily = yaml.safe_load(DAILY_CONFIG.read_text(encoding="utf-8"))
    assert set(daily["sources"]["OECD"]["job_manifests"]) == {
        "config/oecd_core_part1.yml",
        "config/oecd_core_part2.yml",
    }
    assert daily["sources"]["RTDSM"]["job_manifest"] == "config/rtdsm_core.yml"
    assert daily["sources"]["IMF"]["enabled"] is True
    assert daily["sources"]["CHINABOND"]["enabled"] is True
    assert daily["sources"]["USTREASURY"]["enabled"] is True

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    visible_rows = conn.execute(
        """
        select canonical_series_id, country, min(period), max(period),
               count(distinct period)
        from observation_vintage
        where country <> 'CN'
          and (
               (source <> 'IMF' and available_at <= ?)
               or (
                    source = 'IMF'
                    and cast(
                        cast(period_end + 41 as varchar)
                        || ' 00:00:00+08:00' as timestamptz
                    ) <= ?
               )
          )
        group by canonical_series_id, country
        order by country, canonical_series_id
        """,
        [now, now],
    ).fetchall()
    all_latest = {
        (row[0], row[1]): row[2]
        for row in conn.execute(
            """
            select canonical_series_id, country, max(period)
            from observation_vintage
            where country <> 'CN'
            group by canonical_series_id, country
            """
        ).fetchall()
    }
    attributes = {
        (row[0], row[1]): row[2:]
        for row in conn.execute(
            """
            select canonical_series_id, country, any_value(source),
                   count(distinct source), any_value(frequency),
                   count(distinct frequency), any_value(unit),
                   count(distinct unit), count(*)
            from observation_vintage
            where country <> 'CN'
            group by canonical_series_id, country
            """
        ).fetchall()
    }
    latest_period_disclosure = {
        (row[0], row[1]): row[2:]
        for row in conn.execute(
            """
            with visible as (
                select *
                from observation_vintage
                where country <> 'CN'
                  and (
                       (source <> 'IMF' and available_at <= ?)
                       or (
                            source = 'IMF'
                            and cast(
                                cast(period_end + 41 as varchar)
                                || ' 00:00:00+08:00' as timestamptz
                            ) <= ?
                       )
                  )
            ), latest as (
                select canonical_series_id, country, max(period) as period
                from visible
                group by canonical_series_id, country
            )
            select v.canonical_series_id, v.country,
                   cast(case
                        when any_value(v.source) = 'IMF'
                        then min(v.period_end) + 40
                        when any_value(v.source) = 'OECD'
                        then cast(timezone('Europe/Paris', min(v.release_at)) as date)
                        else cast(timezone('America/New_York', min(v.release_at)) as date)
                        end as varchar) as first_release_date,
                   cast(case
                        when any_value(v.source) = 'IMF'
                        then min(v.period_end) + 41
                        when any_value(v.source) = 'OECD'
                        then cast(timezone('Europe/Paris', min(v.available_at)) as date)
                        else cast(timezone('America/New_York', min(v.available_at)) as date)
                        end as varchar) as first_available_date,
                   arg_min(v.release_date_source, v.available_at) as release_date_source
            from visible v
            join latest l
              on v.canonical_series_id = l.canonical_series_id
             and v.country = l.country
             and v.period = l.period
            group by v.canonical_series_id, v.country
            """,
            [now, now],
        ).fetchall()
    }
    conn.close()

    assert len(visible_rows) == 72
    rows = []
    for field, country, first_period, visible_last, distinct_periods in visible_rows:
        source, source_count, frequency, frequency_count, unit, unit_count, vintages = attributes[(field, country)]
        assert source_count == frequency_count == unit_count == 1
        first_release_date, first_available_date, release_date_source = latest_period_disclosure[(field, country)]
        english, chinese = names_for(field, country)
        country_en, country_zh, _ = COUNTRIES[country]
        rows.append(
            {
                "field_code": field,
                "country_code": country,
                "country_en": country_en,
                "country_cn": country_zh,
                "english_name": english,
                "chinese_name": chinese,
                "frequency": frequency,
                "frequency_cn": FREQUENCY_NAMES[frequency],
                "unit": unit,
                "unit_cn": UNIT_NAMES[unit],
                "source": source,
                "start_period": first_period,
                "end_period_visible_at_generated_time": visible_last,
                "latest_period_first_disclosure_date": first_release_date,
                "latest_period_pit_available_date": first_available_date,
                "latest_period_release_date_source": release_date_source,
                "database_latest_period": all_latest[(field, country)],
                "visible_distinct_periods": distinct_periods,
                "vintage_rows": vintages,
                "update_method": UPDATE_METHODS[source],
                "automatic_daily_update": True,
            }
        )

    source_counts = Counter(row["source"] for row in rows)
    country_counts = Counter(row["country_code"] for row in rows)
    assert dict(source_counts) == {
        "IMF": 1, "OECD": 53, "RTDSM": 15, "USTREASURY": 3
    }
    assert dict(country_counts) == {
        "GLB": 1,
        "AUS": 5,
        "BRA": 5,
        "CAN": 5,
        "DEU": 5,
        "FRA": 5,
        "GBR": 5,
        "IND": 3,
        "ITA": 5,
        "JPN": 5,
        "KOR": 5,
        "MEX": 5,
        "US": 18,
    }
    assert len({row["field_code"] for row in rows}) == 72
    assert all(row["start_period"] and row["end_period_visible_at_generated_time"] for row in rows)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "all_72_non_cn_fields_bilingual_coverage_update.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    future_difference = [
        {
            "field_code": row["field_code"],
            "visible_end": row["end_period_visible_at_generated_time"],
            "database_end": row["database_latest_period"],
        }
        for row in rows
        if row["end_period_visible_at_generated_time"] != row["database_latest_period"]
    ]
    stale_fields = [
        {
            "field_code": row["field_code"],
            "visible_end": row["end_period_visible_at_generated_time"],
        }
        for row in rows
        if int(row["end_period_visible_at_generated_time"][:4]) < 2025
    ]

    lines = [
        "# 中国以外72个宏观字段：英文、中文、覆盖时间与更新方式",
        "",
        f"生成时间：{now.isoformat()}。",
        "",
        "主库目前包含12个非中国国家及1项全球汇总、72个字段：11个国家的53项OECD修订数据、美国15项费城联储RTDSM实时数据、美国财政部3项国债收益率，以及1项IMF全球商品价格代理。",
        "",
        "开始时间和结束时间均指原始数据期。结束时间只统计生成时点已满足PIT可见条件的记录；库内最晚期另列，可能包含尚未到可用日的保守版本。",
        "",
        "最晚期首次披露日期取该数据期最早一个vintage的发布日期，并按来源当地日期展示；PIT可用日期按PIT_B规则保守后移至次日00:00。后续修订不会改变这里的首次披露日期。",
        "",
        "每日全球任务在Asia/Shanghai 00:00依次刷新OECD全球清单、美国RTDSM清单、美国财政部收益率曲线、ChinaBond市场因子和IMF商品价格工作簿；以下72项均已纳入无人值守自动更新。若22:00中国任务仍在写库，国外任务等待共享锁释放后再开始。",
        "",
    ]
    for country in COUNTRIES:
        selected = [row for row in rows if row["country_code"] == country]
        if not selected:
            continue
        country_en, country_zh, _ = COUNTRIES[country]
        sources = sorted({row["source"] for row in selected})
        source_label = ", ".join(sources)
        lines.extend([
            f"## {country} / {country_en} / {country_zh}（{len(selected)}项，{source_label}）",
            "",
            "<br>".join(UPDATE_METHODS[item] for item in sources),
            "",
            "| Field code | English | 中文 | 频率 | 开始时间 | 当前PIT可见结束时间 | 最晚期首次披露日 | PIT可用日 | 库内最晚期 |",
            "|---|---|---|---|---:|---:|---:|---:|---:|",
        ])
        for row in selected:
            lines.append(
                f"| {BT}{row['field_code']}{BT} | {row['english_name']} | "
                f"{row['chinese_name']} | {row['frequency_cn']} | "
                f"{row['start_period']} | {row['end_period_visible_at_generated_time']} | "
                f"{row['latest_period_first_disclosure_date']} | "
                f"{row['latest_period_pit_available_date']} | "
                f"{row['database_latest_period']} |"
            )
        lines.append("")

    lines.extend([
        "## 数据质量核对",
        "",
        "- 非中国字段数：72；字段代码唯一，中英文名称及起止期均完整。",
        "- 72项均补充最晚PIT可见数据期的首次披露日期、PIT可用日期和日期证据来源。",
        "- 来源分布：OECD 53项、RTDSM 15项、美国财政部3项、IMF 1项。",
        "- 国家分布：澳大利亚、巴西、加拿大、德国、法国、英国、印度、意大利、日本、韩国、墨西哥、美国，共12国；另含全球汇总1项。",
        f"- 生成时库内末期与当前PIT可见末期不同：{len(future_difference)}项。",
        f"- 当前可见结束年份早于2025年的陈旧/终止序列：{len(stale_fields)}项；具体字段见quality_summary.json。",
        "",
        "## Sources receipt",
        "",
        f"- 数据库：{BT}macro_pit_v2.duckdb{BT}，只读聚合所有country不等于CN的记录。",
        f"- OECD清单：{BT}config/oecd_core_part1.yml{BT}、{BT}config/oecd_core_part2.yml{BT}。",
        f"- 美国RTDSM清单：{BT}config/rtdsm_core.yml{BT}。",
        f"- 美国财政部日度曲线：{BT}src/macro_pit/sources/us_treasury.py{BT}。",
        f"- 每日任务配置：{BT}config/daily_global_update.yml{BT}，OECD、RTDSM、美国财政部、ChinaBond和IMF均已调度。",
        f"- 本清单生成器：{BT}scripts/tools/export_non_cn_field_inventory.py{BT}。",
    ])
    md_path = OUT_DIR / "README.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    quality = {
        "generated_at": now.isoformat(),
        "database": str(DB_PATH),
        "countries": len(country_counts),
        "field_count": len(rows),
        "unique_field_codes": len({row["field_code"] for row in rows}),
        "all_names_mapped": True,
        "all_start_end_non_null": all(
            row["start_period"] and row["end_period_visible_at_generated_time"]
            for row in rows
        ),
        "all_latest_disclosure_dates_non_null": all(
            row["latest_period_first_disclosure_date"]
            and row["latest_period_pit_available_date"]
            and row["latest_period_release_date_source"]
            for row in rows
        ),
        "automatic_daily_fields": len(rows),
        "manual_on_demand_fields": 0,
        "source_field_counts": dict(source_counts),
        "country_field_counts": dict(country_counts),
        "future_visibility_differences": future_difference,
        "stale_or_discontinued_before_2025": stale_fields,
        "daily_task_scope_note": "OECD, RTDSM, USTREASURY, ChinaBond, and IMF are scheduled daily at 00:00 Asia/Shanghai with a shared database lock.",
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
