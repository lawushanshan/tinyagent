# tasks/chat.py — 自由对话（Agent Loop + 工具调用）
#
# 使用 executor 模型（快速响应）

import json
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.llm import LLMPool
from core.memory import Memory
from core.tools import get_definitions, execute as tool_execute


class ChatTask:
    """自由对话任务（Agent Loop 模式）"""

    name = "对话"
    description = "自由对话（支持工具调用：文件操作、记忆等）"

    def __init__(self, pool: LLMPool):
        self.pool = pool
        self.memory = Memory()
        self._last_elapsed = 0

    def run(self):
        print("\n  你可以：")
        print("    - 自由提问和聊天")
        print("    - 让我操作文件（读取、写入、列出）")
        print('    - 让我记住信息（说"记住XX是XX"）')
        print("    - 输入 '退出' 结束\n")

        messages = [{"role": "system", "content": self._build_system_prompt()}]

        while True:
            user_input = input("\n你：").strip()

            if user_input in ("退出", "quit", "exit"):
                print("\n助手：再见！\n")
                break

            if not user_input:
                continue

            answer = self._agent_loop(user_input, messages)
            print(f"\n助手：{answer}  ({self._last_elapsed:.1f}s)" if self._last_elapsed else f"\n助手：{answer}")

            if len(messages) > 20:
                system_msg = messages[0]
                messages = [system_msg] + messages[-16:]
                print("  [系统] 对话历史已压缩")

    def _build_system_prompt(self) -> str:
        import datetime
        now = datetime.datetime.now()
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

        prompt = f"""你是一个有用的 AI 助手，运行在本地边缘模型上。

## 身份
- 角色：AI 助手，擅长回答问题、文件操作、信息管理

## 核心约束
- 回答简洁，一般不超过 3 句话
- 不确定的事情直接说不确定
- 使用工具时确保参数正确

## 当前环境
- 时间：{now.strftime('%Y年%m月%d日')} {weekdays[now.weekday()]} {now.strftime('%H:%M')}

{self.memory.get_context()}"""

        return prompt

    def _agent_loop(self, user_input: str, messages: list) -> str:
        messages.append({"role": "user", "content": user_input})
        llm = self.pool.get("executor")
        tools = get_definitions()
        max_turns = 15

        total_start = time.time()
        self._last_elapsed = 0
        for turn in range(max_turns):
            try:
                t0 = time.time()
                response = llm.chat(messages, tools=tools)
                elapsed = time.time() - t0
            except Exception as e:
                messages.pop()
                return f"调用模型失败：{e}"

            if turn > 0 or len(messages) > 2:
                print(f"  [轮次 {turn + 1}] {elapsed:.1f}s", flush=True)

            content = response["content"]
            tool_calls = response["tool_calls"]

            if tool_calls:
                assistant_msg = {"role": "assistant", "content": content or "", "tool_calls": tool_calls}
                messages.append(assistant_msg)

                for tc in tool_calls:
                    name = tc["name"]
                    args = json.loads(tc["arguments"])
                    print(f"  [工具] {name}({json.dumps(args, ensure_ascii=False)})", end="")

                    result = tool_execute(name, args)
                    result_str = json.dumps(result, ensure_ascii=False)
                    print(f" → {result_str[:50]}{'...' if len(result_str) > 50 else ''}")

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_str,
                    })
                print()
            else:
                messages.append({"role": "assistant", "content": content})
                self._last_elapsed = time.time() - total_start
                return content

        return "抱歉，尝试了很多步还是没能完成任务。请换个方式描述你的需求。"


def create_chat_task(pool: LLMPool) -> ChatTask:
    """工厂函数：需要 pool 才能创建"""
    return ChatTask(pool)
