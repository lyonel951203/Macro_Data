"""Archive a bounded historical manifest with immutable provenance and checkpoints."""
import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil

from macro_pit.db import get_connection, record_crawl_events
from macro_pit.pipeline import _validate_manifest
from macro_pit.sources.cn_nbs import NBSSource
from macro_pit.timeutils import SHANGHAI

OUT = Path("reports/v2/nbs_early_2005")
MANIFEST = Path("config/nbs_early_2005_candidates.json")
STATE = Path("data/history_backfill/nbs_early_2005_download_state.json")


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def run(allow_network=False):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    items = manifest["items"]
    assert 1 <= len(items) <= 20 and len({i['url'] for i in items}) == len(items)
    for item in items:
        evidence = json.loads(Path(item["index_raw_file"]).read_text(encoding="utf-8"))
        if item.get("kind") == "web_discovery_seed":
            assert evidence["method"] == "official_web_search_result"
            assert any(x["url"] == item["url"] and x["title"] == item["title"] for x in evidence["items"])
        else:
            assert any(x.get("data", {}).get("url") == item["url"] for x in evidence["resultDocs"])
    digest = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"items": {}}
    assert state.get("manifest_sha256", digest) == digest
    if state.get("status") == "COMPLETE":
        print("All manifest articles already archived; no requests made")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    lock = Path("data/history_backfill/nbs_price_batch.lock")
    with lock.open("x", encoding="utf-8") as handle:
        json.dump({"pid": os.getpid(), "batch": "nbs_early_2005", "phase": "raw_download"}, handle)
    source = None
    try:
        before = OUT / "before"
        before.mkdir(exist_ok=True)
        for path in [*Path("data/exports").glob("cn_pit_month_end_2005_20260731*"), Path("reports/v2/pit_csv_inspection/field_history.csv")]:
            if not (before / path.name).exists():
                shutil.copyfile(path, before / path.name)
        if not (OUT / "before_nbs_observations.parquet").exists():
            with get_connection("macro_pit_v2.duckdb", read_only=True) as conn:
                conn.sql("SELECT * FROM observation_vintage WHERE source='NBS'").df().to_parquet(OUT / "before_nbs_observations.parquet", index=False)
                conn.sql("SELECT source,count(*) row_count FROM observation_vintage GROUP BY source").df().to_csv(before / "database_source_counts.csv", index=False)
        state.update(status="RUNNING", pid=os.getpid(), manifest_sha256=digest, total=len(items))
        state.setdefault("started_at", datetime.now(SHANGHAI).isoformat())
        source = NBSSource(allow_network=allow_network)
        _validate_manifest([i["url"] for i in items], source.policy)
        for item in items:
            if item["url"] in state["items"]:
                continue
            state.update(current_url=item["url"], pending=len(items)-len(state["items"]))
            save(STATE, state)
            offset = len(source.client.events)
            try:
                fetched = source.fetch(item["url"], refresh=False)
                artifact = asdict(fetched.artifact)
                artifact["retrieved_at"] = fetched.artifact.retrieved_at.isoformat()
                state["items"][item["url"]] = {**item, "artifact": artifact, "from_cache": fetched.from_cache}
                state.update(pending=len(items)-len(state["items"]), updated_at=datetime.now(SHANGHAI).isoformat())
                save(STATE, state)
                print(json.dumps({"downloaded":len(state["items"]), "total":len(items), "title":item["title"], "raw":artifact["path"]}, ensure_ascii=False), flush=True)
            finally:
                if source.client.events[offset:]:
                    with get_connection("macro_pit_v2.duckdb") as conn:
                        record_crawl_events(conn, source.client.events[offset:], parser_version="nbs_early_2005_download_v1")
        state.update(status="COMPLETE")
        state.pop("last_error", None)
    except Exception as exc:
        state.update(status="STOPPED", last_error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if source:
            source.close()
        state.update(pending=len(items)-len(state["items"]), updated_at=datetime.now(SHANGHAI).isoformat())
        save(STATE, state)
        lock.unlink()
    print(json.dumps({"status":state["status"], "total":len(items)}), flush=True)


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parents[1])
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--allow-network", action="store_true")
    run(p.parse_args().allow_network)
