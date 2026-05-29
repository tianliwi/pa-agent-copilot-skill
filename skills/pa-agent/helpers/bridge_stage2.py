"""Validate Stage 1 JSON and build Stage 2 prompt.

Usage:
    python bridge_stage2.py <frame_json_path> <stage1_json_string>

Reads:
  - frame_json_path: path to a JSON file containing the serialised KlineFrame
  - stage1_json_string: the raw Stage 1 JSON output from Claude

Outputs JSON to stdout with keys:
  - stage2_messages: list of {role, content} for the Stage 2 prompt
  - stage1_diagnosis: validated Stage 1 dict
  - strategy_files: list of routed strategy file names
  - validation_error: string if Stage 1 validation failed
  - error: string if something else went wrong
"""
from __future__ import annotations

import json
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Resolve repo root: helpers/ → pa-agent/ → skills/ → repo root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pa_agent.config.paths import PROMPT_DIR, EXPERIENCE_DIR
from pa_agent.data.base import KlineBar, KlineFrame, IndicatorBundle
from pa_agent.ai.prompt_assembler import PromptAssembler
from pa_agent.ai.json_validator import JsonValidator, Ok, ValidationError
from pa_agent.ai.router import route_strategy_files
from pa_agent.records.experience_reader import ExperienceReader


def _reconstruct_frame(frame_dict: dict) -> KlineFrame:
    """Rebuild a KlineFrame from the serialised dict."""
    bars = [KlineBar(**b) for b in frame_dict["bars"]]
    indicators = IndicatorBundle(
        ema20=tuple(frame_dict["indicators"]["ema20"]),
        atr14=tuple(frame_dict["indicators"]["atr14"]),
    )
    return KlineFrame(
        symbol=frame_dict["symbol"],
        timeframe=frame_dict["timeframe"],
        bars=tuple(bars),
        indicators=indicators,
        snapshot_ts_local_ms=0,
    )


def main() -> None:
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: bridge_stage2.py <frame_json_path> <stage1_json_string>"}))
        sys.exit(1)

    frame_path = Path(sys.argv[1])
    stage1_raw = sys.argv[2]

    # Load frame
    try:
        frame_dict = json.loads(frame_path.read_text(encoding="utf-8"))
        frame = _reconstruct_frame(frame_dict)
    except Exception as exc:
        print(json.dumps({"error": f"Failed to load frame: {exc}"}, ensure_ascii=False))
        sys.exit(1)

    # Validate Stage 1
    validator = JsonValidator()
    result = validator.validate("stage1", stage1_raw)

    if isinstance(result, ValidationError):
        print(json.dumps({
            "validation_error": f"Stage 1 validation failed [{result.category}]: {result.message}",
            "missing_fields": result.missing_fields,
            "invalid_fields": result.invalid_fields,
        }, ensure_ascii=False))
        sys.exit(1)

    stage1_json = result.obj

    # Route strategy files
    strategy_files = route_strategy_files(stage1_json)

    # Load experience entries
    try:
        exp_reader = ExperienceReader(EXPERIENCE_DIR)
        experience = exp_reader.read_top5(
            cycle_position=stage1_json.get("cycle_position", ""),
        )
        experience_dicts = [e.model_dump() if hasattr(e, "model_dump") else e for e in experience]
    except Exception:
        experience = []
        experience_dicts = []

    # Build Stage 2 messages
    assembler = PromptAssembler(PROMPT_DIR)
    messages = assembler.build_stage2(
        frame=frame,
        stage1_json=stage1_json,
        strategy_files=strategy_files,
        experience_entries=experience,
        decision_stance="balanced",
    )

    output = {
        "stage2_messages": messages,
        "stage1_diagnosis": stage1_json,
        "strategy_files": strategy_files,
        "experience_loaded": experience_dicts,
    }
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
