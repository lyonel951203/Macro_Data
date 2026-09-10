"""Find repeated result pages in archived NBS search responses, without network."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from macro_pit.nbs_search import _page_fingerprint, _save_state


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--repair-state", action="store_true")
args = parser.parse_args()
os.chdir(Path(__file__).resolve().parents[1])
state_path = Path("data/history_backfill/nbs_legacy_search_state.json")
state = json.loads(state_path.read_text(encoding="utf-8"))
pages = []
for cache_file in Path("data/http_cache/nbs").glob("*.json"):
    cache = json.loads(cache_file.read_text(encoding="utf-8"))
    url = cache.get("url", "")
    if not url.startswith("https://api.so-gov.cn/query/s?"):
        continue
    query = parse_qs(urlparse(url).query)
    if query.get("startDateStr") != [state["start_date"]] or query.get("endDateStr") != [state["end_date"]]:
        continue
    content = Path(cache["raw_file"]).read_bytes()
    if hashlib.sha256(content).hexdigest() != cache["raw_sha256"]:
        raise ValueError(f"Corrupt raw search response: {cache['raw_file']}")
    payload = json.loads(content)
    pages.append({"term": query["qt"][0], "page": int(query["page"][0]),
                  "fingerprint": _page_fingerprint(payload), "raw_file": cache["raw_file"]})
repeats = []
for term in state["terms"]:
    seen = {}
    fingerprints = {}
    for page in sorted((p for p in pages if p["term"] == term), key=lambda p: p["page"]):
        fingerprint = page["fingerprint"]
        if fingerprint and fingerprint in seen:
            repeats.append({**page, "matches_page": seen[fingerprint]})
        elif fingerprint:
            seen[fingerprint] = page["page"]
            fingerprints[str(page["page"])] = fingerprint
    state["items"][term]["page_fingerprints"] = fingerprints
for repeat in repeats:
    state["items"][repeat["term"]].update({
        "complete": False, "needs_narrowing": True,
        "pagination_repeat": {key: repeat[key] for key in ["page", "matches_page", "raw_file"]},
    })
if args.repair_state:
    backup = state_path.with_name("nbs_legacy_search_state.pre_repeat_audit_20260908.json")
    if not backup.exists():
        backup.write_bytes(state_path.read_bytes())
    if repeats:
        state["status"] = "PAUSED"  # Other terms remain available for bounded resume.
    _save_state(state_path, state)
output = Path("reports/v2/nbs_legacy/search_pagination_audit.json")
output.write_text(json.dumps({"pages_checked": len(pages), "repeats": repeats,
                              "state_repaired": args.repair_state}, ensure_ascii=False, indent=2), encoding="utf-8")
print(output.read_text(encoding="utf-8"))
