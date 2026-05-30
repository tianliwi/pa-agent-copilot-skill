"""Generate Chinese Markdown report with annotated candlestick chart, then convert to PDF.

Usage:
    python generate_report.py <frame_json_path> <stage1_json_path> <stage2_json_string>

Outputs JSON to stdout:
  - report_dir: directory containing all generated files
  - md_path: path to generated Markdown report
  - pdf_path: path to generated PDF report
  - chart_path: path to generated chart PNG
  - error: string if something went wrong
"""
from __future__ import annotations

import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

# Resolve repo root: helpers/ → pa-agent/ → skills/ → repo root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ── Chinese font setup ──────────────────────────────────────────────────────

_ZH_FONT_CONFIGURED = False


def _setup_zh_font() -> None:
    """Configure matplotlib to use a CJK font globally."""
    global _ZH_FONT_CONFIGURED
    if _ZH_FONT_CONFIGURED:
        return

    candidates = [
        "Microsoft YaHei", "SimHei", "SimSun", "NSimSun",
        "FangSong", "KaiTi", "DengXian",
        "PingFang SC", "Heiti SC", "STHeiti", "Hiragino Sans GB",
        "WenQuanYi Micro Hei", "Noto Sans CJK SC", "Noto Sans SC",
        "Source Han Sans SC",
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name] + plt.rcParams.get("font.sans-serif", [])
            plt.rcParams["axes.unicode_minus"] = False
            _ZH_FONT_CONFIGURED = True
            return


# ── Helpers ──────────────────────────────────────────────────────────────────

CYCLE_POSITION_ZH = {
    "spike": "尖峰", "micro_channel": "微型通道", "tight_channel": "紧凑通道",
    "normal_channel": "常规通道", "broad_channel": "宽通道/台阶",
    "trending_tr": "趋势型交易区间", "trading_range": "交易区间",
    "extreme_tr": "极端交易区间", "unknown": "未知",
}

DIRECTION_ZH = {"bullish": "多头", "bearish": "空头", "neutral": "中性"}

MARKET_PHASE_ZH = {"stable": "稳定", "transitioning": "转换中"}

ORDER_TYPE_ZH = {"限价单": "限价单", "突破单": "突破单", "市价单": "市价单", "不下单": "不下单"}


def text(value: Any, fallback: str = "N/A") -> str:
    """Extract a clean string from any value."""
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip() or fallback


def price_fmt(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return text(value)


def zh_cycle(value: Any) -> str:
    return CYCLE_POSITION_ZH.get(text(value, ""), text(value))


def zh_direction(value: Any) -> str:
    return DIRECTION_ZH.get(text(value, ""), text(value))


def zh_phase(value: Any) -> str:
    return MARKET_PHASE_ZH.get(text(value, ""), text(value))


def parse_seq(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    match = re.search(r"K(\d+)", str(value), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def bullet_list(values: Any) -> list[str]:
    if isinstance(values, list):
        return [text(v) for v in values if text(v, "")]
    if values:
        return [text(values)]
    return []


def extract_exchange(frame: dict, stage1: dict, stage2: dict) -> str:
    for src in (frame, stage1, stage2):
        v = src.get("exchange")
        if v:
            return text(v)
    meta = stage2.get("meta")
    if isinstance(meta, dict) and meta.get("exchange"):
        return text(meta["exchange"])
    return "N/A"


# ── Chart annotation helpers ────────────────────────────────────────────────

def chart_annotation_candidates(
    bars_by_seq: dict[int, dict],
    stage1: dict,
    stage2: dict | None = None,
) -> set[int]:
    """Return K-bar indices mentioned anywhere in the report data."""
    key_seqs: set[int] = set()

    # Collect from bar_by_bar_summary
    for item in (stage1.get("bar_by_bar_summary") or []):
        seq = parse_seq(item.get("bar_id") or item.get("bar"))
        if seq is not None:
            key_seqs.add(seq)

    # Scan all text fields in stage1 and stage2 for K-line references
    def _extract_k_refs(obj: Any) -> None:
        if isinstance(obj, str):
            for m in re.findall(r"K(\d+)", obj, re.I):
                seq = int(m)
                if seq in bars_by_seq:
                    key_seqs.add(seq)
        elif isinstance(obj, dict):
            for v in obj.values():
                _extract_k_refs(v)
        elif isinstance(obj, list):
            for v in obj:
                _extract_k_refs(v)

    _extract_k_refs(stage1)
    if stage2:
        _extract_k_refs(stage2)

    return key_seqs


# ── Chart generation (white background, green/red bars) ─────────────────────

def generate_chart(
    frame: dict,
    stage1: dict,
    stage2: dict,
    decision: dict,
    symbol: str,
    timeframe: str,
    exchange: str,
    chart_path: Path,
) -> None:
    bars = list(frame.get("bars") or [])
    ema_list = list((frame.get("indicators") or {}).get("ema20") or [])
    atr_list = list((frame.get("indicators") or {}).get("atr14") or [])
    if not bars:
        raise ValueError("Frame JSON does not contain bars")

    newest_first_bars = list(bars)
    bars.reverse()
    ema_list.reverse()
    atr_list.reverse()

    dates = [datetime.fromtimestamp(float(bar["ts_open"]) / 1000) for bar in bars]
    opens = np.array([float(bar["open"]) for bar in bars], dtype=float)
    highs = np.array([float(bar["high"]) for bar in bars], dtype=float)
    lows = np.array([float(bar["low"]) for bar in bars], dtype=float)
    closes = np.array([float(bar["close"]) for bar in bars], dtype=float)
    volumes = np.array([float(bar.get("volume", 0.0)) for bar in bars], dtype=float)
    seqs = [int(bar["seq"]) for bar in bars]
    x = np.arange(len(bars))

    ema_points = [(i, float(v)) for i, v in enumerate(ema_list[:len(bars)]) if v is not None]
    atr_points = [(i, float(v)) for i, v in enumerate(atr_list[:len(bars)]) if v is not None]

    bars_by_seq = {int(bar["seq"]): bar for bar in newest_first_bars}
    key_seqs = chart_annotation_candidates(bars_by_seq, stage1, stage2)

    max_price, min_price = float(np.max(highs)), float(np.min(lows))
    price_range = max(max_price - min_price, 1e-6)
    annotation_offset = price_range * 0.03

    _setup_zh_font()

    # --- Create figure: white background ---
    fig = plt.figure(figsize=(20, 14), facecolor="white")
    gs = fig.add_gridspec(3, 1, height_ratios=[4, 1, 1], hspace=0.08)
    ax_price = fig.add_subplot(gs[0])
    ax_volume = fig.add_subplot(gs[1], sharex=ax_price)
    ax_atr = fig.add_subplot(gs[2], sharex=ax_price)

    for ax in (ax_price, ax_volume, ax_atr):
        ax.set_facecolor("white")
        ax.grid(True, alpha=0.25, color="#cccccc", linestyle="--")
        for spine in ax.spines.values():
            spine.set_color("#bbbbbb")
        ax.tick_params(colors="#333333", labelsize=8)

    title = f"{symbol}  {timeframe.upper()}  |  价格行为分析  |  {exchange}"
    ax_price.set_title(title, fontsize=16, fontweight="bold", color="#222222", pad=12)

    # --- Candlesticks ---
    bull_color, bear_color = "#22ab55", "#e23636"
    width = 0.6
    for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes)):
        color = bull_color if c >= o else bear_color
        body = max(abs(c - o), price_range * 0.002)
        ax_price.bar(x[i], body, width, bottom=min(o, c), color=color, edgecolor=color, linewidth=0.5, zorder=3)
        ax_price.vlines(x[i], l, h, color=color, linewidth=0.8, zorder=2)

    # --- EMA20 ---
    if ema_points:
        ax_price.plot([p[0] for p in ema_points], [p[1] for p in ema_points],
                      color="#e6a817", linewidth=1.8, label="EMA20", zorder=4)

    # --- K-line sequence labels ---
    seq_to_index = {seq: idx for idx, seq in enumerate(seqs)}
    for seq in sorted(key_seqs):
        idx = seq_to_index.get(seq)
        if idx is None:
            continue
        ax_price.annotate(
            f"K{seq}", xy=(x[idx], lows[idx]),
            xytext=(x[idx], lows[idx] - annotation_offset),
            fontsize=10, color="#444444", ha="center", fontweight="bold",
            arrowprops=dict(arrowstyle="-", color="#999999", linewidth=0.4),
        )

    # --- Entry / Stop / Target lines ---
    entry = decision.get("entry_price")
    stop = decision.get("stop_loss_price")
    target = decision.get("take_profit_price")
    for level, color, label in ((entry, "#0088ff", "入场"), (stop, "#e23636", "止损"), (target, "#22ab55", "止盈")):
        if level is None:
            continue
        lv = float(level)
        ax_price.axhline(y=lv, color=color, linestyle="--", linewidth=1.2, alpha=0.85, label=f"{label} {price_fmt(lv)}")

    # --- Risk / reward shading ---
    direction = text(decision.get("order_direction"), "").lower()
    if entry is not None and stop is not None and target is not None:
        ev, sv, tv = float(entry), float(stop), float(target)
        if "short" in direction or "bear" in direction or "空" in direction:
            ax_price.axhspan(ev, sv, alpha=0.06, color="#e23636")
            ax_price.axhspan(tv, ev, alpha=0.06, color="#22ab55")
        else:
            ax_price.axhspan(sv, ev, alpha=0.06, color="#e23636")
            ax_price.axhspan(ev, tv, alpha=0.06, color="#22ab55")

    legend = ax_price.legend(loc="upper left", fontsize=9, facecolor="white", edgecolor="#cccccc")
    ax_price.set_ylabel("价格", fontsize=11, color="#333333")

    # --- Volume ---
    vol_colors = [bull_color if closes[i] >= opens[i] else bear_color for i in range(len(bars))]
    ax_volume.bar(x, volumes / 1e6, width, color=vol_colors, alpha=0.7)
    ax_volume.set_ylabel("成交量(M)", fontsize=10, color="#333333")

    # --- ATR14 ---
    if atr_points:
        ax_atr.fill_between([p[0] for p in atr_points], [p[1] for p in atr_points],
                            alpha=0.3, color="#8888dd")
        ax_atr.plot([p[0] for p in atr_points], [p[1] for p in atr_points],
                    color="#6666bb", linewidth=1.2, label="ATR14")
        ax_atr.legend(loc="upper left", fontsize=8, facecolor="white", edgecolor="#cccccc")
    ax_atr.set_ylabel("ATR14", fontsize=10, color="#333333")

    # --- X axis date labels ---
    tick_positions = list(range(0, len(dates), max(1, len(dates) // 10)))
    if tick_positions[-1] != len(dates) - 1:
        tick_positions.append(len(dates) - 1)
    ax_atr.set_xticks(tick_positions)
    ax_atr.set_xticklabels([dates[i].strftime("%m/%d") for i in tick_positions], rotation=45, fontsize=8)
    plt.setp(ax_price.get_xticklabels(), visible=False)
    plt.setp(ax_volume.get_xticklabels(), visible=False)

    fig.savefig(str(chart_path), dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ── Markdown report generation (Chinese) ────────────────────────────────────

def generate_markdown(
    frame: dict,
    stage1: dict,
    stage2: dict,
    decision: dict,
    symbol: str,
    timeframe: str,
    exchange: str,
    chart_path: Path,
    report_path: Path,
) -> None:
    bars = list(frame.get("bars") or [])
    bar_count = len(bars)
    newest_bar = bars[0] if bars else {}
    report_ts = float(newest_bar.get("ts_open", datetime.now().timestamp() * 1000)) / 1000
    report_date = datetime.fromtimestamp(report_ts).strftime("%Y-%m-%d %H:%M")

    cycle = zh_cycle(stage1.get("cycle_position"))
    alt_cycle = zh_cycle(stage1.get("alternative_cycle_position"))
    direction_str = zh_direction(stage1.get("direction"))
    confidence = stage1.get("diagnosis_confidence", "N/A")
    phase = zh_phase(stage1.get("market_phase"))
    always_in = text((stage1.get("bar_analysis") or {}).get("always_in"))
    gate = text(stage1.get("gate_result"))

    order_type = text(decision.get("order_type"), "不下单")
    order_dir = decision.get("order_direction")
    entry_price = decision.get("entry_price")
    stop_price = decision.get("stop_loss_price")
    target_price = decision.get("take_profit_price")
    trade_conf = decision.get("trade_confidence", "N/A")
    win_rate = decision.get("estimated_win_rate")
    diag_conf = decision.get("diagnosis_confidence", confidence)

    # Compute R:R
    rr_str = "N/A"
    if entry_price is not None and stop_price is not None and target_price is not None:
        ev, sv, tv = float(entry_price), float(stop_price), float(target_price)
        risk = abs(ev - sv)
        reward = abs(tv - ev)
        if risk > 0:
            rr_str = f"{reward / risk:.2f}:1"

    # Use relative path for chart image
    chart_rel = chart_path.name

    lines: list[str] = []
    w = lines.append  # shorthand

    # ── Header ───────────────────────────────────────────────────────────
    w(f"# 📊 {symbol} {timeframe.upper()} 价格行为分析报告")
    w("")
    w(f"> **交易所**: {exchange}　|　**K线数量**: {bar_count}　|　**数据截至**: {report_date}")
    w("")
    w(f"![{symbol} K线图]({chart_rel})")
    w("")

    # ── Section 1: 当前市场分析 ──────────────────────────────────────────
    w("---")
    w("")
    w("## 一、当前市场分析")
    w("")

    w("### 诊断概览")
    w("")
    w(f"| 指标 | 值 |")
    w(f"|------|------|")
    w(f"| 周期位置 | **{cycle}**（备选：{alt_cycle}） |")
    w(f"| 方向偏好 | **{direction_str}** |")
    w(f"| 诊断置信度 | {confidence}/100 |")
    w(f"| 市场阶段 | {phase} |")
    w(f"| Always In | {always_in} |")
    w(f"| 闸门结果 | {'✅ 通过' if gate == 'proceed' else '⏸️ 等待' if gate == 'wait' else gate} |")
    w("")

    # HTF context
    htf = text(stage1.get("htf_context"), "")
    if htf:
        w("### 高时间框架背景")
        w("")
        w(f"> {htf}")
        w("")

    # Key signals
    key_signals = bullet_list(stage1.get("key_signals"))
    if key_signals:
        w("### 关键信号")
        w("")
        for sig in key_signals:
            w(f"- {sig}")
        w("")

    # Reasoning
    reasoning = text(decision.get("reasoning"), "")
    if reasoning:
        w("### 分析推理")
        w("")
        w(reasoning)
        w("")

    # Bar-by-bar summary
    bar_summary = stage1.get("bar_by_bar_summary") or []
    if bar_summary:
        w("### 逐K分析摘要")
        w("")
        w("| K线 | 说明 |")
        w("|------|------|")
        for item in bar_summary:
            bar_id = text(item.get("bar_id") or item.get("bar"), "?")
            reason = text(item.get("reason"), "").replace("|", "\\|")
            w(f"| {bar_id} | {reason} |")
        w("")

    # ── Section 2: 市场预测 ──────────────────────────────────────────────
    w("---")
    w("")
    w("## 二、市场预测")
    w("")

    next_bar = decision.get("next_bar_prediction") or {}
    if isinstance(next_bar, dict) and next_bar:
        scenario_bull = text(next_bar.get("scenario_bull"), "")
        scenario_bear = text(next_bar.get("scenario_bear"), "")
        scenario_neutral = text(next_bar.get("scenario_neutral"), "")

        if scenario_bull:
            w(f"**🟢 看涨情景**：{scenario_bull}")
            w("")
        if scenario_bear:
            w(f"**🔴 看跌情景**：{scenario_bear}")
            w("")
        if scenario_neutral:
            w(f"**⚪ 中性情景**：{scenario_neutral}")
            w("")

        # Also handle structured probability format
        prob = next_bar.get("probability") or next_bar.get("probabilities") or {}
        if prob:
            w(f"概率分布：看涨 {text(prob.get('bullish'), '?')}% / 看跌 {text(prob.get('bearish'), '?')}% / 中性 {text(prob.get('neutral'), '?')}%")
            w("")

        reasoning_nb = text(next_bar.get("reason") or next_bar.get("reasoning"), "")
        if reasoning_nb:
            w(f"> {reasoning_nb}")
            w("")
    else:
        w("当前数据尚不足以做出明确的下根K线预测，需等待更多价格行为确认。")
        w("")

    # Watch points
    watch_points = bullet_list(decision.get("watch_points")) or bullet_list(stage2.get("watch_points"))
    if watch_points:
        w("### 关注要点")
        w("")
        for wp in watch_points:
            w(f"- 👀 {wp}")
        w("")

    # ── Section 3: 潜在风险 ──────────────────────────────────────────────
    w("---")
    w("")
    w("## 三、潜在风险")
    w("")

    risk_assessment = text(decision.get("risk_assessment"), "") or text(stage2.get("risk_assessment"), "")
    if risk_assessment:
        w(risk_assessment)
        w("")

    risk_warning = text(stage1.get("risk_warning"), "")
    if risk_warning:
        w(f"> ⚠️ **风险预警**：{risk_warning}")
        w("")

    transition_risk = text(stage1.get("transition_risk"), "")
    if transition_risk and transition_risk not in ("null", "None"):
        w(f"- **转换风险等级**：{transition_risk}")
        w("")

    invalidation = text(decision.get("invalidation_condition"), "") or text(decision.get("invalidation"), "") or text(stage2.get("invalidation"), "")
    if invalidation:
        w(f"- **失效条件**：{invalidation}")
        w("")

    # Key factors
    key_factors = bullet_list(decision.get("key_factors")) or bullet_list(stage2.get("key_factors"))
    if key_factors:
        w("### 关键风险因素")
        w("")
        for kf in key_factors:
            w(f"- ⚡ {kf}")
        w("")

    # ── Section 4: 交易建议 ──────────────────────────────────────────────
    w("---")
    w("")
    w("## 四、交易建议")
    w("")

    if order_type == "不下单":
        w("### 🚫 建议：暂不交易")
        w("")
    else:
        dir_emoji = "🟢" if order_dir and ("long" in order_dir.lower() or "bull" in order_dir.lower()) else "🔴"
        w(f"### {dir_emoji} 建议：{order_type}")
        w("")

    w("| 项目 | 值 |")
    w("|------|------|")
    w(f"| 下单类型 | {order_type} |")
    w(f"| 方向 | {text(order_dir, '无')} |")
    w(f"| 入场价 | {price_fmt(entry_price)} |")
    w(f"| 止损价 | {price_fmt(stop_price)} |")
    w(f"| 止盈价 | {price_fmt(target_price)} |")
    w(f"| 风险收益比 | {rr_str} |")
    w(f"| 交易置信度 | {trade_conf}/100 |")
    w(f"| 胜率估计 | {text(win_rate, 'N/A')}{'%' if win_rate is not None else ''} |")
    w(f"| 诊断置信度 | {diag_conf}/100 |")
    w("")

    # Trade confidence reasoning
    tc_reasoning = text(decision.get("trade_confidence_reasoning"), "")
    if tc_reasoning:
        w("### 置信度分析")
        w("")
        w(tc_reasoning)
        w("")

    # Terminal
    terminal = stage2.get("terminal") or {}
    terminal_outcome = text(terminal.get("outcome"), "")
    terminal_reason = text(terminal.get("reason"), "")
    next_step = text(terminal.get("next_step"), "")
    if terminal_outcome:
        outcome_zh = {"wait": "⏸️ 等待", "trade": "✅ 交易", "reject": "❌ 拒绝"}.get(terminal_outcome, terminal_outcome)
        w(f"### 决策结论：{outcome_zh}")
        w("")
        if terminal_reason:
            w(f"> {terminal_reason}")
            w("")
        if next_step:
            w(f"**下一步**：{next_step}")
            w("")

    # ── Footer ───────────────────────────────────────────────────────────
    w("---")
    w("")
    w(f"*报告由 PA Agent 自动生成 | {datetime.now().strftime('%Y-%m-%d %H:%M')}*")

    report_path.write_text("\n".join(lines), encoding="utf-8")


# ── MD → PDF conversion ─────────────────────────────────────────────────────

def md_to_pdf(md_path: Path, pdf_path: Path, chart_path: Path) -> None:
    """Convert Markdown file to PDF via playwright Chromium."""
    import base64
    import markdown as md_lib
    from playwright.sync_api import sync_playwright

    md_text = md_path.read_text(encoding="utf-8")

    # Embed chart as base64 so PDF can render it
    if chart_path.exists():
        img_b64 = base64.b64encode(chart_path.read_bytes()).decode("ascii")
        md_text = re.sub(
            r"!\[[^\]]*\]\([^)]*\)",
            f'<img src="data:image/png;base64,{img_b64}" style="width:100%"/>',
            md_text,
        )

    html_body = md_lib.markdown(md_text, extensions=["tables", "extra"])
    # Wrap with minimal page structure and CJK font
    full_html = (
        "<html><head><meta charset='utf-8'/>"
        "<style>"
        "body{font-family:'Microsoft YaHei',SimHei,sans-serif;margin:20px;font-size:13px;line-height:1.7;color:#222}"
        "table{border-collapse:collapse;width:100%;margin:12px 0;font-size:12px}"
        "th,td{border:1px solid #bbb;padding:6px 10px;text-align:left}"
        "th{background:#e8f0e8;font-weight:bold}"
        "blockquote{border-left:4px solid #2ecc71;background:#f0faf0;padding:10px 16px;margin:12px 0}"
        "img{max-width:100%}"
        "h1{color:#1a5276;border-bottom:2px solid #1a5276;padding-bottom:8px}"
        "h2{color:#1a6e3a;margin-top:28px}"
        "hr{border:none;border-top:1px solid #ddd;margin:20px 0}"
        "</style></head>"
        f"<body>{html_body}</body></html>"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(full_html, wait_until="networkidle")
        page.pdf(path=str(pdf_path), format="A4", print_background=True,
                 margin={"top":"18mm","bottom":"18mm","left":"14mm","right":"14mm"})
        browser.close()


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 4:
        print(json.dumps({"error": "Usage: generate_report.py <frame_json_path> <stage1_json_path> <stage2_json_string>"}))
        sys.exit(1)

    try:
        frame_path = Path(sys.argv[1])
        stage1_path = Path(sys.argv[2])
        stage2_raw = sys.argv[3]

        frame = json.loads(frame_path.read_text(encoding="utf-8"))
        stage1_data = json.loads(stage1_path.read_text(encoding="utf-8-sig"))
        stage1 = stage1_data.get("stage1_diagnosis", stage1_data)
        stage2 = json.loads(stage2_raw)
        decision = stage2.get("decision", {})

        symbol = text(frame.get("symbol"), "UNKNOWN")
        timeframe = text(frame.get("timeframe"), "")
        exchange = extract_exchange(frame, stage1_data, stage2)

        # Output directory: REPO_ROOT/records/{timestamp}_{symbol}_{timeframe}/
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_dir = REPO_ROOT / "records" / f"{timestamp}_{symbol}_{timeframe}"
        report_dir.mkdir(parents=True, exist_ok=True)

        chart_path = report_dir / f"pa_chart_{symbol.lower()}.png"
        md_path = report_dir / f"PA_Report_{symbol}_{timeframe}.md"
        pdf_path = report_dir / f"PA_Report_{symbol}_{timeframe}.pdf"

        generate_chart(frame, stage1, stage2, decision, symbol, timeframe, exchange, chart_path)
        generate_markdown(frame, stage1, stage2, decision, symbol, timeframe, exchange, chart_path, md_path)
        md_to_pdf(md_path, pdf_path, chart_path)

        print(json.dumps({
            "report_dir": str(report_dir),
            "md_path": str(md_path),
            "pdf_path": str(pdf_path),
            "chart_path": str(chart_path),
        }, ensure_ascii=False))
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
