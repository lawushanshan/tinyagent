# trace.py — 执行追踪，记录 workflow 运行中每步 LLM 调用的详细过程

import copy
import json
import os
import time
from datetime import datetime


class RunTrace:
    """单次 workflow 运行的执行追踪。

    生成 JSON 结构：
    {
        "run_id": "20260514_230100",
        "task": "翻译",
        "input": "...",
        "start_time": "...",
        "steps": [
            {
                "step": "翻译",
                "model_role": "translator",
                "model": "hy-mt1.5-1.8b",
                "calls": [
                    {
                        "messages": [...],
                        "attempts": [
                            {"attempt": 1, "elapsed_s": 2.3, "raw_output": "...", "error": null}
                        ],
                        "output": {...},
                        "total_elapsed_s": 2.3
                    }
                ],
                "total_elapsed_s": 2.3
            }
        ],
        "total_elapsed_s": 15.2
    }
    """

    _MAX_RAW = 5000

    def __init__(self, task_name: str, user_input: str, trace_dir: str = "data/traces"):
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.trace_dir = trace_dir
        self._run_start = time.time()
        self._step_start = 0.0
        self._current_step = None
        self._current_call = None
        self._calls: list[dict] = []

        self.data: dict = {
            "run_id": self.run_id,
            "task": task_name,
            "input": user_input,
            "start_time": datetime.now().isoformat(),
            "steps": [],
            "total_elapsed_s": None,
        }

    def begin_step(self, step_name: str, model_role: str, model_id: str):
        self._current_step = {
            "step": step_name,
            "model_role": model_role,
            "model": model_id,
            "calls": [],
            "total_elapsed_s": None,
        }
        self._step_start = time.time()
        self._calls = []

    def begin_call(self, messages: list[dict]):
        self._current_call = {
            "messages": copy.deepcopy(messages),
            "attempts": [],
            "output": None,
            "total_elapsed_s": None,
        }

    def record_attempt(self, attempt_num: int, elapsed_s: float,
                       raw_output: str = None, error: str = None):
        if self._current_call is None:
            return
        entry: dict = {
            "attempt": attempt_num,
            "elapsed_s": round(elapsed_s, 2),
        }
        if raw_output:
            entry["raw_output"] = raw_output[:self._MAX_RAW]
        if error:
            entry["error"] = error[:500]
        self._current_call["attempts"].append(entry)

    def end_call(self, output: dict, total_elapsed_s: float):
        if self._current_call is None:
            return
        self._current_call["output"] = output
        self._current_call["total_elapsed_s"] = round(total_elapsed_s, 2)
        self._calls.append(self._current_call)
        self._current_call = None

    def fail_call(self, error: str):
        if self._current_call is None:
            return
        self._current_call["error"] = error[:500]
        self._calls.append(self._current_call)
        self._current_call = None

    def end_step(self):
        if self._current_step is None:
            return
        elapsed = round(time.time() - self._step_start, 2)
        self._current_step["calls"] = self._calls
        self._current_step["total_elapsed_s"] = elapsed
        self.data["steps"].append(self._current_step)
        self._current_step = None
        self._calls = []

    def save(self):
        self.data["total_elapsed_s"] = round(time.time() - self._run_start, 2)
        os.makedirs(self.trace_dir, exist_ok=True)
        path = os.path.join(self.trace_dir, f"{self.run_id}.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
