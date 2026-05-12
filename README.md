# Read Screen Tool

> 截图 → OCR/视觉 → 大模型流式输出 → 透明悬浮窗
>
> Screenshot → OCR/Vision → LLM Streaming → Transparent Overlay

[English](#english) | [中文](#中文)

---

## English

### What Is This

A Windows-only desktop tool that lets you screenshot any region of the screen, sends it to an LLM (via OpenAI-compatible API), and displays the response in a transparent overlay window.

**Key features:**

- Global hotkey screenshot selection
- OCR text extraction (EasyOCR) for non-vision models
- Direct image input for vision-capable models
- Streaming LLM response in a transparent frameless overlay
- Markdown rendering (bold, italic, code, headings, lists)
- Knowledge base tools (grep/read/write files)
- Web search via DuckDuckGo
- Session memory with automatic compression
- System tray integration

### Architecture

Signal-based modular design. All inter-module communication uses `signals.Signal`.

```
main.py (ReadScreenApp) — orchestrator, wires all signals
├── hotkey.py (HotkeyManager) — pynput global hotkeys
├── screenshot.py (ScreenshotOverlay) — tkinter fullscreen selection
├── ocr.py (OcrEngine) — EasyOCR wrapper, lazy-loaded
├── llm.py (LlmClient) — OpenAI API streaming + tool calling
├── session.py (ConversationSession) — message history + token counting
├── overlay.py (OutputOverlay) — transparent tkinter text overlay
├── tray.py (TrayManager) — pystray system tray
├── knowledge.py — tool definitions for LLM (grep/read/write)
├── web_search.py — DuckDuckGo web search tool
├── config.py — YAML config loading + dataclass validation
└── signals.py — Signal/SignalSpy primitives
```

**Signal flow:**

```
HotkeyManager.screenshot_requested
  → ScreenshotOverlay.start_selection
    → screenshot_taken
      → OCR (if non-vision model) or direct image
        → LlmClient.send
          → token_received → OutputOverlay.append_text
          → tool_call_requested → knowledge/web_search tools
          → response_complete
```

### Repo Structure

```
read-screen-tool/
├── main.py                 # Application entry point and orchestrator
├── config.py               # YAML config loading + dataclass validation
├── config.yaml.example     # Example configuration (copy to config.yaml)
├── hotkey.py               # Global hotkey management (pynput)
├── screenshot.py           # Fullscreen screenshot selection overlay
├── ocr.py                  # EasyOCR wrapper (lazy-loaded)
├── llm.py                  # OpenAI-compatible API client with streaming
├── session.py              # Conversation session + token counting
├── overlay.py              # Transparent frameless text overlay (tkinter)
├── tray.py                 # System tray icon (pystray)
├── knowledge.py            # Knowledge base tools (grep/read/write)
├── web_search.py           # DuckDuckGo web search tool
├── signals.py              # Lightweight signal/slot mechanism
├── design.md               # Design document (Chinese)
├── pyproject.toml          # Project metadata and dependencies
├── pyrightconfig.json      # Pyright type checker config
├── knowledge/              # Knowledge base directory (user content)
│   └── *.md, *.txt         # Text files searchable by LLM
├── memory/                 # Memory directory (LLM read/write)
└── tests/                  # Test suite
    ├── conftest.py         # Shared fixtures
    └── test_*.py           # Unit tests
```

### Tool Setup

#### Prerequisites

- Windows 10/11
- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

#### Installation

```bash
# Clone the repository
git clone <repo-url>
cd read-screen-tool

# Install dependencies with uv (recommended)
uv sync

# Or with pip
pip install -e .
```

#### Configuration

1. Copy the example config:

   ```bash
   cp config.yaml.example config.yaml
   ```

2. Edit `config.yaml` with your settings:

   ```yaml
   provider:
     - name: deepseek
       api_key: "sk-..."           # Your API key
       base_url: "https://api.deepseek.com"
     - name: dashscope
       api_key: "sk-..."
       base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"

   models:
     - name: deepseek-v4-pro
       provider: deepseek
       context: 1048576            # Context window size
       vision: false               # Set true for vision models
     - name: qwen3.6-plus
       provider: dashscope
       context: 1048576
       vision: true

   default_model: "deepseek-v4-pro"

   ocr:
     language: "ch"                # OCR language
     device: "gpu"                 # "cpu" or "gpu"

   hotkeys:
     screenshot: "ctrl+shift+left"
     toggle_overlay: "ctrl+alt+a"
     move_overlay: "ctrl+shift+right"

   output_window:
     position: { x: 100, y: 100 }
     size: { width: 600, height: 400 }
     font:
       family: "Microsoft YaHei"
       size: 14
       color: "#FFFFFF"
     shadow: true

   knowledge:
     enabled: true
     directory: "knowledge"
   ```

**Important:** `config.yaml` is gitignored (contains API keys). Never commit it.

### Tool Usage

#### Running the App

```bash
# With uv (recommended)
uv run python main.py

# Or directly
python main.py

# With custom config path
python main.py path/to/config.yaml
```

#### Hotkeys

| Action | Default Hotkey |
|--------|----------------|
| Screenshot selection | `Ctrl+Shift+LeftClick` |
| Toggle overlay visibility | `Ctrl+Alt+A` |
| Move overlay to cursor | `Ctrl+Shift+RightClick` |
| Cancel selection | `Escape` |

#### Workflow

1. Press `Ctrl+Shift+LeftClick` to start screenshot selection
2. Drag to select a region
3. Release mouse to confirm
4. The tool processes the screenshot:
   - Vision models: image sent directly
   - Non-vision models: OCR extracts text first
5. LLM response streams into the transparent overlay

#### Knowledge Base

Place text files in the `knowledge/` directory:

- `.md` files: searched by section (heading → next heading)
- `.tex` files: searched by section (`\section` → next `\section`)
- `.txt` files: searched by line with context

The LLM can call these tools:

- `grep_knowledge`: Search files in knowledge base
- `read_file`: Read files from knowledge/ or memory/
- `write_file`: Write files to knowledge/ or memory/

#### Web Search

The LLM can search the web via DuckDuckGo's Instant Answer API.

### Dev Guide

#### Commands

```bash
# Install dependencies
uv sync

# Run the app
uv run python main.py

# Lint + format check
uv run ruff check .
uv run ruff format --check .

# Auto-fix lint + format
uv run ruff check --fix .
uv run ruff format .

# Type check
uv run pyright

# Tests
uv run pytest                        # all tests
uv run pytest tests/test_config.py   # single file
uv run pytest -k test_name           # single test by name
uv run pytest -v --tb=short          # verbose with short tracebacks
```

**Command order matters:** `ruff check` → `ruff format` → `pyright` → `pytest`

#### Testing

- Fixtures in `tests/conftest.py`: `temp_dir`, `sample_config_dict`, `sample_config_path`
- Tests mock pynput/EasyOCR imports to avoid hardware dependencies
- `config.yaml` is not needed for tests — fixtures create temp configs

#### Style

- **Ruff rules**: E, F, I, N, W, UP, B, SIM
- **Line length**: 100
- **Quote style**: double quotes
- **Python target**: 3.13 (use modern syntax: `X | Y` unions, `type` statements)
- **Docstrings**: Google style

#### Critical Quirks

##### Thread Safety

- **tkinter is single-threaded.** Use `Signal.safe_emit()` from ANY background thread (pynput, OCR, LLM worker). `safe_emit()` marshals via `root.after_idle()`.
- `Signal.emit()` is synchronous — only safe from the tkinter main thread.
- OCR runs in a daemon thread (`_OcrWorker`).
- LLM streaming runs on a persistent worker thread (`_LlmWorker`).

##### DeepSeek API Quirks

- `finish_reason="tool_calls"` appears on EVERY tool_call chunk, not just the last one. Do NOT break early on this.
- Stream may have `finish_reason` set while `delta` still has content. Only break when `finish_reason` is set AND `delta.tool_calls` is empty.
- `reasoning_content` is a custom field on assistant messages (not standard OpenAI). Must round-trip it for tool call continuations.

##### Tool Call Batching

When the LLM makes multiple tool calls in one response, ALL results must be submitted together before calling `continue_after_tool()`. The code batches them: `_on_tool_call_requested` accumulates results, and `_on_response_complete` calls `continue_after_tool()` once all are ready.

##### Session Compression

- Compresses at 70% of context window (`_compression_threshold = 0.7`).
- Keeps newest ~30% of context, summarizes older messages.
- Compression is text-only (truncates to 200 chars per message). No LLM call for summary.

##### tkinter Overlay

- `OutputOverlay` uses a singleton `tk.Tk` root via `overlay._get_root()`.
- Markdown rendering is debounced (150ms) for streaming. Raw text inserts immediately; formatted re-render follows.
- Window alpha controls visibility: 0.82 = visible, 0.0 = hidden.

##### Config

- `config.yaml` is gitignored (contains API keys). Use `config.yaml.example` as template.
- YAML key `provider` maps to field `providers` (plural). See `_YAML_TO_FIELD` in config.py.
- `default_model` is optional — defaults to first model in list if unset.

##### OCR Language Mapping

- `"ch"`, `"cn"`, `"zh"`, `"zh-cn"` all map to EasyOCR's `"ch_sim"`.
- `"ch_sim"` automatically includes `"en"` as well.

##### Screenshot Format

- mss captures BGRA → drop alpha → BGR numpy array.
- EasyOCR accepts BGR directly.
- Vision models get RGB (converted in `_encode_image` via PIL).

---

## 中文

### 这是什么

一个 Windows 桌面工具，可以截图任意屏幕区域，发送给大模型（通过 OpenAI 兼容 API），并在透明悬浮窗中显示回复。

**主要功能：**

- 全局热键截图选择
- OCR 文字识别（EasyOCR），适用于非视觉模型
- 直接图片输入，适用于视觉模型
- 流式大模型回复，显示在透明无边框悬浮窗
- Markdown 渲染（粗体、斜体、代码、标题、列表）
- 知识库工具（grep/read/write 文件）
- DuckDuckGo 网页搜索
- 会话记忆，自动压缩
- 系统托盘集成

### 架构

基于信号的模块化设计。所有模块间通信使用 `signals.Signal`。

```
main.py (ReadScreenApp) — 编排器，连接所有信号
├── hotkey.py (HotkeyManager) — pynput 全局热键
├── screenshot.py (ScreenshotOverlay) — tkinter 全屏选择
├── ocr.py (OcrEngine) — EasyOCR 封装，懒加载
├── llm.py (LlmClient) — OpenAI API 流式 + 工具调用
├── session.py (ConversationSession) — 消息历史 + token 计数
├── overlay.py (OutputOverlay) — 透明 tkinter 文本悬浮窗
├── tray.py (TrayManager) — pystray 系统托盘
├── knowledge.py — 大模型工具定义（grep/read/write）
├── web_search.py — DuckDuckGo 网页搜索工具
├── config.py — YAML 配置加载 + dataclass 验证
└── signals.py — Signal/SignalSpy 原语
```

**信号流：**

```
HotkeyManager.screenshot_requested
  → ScreenshotOverlay.start_selection
    → screenshot_taken
      → OCR（非视觉模型）或直接图片
        → LlmClient.send
          → token_received → OutputOverlay.append_text
          → tool_call_requested → knowledge/web_search 工具
          → response_complete
```

### 仓库结构

```
read-screen-tool/
├── main.py                 # 应用入口和编排器
├── config.py               # YAML 配置加载 + dataclass 验证
├── config.yaml.example     # 示例配置（复制为 config.yaml）
├── hotkey.py               # 全局热键管理（pynput）
├── screenshot.py           # 全屏截图选择覆盖层
├── ocr.py                  # EasyOCR 封装（懒加载）
├── llm.py                  # OpenAI 兼容 API 客户端，流式传输
├── session.py              # 会话管理 + token 计数
├── overlay.py              # 透明无边框文本悬浮窗（tkinter）
├── tray.py                 # 系统托盘图标（pystray）
├── knowledge.py            # 知识库工具（grep/read/write）
├── web_search.py           # DuckDuckGo 网页搜索工具
├── signals.py              # 轻量级信号/槽机制
├── design.md               # 设计文档
├── pyproject.toml          # 项目元数据和依赖
├── pyrightconfig.json      # Pyright 类型检查配置
├── knowledge/              # 知识库目录（用户内容）
│   └── *.md, *.txt         # 大模型可搜索的文本文件
├── memory/                 # 记忆目录（大模型读写）
└── tests/                  # 测试套件
    ├── conftest.py         # 共享 fixtures
    └── test_*.py           # 单元测试
```

### 工具安装

#### 前置条件

- Windows 10/11
- Python 3.13+
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip

#### 安装步骤

```bash
# 克隆仓库
git clone <repo-url>
cd read-screen-tool

# 使用 uv 安装依赖（推荐）
uv sync

# 或使用 pip
pip install -e .
```

#### 配置

1. 复制示例配置：

   ```bash
   cp config.yaml.example config.yaml
   ```

2. 编辑 `config.yaml`，填写你的配置：

   ```yaml
   provider:
     - name: deepseek
       api_key: "sk-..."           # 你的 API key
       base_url: "https://api.deepseek.com"
     - name: dashscope
       api_key: "sk-..."
       base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"

   models:
     - name: deepseek-v4-pro
       provider: deepseek
       context: 1048576            # 上下文窗口大小
       vision: false               # 视觉模型设为 true
     - name: qwen3.6-plus
       provider: dashscope
       context: 1048576
       vision: true

   default_model: "deepseek-v4-pro"

   ocr:
     language: "ch"                # OCR 语言
     device: "gpu"                 # "cpu" 或 "gpu"

   hotkeys:
     screenshot: "ctrl+shift+left"
     toggle_overlay: "ctrl+alt+a"
     move_overlay: "ctrl+shift+right"

   output_window:
     position: { x: 100, y: 100 }
     size: { width: 600, height: 400 }
     font:
       family: "Microsoft YaHei"
       size: 14
       color: "#FFFFFF"
     shadow: true

   knowledge:
     enabled: true
     directory: "knowledge"
   ```

**注意：** `config.yaml` 已被 gitignore（包含 API key）。切勿提交。

### 工具使用

#### 运行应用

```bash
# 使用 uv（推荐）
uv run python main.py

# 或直接运行
python main.py

# 指定配置文件路径
python main.py path/to/config.yaml
```

#### 热键

| 操作 | 默认热键 |
|------|----------|
| 截图选择 | `Ctrl+Shift+左键` |
| 切换悬浮窗可见性 | `Ctrl+Alt+A` |
| 移动悬浮窗到光标位置 | `Ctrl+Shift+右键` |
| 取消选择 | `Escape` |

#### 工作流程

1. 按 `Ctrl+Shift+左键` 开始截图选择
2. 拖拽选择区域
3. 松开鼠标确认
4. 工具处理截图：
   - 视觉模型：直接发送图片
   - 非视觉模型：先 OCR 提取文字
5. 大模型回复流式显示在透明悬浮窗

#### 知识库

在 `knowledge/` 目录放置文本文件：

- `.md` 文件：按章节搜索（标题 → 下一个标题）
- `.tex` 文件：按章节搜索（`\section` → 下一个 `\section`）
- `.txt` 文件：按行搜索，附带上下文

大模型可调用这些工具：

- `grep_knowledge`：搜索知识库文件
- `read_file`：读取 knowledge/ 或 memory/ 中的文件
- `write_file`：写入 knowledge/ 或 memory/ 中的文件

#### 网页搜索

大模型可通过 DuckDuckGo Instant Answer API 搜索网页。

### 开发指南

#### 命令

```bash
# 安装依赖
uv sync

# 运行应用
uv run python main.py

# 代码检查 + 格式检查
uv run ruff check .
uv run ruff format --check .

# 自动修复代码检查 + 格式
uv run ruff check --fix .
uv run ruff format .

# 类型检查
uv run pyright

# 测试
uv run pytest                        # 所有测试
uv run pytest tests/test_config.py   # 单个文件
uv run pytest -k test_name           # 按名称运行单个测试
uv run pytest -v --tb=short          # 详细输出，简短回溯
```

**命令顺序很重要：** `ruff check` → `ruff format` → `pyright` → `pytest`

#### 测试

- Fixtures 在 `tests/conftest.py`：`temp_dir`、`sample_config_dict`、`sample_config_path`
- 测试 mock 了 pynput/EasyOCR 导入，避免硬件依赖
- 测试不需要 `config.yaml` — fixtures 会创建临时配置

#### 代码风格

- **Ruff 规则**：E, F, I, N, W, UP, B, SIM
- **行长度**：100
- **引号风格**：双引号
- **Python 目标**：3.13（使用现代语法：`X | Y` 联合类型，`type` 语句）
- **文档字符串**：Google 风格

#### 关键注意事项

##### 线程安全

- **tkinter 是单线程的。** 从任何后台线程（pynput、OCR、LLM worker）使用 `Signal.safe_emit()`。`safe_emit()` 通过 `root.after_idle()` 调度。
- `Signal.emit()` 是同步的 — 仅在 tkinter 主线程安全。
- OCR 在守护线程运行（`_OcrWorker`）。
- LLM 流式传输在持久 worker 线程运行（`_LlmWorker`）。

##### DeepSeek API 特殊行为

- `finish_reason="tool_calls"` 出现在每个 tool_call 块上，不仅仅是最后一个。不要提前 break。
- 流可能在 `delta` 仍有内容时设置 `finish_reason`。仅当 `finish_reason` 已设置且 `delta.tool_calls` 为空时才 break。
- `reasoning_content` 是 assistant 消息的自定义字段（非标准 OpenAI）。工具调用续传时必须保留。

##### 工具调用批处理

当大模型在一个响应中发起多个工具调用时，所有结果必须在调用 `continue_after_tool()` 之前一起提交。代码会批处理它们：`_on_tool_call_requested` 累积结果，`_on_response_complete` 在所有结果就绪后调用 `continue_after_tool()`。

##### 会话压缩

- 在上下文窗口的 70% 时压缩（`_compression_threshold = 0.7`）。
- 保留最新的约 30% 上下文，总结旧消息。
- 压缩仅处理文本（每条消息截断到 200 字符）。不调用 LLM 进行总结。

##### tkinter 悬浮窗

- `OutputOverlay` 使用单例 `tk.Tk` 根窗口，通过 `overlay._get_root()`。
- Markdown 渲染防抖（150ms）用于流式传输。原始文本立即插入；格式化重渲染随后进行。
- 窗口 alpha 控制可见性：0.82 = 可见，0.0 = 隐藏。

##### 配置

- `config.yaml` 已被 gitignore（包含 API key）。使用 `config.yaml.example` 作为模板。
- YAML 键 `provider` 映射到字段 `providers`（复数）。参见 config.py 中的 `_YAML_TO_FIELD`。
- `default_model` 是可选的 — 未设置时默认使用列表中的第一个模型。

##### OCR 语言映射

- `"ch"`、`"cn"`、`"zh"`、`"zh-cn"` 都映射到 EasyOCR 的 `"ch_sim"`。
- `"ch_sim"` 自动包含 `"en"`。

##### 截图格式

- mss 捕获 BGRA → 丢弃 alpha → BGR numpy 数组。
- EasyOCR 直接接受 BGR。
- 视觉模型获得 RGB（通过 PIL 在 `_encode_image` 中转换）。
