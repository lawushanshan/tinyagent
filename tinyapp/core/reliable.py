# core/reliable.py — 三层可靠性栈
#
# 借鉴 instructor + Ollama Structured Outputs 的核心理念：
#   1. 约束解码（Ollama format）→ token 层面保证 JSON 合法
#   2. Pydantic 验证 → 语义层面校验
#   3. 验证失败 → 错误反馈 → LLM 自我纠正 → 重试

from pydantic import BaseModel, ValidationError
import json
import time
from typing import Type

from .llm import LLMClient


def reliable_call(
    llm: LLMClient,
    messages: list[dict],
    output_model: Type[BaseModel],
    max_retries: int = 3,
    temperature: float = 0,
) -> BaseModel:
    schema = output_model.model_json_schema()
    schema_str = json.dumps(schema, ensure_ascii=False, indent=2)

    original_last_msg = messages[-1]["content"]
    fields_desc = _schema_to_brief(schema)
    anchored_msg = f"{original_last_msg}\n\n请严格按以下 JSON 格式输出：\n{fields_desc}"
    messages[-1] = {"role": "user", "content": anchored_msg}

    last_error = None
    total_start = time.time()
    for attempt in range(max_retries):
        t0 = time.time()
        response = llm.chat(
            messages=messages,
            format_schema=schema,
            temperature=temperature,
        )
        elapsed = time.time() - t0
        content = response["content"]

        if not content.strip():
            last_error = "模型返回空内容"
            print(f" ({elapsed:.1f}s, 空)", end="", flush=True)
            if attempt < max_retries - 1:
                _append_retry_feedback(messages, content, last_error)
                time.sleep(1 * (attempt + 1))
            continue

        # 剥离思考内容（<think/>, <|im_start|>think 等）
        content = _strip_thinking(content)

        if not content.strip():
            last_error = "剥离思考内容后为空"
            print(f" ({elapsed:.1f}s, 仅有思考)", end="", flush=True)
            if attempt < max_retries - 1:
                _append_retry_feedback(messages, content, last_error)
                time.sleep(1 * (attempt + 1))
            continue

        try:
            result = output_model.model_validate_json(content)
            total_elapsed = time.time() - total_start
            retry_info = f", 重试 {attempt} 次" if attempt > 0 else ""
            print(f" ({elapsed:.1f}s{retry_info})", end="", flush=True)
            return result
        except (ValidationError, json.JSONDecodeError) as e:
            last_error = str(e)
            print(f" ({elapsed:.1f}s, 重试)", end="", flush=True)
            if attempt < max_retries - 1:
                _append_retry_feedback(messages, content, last_error)
                time.sleep(1 * (attempt + 1))

    total_elapsed = time.time() - total_start
    raise RuntimeError(
        f"经过 {max_retries} 次尝试仍未能生成有效输出（{total_elapsed:.1f}s）。最后错误：{last_error}"
    )


def reliable_call_json(
    llm: LLMClient,
    messages: list[dict],
    max_retries: int = 3,
    temperature: float = 0,
) -> dict:
    """
    不使用 Pydantic 模型的可靠 JSON 调用（用于自由对话场景）。
    """
    schema = {"type": "object", "properties": {}}

    for attempt in range(max_retries):
        response = llm.chat(
            messages=messages,
            format_schema=schema,
            temperature=temperature,
        )
        content = response["content"]
        if content.strip():
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                pass
        time.sleep(1 * (attempt + 1))

    return {"raw": response["content"]} if response.get("content") else {}


def _append_retry_feedback(messages: list[dict], prev_content: str, error: str):
    """将验证错误反馈追加到消息列表，让 LLM 自我纠正"""
    # 截断错误信息，避免 prompt 过长
    error_brief = error[:200] if len(error) > 200 else error
    messages.append({"role": "assistant", "content": prev_content})
    messages.append({
        "role": "user",
        "content": f"输出验证失败：{error_brief}\n请修正后重新输出有效 JSON。",
    })


def _schema_to_brief(schema: dict) -> str:
    """将 JSON Schema 转为精简的字段描述，减少 prompt token 数"""
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    lines = ["{"]
    for name, info in properties.items():
        desc = info.get("description", "")
        type_str = info.get("type", "string")
        # 推断格式
        if "enum" in info:
            type_str = "|".join(info["enum"])
        req = "（必填）" if name in required else ""
        line = f'  "{name}": <{type_str}>{req}'
        if desc:
            line += f"  // {desc}"
        lines.append(line)
    lines.append("}")
    return "\n".join(lines)


import re

def _strip_thinking(text: str) -> str:
    """从模型输出中剥离思考内容，只保留最终回答。

    支持格式：
      - <|im_start|>think\\n...\\n<|im_end|>  (Qwen im_start)
      - <think\\n...\\n</think\\n>             (Qwen3 原生，无 >)
      - <think ...>\\n...\\n</think ...>       (标准 XML-like)
      - <thought>...</thought>                  (通用)
    """
    # Qwen im_start 格式
    text = re.sub(r'<\|im_start\|>\s*think\s*\n.*?\n<\|im_end\|>', '', text, flags=re.DOTALL)
    # <think ...> 格式（含 Qwen3 无 > 的 <think\\n...\\n</think\\n>）
    # 关键：用 [^\\n>]* 限定标签属性不跨行，避免贪婪匹配吞掉 </think
    text = re.sub(
        r'<think\b[^\n>]*>?[ \t]*\n.*?</think\b[^\n>]*>?[ \t]*\n\s*>?',
        '', text, flags=re.DOTALL
    )
    # <thought>...</thought> 格式
    text = re.sub(
        r'<thought\b[^\n>]*>?[ \t]*\n.*?</thought\b[^\n>]*>?[ \t]*\n\s*>?',
        '', text, flags=re.DOTALL
    )
    # 清理残留空行
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text
