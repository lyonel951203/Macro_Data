"""Replay the frozen pre-batch archives, accounting for previously logged repairs."""
import hashlib
import json
from pathlib import Path
import pandas as pd
from macro_pit.archive import RawArtifact
from macro_pit.sources.cn_nbs import NBSSource

OUT=Path("reports/v2/nbs_economy_batch2")


def check():
    baseline=pd.read_parquet(OUT/"before_nbs_observations.parquet")
    prior=pd.read_csv("reports/v2/nbs_economy_batch1/parser_correction_ledger.csv")
    obsolete={(r.raw_sha256,r.canonical_series_id,r.period,r.before_value) for r in prior.itertuples()}
    baseline_keys=set(zip(baseline.canonical_series_id,baseline.period))
    compared=skipped=0; differences=[]; new=[]; failures=[]
    source=NBSSource(allow_network=False)
    groups=baseline.groupby(["raw_file","raw_sha256"])
    try:
        for i,((path,sha),group) in enumerate(groups,1):
            content=Path(path).read_bytes(); assert hashlib.sha256(content).hexdigest()==sha
            first=group.iloc[0]
            artifact=RawArtifact("NBS",first.source_url,path,sha,"text/html",first.retrieved_at.to_pydatetime(),len(content))
            try: parsed={(r["canonical_series_id"],r["period"]):r for r in source.parse(content,artifact)}
            except Exception as exc:
                failures.append(dict(raw_file=path,error=str(exc))); continue
            for row in group.to_dict("records"):
                if (sha,row["canonical_series_id"],row["period"],row["value"]) in obsolete:
                    skipped+=1; continue
                after=parsed.get((row["canonical_series_id"],row["period"]))
                fields=[k for k in ["value","release_at","available_at","pit_grade","unit","frequency"] if after is None or after[k]!=row[k]]
                compared+=1
                if fields: differences.append(dict(raw_file=path,indicator=row["canonical_series_id"],period=row["period"],fields=fields))
            for (canonical,period),row in parsed.items():
                if (canonical,period) not in baseline_keys:
                    new.append(dict(raw_file=path,raw_sha256=sha,canonical_series_id=canonical,period=period,value=row["value"]))
            if i%50==0: print(f"Replayed {i}/{len(groups)} frozen archives",flush=True)
    finally: source.close()
    result=dict(baseline_rows=len(baseline),archives=len(groups),compared_rows=compared,previously_corrected_obsolete_rows=skipped,
                changed_valid_rows=len(differences),differences=differences,parse_failures=failures,new_cached_series_periods=len(new))
    result["status"]="PASS" if not differences and not failures and compared+skipped==len(baseline) and skipped==13 else "FAIL"
    (OUT/"regression_result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    pd.DataFrame(new).to_csv(OUT/"new_cached_candidates.csv",index=False,encoding="utf-8-sig")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    assert result["status"]=="PASS"
    return result


if __name__=='__main__': check()
