# eval/runner.py — 评测执行器

import sys
import os
import time
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime

from core.llm import LLMPool
from core.workflow import WorkflowEngine
from core.reliable import get_call_metrics_log, reset_call_metrics_log
from tasks import discover_tasks, get_task
from .metrics import StepMetrics, CaseResult, EvalRunConfig


class EvalRunner:
    """评测运行器：批量执行 workflow 任务并收集指标"""

    def __init__(self, pool: LLMPool = None, config: EvalRunConfig = None):
        self.pool = pool or LLMPool()
        self.engine = WorkflowEngine(self.pool)
        self.config = config or EvalRunConfig()
        discover_tasks()

    def load_cases(self, cases_dir: str = None) -> list[dict]:
        """加载测试用例（扫描 YAML 文件）"""
        if cases_dir is None:
            cases_dir = os.path.join(os.path.dirname(__file__), "cases")
        all_cases = []
        for filename in sorted(os.listdir(cases_dir)):
            if not filename.endswith((".yaml", ".yml")):
                continue
            filepath = os.path.join(cases_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            task_name = data["task"]
            for case in data["cases"]:
                case["_task_name"] = task_name
                all_cases.append(case)
        return all_cases

    def run_single(self, case: dict) -> CaseResult:
        """执行单个测试用例，收集指标"""
        task_name = case["_task_name"]
        task = get_task(task_name)

        if not task:
            return CaseResult(
                case_id=case["id"],
                task_name=task_name,
                description=case.get("description", ""),
                input_summary=case["input"][:80],
                success=False,
                total_elapsed=0,
                error=f"未找到任务: {task_name}",
                timestamp=datetime.now().isoformat(),
            )

        steps = [s.to_dict() for s in task.steps]
        user_input = case["input"]

        # 清空指标日志，执行 workflow
        reset_call_metrics_log()
        total_start = time.time()

        try:
            result = self.engine.run(
                task_name=task_name,
                steps=steps,
                user_input=user_input,
            )
        except Exception as e:
            return CaseResult(
                case_id=case["id"],
                task_name=task_name,
                description=case.get("description", ""),
                input_summary=user_input[:80] + ("..." if len(user_input) > 80 else ""),
                success=False,
                total_elapsed=round(time.time() - total_start, 2),
                error=str(e),
                timestamp=datetime.now().isoformat(),
            )

        total_elapsed = time.time() - total_start
        metrics_log = get_call_metrics_log()

        # 构建 StepMetrics（按步骤顺序）
        step_metrics = []
        for i, step in enumerate(task.steps):
            sm = StepMetrics(
                step_name=step.name,
                model_role=step.model_role,
                success=step.name in result.step_outputs,
                total_attempts=1,
                total_elapsed=0,
            )

            if i < len(metrics_log):
                m = metrics_log[i]
                sm.total_attempts = m["attempts"]
                sm.total_elapsed = m["total_elapsed"]
                if not m["success"] and sm.success:
                    sm.error = m.get("final_error", "")

            # 提取质量评分（仅从包含 quality_score 的步骤）
            step_data = result.step_outputs.get(step.name, {})
            if "quality_score" in step_data:
                sm.quality_score = step_data["quality_score"]

            step_metrics.append(sm)

        final_output = self._summarize_output(result)

        return CaseResult(
            case_id=case["id"],
            task_name=task_name,
            description=case.get("description", ""),
            input_summary=user_input[:80] + ("..." if len(user_input) > 80 else ""),
            success=result.success,
            total_elapsed=round(total_elapsed, 2),
            steps=step_metrics,
            final_output_summary=final_output,
            error=result.error,
            timestamp=datetime.now().isoformat(),
        )

    def _summarize_output(self, result) -> str:
        """从最终步骤输出中提取摘要文本"""
        output = result.final_output
        for key in ("final_text", "final_content", "translated_text", "content"):
            if key in output:
                val = str(output[key])
                if len(val) > 100:
                    val = val[:97] + "..."
                return val
        # 最终步骤无正文时，从前序步骤中查找
        for step_data in result.step_outputs.values():
            for key in ("content", "final_text", "final_content", "translated_text"):
                if key in step_data:
                    val = str(step_data[key])
                    if len(val) > 100:
                        val = val[:97] + "..."
                    return val
        return str(list(output.keys()))
