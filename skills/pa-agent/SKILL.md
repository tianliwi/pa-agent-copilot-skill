---
name: pa-agent
description: PA Agent 价格行为分析 Skill。对任何交易品种执行两阶段 AI 分析（市场诊断 → 交易决策），使用 PA_Agent 的完整提示词工程和策略文件体系。触发词包括：analyze、analysis、分析、price action、PA、K线、kline，后跟品种名和周期。例如"analyze XAUUSD 15m"、"分析黄金15分钟"、"分析 MSFT 1d on NASDAQ"。即使用户只说"帮我看看XAUUSD"或"分析一下这个品种"，只要上下文涉及交易/K线/价格行为，也应触发。不要用于与交易分析无关的请求。
---

# PA Agent — 价格行为两阶段分析 Skill

通过 TradingView 获取 K 线数据，使用 PA_Agent 的完整提示词体系执行两阶段分析（Stage 1 市场诊断 → Stage 2 交易决策），Claude 直接作为分析 AI，无 token 限制。

## 路径约定

本 Skill 所有路径基于 **SKILL_DIR**（本 SKILL.md 所在目录）推算：

- **SKILL_DIR**: 本文件所在目录（`skills/pa-agent/`）
- **REPO_ROOT**: `SKILL_DIR/../../`（即仓库根目录）
- **HELPERS**: `SKILL_DIR/helpers/`
- **VENV_PYTHON**: `REPO_ROOT/venv/Scripts/python.exe`（Windows）或 `REPO_ROOT/venv/bin/python`（Linux/macOS）

> 在执行命令前，先确定 SKILL_DIR 的实际绝对路径，然后推算其他路径。

## 工作流程

### Step 0: 环境自检（首次运行自动执行）

检查 venv 是否存在，如果不存在则自动创建并安装依赖：

```powershell
# 确定 REPO_ROOT（从 SKILL_DIR 向上两级）
# 检查 venv 是否存在
if (-not (Test-Path "$REPO_ROOT\venv")) {
    Write-Host "首次运行，正在创建虚拟环境并安装依赖..."
    python -m venv "$REPO_ROOT\venv"
    & "$REPO_ROOT\venv\Scripts\pip.exe" install -e "$REPO_ROOT" --quiet
}
```

Linux/macOS 下：
```bash
if [ ! -d "$REPO_ROOT/venv" ]; then
    python3 -m venv "$REPO_ROOT/venv"
    "$REPO_ROOT/venv/bin/pip" install -e "$REPO_ROOT" --quiet
fi
```

### Step 1: 解析用户输入

从用户的自然语言中提取：
- **symbol**: 交易品种代码（如 XAUUSD, MSFT, AAPL, EURUSD）
- **timeframe**: 周期（如 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w）
- **exchange**: 交易所（默认 OANDA；股票用 NASDAQ/NYSE；如用户指定则用指定值）
- **bar_count**: K 线数量（默认 100）

常见品种-交易所映射：
- 黄金/XAUUSD → OANDA
- 外汇对 (EURUSD, GBPUSD 等) → OANDA
- 美股 (MSFT, AAPL, TSLA 等) → NASDAQ 或 NYSE
- A股 → 用 SSE 或 SZSE

### Step 2: 获取数据并构建 Stage 1 提示词

运行 Python helper 脚本获取 K 线数据并构建 Stage 1 消息：

```powershell
cd $REPO_ROOT; .\venv\Scripts\python.exe $HELPERS\fetch_data.py <symbol> <timeframe> [exchange] [bar_count]
```

这会输出一个 JSON，包含 `stage1_messages`（消息列表）和 `frame`（序列化的 K 线数据）。

**关键**：将 `frame` 保存到临时 JSON 文件供后续步骤使用：
```powershell
# 解析输出，将 frame 部分写入临时文件
```

### Step 3: 执行 Stage 1 分析（你自己做）

从 `stage1_messages` 中提取 system 和 user 消息内容。**你就是分析 AI**。

仔细阅读 system prompt（包含人设、PA 术语、闸门决策树）和 user prompt（包含 K 线数据表、几何特征表、输出格式要求），然后：

1. 按照提示词中的要求进行逐 K 分析
2. 执行 §0-§2 闸门判断（gate_trace）
3. **直接输出完整的阶段一诊断 JSON**（裸 JSON，不要 markdown 围栏）

阶段一 JSON 必须包含：cycle_position, direction, diagnosis_confidence, bar_analysis, bar_by_bar_summary, gate_trace, gate_result 等必填字段。

### Step 4: 验证 Stage 1 并构建 Stage 2 提示词

将你的 Stage 1 JSON 输出传给验证脚本：

```powershell
cd $REPO_ROOT; .\venv\Scripts\python.exe $HELPERS\bridge_stage2.py <frame_json_path> '<stage1_json_string>'
```

如果验证通过，输出包含 `stage2_messages`。如果验证失败，查看错误信息并修正你的 Stage 1 JSON。

### Step 5: 执行 Stage 2 分析（你自己做）

从 `stage2_messages` 中提取 system 和 user 消息内容。

仔细阅读 Stage 2 的 system prompt（人设 + 完整二元决策树）和 user prompt（交易倾向、策略文件、阶段一诊断、K 线数据、输出格式），然后：

1. 按 §3-§11, §14 执行完整决策路径
2. 评估入场信号（§9）、风险收益（§10）、下单方式（§11）
3. **直接输出完整的阶段二决策 JSON**

### Step 6: 验证并保存记录

```powershell
cd $REPO_ROOT; .\venv\Scripts\python.exe $HELPERS\save_record.py <meta_json_path> <stage1_json_path> '<stage2_json_string>'
```

### Step 7: 向用户展示结果

用清晰的中文向用户展示分析结果：

1. **市场诊断**：周期位置、方向、诊断置信度
2. **闸门结果**：是否通过（proceed/wait/unknown）
3. **交易决策**：
   - 下单方向和类型（或不下单）
   - 入场价、止损价、止盈价
   - 风险收益比
   - 交易置信度和胜率估计
4. **关键因素**和**注意事项**
5. **记录保存路径**

## 错误处理

- 数据获取失败：告知用户检查品种代码和交易所是否正确
- Stage 1 验证失败：自动修正并重试（最多 2 次）
- Stage 2 验证失败：向用户报告哪些字段有问题
- 如果 gate_result 不是 proceed，告知用户市场状态不适合交易，跳过 Stage 2

## 注意事项

- 所有思考过程和 JSON 说明必须使用**简体中文**
- JSON 输出必须是裸 JSON（不要 markdown 围栏）
- gate_trace 和 decision_trace 中的 bar_range 必须由你据实填写
- 严格遵守 PA_Agent 提示词中的所有硬约束和枚举限制
