# TinyApp — 本地 LLM Workflow 平台

基于本地模型驱动的 Agent/Workflow 平台，通过结构化工作流模板让边缘 LLM 稳定完成翻译、文档编写、邮件撰写等任务。使用 llama.cpp 提供推理服务，支持按步骤分配不同模型角色。

## 特性

- **本地运行** — 数据不出本机，基于 llama.cpp 推理
- **多模型协作** — 按任务步骤分配不同模型角色（翻译专用 / 快速执行 / 深度思考）
- **Workflow 模板** — 将复杂任务拆分为结构化步骤，引导边缘模型稳定输出
- **三层可靠性栈** — 约束解码 + Pydantic 验证 + 错误反馈重试，确保输出质量
- **自动任务发现** — 在 `tasks/` 下新建文件即可扩展新任务
- **极简依赖** — 仅需 `openai`、`pydantic`、`pyyaml` 三个库

## 快速开始

### 1. 准备推理后端

使用 **llama.cpp** 的 `llama-server` 提供 OpenAI 兼容 API：

```bash
# 编译安装 llama.cpp 后，启动模型服务
./llama-server -m model.gguf --port 8080
```

可在不同端口部署多个模型，在 `config.yaml` 中按角色配置。

### 2. 创建虚拟环境并安装依赖

```bash
cd tinyapp
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. 启动

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

  [步骤 1/3] 分析源文本...
    → 源语言: 英语 | 类型: 通用
  [步骤 2/3] 执行翻译...
    → 敏捷的棕色狐狸跳过了懒惰的狗
  [步骤 3/3] 校对润色...
    → 质量评分: ★★★★★

翻译结果: 敏捷的棕色狐狸跳过了懒惰的狗
```

### 编写文档/邮件

```
选择: 2
文档类型（默认：邮件）: 邮件
目标读者（默认：通用）: 客户
请描述你要写的内容: 感谢客户合作，确认下周三的会议时间

  [步骤 1/3] 分析写作需求...
  [步骤 2/3] 起草文档...
  [步骤 3/3] 润色优化...
```

### 自由对话

```
选择: 3

你：帮我记住我的邮箱是 test@example.com
  [工具] remember(...) → 已记住：邮箱 = test@example.com

你：我的邮箱是什么？
  [工具] recall(...) → 邮箱 = test@example.com
助手：你的邮箱是 test@example.com。
```

## 项目结构

```
tinyapp/
├── config.yaml              # 配置文件
├── requirements.txt         # Python 依赖
├── main.py                  # CLI 入口
├── core/
│   ├── llm.py               # LLM 客户端（OpenAI 兼容协议，连接 llama.cpp）
│   ├── reliable.py          # 三层可靠性栈
│   ├── workflow.py          # Workflow 引擎
│   ├── tools.py             # 工具注册系统
│   └── memory.py            # 持久化记忆
├── tasks/
│   ├── __init__.py          # 任务自动发现
│   ├── base.py              # 任务基类
│   ├── translate.py         # 翻译任务
│   ├── writer.py            # 文档/邮件编写任务
│   └── chat.py              # 自由对话任务
├── tools/
│   ├── file_tools.py        # 文件操作工具
│   └── text_tools.py        # 文本处理工具
└── data/
    └── memory.json          # 记忆存储
```

## 核心设计

### 三层可靠性栈

边缘模型输出不稳定是核心挑战。本系统采用三层保障：

```
LLM 输出
  ↓
第 1 层：约束解码（llama.cpp grammar，token 层面保证 JSON 合法）
  ↓
第 2 层：Pydantic 模型验证（字段类型、值范围语义检查）
  ↓ 失败
第 3 层：错误反馈 → LLM 自我纠正 → 重试（最多 3 次）
```

### Workflow 模板

每个任务由多个 Step 组成，每步定义独立的 Pydantic 输出模型。步骤间自动传递上下文（State），每步执行前保存 Checkpoint。

以翻译为例：
1. **分析** — 识别语言、类型、关键术语 → `AnalysisOutput`
2. **翻译** — 执行翻译 → `TranslationOutput`
3. **校对** — 检查质量、修正错误 → `ReviewOutput`

### 任务自动发现

系统启动时自动扫描 `tasks/` 目录，加载所有任务模块。添加新任务只需：

1. 在 `tasks/` 下新建 `.py` 文件
2. 定义 Pydantic 输出模型（每步一个，扁平结构，不超过 5 个字段）
3. 创建 `WorkflowTask` 实例并设置 `name` 属性

参考 `tasks/translate.py` 的写法。

## 配置说明

编辑 `config.yaml`。系统支持多模型角色，每个角色可独立配置推理后端和模型：

```yaml
llm:
  translator:                    # 翻译专用模型（轻量快速）
    base_url: "http://127.0.0.1:8082/v1"
    model: "HY-MT1.5-1.8B-Q4_K_M"
  executor:                      # 执行模型（快速，非思考）
    base_url: "http://127.0.0.1:8081/v1"
    model: "Qwen3.5-4B-IQ4_XS"
    no_think: true
  reviewer:                      # 评分模型（慢，带思考）
    base_url: "http://127.0.0.1:8080/v1"
    model: "gemma-4-E2B-it"
```

| 配置项 | 说明 |
|--------|------|
| `llm.<role>.base_url` | llama-server API 地址 |
| `llm.<role>.model` | 模型名称 |
| `llm.<role>.timeout` | 请求超时（秒），默认 `120` |
| `llm.<role>.no_think` | 禁用思考模式（Qwen3.5 等支持 `/no_think` 的模型） |
| `reliability.max_retries` | 验证失败重试次数，默认 `5` |
| `workflow.checkpoint_dir` | Checkpoint 保存目录 |
| `agent.max_turns` | 对话模式最大循环轮数，默认 `15` |
| `memory.file` | 记忆存储文件路径 |

## 参考与借鉴

| 项目/理念 | 借鉴内容 |
|-----------|---------|
| [llama.cpp](https://github.com/ggerganov/llama.cpp) | OpenAI 兼容 API 服务 + grammar 约束解码 |
| [instructor](https://github.com/567-labs/instructor) | 验证失败错误反馈重试 |
| [pydantic-ai](https://github.com/pydantic/pydantic-ai) | Pydantic 模型定义输出 Schema |
| [LangGraph](https://docs.langchain.com/oss/python/langgraph/graph-api) | StateGraph 状态传递 + Checkpoint |
| [Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework) | Agent 定义与 Workflow 编排分离 |
| [smolagents](https://github.com/huggingface/smolagents) | 极简 Agent Loop 设计 |
