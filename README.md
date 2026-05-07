# TinyAgent —— 从零开始构建你的第一个 AI Agent

## 课程简介

这是一门为初中生设计的 AI Agent 入门课程。我们将从最基础的概念出发，一步步构建一个**极简 Agent** —— 一个能听懂你说话、会思考、能使用工具、还能记住过去的 AI 小助手。

## 你需要什么

- 会 Python 基础（print、if、for、函数、字典）
- 有一个 [智谱 AI](https://open.bigmodel.cn/) 的账号（免费注册，送免费额度）
- 一台能上网的电脑

## 课程大纲

| 课号 | 主题 | 你会学到 |
|------|------|----------|
| 第1课 | 什么是 Agent | Agent 的核心概念：感知-决策-行动-反馈循环 |
| 第2课 | 和大模型对话 | 用 Python 调用智谱 GLM API，实现人机对话 |
| 第3课 | 让大模型调用函数 | Function Calling：教大模型使用你写的 Python 函数 |
| 第4课 | Agent 循环 | 实现 Agent 的核心循环：感知→决策→行动→反馈 |
| 第5课 | 给 Agent 装上工具箱 | 设计多工具系统：计算器、天气查询、文件操作 |
| 第6课 | 记忆系统 | 让 Agent 能记住跨对话的信息 |
| 第7课 | 给 Agent 定规矩 | 系统提示工程：身份、约束、行为规范 |
| 第8课 | 终极作品：极简 Agent | 串起所有能力，打造一个完整的极简 Agent |

## 配套代码

每课都有可运行的示例代码，放在 `lessons/` 目录下对应编号的文件夹中。

```
tinyagent/
├── README.md              # 你正在看的文件
├── lessons/
│   ├── 01_what_is_agent/
│   │   └── demo.py
│   ├── 02_chat_with_llm/
│   │   ├── demo.py
│   │   └── config.py
│   ├── 03_function_calling/
│   │   └── demo.py
│   ├── 04_agent_loop/
│   │   └── demo.py
│   ├── 05_toolbox/
│   │   └── demo.py
│   ├── 06_memory/
│   │   └── demo.py
│   ├── 07_system_prompt/
│   │   └── demo.py
│   └── 08_tiny_agent/
│       ├── tiny_agent.py      # 终极作品！
│       ├── config.py
│       └── tools.py
```

## 快速开始

1. 安装依赖：`pip install zhipuai`
2. 复制 `lessons/02_chat_with_llm/config.py`，填入你的 API Key
3. 从第1课开始，按顺序学习

## 灵感来源

本课程基于文章《你不知道的 Agent：原理、架构与工程实践》，将其中复杂的工程概念简化为适合初中生理解的内容和可动手实践的代码。
