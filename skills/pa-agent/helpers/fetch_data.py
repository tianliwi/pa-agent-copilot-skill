"""Fetch K-line data from TradingView and build Stage 1 prompt.

Usage:
    python fetch_data.py <symbol> <timeframe> [exchange] [bar_count]

Outputs JSON to stdout with keys:
  - stage1_messages: list of {role, content} for the Stage 1 prompt
  - kline_data: serialised bar data
  - frame: serialised KlineFrame for stage2 bridge
  - symbol, timeframe, exchange, bar_count: echo back
  - error: string if something went wrong

Requires PA_Agent's venv and modules.
"""
from __future__ import annotations

import json
import logging
import sys
import io
from pathlib import Path

# Force UTF-8 stdout on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Suppress noisy tvdatafeed logs on stderr
logging.basicConfig(level=logging.WARNING)

# Resolve repo root: helpers/ → pa-agent/ → skills/ → repo root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import dataclasses
from pa_agent.config.paths import PROMPT_DIR
from pa_agent.data.tradingview import TradingViewSource
from pa_agent.data.snapshot import build_analysis_frame, INDICATOR_WARMUP_BARS
from pa_agent.ai.prompt_assembler import PromptAssembler


def main() -> None:
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: fetch_data.py <symbol> <timeframe> [exchange] [bar_count]"}))
        sys.exit(1)

    symbol = sys.argv[1]
    timeframe = sys.argv[2]
    exchange = sys.argv[3] if len(sys.argv) > 3 else "OANDA"
    bar_count = int(sys.argv[4]) if len(sys.argv) > 4 else 100

    # Fetch data via TradingView
    try:
        source = TradingViewSource()
        source.set_exchange(exchange)
        source.connect()
        source.subscribe(symbol, timeframe)
        # Fetch extra bars for indicator warmup
        raw_bars = source.latest_snapshot(bar_count + INDICATOR_WARMUP_BARS)
        source.disconnect()
    except Exception as exc:
        print(json.dumps({"error": f"Data fetch failed: {exc}"}, ensure_ascii=False))
        sys.exit(1)

    if not raw_bars:
        print(json.dumps({"error": "No data returned from TradingView"}, ensure_ascii=False))
        sys.exit(1)

    # Build analysis frame (closed bars only, with indicators)
    frame = build_analysis_frame(raw_bars, bar_count, symbol, timeframe)
    if frame is None:
        print(json.dumps({"error": f"Not enough closed bars (need {bar_count}, got fewer)"}, ensure_ascii=False))
        sys.exit(1)

    # Build Stage 1 messages
    assembler = PromptAssembler(PROMPT_DIR)
    messages = assembler.build_stage1(frame)

    # Serialise kline data for record-keeping
    kline_data = []
    for bar in frame.bars:
        if dataclasses.is_dataclass(bar) and not isinstance(bar, type):
            kline_data.append(dataclasses.asdict(bar))
        else:
            kline_data.append(bar.__dict__)

    # Serialise frame for stage2 bridge
    frame_dict = {
        "symbol": frame.symbol,
        "timeframe": frame.timeframe,
        "bars": kline_data,
        "indicators": {
            "ema20": list(frame.indicators.ema20),
            "atr14": list(frame.indicators.atr14),
        },
    }

    result = {
        "stage1_messages": messages,
        "kline_data": kline_data,
        "frame": frame_dict,
        "symbol": symbol,
        "timeframe": timeframe,
        "exchange": exchange,
        "bar_count": len(frame.bars),
    }

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
