"""Send the latest stored update and DeepSeek audit reports by email."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from macro_pit.email_delivery import send_audit_email
from scripts.run_daily_web_update import DEFAULT_CONFIG, load_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()
    config = load_config(args.config)
    email = config.get("email_notification")
    audit = config.get("semantic_audit")
    if not email or not audit:
        parser.error("selected config requires email_notification and semantic_audit")
    update_dir = Path(config["report_dir"])
    audit_dir = Path(audit["report_dir"])
    update_report = json.loads(
        (update_dir / "latest.json").read_text(encoding="utf-8")
    )
    audit_result = json.loads(
        (audit_dir / "latest.json").read_text(encoding="utf-8")
    )
    audit_result["report_md"] = str(audit_dir / "latest.md")
    result = send_audit_email(
        settings=email,
        update_report=update_report,
        audit_result=audit_result,
        update_report_md=update_dir / "latest.md",
    )
    print(json.dumps({
        "status": result["status"],
        "recipient": result["recipient"],
        "attachments": result.get("attachments", []),
        "error": result.get("error"),
        "receipt": result.get("latest_report"),
    }, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "SENT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
