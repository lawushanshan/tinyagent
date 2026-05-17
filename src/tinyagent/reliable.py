# reliable.py — 三层可靠性栈
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


_call_metrics_log: list[dict] = []


def get_call_metrics_log() -> list[dict]:
    return _call_metrics_log


def reset_call_metrics_log():
    _call_metrics_log.clear()


def reliable_call(
    llm: LLMClient,
    messages: list[dict],
    output_model: Type[BaseModel],
    max_retries: int = 2,
    temperature: float = 0,
    max_tokens: int = None,
    frequency_penalty: float = 0.3,
    presence_penalty: float = 0.3,
) -> BaseModel:
    schema = output_model.model_json_schema()

    # 在 system 消息末尾追加精简字段提示（帮助小模型理解输出结构）
    fields = list(schema.get("properties", {}).keys())
    if fields:
        for msg in messages:
            if msg.get("role") == "system":
                msg["content"] += f"\n输出字段：{', '.join(fields)}"
                break

    last_error = None
    total_start = time.time()
    call_metrics = {"attempts": 0, "attempts_detail": [], "total_elapsed": 0, "success": False, "final_error": None}

    for attempt in range(max_retries):
        t0 = time.time()
        response = llm.chat(
            messages=messages,
            format_schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
        )
        elapsed = time.time() - t0
        content = response["content"]
        call_metrics["attempts"] = attempt + 1

        if not content.strip():
            last_error = "模型返回空内容"
            call_metrics["attempts_detail"].append({"attempt": attempt + 1, "elapsed": round(elapsed, 2), "success": False, "error": last_error})
            print(f" ({elapsed:.1f}s, 空)", end="", flush=True)
            if attempt < max_retries - 1:
                _append_retry_feedback(messages, content, last_error)
                time.sleep(1 * (attempt + 1))
            continue

        # 剥离思考内容（<think/>, <|im_start|>think 等）
        content = _strip_thinking(content)

        if not content.strip():
            last_error = "剥离思考内容后为空"
            call_metrics["attempts_detail"].append({"attempt": attempt + 1, "elapsed": round(elapsed, 2), "success": False, "error": last_error})
            print(f" ({elapsed:.1f}s, 仅有思考)", end="", flush=True)
            if attempt < max_retries - 1:
                _append_retry_feedback(messages, content, last_error)
                time.sleep(1 * (attempt + 1))
            continue

        try:
            result = output_model.model_validate_json(content)

            # 检查文本字段是否存在重复退化
            rep_issue = _check_repetition(result)
            if rep_issue:
                last_error = rep_issue
                call_metrics["attempts_detail"].append({"attempt": attempt + 1, "elapsed": round(elapsed, 2), "success": False, "error": last_error[:200]})
                print(f" ({elapsed:.1f}s, 重复退化)", end="", flush=True)
                if attempt < max_retries - 1:
                    _append_retry_feedback(messages, content, last_error)
                    time.sleep(1 * (attempt + 1))
                continue

            total_elapsed = time.time() - total_start
            retry_info = f", 重试 {attempt} 次" if attempt > 0 else ""
            print(f" ({elapsed:.1f}s{retry_info})", end="", flush=True)
            call_metrics["attempts_detail"].append({"attempt": attempt + 1, "elapsed": round(elapsed, 2), "success": True, "error": None})
            call_metrics["success"] = True
            call_metrics["total_elapsed"] = round(total_elapsed, 2)
            _call_metrics_log.append(call_metrics)
            return result
        except (ValidationError, json.JSONDecodeError) as e:
            last_error = str(e)
            call_metrics["attempts_detail"].append({"attempt": attempt + 1, "elapsed": round(elapsed, 2), "success": False, "error": last_error[:200]})
            print(f" ({elapsed:.1f}s, 重试)", end="", flush=True)
            if attempt < max_retries - 1:
                _append_retry_feedback(messages, content, last_error)
                time.sleep(1 * (attempt + 1))

    total_elapsed = time.time() - total_start
    call_metrics["total_elapsed"] = round(total_elapsed, 2)
    call_metrics["final_error"] = last_error
    _call_metrics_log.append(call_metrics)
    raise RuntimeError(
        f"经过 {max_retries} 次尝试仍未能生成有效输出（{total_elapsed:.1f}s）。最后错误：{last_error}"
    )


def reliable_call_json(
    llm: LLMClient,
    messages: list[dict],
    max_retries: int = 2,
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
            frequency_penalty=0.3,
            presence_penalty=0.3,
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
    error_brief = error[:200] if len(error) > 200 else error
    truncated = prev_content[:100] if len(prev_content) > 100 else prev_content
    messages.append({"role": "assistant", "content": truncated})
    messages.append({
        "role": "user",
        "content": f"格式有误：{error_brief}\n请重新输出。",
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


def _check_repetition(result: BaseModel) -> str | None:
    """检查模型输出中的文本字段是否存在重复退化。

    检测逻辑：将文本按句号/感叹号/问号分句，如果同一个连续片段（4+ 字符）
    在文本中出现 3 次以上，则判定为重复退化。
    """
    for field_name in ("content", "final_content", "translated_text", "final_text",
                        "section_title", "title", "draft", "text"):
        val = getattr(result, field_name, None)
        if not isinstance(val, str) or len(val) < 10:
            continue

        # 按标点分句，检查连续重复片段
        sentences = re.split(r'[。！？.!?\n]', val)
        sentences = [s.strip() for s in sentences if len(s.strip()) >= 4]

        # 检查是否有连续 3+ 个相同句子
        for i in range(len(sentences)):
            count = 1
            for j in range(i + 1, min(i + 5, len(sentences))):
                if sentences[j] == sentences[i]:
                    count += 1
                else:
                    break
            if count >= 3:
                return f"输出重复退化：\"{sentences[i][:20]}...\" 连续重复 {count} 次。请避免重复，每次输出新内容。"

        # 检查是否有短片段在整个文本中重复过多
        if len(val) > 100:
            chunk_len = min(8, len(val) // 4)
            for start in range(0, len(val) - chunk_len, chunk_len):
                chunk = val[start:start + chunk_len]
                if len(chunk) < 4:
                    continue
                occurrences = val.count(chunk)
                if occurrences >= 4:
                    return f"输出重复退化：\"{chunk}\" 在文本中出现 {occurrences} 次。请避免重复，用不同方式表达。"

    return None
