---
name: pa-agent
description: PA Agent 价格行为分析 Skill。对任何交易品种执行两阶段 AI 分析（市场诊断 → 交易决策），使用 PA_Agent 的完整提示词工程和策略文件体系。触发词包括：analyze、analysis、分析、price action、PA、K线、kline，后跟品种名和周期。例如"analyze XAUUSD 15m"、"分析黄金15分钟"、"分析 MSFT 1d on NASDAQ"。即使用户只说"帮我看看XAUUSD"或"分析一下这个品种"，只要上下文涉及交易/K线/价格行为，也应触发。不要用于与交易分析无关的请求。
---

# PA Agent — 价格行为两阶段分析 Skill

通过 TradingView 获取 K 线数据，使用 PA_Agent 的完整提示词体系执行两阶段分析（Stage 1 市场诊断 → Stage 2 交易决策），Claude 直接作为分析 AI，无 token 限制。

## 路径约定

本 Skill 需要完整的仓库代码（pa_agent 包、prompt_engineering 等），而非仅 SKILL.md 自身。

- **REPO_ROOT**: 仓库克隆位置，默认 `~/.pa-agent-repo`（可通过环境变量 `PA_AGENT_REPO` 覆盖）
- **HELPERS**: `REPO_ROOT/skills/pa-agent/helpers/`
- **VENV_PYTHON**: `REPO_ROOT/venv/Scripts/python.exe`（Windows）或 `REPO_ROOT/venv/bin/python`（Linux/macOS）

## 工作流程

### Step 0: 环境自检（首次运行自动执行）

检查仓库和 venv 是否就绪。优先使用已有的仓库路径（插件安装目录或环境变量），仅在找不到时才克隆：

```powershell
# Windows — 按优先级查找 REPO_ROOT
if ($env:PA_AGENT_REPO) {
    $REPO_ROOT = $env:PA_AGENT_REPO
} else {
    # 1) 检查插件安装目录（gh skill install / plugin marketplace）
    $pluginDir = Get-ChildItem "$env:USERPROFILE\.copilot\installed-plugins\*\pa-agent-copilot-skill\pa_agent" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pluginDir) {
        $REPO_ROOT = $pluginDir.Parent.FullName
    }
    # 2) 检查个人 skill 目录的上级（手动安装可能把整个仓库放在 skills 同级）
    elseif (Test-Path "$env:USERPROFILE\.copilot\skills\pa-agent\helpers") {
        # 个人 skill 只有 skill 文件夹，仍需完整仓库
        $REPO_ROOT = "$env:USERPROFILE\.pa-agent-repo"
    }
    else {
        $REPO_ROOT = "$env:USERPROFILE\.pa-agent-repo"
    }
}

# 只在没有 pa_agent 包时才克隆
if (-not (Test-Path "$REPO_ROOT\pa_agent")) {
    Write-Host "首次运行，正在克隆仓库..."
    git clone https://github.com/tianliwi/pa-agent-copilot-skill.git $REPO_ROOT
}

if (-not (Test-Path "$REPO_ROOT\venv")) {
    Write-Host "正在创建虚拟环境并安装依赖..."
    python -m venv "$REPO_ROOT\venv"
    & "$REPO_ROOT\venv\Scripts\pip.exe" install -e "$REPO_ROOT" --quiet
    & "$REPO_ROOT\venv\Scripts\pip.exe" install matplotlib numpy fpdf2 --quiet
}
```

Linux/macOS 下：
```bash
if [ -n "$PA_AGENT_REPO" ]; then
    REPO_ROOT="$PA_AGENT_REPO"
else
    # 1) Check plugin install directory
    PLUGIN_DIR=$(find "$HOME/.copilot/installed-plugins" -maxdepth 2 -name "pa-agent-copilot-skill" -type d 2>/dev/null | head -1)
    if [ -d "$PLUGIN_DIR/pa_agent" ]; then
        REPO_ROOT="$PLUGIN_DIR"
    else
        REPO_ROOT="$HOME/.pa-agent-repo"
    fi
fi

if [ ! -d "$REPO_ROOT/pa_agent" ]; then
    git clone https://github.com/tianliwi/pa-agent-copilot-skill.git "$REPO_ROOT"
fi

if [ ! -d "$REPO_ROOT/venv" ]; then
    python3 -m venv "$REPO_ROOT/venv"
    "$REPO_ROOT/venv/bin/pip" install -e "$REPO_ROOT" --quiet
    "$REPO_ROOT/venv/bin/pip" install matplotlib numpy fpdf2 --quiet
fi
```

> **优先级**：`PA_AGENT_REPO` 环境变量 > 插件安装目录 > `~/.pa-agent-repo`（最后才 clone）。
> 如果你已有本地克隆（如 `C:\playground\pa-agent-copilot-skill`），设置 `PA_AGENT_REPO` 指向它即可。

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

### Step 8: 生成英文 PDF 报告

运行报告生成脚本，自动生成带 K 线图和分析内容的 PDF 报告：

```powershell
cd $REPO_ROOT; .\venv\Scripts\python.exe $HELPERS\generate_report.py <frame_json_path> <stage1_json_path> '<stage2_json_string>'
```

Linux/macOS：
```bash
cd $REPO_ROOT && "$REPO_ROOT/venv/bin/python" "$HELPERS/generate_report.py" <frame_json_path> <stage1_json_path> '<stage2_json_string>'
```

参数说明：
- `frame_json_path`：Step 2 中保存的 frame 临时 JSON 文件路径
- `stage1_json_path`：Step 3/4 中保存的 Stage 1 诊断 JSON 文件路径
- `stage2_json_string`：Step 5 中生成的 Stage 2 决策 JSON 字符串（裸 JSON）

输出 JSON 到 stdout：
```json
{"pdf_path": "/path/to/PA_Report_SYMBOL_TIMEFRAME.pdf", "chart_path": "/path/to/pa_chart_symbol.png"}
```

报告内容包括：
- **封面 + K 线图**：暗色主题蜡烛图，标注 K 线编号、关键结构位、EMA20、交易水平线（入场/止损/止盈）
- **Stage 1 诊断**：周期位置、方向、置信度、HTF 上下文、关键信号、风险提示
- **Stage 2 决策**：交易方向/类型、入场/止损/止盈、风险收益计算、推理依据、关键因素、注意事项
- **逐 K 分析**：bar_by_bar_summary 全部条目 + 闸门轨迹
- **下根 K 线预测 + 决策轨迹**

> **依赖**：首次运行前需安装 `matplotlib`、`numpy`、`fpdf2`。在 Step 0 的 venv 安装后追加：
> ```powershell
> & "$REPO_ROOT\venv\Scripts\pip.exe" install matplotlib numpy fpdf2 --quiet
> ```

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
