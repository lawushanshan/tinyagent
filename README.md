# TinyApp — 本地 LLM Workflow 平台

基于本地模型驱动的 Agent/Workflow 平台，通过结构化工作流模板让边缘 LLM 稳定完成翻译、文档编写、文本改写等任务。使用 llama.cpp 提供推理服务，支持按步骤分配不同模型角色。

## 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                        接入层                                 │
│  ┌──────────┐  ┌──────────────────────────┐  ┌───────────┐  │
│  │ CLI      │  │ Web GUI (Flask + SSE)     │  │ 评测运行器 │  │
│  │ main.py  │  │ gui.py → web/app.py       │  │ eval_run  │  │
│  └────┬─────┘  └─────────┬────────────────┘  └─────┬─────┘  │
│       │                  │                         │         │
└───────┼──────────────────┼─────────────────────────┼─────────┘
        │                  │                         │
        ▼                  ▼                         ▼
┌──────────────────────────────────────────────────────────────┐
│                      任务层 (tasks/)                          │
│  ┌─────────┐ ┌──────┐ ┌──────┐ ┌──────┐                     │
│  │ 翻译    │ │ 编写 │ │ 改写 │ │ 对话 │  ← 自动发现注册      │
│  │ 2 steps │ │ 4 st │ │ 3 st │ │ loop │                     │
│  └────┬────┘ └──┬───┘ └──┬───┘ └──┬───┘                     │
│       └────────┬┘─────────┘        │                         │
│                │                    │                         │
│       WorkflowTask              ChatTask                      │
│       (base.py)              (Agent Loop)                     │
└────────────────┼────────────────────┼────────────────────────┘
                 │                    │
                 ▼                    ▼
┌──────────────────────────────────────────────────────────────┐
│                       引擎层 (core/)                          │
│                                                               │
│  ┌──────────────────┐    ┌──────────────┐                    │
│  │ WorkflowEngine   │    │ Agent Loop   │                    │
│  │ (workflow.py)    │    │ (chat.py)    │                    │
│  │                  │    │              │                    │
│  │ · Step 执行      │    │ · 多轮工具调用 │                    │
│  │ · State 传递     │    │ · 自动压缩历史 │                    │
│  │ · Checkpoint     │    └──────┬───────┘                    │
│  │ · 自定义 Handler │           │                             │
│  └────────┬─────────┘           │                             │
│           │                     │                             │
│           ▼                     ▼                             │
│  ┌─────────────────────────────────────┐                     │
│  │         LLMPool (llm.py)            │                     │
│  │  按角色分发: translator/executor/    │                     │
│  │              reviewer                │                     │
│  └──────────────┬──────────────────────┘                     │
│                 │                                             │
│  ┌──────────────▼──────────────────────┐                     │
│  │      reliable.py 三层可靠性栈        │                     │
│  │  ① JSON Grammar 约束解码            │                     │
│  │  ② Pydantic 模型验证                │                     │
│  │  ③ 错误反馈 → LLM 自纠正 → 重试     │                     │
│  └──────────────────────────────────────┘                     │
│                                                               │
│  ┌────────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐     │
│  │ tools.py   │ │ memory.py│ │chunker.py│ │ languages  │     │
│  │ 工具注册    │ │ 持久记忆 │ │ 长文本分 │ │ 语言注册表 │     │
│  └────────────┘ └──────────┘ └──────────┘ └───────────┘     │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                  推理后端 (llama-server)                      │
│  统一端口 8080，按 model ID 路由                               │
│                                                               │
│  ┌─────────────────┐ ┌─────────────────┐ ┌────────────────┐ │
│  │ translator       │ │ executor        │ │ reviewer       │ │
│  │ HY-MT1.5-1.8B   │ │ Qwen2.5-3B      │ │ Gemma-4-E2B   │ │
│  │ 翻译专用，轻量快  │ │ 快速，非思考     │ │ 深度思考，慢    │ │
│  └─────────────────┘ └─────────────────┘ └────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

## Workflow 执行流程

以翻译任务为例，展示单次请求的完整生命周期：

```
用户输入: "请将以下文本翻译为中文：Hello World"
     │
     ▼
┌─ WorkflowEngine.run() ─────────────────────────────────────┐
│                                                             │
│  Step 1: 翻译 (model_role=translator)                       │
│  ┌───────────────────────────────────────────────────┐      │
│  │  1. 构建 messages                                  │      │
│  │     system: [rid:abc123] 你是专业翻译...            │      │
│  │     user: 请将以下文本翻译为中文：Hello World        │      │
│  │                                                    │      │
│  │  2. reliable_call(llm, messages, TranslationOutput) │      │
│  │     ├─ LLM 生成 (JSON grammar 约束)               │      │
│  │     ├─ Pydantic 验证 ← 失败则反馈错误重试          │      │
│  │     └─ 输出: {translated_text: "你好世界"}         │      │
│  │                                                    │      │
│  │  3. 存入 state["steps"]["翻译"] = {...}            │      │
│  │  4. 保存 checkpoint                               │      │
│  └───────────────────────────────────────────────────┘      │
│                         │                                    │
│                         ▼ state 自动传递前序步骤结果          │
│                                                             │
│  Step 2: 校对 (model_role=reviewer)                         │
│  ┌───────────────────────────────────────────────────┐      │
│  │  system: [rid:def456] 你是资深翻译审校专家...       │      │
│  │  user: 前序步骤结果：- 翻译: translated_text=...   │      │
│  │  assistant: 已了解，继续执行。                       │      │
│  │  user: 请将以下文本翻译为中文：Hello World          │      │
│  │                                                    │      │
│  │  reliable_call(llm, messages, ReviewOutput)         │      │
│  │  → {final_text, quality_score, corrections, issues} │      │
│  └───────────────────────────────────────────────────┘      │
│                                                             │
│  → 清除 checkpoint，返回 WorkflowResult                      │
└─────────────────────────────────────────────────────────────┘
     │
     ▼
  task.format_result(result) → 格式化输出给用户
```

### 自定义 Handler 流程

编写任务的「分段起草」、改写任务的「分段改写」使用自定义 handler，引擎内流程如下：

```
Step 定义: handler=_segmented_draft_handler
     │
     ▼
  engine 检测到 handler → 跳过默认 reliable_call
     │
     ▼
  handler(engine, step, state) 由步骤自行控制:
  ┌─────────────────────────────────────────────┐
  │  1. 从 state["steps"] 取前序步骤输出          │
  │  2. 按需分段 (chunker.split_text)            │
  │  3. 循环调用 engine.call_llm(role, msgs, M)  │
  │     每段独立构建 messages，携带前文上下文      │
  │  4. 合并所有段落 → 返回 step_data             │
  └─────────────────────────────────────────────┘
     │
     ▼
  engine 将多轮 metrics 合并为单条记录
```

## 三层可靠性栈

边缘模型输出不稳定是核心挑战。每步 LLM 调用都经过三层保障：

```
LLM 输出 (JSON 格式)
  │
  ▼
第 1 层: 约束解码 (llama-server grammar)
  │  token 层面保证 JSON 合法，由 _clean_schema() 清理
  │  Pydantic schema → 移除 title/description → 内联 $ref
  │
  ▼
第 2 层: Pydantic 模型验证
  │  字段类型、值范围、必填项等语义检查
  │
  ├─ 通过 → 返回结构化结果
  │
  └─ 失败
      │
      ▼
第 3 层: 错误反馈 → LLM 自纠正 → 重试 (最多 N 次)
  │  _append_retry_feedback() 追加 assistant + user 消息
  │  包含具体错误信息和原始输出片段
  │  线性递增延迟: 1s, 2s, 3s...
  │
  └─ 全部失败 → raise RuntimeError
```

**额外处理：**
- `_strip_thinking()` — 剥离 Qwen/Gemma 的 `<think/>` 思考内容
- 空/纯思考输出 — 视为失败，触发重试
- 唯一请求 ID `[rid:xxx]` — 避免 llama-server 跨任务复用 KV 缓存

## 特性

- **本地运行** — 数据不出本机，基于 llama.cpp 推理
- **多模型协作** — 按任务步骤分配不同模型角色（翻译专用 / 快速执行 / 深度思考）
- **Workflow 模板** — 将复杂任务拆分为结构化步骤，引导边缘模型稳定输出
- **三层可靠性栈** — 约束解码 + Pydantic 验证 + 错误反馈重试，确保输出质量
- **自定义 Handler** — 分段起草/改写等场景由步骤自行控制 LLM 调用逻辑
- **自动任务发现** — 在 `tasks/` 下新建文件即可扩展新任务
- **极简依赖** — 仅需 `openai`、`pydantic`、`pyyaml`、`flask` 四个库

## 快速开始

### 1. 准备推理后端

使用 **llama.cpp** 的 `llama-server` 提供 OpenAI 兼容 API。项目采用路由模式——所有模型通过单一端口访问，按 model ID 自动调度：

```bash
# 参考 models.ini 配置，启动路由服务
llama-server --config models.ini --port 8080
```

可在 `models.ini` 中调整模型路径和参数，在 `config.yaml` 中按角色配置。

### 2. 创建虚拟环境并安装依赖

```bash
cd tinyapp
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. 启动

**Web GUI（推荐）：**

```bash
source venv/bin/activate
python gui.py
```

启动后自动打开浏览器，访问 `http://localhost:5001`。

**CLI 模式：**

```bash
source venv/bin/activate
python main.py
```

## 使用示例

### 翻译

```
选择: 1
请输入要翻译的文本: The quick brown fox jumps over the lazy dog.
目标语言（默认：中文）: 中文

  [步骤 1/2] 执行翻译 [翻译]...
    → 敏捷的棕色狐狸跳过了懒惰的狗 ✓
  [步骤 2/2] 校对评分 [深度思考]...
    → 质量评分: ★★★★★ ✓

翻译结果: 敏捷的棕色狐狸跳过了懒惰的狗
```

### 编写文档/邮件

```
选择: 2
文档类型（默认：邮件）: 邮件
目标读者（默认：通用）: 客户
请描述你要写的内容: 感谢客户合作，确认下周三的会议时间

  [步骤 1/4] 分析写作需求 [快速]... ✓
  [步骤 2/4] 生成写作大纲 [快速]... ✓
  [步骤 3/4] 分段起草文档 [快速]...
    → [1/3] 称呼
    → [2/3] 正文
    → [3/3] 祝语 ✓
  [步骤 4/4] 润色评分 [深度思考]... ✓
```

### 文本改写

```
选择: 3
  操作类型：
    1. 扩写 — 补充细节，丰富内容
    2. 缩写 — 精简压缩，保留要点
    3. 改写 — 换说法/调语气
    4. 纠错 — 修复语法和用词错误
    5. 续写 — 基于原文继续扩展
  选择操作: 1
  请输入要改写的文本: ...

  [步骤 1/3] 分析原文和改写需求 [快速]... ✓
  [步骤 2/3] 分段改写 [快速]...
    → [1/2] 已改写
    → [2/2] 已改写 ✓
  [步骤 3/3] 审校评分 [深度思考]... ✓
```

### 自由对话

```
选择: 4

你：帮我记住我的邮箱是 test@example.com
  [工具] remember(...) → 已记住：邮箱 = test@example.com

你：我的邮箱是什么？
  [工具] recall(...) → 邮箱 = test@example.com
助手：你的邮箱是 test@example.com。
```

## 项目结构

```
tinyapp/
├── config.yaml              # 应用配置（模型角色、可靠性参数等）
├── requirements.txt         # Python 依赖
├── main.py                  # CLI 入口
├── gui.py                   # Web GUI 入口（双击启动）
├── eval_run.py              # 评测 CLI 入口
│
├── core/                    # ── 引擎层 ──
│   ├── llm.py               #   LLMClient + LLMPool（OpenAI 兼容，按角色分发）
│   ├── reliable.py          #   三层可靠性栈（grammar → Pydantic → 重试）
│   ├── workflow.py          #   WorkflowEngine（步骤执行 + State + Checkpoint）
│   ├── tools.py             #   工具注册系统（装饰器模式）
│   ├── memory.py            #   持久化记忆（JSON 文件存储）
│   └── chunker.py           #   长文本分段工具
│
├── tasks/                   # ── 任务层（自动发现）──
│   ├── __init__.py          #   任务自动发现 + 注册
│   ├── base.py              #   WorkflowTask + StepDef 基类
│   ├── translate.py         #   翻译任务（翻译 → 校对）
│   ├── writer.py            #   编写任务（分析 → 大纲 → 分段起草 → 润色）
│   ├── rewrite.py           #   改写任务（分析 → 分段改写 → 审校）
│   ├── chat.py              #   自由对话（Agent Loop + 工具调用）
│   └── languages.py         #   支持的语言注册表（37 种语言）
│
├── tools/                   # ── 工具实现（供 chat agent 调用）──
│   ├── file_tools.py        #   list_files / read_file / write_file
│   └── text_tools.py        #   count_words / format_text
│
├── web/                     # ── Web 层 ──
│   ├── app.py               #   Flask 应用 + API 路由 + SSE 流式推送
│   ├── templates/           #   HTML 模板（index.html, landing.html）
│   └── static/              #   静态资源（CSS, JS, 图片）
│
├── eval/                    # ── 评测系统 ──
│   ├── runner.py            #   评测执行器（批量运行 + 指标收集）
│   ├── metrics.py           #   数据模型（StepMetrics, CaseResult, EvalReport）
│   ├── report.py            #   报告生成（控制台 + JSON + Markdown）
│   └── cases/               #   测试用例 YAML 文件
│       ├── translate.yaml
│       ├── rewrite.yaml
│       └── writer.yaml
│
└── data/                    # ── 运行时数据 ──
    ├── memory.json          #   持久化记忆存储
    ├── checkpoints/         #   Workflow checkpoint 文件
    └── eval_results/        #   评测报告输出
```

## 核心类关系

```
                     ┌──────────────┐
                     │  LLMPool     │
                     │  (llm.py)    │
                     │              │
                     │ get(role) → LLMClient
                     └──────┬───────┘
                            │ uses
                            ▼
┌──────────────┐    ┌───────────────┐    ┌─────────────────┐
│ WorkflowTask │───▶│WorkflowEngine │───▶│ reliable_call() │
│  (base.py)   │    │ (workflow.py) │    │  (reliable.py)  │
│              │    │               │    │                 │
│ · name       │    │ · run()       │    │ · grammar 约束  │
│ · steps[]    │    │ · call_llm()  │    │ · Pydantic 校验 │
│ · collect_   │    │ · resume()    │    │ · 错误反馈重试  │
│   input()    │    └───────────────┘    └─────────────────┘
│ · format_    │            │
│   result()   │            │ handler
└──────────────┘            ▼
                     ┌───────────────┐
┌──────────────┐    │ 自定义 Handler │
│   StepDef    │    │ (writer.py    │
│  (base.py)   │    │  rewrite.py)  │
│              │    │               │
│ · name       │    │ 按 handler    │
│ · system_    │    │ 字段分发:      │
│   prompt     │    │ None → 默认   │
│ · output_    │    │  reliable_call│
│   model      │    │ func → 自定义 │
│ · model_role │    │  分段逻辑     │
│ · handler?   │    └───────────────┘
└──────────────┘
```

## 配置说明

### config.yaml

```yaml
llm:
  translator:                    # 翻译专用模型（轻量快速）
    base_url: "http://127.0.0.1:8080/v1"
    model: "hy-mt1.5-1.8b"
  executor:                      # 执行模型（快速，非思考）
    base_url: "http://127.0.0.1:8080/v1"
    model: "qwen2.5-3b"
  reviewer:                      # 评分模型（慢，带思考）
    base_url: "http://127.0.0.1:8080/v1"
    model: "gemma-4-e2b"

reliability:
  max_retries: 5                 # 验证失败重试次数
  retry_delay: 1                 # 重试基础延迟（秒）

workflow:
  checkpoint_dir: "data/checkpoints"
  max_steps: 10

agent:
  max_turns: 15                  # 对话模式最大循环轮数
  context_window: 18             # 对话历史保留条数

memory:
  file: "data/memory.json"
```

### models.ini

llama-server 路由配置，定义每个模型的路径和参数：

| 配置项 | 说明 |
|--------|------|
| `ctx-size` | 上下文窗口大小 |
| `cache-type-k/v` | KV cache 量化类型（q4_0 节省显存）|
| `parallel` | 并行 slot 数（reviewer 设 1 避免 KV 竞争）|
| `batch-size` | 批处理大小（影响推理速度）|

### 模型角色与步骤分配

| 角色 | 模型 | 用途 | 使用步骤 |
|------|------|------|---------|
| `translator` | HY-MT1.5-1.8B | 翻译专用，轻量快速 | 翻译任务的「翻译」步骤 |
| `executor` | Qwen2.5-3B | 快速生成，非思考 | 分析、大纲、起草、改写 |
| `reviewer` | Gemma-4-E2B | 深度思考，慢 | 校对、审校、润色评分 |

## 开发指南

### 添加新任务

1. 在 `tasks/` 下新建 `.py` 文件
2. 定义每步的 Pydantic 输出模型（扁平结构，不超过 5 个字段）
3. 创建 `WorkflowTask` 实例，设置 `name`、`steps`、`collect_input`、`format_result`
4. 如需分段处理，为步骤定义 `handler` 函数

最小示例（单步任务）：

```python
from pydantic import BaseModel, Field
from .base import WorkflowTask, StepDef

class MyOutput(BaseModel):
    result: str = Field(description="处理结果")

MY_TASK = WorkflowTask()
MY_TASK.name = "我的任务"
MY_TASK.description = "一个示例任务"
MY_TASK.steps = [
    StepDef(
        name="处理",
        description="执行处理",
        system_prompt="你是处理专家。",
        output_model=MyOutput,
        model_role="executor",  # 或 "translator" / "reviewer"
    ),
]
```

### 添加新工具

在 `tools/` 下使用 `@register` 装饰器注册，chat agent 自动可用：

```python
from core.tools import register

@register(
    name="my_tool",
    description="工具描述",
    parameters={"type": "object", "properties": {"arg1": {"type": "string"}}},
)
def tool_my_tool(arg1: str) -> dict:
    return {"result": "..."}
```

注意：工具模块需在 `main.py` 中 import 以触发注册。

### Web API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/tasks` | GET | 获取所有可用任务 |
| `/api/status` | GET | 获取模型连接状态 |
| `/api/languages` | GET | 获取支持的语言列表 |
| `/api/run` | POST | 执行 workflow（SSE 流式返回）|
| `/api/chat` | POST | 聊天对话 |
| `/api/chat/reset` | POST | 重置聊天会话 |
| `/api/parse-file` | POST | 解析上传文件（txt/docx/pdf）|

## 评测工具

内置评测工具，对 workflow 任务进行批量测试，量化评估稳定性与质量。

### 使用方式

```bash
cd tinyapp

# 运行全部测试用例
python eval_run.py

# 指定任务
python eval_run.py --task 翻译

# 指定任务 + 标签（用于对比不同 prompt / 模型的效果）
python eval_run.py --task 翻译 --label "baseline"
python eval_run.py --task 翻译 --label "prompt-v2"

# 快速验证（只跑前 N 条）
python eval_run.py -n 2

# 指定报告输出目录
python eval_run.py -o ./my_results

# 使用自定义测试用例目录
python eval_run.py --cases-dir ./my_cases
```

### 命令行参数

| 参数 | 缩写 | 说明 |
|------|------|------|
| `--label` | `-l` | 运行标签，用于标识和对比不同批次 |
| `--task` | `-t` | 指定任务名（翻译、编写、改写），默认运行全部 |
| `--max-cases` | `-n` | 最大用例数，`0` 表示不限 |
| `--output` | `-o` | 报告输出目录，默认 `data/eval_results/` |
| `--cases-dir` | | 测试用例目录，默认 `eval/cases/` |

### 评估指标

| 指标 | 说明 |
|------|------|
| 成功率 | 一次跑通无重试的比例 |
| 平均质量评分 | reviewer 模型给出的质量分（1-5） |
| 总重试次数 | 所有步骤重试次数之和 |
| 平均重试/步 | 每步平均重试次数 |
| 每步延迟 | 各步骤平均耗时 |
| 每步成功率 | 各步骤独立成功率 |

### 测试用例

测试用例为 YAML 文件，存放在 `eval/cases/` 目录下，按任务分文件：

```yaml
# eval/cases/translate.yaml
task: 翻译
cases:
  - id: en-zh-simple-01
    input: "请将以下文本翻译为中文：\n\nThe quick brown fox jumps over the lazy dog."
    description: "简单英文→中文"
```

### 报告输出

评测完成后自动生成三种输出：

- **控制台**：汇总统计 + 逐条结果，即时查看
- **JSON**：保存到 `data/eval_results/eval_{run_id}.json`，同 schema 可直接对比两次运行差异
- **Markdown**：保存到 `data/eval_results/eval_{run_id}.md`，包含表格化的汇总和逐条结果

## 参考与借鉴

| 项目/理念 | 借鉴内容 |
|-----------|---------|
| [llama.cpp](https://github.com/ggerganov/llama.cpp) | OpenAI 兼容 API 服务 + grammar 约束解码 |
| [instructor](https://github.com/567-labs/instructor) | 验证失败错误反馈重试 |
| [pydantic-ai](https://github.com/pydantic/pydantic-ai) | Pydantic 模型定义输出 Schema |
| [LangGraph](https://docs.langchain.com/oss/python/langgraph/graph-api) | StateGraph 状态传递 + Checkpoint |
| [Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework) | Agent 定义与 Workflow 编排分离 |
| [smolagents](https://github.com/huggingface/smolagents) | 极简 Agent Loop 设计 |
