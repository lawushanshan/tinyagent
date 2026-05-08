# eval/report.py — 报告生成（控制台 + JSON）

import json
import os

from .metrics import EvalReport


def compute_summary(report: EvalReport) -> EvalReport:
    """计算汇总统计"""
    results = report.results
    report.total_cases = len(results)
    report.success_count = sum(1 for r in results if r.success)
    report.success_rate = report.success_count / report.total_cases if report.total_cases else 0
    report.avg_total_latency = (
        sum(r.total_elapsed for r in results) / report.total_cases
        if report.total_cases else 0
    )

    scores = []
    total_retries = 0
    total_steps = 0
    per_step: dict = {}

    for r in results:
        for sm in r.steps:
            total_steps += 1
            total_retries += max(0, sm.total_attempts - 1)
            if sm.quality_score is not None:
                scores.append(sm.quality_score)

            if sm.step_name not in per_step:
                per_step[sm.step_name] = {"latencies": [], "attempts": [], "successes": 0, "total": 0}
            per_step[sm.step_name]["latencies"].append(sm.total_elapsed)
            per_step[sm.step_name]["attempts"].append(sm.total_attempts)
            per_step[sm.step_name]["total"] += 1
            if sm.success:
                per_step[sm.step_name]["successes"] += 1

    report.avg_quality_score = sum(scores) / len(scores) if scores else 0
    report.total_retries = total_retries
    report.avg_retries_per_step = total_retries / total_steps if total_steps else 0

    for name, data in per_step.items():
        n = data["total"]
        report.per_step_stats[name] = {
            "avg_latency": round(sum(data["latencies"]) / n, 2),
            "avg_attempts": round(sum(data["attempts"]) / n, 2),
            "success_rate": round(data["successes"] / n, 3),
        }

    return report


def print_report(report: EvalReport):
    """控制台输出报告"""
    print()
    print("=" * 60)
    label = report.label or report.run_id
    print(f"  评测报告 — {label}")
    print(f"  时间：{report.timestamp}")
    print("=" * 60)
    print(f"  总用例：{report.total_cases}  |  "
          f"成功：{report.success_count}  |  "
          f"成功率：{report.success_rate:.1%}")
    print(f"  平均延迟：{report.avg_total_latency:.1f}s  |  "
          f"平均质量：{report.avg_quality_score:.1f}/5  |  "
          f"总重试：{report.total_retries}  |  "
          f"平均重试/步：{report.avg_retries_per_step:.2f}")
    print("-" * 60)

    for name, stats in report.per_step_stats.items():
        print(f"  {name:<12s}  延迟={stats['avg_latency']:.1f}s  "
              f"尝试={stats['avg_attempts']:.1f}  "
              f"成功率={stats['success_rate']:.0%}")

    print("-" * 60)

    for r in report.results:
        status = "PASS" if r.success else "FAIL"
        score_str = ""
        if r.success and r.steps:
            for sm in reversed(r.steps):
                if sm.quality_score is not None:
                    score_str = f"  质量={sm.quality_score}/5"
                    break
        print(f"  [{status}] {r.case_id:<20s}  {r.total_elapsed:.1f}s{score_str}")
        if r.error:
            err = r.error[:60] if len(r.error) > 60 else r.error
            print(f"         错误: {err}")

    print("=" * 60)


def save_report(report: EvalReport, output_dir: str = None) -> str:
    """保存报告为 JSON 文件，返回文件路径"""
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(__file__), "..", "data", "eval_results")
    os.makedirs(output_dir, exist_ok=True)
    filename = f"eval_{report.run_id}.json"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report.model_dump(), f, ensure_ascii=False, indent=2)
    return filepath
