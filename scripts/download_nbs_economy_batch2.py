"""Download exactly the reviewed 20-article economy manifest; never ingest values."""
from dataclasses import asdict
from datetime import datetime
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import pandas as pd
from macro_pit.db import get_connection, record_crawl_events
from macro_pit.pipeline import _validate_manifest
from macro_pit.sources.cn_nbs import NBSSource
from macro_pit.timeutils import SHANGHAI

OUT=Path("reports/v2/nbs_economy_batch2")
STATE=Path("data/history_backfill/nbs_economy_batch2_download_state.json")
MANIFEST=Path("config/nbs_economy_batch2_candidates.json")


def save(path, value):
    temporary=path.with_suffix(path.suffix+".tmp")
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    os.replace(temporary,path)


def run(*,allow_network=False):
    items=json.loads(MANIFEST.read_text(encoding="utf-8"))["items"]
    assert len(items)==20 and len({i['url'] for i in items})==20
    # Check official archived index provenance before network access.
    for item in items:
        soup=BeautifulSoup(Path(item["index_raw_file"]).read_text(encoding="utf-8"),"lxml")
        matches=[a for a in soup.find_all("a",href=True)
                 if urljoin("https://www.stats.gov.cn/sj/zxfb/",str(a["href"]))==item["url"]]
        assert matches and all(re.sub(r"\s+","",a.get("title") or a.get_text())==re.sub(r"\s+","",item["title"]) for a in matches)
    OUT.mkdir(exist_ok=True)
    state=json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"items":{}}
    digest=hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    assert state.get("manifest_sha256",digest)==digest
    if state.get("status")=="COMPLETE":
        print("All 20 raw articles already archived; no network needed",flush=True)
        return
    lock=Path("data/history_backfill/nbs_price_batch.lock")
    with lock.open("x",encoding="utf-8") as handle:
        json.dump(dict(pid=os.getpid(),batch="nbs_economy_batch2",phase="raw_download"),handle)
    source=None
    try:
        before=OUT/"before"
        before.mkdir(exist_ok=True)
        for p in [*Path("data/exports").glob("cn_pit_month_end_2005_20260731*"),Path("reports/v2/pit_csv_inspection/field_history.csv")]:
            if not (before/p.name).exists(): shutil.copyfile(p,before/p.name)
        baseline=OUT/"before_nbs_observations.parquet"
        if not baseline.exists():
            with get_connection("macro_pit_v2.duckdb",read_only=True) as conn:
                conn.sql("SELECT * FROM observation_vintage WHERE source='NBS'").df().to_parquet(baseline,index=False)
                counts=conn.sql("SELECT source,count(*) row_count FROM observation_vintage GROUP BY source").df()
                counts.to_csv(before/"database_source_counts.csv",index=False)
        state.update(status="RUNNING",pid=os.getpid(),manifest_sha256=digest,updated_at=datetime.now(SHANGHAI).isoformat())
        state.setdefault("started_at",state["updated_at"])
        source=NBSSource(allow_network=allow_network)
        _validate_manifest([i["url"] for i in items],source.policy)
        for item in items:
            if item["url"] in state["items"]: continue
            state.update(current_url=item["url"],pending=20-len(state["items"]))
            save(STATE,state)
            offset=len(source.client.events)
            try:
                fetched=source.fetch(item["url"],refresh=False)
                artifact=asdict(fetched.artifact)
                artifact["retrieved_at"]=fetched.artifact.retrieved_at.isoformat()
                state["items"][item["url"]]={**item,"artifact":artifact,"from_cache":fetched.from_cache}
                state["updated_at"]=datetime.now(SHANGHAI).isoformat()
                state["pending"]=20-len(state["items"])
                save(STATE,state)
                print(json.dumps(dict(downloaded=len(state["items"]),total=20,period=item["period"],title=item["title"],raw=artifact["path"]),ensure_ascii=False),flush=True)
            finally:
                if source.client.events[offset:]:
                    with get_connection("macro_pit_v2.duckdb") as conn:
                        record_crawl_events(conn,source.client.events[offset:],parser_version="nbs_economy_batch2_raw_v1")
        state["status"]="COMPLETE"
        state.pop("last_error",None)
    except Exception as exc:
        state.update(status="STOPPED",last_error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if source: source.close()
        state.update(pending=20-len(state["items"]),updated_at=datetime.now(SHANGHAI).isoformat())
        save(STATE,state)
        lock.unlink()
    print(json.dumps(dict(status=state["status"],downloaded=len(state["items"]),pending=state["pending"])),flush=True)


if __name__=="__main__":
    os.chdir(Path(__file__).resolve().parents[1])
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-network",action="store_true")
    run(allow_network=parser.parse_args().allow_network)
