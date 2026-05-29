"""Validate Stage 2 JSON and save the full AnalysisRecord.

Usage:
    python save_record.py <meta_json_path> <stage1_json_path> <stage2_json_string>

Reads:
  - meta_json_path: JSON with kline_data, stage1_messages, stage2_messages,
                     strategy_files, experience_loaded, symbol, timeframe, bar_count
  - stage1_json_path: JSON with validated stage1_diagnosis
  - stage2_json_string: the raw Stage 2 JSON output from Claude

Outputs JSON to stdout with keys:
  - saved_path: path to the saved record
  - stage2_decision: validated Stage 2 dict
  - validation_error: string if Stage 2 validation failed
  - error: string if something else went wrong
"""
from __future__ import annotations

import json
import sys
import io
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Resolve repo root: helpers/ → pa-agent/ → skills/ → repo root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pa_agent.config.paths import RECORDS_PENDING_DIR
from pa_agent.ai.json_validator import JsonValidator, Ok, ValidationError
from pa_agent.records.schema import AnalysisRecord, RecordMeta
from pa_agent.util.timefmt import now_local_ms


def main() -> None:
    if len(sys.argv) < 4:
        print(json.dumps({"error": "Usage: save_record.py <meta_json_path> <stage1_json_path> <stage2_raw>"}))
        sys.exit(1)

    meta_path = Path(sys.argv[1])
    stage1_path = Path(sys.argv[2])
    stage2_raw = sys.argv[3]

    # Load metadata and stage1
    try:
        meta_dict = json.loads(meta_path.read_text(encoding="utf-8"))
        stage1_json = json.loads(stage1_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"error": f"Failed to load inputs: {exc}"}, ensure_ascii=False))
        sys.exit(1)

    # Validate Stage 2
    validator = JsonValidator()
    result = validator.validate(
        "stage2",
        stage2_raw,
        stage1_json=stage1_json.get("stage1_diagnosis", {}),
    )

    if isinstance(result, ValidationError):
        print(json.dumps({
            "validation_error": f"Stage 2 validation failed [{result.category}]: {result.message}",
            "missing_fields": result.missing_fields,
            "invalid_fields": result.invalid_fields,
        }, ensure_ascii=False))
        sys.exit(1)

    stage2_json = result.obj

    # Build the AnalysisRecord
    now = now_local_ms()
    ts_iso = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    meta = RecordMeta(
        timestamp_local_iso=ts_iso,
        timestamp_local_ms=now,
        symbol=meta_dict["symbol"],
        timeframe=meta_dict["timeframe"],
        bar_count=meta_dict["bar_count"],
        ai_provider={"model": "claude-copilot-cli", "base_url": "local", "thinking": True},
        decision_stance="balanced",
    )

    record = AnalysisRecord(
        meta=meta,
        kline_data=meta_dict.get("kline_data", []),
        htf_text="",
        stage1_messages=meta_dict.get("stage1_messages", []),
        stage1_response={"content": "", "reasoning_content": ""},
        stage1_diagnosis=stage1_json.get("stage1_diagnosis", {}),
        stage2_messages=meta_dict.get("stage2_messages", []),
        stage2_response={"content": "", "reasoning_content": ""},
        stage2_decision=stage2_json,
        strategy_files_used=meta_dict.get("strategy_files", []),
        experience_loaded=meta_dict.get("experience_loaded", []),
        exception=None,
        usage_total={"model": "claude-copilot-cli", "note": "via Copilot CLI skill"},
    )

    # Save
    RECORDS_PENDING_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{ts_iso}_{meta_dict['symbol']}_{meta_dict['timeframe']}.json"
    save_path = RECORDS_PENDING_DIR / filename

    try:
        save_path.write_text(
            json.dumps(record.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        print(json.dumps({"error": f"Failed to save record: {exc}"}, ensure_ascii=False))
        sys.exit(1)

    print(json.dumps({
        "saved_path": str(save_path),
        "stage2_decision": stage2_json,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
