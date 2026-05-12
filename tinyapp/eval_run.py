# eval_run.py — TinyApp 评测 CLI 入口

import sys
import os
import time
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.llm import LLMPool
from eval.runner import EvalRunner
from eval.report import compute_summary, print_report, save_report, save_markdown_report
from eval.metrics import EvalRunConfig, EvalReport


def main():
    parser = argparse.ArgumentParser(description="TinyApp 评测工具")
    parser.add_argument("--label", "-l", default="", help="运行标签（如 prompt-v2）")
    parser.add_argument("--task", "-t", default=None, help="指定任务名（默认全部）")
    parser.add_argument("--max-cases", "-n", type=int, default=0, help="最大用例数（0=不限）")
    parser.add_argument("--output", "-o", default=None, help="报告输出目录")
    parser.add_argument("--cases-dir", default=None, help="测试用例目录")
    args = parser.parse_args()

    config = EvalRunConfig(
        run_label=args.label,
        task_name=args.task,
        max_cases=args.max_cases,
    )

    pool = LLMPool()
    runner = EvalRunner(pool=pool, config=config)

    # 加载用例
    all_cases = runner.load_cases(args.cases_dir)
    if args.task:
        all_cases = [c for c in all_cases if c["_task_name"] == args.task]
    if args.max_cases:
        all_cases = all_cases[:args.max_cases]

    if not all_cases:
        print(f"\n  没有找到测试用例。")
        return

    print(f"\n  TinyApp 评测工具")
    print(f"  共 {len(all_cases)} 个测试用例")
    print(f"  标签: {args.label or '(无)'}")
    print(f"  " + "-" * 40)

    # 检查模型连接
    status = pool.check_all()
    disconnected = [r for r, ok in status.items() if not ok]
    if disconnected:
        print(f"\n  [警告] 以下模型未连接：{', '.join(disconnected)}")
        print(f"  部分任务可能无法执行\n")

    # 逐条执行
    results = []
    for i, case in enumerate(all_cases, 1):
        if i > 1:
            time.sleep(2)
        desc = case.get("description", case["id"])
        print(f"\n  [{i}/{len(all_cases)}] {desc}...")
        result = runner.run_single(case)
        results.append(result)
        status = "PASS" if result.success else "FAIL"
        print(f"    -> {status} ({result.total_elapsed:.1f}s)")

    # 生成报告
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = EvalReport(
        run_id=run_id,
        label=args.label,
        timestamp=datetime.now().isoformat(),
        config=config,
        results=results,
    )
    compute_summary(report)
    print_report(report)

    filepath = save_report(report, args.output)
    md_path = save_markdown_report(report, args.output)
    print(f"\n  报告已保存:")
    print(f"    JSON: {filepath}")
    print(f"    Markdown: {md_path}\n")


if __name__ == "__main__":
    main()
