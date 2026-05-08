# eval/metrics.py — 评测数据模型

from pydantic import BaseModel
from typing import Optional


class StepMetrics(BaseModel):
    """单步执行指标"""
    step_name: str
    model_role: str
    success: bool
    total_attempts: int
    total_elapsed: float
    quality_score: Optional[int] = None
    error: Optional[str] = None


class CaseResult(BaseModel):
    """单个测试用例执行结果"""
    case_id: str
    task_name: str
    description: str = ""
    input_summary: str
    success: bool
    total_elapsed: float
    steps: list[StepMetrics] = []
    final_output_summary: str = ""
    error: Optional[str] = None
    timestamp: str = ""


class EvalRunConfig(BaseModel):
    """评测运行配置"""
    run_label: str = ""
    task_name: Optional[str] = None
    max_cases: int = 0


class EvalReport(BaseModel):
    """评测报告"""
    run_id: str
    label: str = ""
    timestamp: str = ""
    config: EvalRunConfig
    results: list[CaseResult] = []

    # 汇总统计（由 compute_summary 计算）
    total_cases: int = 0
    success_count: int = 0
    success_rate: float = 0.0
    avg_total_latency: float = 0.0
    avg_quality_score: float = 0.0
    total_retries: int = 0
    avg_retries_per_step: float = 0.0
    per_step_stats: dict = {}
