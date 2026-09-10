"""Fetch a bounded reviewed manifest, checkpoint raw files, and exit. No ingestion."""
from pathlib import Path
import argparse
import json
import os
from dataclasses import asdict

from macro_pit.db import get_connection, record_crawl_events
from macro_pit.errors import CrawlSafetyError
from macro_pit.pipeline import _validate_manifest
from macro_pit.sources.cn_nbs import NBSSource


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--max-urls", type=int, default=1)
parser.add_argument("--allow-network", action="store_true")
parser.add_argument("--manifest", default="config/nbs_legacy_validation_batch.json")
parser.add_argument("--state-path", default="data/history_backfill/nbs_legacy_validation_state.json")
args = parser.parse_args()
if not 1 <= args.max_urls <= 20:
    parser.error("max-urls must be 1..20")
root = Path(__file__).resolve().parents[1]
os.chdir(root)
manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
state_path = Path(args.state_path)
state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"items": {}}
source = NBSSource(allow_network=args.allow_network)
_validate_manifest([item["url"] for item in manifest["items"]], source.policy)
pending = [item for item in manifest["items"] if item["url"] not in state["items"]]
state["status"] = "RUNNING"
state.pop("last_error", None)
def save():
    temporary = state_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, state_path)

save()
try:
    for item in pending[:args.max_urls]:
        offset = len(source.client.events)
        try:
            fetched = source.fetch(item["url"], refresh=False)
            evidence = asdict(fetched.artifact)
            evidence["retrieved_at"] = fetched.artifact.retrieved_at.isoformat()
            state["items"][item["url"]] = {**item, "artifact": evidence, "from_cache": fetched.from_cache}
            save()
            print(json.dumps({"downloaded": item["title"], "raw": evidence["path"]}, ensure_ascii=False), flush=True)
        finally:
            conn = get_connection("macro_pit_v2.duckdb")
            try:
                record_crawl_events(conn, source.client.events[offset:], parser_version="nbs_legacy_raw_review_v1")
            finally:
                conn.close()
    state["pending"] = sum(item["url"] not in state["items"] for item in manifest["items"])
    state["status"] = "COMPLETE" if not state["pending"] else "PAUSED"
except Exception as exc:
    state["status"] = "BLOCKED" if isinstance(exc, CrawlSafetyError) else "FAILED"
    state["last_error"] = f"{type(exc).__name__}: {exc}"
    raise
finally:
    state["pending"] = sum(item["url"] not in state["items"] for item in manifest["items"])
    save()
    source.close()
print(json.dumps({"status": state["status"], "downloaded": len(state["items"]), "pending": state.get("pending")}), flush=True)
