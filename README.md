# PA Agent Copilot Skill

Two-stage Price Action analysis skill for GitHub Copilot CLI, based on Al Brooks' methodology.

## What it does

Fetches K-line data from TradingView, performs two-stage AI analysis:
- **Stage 1**: Market diagnosis (cycle position, direction, gate checks)
- **Stage 2**: Trading decision (entry/stop/target, risk-reward, trader's equation)

## Installation

Install as a Copilot CLI skill:

```
/install <github-user>/pa-agent-copilot-skill
```

On first use, the skill will auto-create a Python virtual environment and install dependencies.

## Usage

After installation, trigger with natural language:

```
analyze XAUUSD 15m
分析黄金15分钟
analyze MSFT 1d on NASDAQ
```

## Requirements

- Python 3.11+
- Internet access (for TradingView data)

## License

MIT
