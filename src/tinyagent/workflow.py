# workflow.py — Workflow 引擎（支持多模型）
#
# 借鉴 LangGraph StateGraph：步骤间 State 传递 + Checkpoint
# 借鉴 Microsoft Agent Framework：Workflow 与 Agent 定义分离

import json
import os
import time
import uuid
from typing import Optional

from pydantic import BaseModel

from .llm import LLMPool
from .reliable import reliable_call


class WorkflowResult:
    """Workflow 执行结果"""

    def __init__(self, final_output: dict, step_outputs: dict, success: bool, error: str = None):
        self.final_output = final_output
        self.step_outputs = step_outputs
        self.success = success
        self.error = error

    def get_final_text(self) -> str:
        if not self.success:
            return f"[错误] {self.error}"
        return self.final_output.get("text", json.dumps(self.final_output, ensure_ascii=False, indent=2))


class WorkflowEngine:
    """
    Workflow 引擎：步骤执行 + State 传递 + checkpoint + 多模型。

    每步通过 step["model_role"] 选择使用哪个 LLM：
        executor → 快速模型（分析、翻译、起草）
        reviewer  → 思考模型（评分、校对、审查）
    """

    def __init__(self, pool: LLMPool, checkpoint_dir: str = None):
        self.pool = pool
        self.checkpoint_dir = checkpoint_dir or "data/checkpoints"
        os.makedirs(self.checkpoint_dir, exist_ok=True)

    def run(
        self,
        task_name: str,
        steps: list[dict],
        user_input: str,
        state: dict = None,
        on_step=None,
    ) -> WorkflowResult:
        if state is None:
            state = {
                "input": user_input,
                "steps": {},
                "current_step": 0,
            }

        total_steps = len(steps)
        step_outputs = {}

        for i, step in enumerate(steps):
            step_name = step["name"]
            step_num = i + 1
            model_role = step.get("model_role", "executor")
            state["current_step"] = step_num

            role_label = {"translator": "翻译", "executor": "快速", "reviewer": "深度"}.get(model_role, model_role)
            step_desc = step.get("description", step_name)

            if on_step:
                on_step(step_num, total_steps, step_name, step_desc, "start", {})
            else:
                print(f"\n  [步骤 {step_num}/{total_steps}] {step_desc} [{role_label}]...", end="", flush=True)

            self._save_checkpoint(task_name, state)
            messages = self._build_messages(step, state, step_num, total_steps)

            llm = self.pool.get(model_role)

            try:
                handler = step.get("handler")
                if handler:
                    # 自定义 handler：由步骤自行控制 LLM 调用逻辑（如分段生成）
                    # 记录 handler 前后的 metrics 偏移，合并为单个 metrics 条目
                    from .reliable import get_call_metrics_log
                    metrics_before = len(get_call_metrics_log())
                    handler_start = time.time()

                    step_data = handler(self, step, state)

                    # 将 handler 内部的多个 metrics 条目合并为一个
                    from .reliable import _call_metrics_log
                    handler_entries = _call_metrics_log[metrics_before:]
                    if handler_entries:
                        total_attempts = sum(e["attempts"] for e in handler_entries)
                        total_elapsed = round(time.time() - handler_start, 2)
                        all_success = all(e["success"] for e in handler_entries)
                        del _call_metrics_log[metrics_before:]
                        _call_metrics_log.append({
                            "attempts": total_attempts,
                            "attempts_detail": handler_entries,
                            "total_elapsed": total_elapsed,
                            "success": all_success,
                            "final_error": None if all_success else "handler 部分调用失败",
                        })
                else:
                    # 默认：单次 reliable_call
                    output_model = step["output_model"]
                    result = reliable_call(
                        llm=llm,
                        messages=messages,
                        output_model=output_model,
                        max_tokens=step.get("max_tokens"),
                    )
                    step_data = result.model_dump()
                step_outputs[step_name] = step_data
                state["steps"][step_name] = step_data

                if on_step:
                    on_step(step_num, total_steps, step_name, step_desc, "done", step_data)
                else:
                    self._print_step_summary(step_name, step_data)
                    print(" ✓")

            except Exception as e:
                if on_step:
                    on_step(step_num, total_steps, step_name, step_desc, "error", {"error": str(e)})
                else:
                    print(f" ✗\n  [错误] 步骤 '{step_name}' 失败: {e}")
                return WorkflowResult(
                    final_output=state["steps"],
                    step_outputs=step_outputs,
                    success=False,
                    error=f"步骤 '{step_name}' 执行失败: {e}",
                )

        final_output = self._extract_final_result(steps, step_outputs)
        self._clear_checkpoint(task_name)

        return WorkflowResult(
            final_output=final_output,
            step_outputs=step_outputs,
            success=True,
        )

    def resume(self, task_name: str) -> Optional[dict]:
        checkpoint_path = os.path.join(self.checkpoint_dir, f"{task_name}.json")
        if os.path.exists(checkpoint_path):
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def call_llm(self, model_role: str, messages: list[dict], output_model, max_tokens=None):
        """供 handler 调用的 LLM 接口"""
        llm = self.pool.get(model_role)
        result = reliable_call(
            llm=llm,
            messages=messages,
            output_model=output_model,
            max_tokens=max_tokens,
        )
        return result.model_dump()

    def _build_messages(self, step: dict, state: dict, step_num: int, total_steps: int) -> list[dict]:
        messages = []

        # 唯一请求 ID 置于 system prompt 开头，使 LCP 前缀完全不同
        # 避免 llama-server 跨任务/跨方向复用 KV 缓存导致输出混乱
        system = f"[rid:{uuid.uuid4().hex[:8]}]\n"
        system += step["system_prompt"]
        system += f"\n\n当前是第 {step_num}/{total_steps} 步。"
        messages.append({"role": "system", "content": system})

        # 前序步骤上下文
        completed_steps = state.get("steps", {})
        if completed_steps:
            # 检查是否有大文本字段需要传递完整内容
            full_text = None
            for name, data in completed_steps.items():
                if isinstance(data, dict):
                    for key in ("final_content", "content", "translated_text", "final_text"):
                        val = data.get(key, "")
                        if isinstance(val, str) and len(val) > 300:
                            full_text = val
                            break
                if full_text:
                    break

            context_parts = ["前序步骤结果："]
            for name, data in completed_steps.items():
                context_parts.append(f"- {name}: {_summarize(data)}")
            messages.append({"role": "user", "content": "\n".join(context_parts)})
            messages.append({"role": "assistant", "content": "已了解，继续执行。"})

            # 对需要审阅完整内容的步骤（如质检），单独传递完整文本
            if full_text:
                messages.append({"role": "user", "content": f"以下是待审阅的完整文档：\n{full_text}"})
                messages.append({"role": "assistant", "content": "已接收完整文档，开始审阅。"})

        messages.append({"role": "user", "content": state["input"]})
        return messages

    def _extract_final_result(self, steps: list[dict], step_outputs: dict) -> dict:
        if not steps:
            return {}
        last_step_name = steps[-1]["name"]
        return step_outputs.get(last_step_name, {})

    def _print_step_summary(self, step_name: str, step_data: dict):
        for key in ("final_text", "translated_text", "content", "title", "summary", "draft"):
            if key in step_data:
                val = str(step_data[key])
                if len(val) > 80:
                    val = val[:77] + "..."
                print(f"\n    → {val}", end="")
                return
        keys = list(step_data.keys())[:3]
        print(f"\n    → {', '.join(keys)}", end="")

    def _save_checkpoint(self, task_name: str, state: dict):
        checkpoint_path = os.path.join(self.checkpoint_dir, f"{task_name}.json")
        try:
            with open(checkpoint_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _clear_checkpoint(self, task_name: str):
        checkpoint_path = os.path.join(self.checkpoint_dir, f"{task_name}.json")
        try:
            if os.path.exists(checkpoint_path):
                os.remove(checkpoint_path)
        except Exception:
            pass


def _summarize(data: dict, max_len: int = 300) -> str:
    for key in ("final_text", "translated_text", "content", "title", "summary", "draft"):
        if key in data:
            val = str(data[key])
            if len(val) > max_len:
                val = val[:max_len - 3] + "..."
            return val
    parts = []
    for k, v in data.items():
        if isinstance(v, str) and len(v) > max_len:
            v = v[:max_len - 3] + "..."
        parts.append(f"{k}={v}")
    summary = ", ".join(parts)
    return summary if len(summary) <= max_len else summary[:max_len - 3] + "..."
