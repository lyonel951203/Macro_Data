"""Independently verify reviewed source cells; main ingestion requires --ingest."""
from dataclasses import asdict
from datetime import datetime, timedelta
import argparse
import hashlib
import json
from pathlib import Path
import re

from lxml import html
import pandas as pd
from macro_pit.archive import RawArtifact
from macro_pit.db import OBSERVATION_COLUMNS, get_connection, insert_observations
from macro_pit.pit import get_snapshot
from macro_pit.sources.cn_nbs import NBSSource
from macro_pit.timeutils import SHANGHAI, ensure_aware

OUT=Path("reports/v2/nbs_economy_batch2")
FIELDS={
    "industry":("CN_INDUSTRIAL_VALUE_ADDED_YOY","规模以上工业增加值",2),
    "services":("CN_SERVICE_PRODUCTION_YOY","服务业生产指数",2),
    "retail":("CN_RETAIL_SALES_YOY","社会消费品零售总额",2),
    "fai":("CN_FAI_YTD_YOY","固定资产投资（不含农户）",4),
    "infra":("CN_INFRA_INVESTMENT_YTD_YOY","基础设施投资",None),
    "manufacturing":("CN_MANUFACTURING_INVESTMENT_YTD_YOY","制造业投资",None),
    "real_estate":("CN_REAL_ESTATE_INVESTMENT_YTD_YOY","房地产开发投资",4),
    "sales_area":("CN_NEW_HOME_SALES_AREA_YTD_YOY","新建商品房销售面积",4),
    "sales_value":("CN_NEW_HOME_SALES_VALUE_YTD_YOY","新建商品房销售额",4),
    "unemployment":("CN_URBAN_SURVEYED_UNEMPLOYMENT","全国城镇调查失业率",1),
    "cpi":("CN_CPI_YOY","居民消费价格",2),
    "ppi":("CN_PPI_YOY","工业生产者出厂价格",2),
}


def compact(s): return re.sub(r"\s+","",s)


def table_evidence(body,month):
    found={}
    allowed={field[1] for field in FIELDS.values()} | {"商品房销售面积","商品房销售额"}
    for table in body.xpath('.//table'):
        rows=[[compact(c.text_content()) for c in tr.xpath('./td|./th')] for tr in table.xpath('.//tr')]
        heads=[i for i,r in enumerate(rows[:8]) if len(r)==3 and r[0] in {"","指标"}
               and re.fullmatch(fr'{month}月份?',r[1]) and re.fullmatch(fr'1[-—–至]{month}月份?',r[2])]
        if not heads: continue
        h=heads[0]
        sub=[x.replace("（","(").replace("）",")") for x in rows[h+1]]
        assert sub==["绝对量","同比增长(%)","绝对量","同比增长(%)"]
        for r in rows[h+2:]:
            if len(r)!=5: continue
            label=re.sub(r'^(?:[一二三四五六七八九十]+、|[（(][一二三四五六七八九十]+[）)])','',r[0])
            label=re.sub(r'[（(](?:亿元|万平方米|%)[）)]$','',label)
            if label not in allowed: continue
            if label in found: assert found[label]==r[1:], (label,found[label],r)
            found[label]=r[1:]
    assert found, "Explicit monthly/YTD table missing"
    return found


def review(*,partial=False,ingest=False):
    assert not (partial and ingest)
    manifest=json.loads(Path("config/nbs_economy_batch2_candidates.json").read_text(encoding="utf-8"))
    state=json.loads(Path("data/history_backfill/nbs_economy_batch2_download_state.json").read_text(encoding="utf-8"))
    expected=json.loads(Path("config/nbs_economy_batch2_review_values.json").read_text(encoding="utf-8"))
    assert state["manifest_sha256"]==hashlib.sha256(Path("config/nbs_economy_batch2_candidates.json").read_bytes()).hexdigest()
    if not partial:
        assert state["status"]=="COMPLETE" and len(state["items"])==20
        assert set(expected["articles"])=={r["period"] for r in manifest["items"]}
    before=pd.read_parquet(OUT/"before_nbs_observations.parquet")
    old_values={(r.canonical_series_id,r.period,r.value) for r in before.itertuples()}
    old_keys={(r.canonical_series_id,r.period) for r in before.itertuples()}
    articles=[]
    for item in state["items"].values():
        if item["period"] in expected["articles"]:
            spec=expected["articles"][item["period"]]
            assert len(spec['values'])==len(expected['column_order'])
            articles.append((item,spec["timestamp"],dict(zip(expected["column_order"],spec["values"]))))
    inventory=pd.read_csv("reports/v2/nbs_economy_batch1/cached_economy_inventory.csv")
    for period,spec in expected["cached_sales"].items():
        inv=inventory[inventory.periods.eq(period)].iloc[0]
        row=before[before.raw_sha256.eq(inv.raw_sha256)].iloc[0]
        a=RawArtifact("NBS",inv.url,inv.raw_file,inv.raw_sha256,"text/html",row.retrieved_at.to_pydatetime(),Path(inv.raw_file).stat().st_size)
        articles.append((dict(period=period,title=inv.title,url=inv.url,artifact=asdict(a)),spec["timestamp"],{k:spec[k] for k in ["sales_area","sales_value"]}))
    evidence=[]; incoming=[]; excluded=[]
    source=NBSSource(allow_network=False)
    try:
        for item,stamp,values in articles:
            raw=dict(item["artifact"]); raw["retrieved_at"]=ensure_aware(raw["retrieved_at"])
            artifact=RawArtifact(**raw)
            content=Path(artifact.path).read_bytes()
            assert hashlib.sha256(content).hexdigest()==artifact.sha256
            tree=html.fromstring(content,parser=html.HTMLParser(encoding="utf-8"))
            assert compact(item["title"]) in compact(tree.findtext('.//title'))
            headers=tree.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," detail-title-des ")]')
            assert len(headers)==1
            stamps=re.findall(r'20\d\d/\d\d/\d\d\s+\d\d:\d\d(?::\d\d)?',headers[0].text_content())
            assert len(stamps)==1 and " ".join(stamps[0].split())==stamp
            release=datetime.strptime(stamp,"%Y/%m/%d %H:%M").replace(tzinfo=SHANGHAI)
            period=item["period"]; month=int(period[-2:])
            assert str(pd.Period(release.date(),freq="M")-1)==period
            bodies=tree.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," txt-content ")]')
            assert len(bodies)==1
            body=bodies[0]; body_text=compact(body.text_content())
            table=table_evidence(body,month)
            parsed={(r["canonical_series_id"],r["period"]):r for r in source.parse(content,artifact)}
            for name,value in values.items():
                canonical,label,column=FIELDS[name]
                proof=None; method="explicit_table_column_and_reviewed_expected_value"
                actual_label=label
                if name in {"sales_area","sales_value"} and label not in table and period[:4] in {"2022","2023"}:
                    actual_label=label.removeprefix("新建")
                    assert Path("reports/v2/nbs_economy_batch2/sales_definition_web_evidence.json").exists()
                if column and actual_label in table:
                    cells=table[actual_label]
                    assert float(cells[column-1])==value,(period,name,cells,value)
                    proof=actual_label+" | "+" | ".join(cells)
                elif name in {"infra","manufacturing"}:
                    paragraphs=[compact(p.text_content()) for p in body.xpath('.//p') if "固定资产投资（不含农户）" in compact(p.text_content()) and "基础设施投资" in compact(p.text_content()) and "制造业投资" in compact(p.text_content())]
                    assert paragraphs,(period,name,"investment scope absent")
                    matches=set()
                    for p in paragraphs:
                        matches.update(re.findall(re.escape(label)+r'(?:同比)?(?:增长|下降)[\d.]+[%％]',p))
                    assert len(matches)==1,(period,name,matches)
                    proof=matches.pop()
                    actual=float(re.search(r'[\d.]+',proof).group())*(-1 if "下降" in proof else 1)
                    assert actual==value,(period,name,proof,value)
                    method="scoped_investment_paragraph_and_reviewed_expected_value"
                elif name=="unemployment":
                    if period=="2022-06":
                        proof="4月份，全国城镇调查失业率为6.1%；5、6月份连续回落，分别为5.9%、5.5%"
                        assert value==5.5 and proof in body_text
                    else:
                        quotes=re.findall(fr'(?<![\d\-—–至]){month}月份[，,]全国城镇调查失业率为[\d.]+[%％]',body_text)
                        assert quotes and all(float(re.search(r'为([\d.]+)',q).group(1))==value for q in quotes),(period,name,quotes,value)
                        proof=quotes[0]
                    method="explicit_national_monthly_rate_and_reviewed_expected_value"
                else:
                    raise AssertionError((period,name,"no independent evidence"))
                row=parsed[(canonical,period)]
                assert row["value"]==value and row["release_at"]==release and row["available_at"]==release,(period,name,row)
                assert row["pit_grade"]=="A" and row["frequency"]=="M"
                assert row["unit"]==("pct" if name=="unemployment" else "pct_yoy")
                repeated=(canonical,period,value) in old_values
                if (canonical,period) in old_keys: assert repeated,(canonical,period,"unreviewed correction")
                evidence.append(dict(canonical_series_id=canonical,period=period,value=value,release_at=release.isoformat(),available_at=release.isoformat(),pit_grade="A",value_evidence=proof,timestamp_evidence=stamp,method=method,raw_file=artifact.path,raw_sha256=artifact.sha256,url=artifact.url,action="already_covered" if repeated else "new_series_period",result="PASS"))
                if not repeated: incoming.append(row)
            reviewed={FIELDS[n][0] for n in values}
            for (canonical,p),row in parsed.items():
                if canonical not in reviewed:
                    assert (canonical,p,row["value"]) in old_values,(canonical,p,"unreviewed new parsed value")
                    excluded.append(dict(canonical_series_id=canonical,period=p,value=row["value"],url=artifact.url,reason="already_covered_value_outside_review_targets"))
    finally:
        source.close()
    suffix="partial" if partial else "validated"
    pd.DataFrame(evidence).to_csv(OUT/f"{suffix}_samples.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(incoming).to_parquet(OUT/f"{suffix}_observations.parquet",index=False)
    summary=dict(status="PARTIAL" if partial else "VERIFIED",reviewed_articles=len(articles),verified_records=len(evidence),new_series_periods=len(incoming),already_covered_records=sum(r["action"]=="already_covered" for r in evidence),downloaded_articles=len(state["items"]),sha256="PASS",independent_values_and_timestamps="PASS")
    if not partial:
        assert len(incoming)==206 and len(evidence)==246
        assert len({(r["canonical_series_id"],r["period"]) for r in incoming})==len(incoming)
        pd.DataFrame(excluded).to_csv(OUT/"excluded_repeat_values.csv",index=False,encoding="utf-8-sig")
        with get_connection(":memory:") as conn:
            first=insert_observations(conn,incoming)
            duplicate=insert_observations(conn,incoming)
            assert first.inserted==206 and duplicate.inserted==0 and duplicate.unchanged==206
            for row in incoming:
                for delta,exists in [(-1,False),(0,True)]:
                    snapshot=get_snapshot(conn,(row["available_at"]+timedelta(seconds=delta)).isoformat(),"CN")
                    found=[r for r in snapshot.to_dicts() if r["canonical_series_id"]==row["canonical_series_id"] and r["period"]==row["period"]]
                    assert bool(found)==exists
        summary.update(release_boundary_checks=412,idempotency="PASS")
    if ingest:
        assert not Path("data/history_backfill/nbs_price_batch.lock").exists()
        regression=json.loads((OUT/"regression_result.json").read_text(encoding="utf-8"))
        assert regression["status"]=="PASS" and regression["new_cached_series_periods"]==6
        candidates=pd.read_csv(OUT/"new_cached_candidates.csv")
        assert {(r.canonical_series_id,r.period,r.value) for r in candidates.itertuples()}.issubset(
            {(r["canonical_series_id"],r["period"],r["value"]) for r in incoming})
        with get_connection("macro_pit_v2.duckdb") as conn:
            prior=conn.sql("SELECT count(*) FROM observation_vintage").fetchone()[0]
            result=insert_observations(conn,incoming)
            conn.register("baseline",before[OBSERVATION_COLUMNS])
            assert conn.sql("SELECT count(*) FROM (SELECT * FROM baseline EXCEPT ALL SELECT * FROM observation_vintage WHERE source='NBS')").fetchone()[0]==0
            for row in incoming:
                snap=get_snapshot(conn,row["available_at"].isoformat(),"CN").to_dicts()
                chosen=[r for r in snap if r["canonical_series_id"]==row["canonical_series_id"] and r["period"]==row["period"]]
                assert len(chosen)==1 and chosen[0]["value"]==row["value"]
            after=conn.sql("SELECT count(*) FROM observation_vintage").fetchone()[0]
        ingested=dict(before_rows=prior,after_rows=after,stats=asdict(result),original_rows_retained=True,snapshot_checks=206,**summary)
        target=OUT/("ingestion_replay.json" if (OUT/"ingestion_result.json").exists() else "ingestion_result.json")
        target.write_text(json.dumps(ingested,ensure_ascii=False,indent=2),encoding="utf-8")
        summary["ingestion"]=ingested
    (OUT/f"{suffix}_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return summary


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partial",action="store_true")
    parser.add_argument("--ingest",action="store_true")
    args=parser.parse_args()
    review(partial=args.partial,ingest=args.ingest)
