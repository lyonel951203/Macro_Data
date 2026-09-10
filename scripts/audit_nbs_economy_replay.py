"""Frozen-before, read-only replay for the bounded economy parser repair."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import pandas as pd

from macro_pit.archive import RawArtifact
from macro_pit.sources.cn_nbs import NBSSource
from macro_pit.timeutils import ensure_aware


OUT = Path("reports/v2/nbs_economy_batch1")


def audit():
    stored = pd.read_parquet(OUT / "before_nbs_observations.parquet")
    artifacts = {}
    for (raw_file, raw_hash), group in stored.groupby(["raw_file", "raw_sha256"]):
        first = group.iloc[0]
        artifacts[raw_hash] = RawArtifact("NBS", first.source_url, raw_file, raw_hash,
            "text/html", first.retrieved_at.to_pydatetime(), Path(raw_file).stat().st_size)
    state = json.loads(Path("data/history_backfill/nbs_economy_sample_batch1_state.json").read_text(encoding="utf-8"))
    for item in state["items"].values():
        artifact = dict(item["artifact"])
        artifact["retrieved_at"] = ensure_aware(artifact["retrieved_at"])
        artifacts[artifact["sha256"]] = RawArtifact(**artifact)
    changes, parsed_rows, errors = [], [], []
    fields = ["value", "release_at", "available_at", "pit_grade", "unit", "frequency"]
    source = NBSSource(allow_network=False)
    compared = unchanged = 0
    try:
        for number, (raw_hash, artifact) in enumerate(artifacts.items(), 1):
            content = Path(artifact.path).read_bytes()
            assert hashlib.sha256(content).hexdigest() == raw_hash
            before = stored[stored.raw_sha256.eq(raw_hash)]
            try:
                after = source.parse(content, artifact)
            except Exception as exc:
                errors.append(dict(raw_sha256=raw_hash, error=f"{type(exc).__name__}: {exc}"))
                continue
            parsed_rows.extend(after)
            keyed = {(r["canonical_series_id"], r["period"]): r for r in after}
            for row in before.to_dict("records"):
                compared += 1
                key = (row["canonical_series_id"], row["period"])
                new = keyed.get(key)
                changed = [k for k in fields if new is None or row[k] != new[k]]
                if not changed:
                    unchanged += 1
                    continue
                changes.append(dict(raw_sha256=raw_hash, url=artifact.url, canonical_series_id=key[0],
                                    period=key[1], before_value=row["value"],
                                    after_value=new["value"] if new else None,
                                    changed_fields=",".join(changed), kind="missing" if new is None else "correction"))
            old_keys = set(zip(before.canonical_series_id, before.period))
            for key, new in keyed.items():
                if key not in old_keys:
                    changes.append(dict(raw_sha256=raw_hash, url=artifact.url, canonical_series_id=key[0],
                                        period=key[1], before_value=None, after_value=new["value"],
                                        changed_fields="new", kind="addition"))
            if number % 50 == 0:
                print(f"Replayed {number}/{len(artifacts)} archives", flush=True)
    finally:
        source.close()
    frame = pd.DataFrame(changes)
    frame.to_csv(OUT / "parser_change_audit.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(parsed_rows).to_parquet(OUT / "parsed_replay.parquet", index=False)
    result = dict(baseline_rows=len(stored), compared_rows=compared, unchanged_rows=unchanged,
                  raw_files=len(artifacts), changes=len(changes), errors=errors,
                  kinds=frame.kind.value_counts().to_dict())
    (OUT / "replay_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "artifacts.json").write_text(json.dumps({k: asdict(v) for k,v in artifacts.items()},
        ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(frame[["kind", "period", "canonical_series_id", "before_value", "after_value"]].to_string(index=False))


if __name__ == "__main__":
    audit()
