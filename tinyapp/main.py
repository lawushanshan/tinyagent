# main.py — TinyApp CLI 入口

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.llm import LLMPool
from core.workflow import WorkflowEngine
from tasks import discover_tasks, get_all_tasks
from tasks.chat import create_chat_task
from tools.file_tools import tool_list_files, tool_read_file, tool_write_file
from tools.text_tools import tool_count_words, tool_format_text


def print_banner(pool: LLMPool):
    print()
    print("=" * 56)
    print("    TinyApp v1.0 — 本地 LLM Workflow 平台")
    print("=" * 56)
    print()
    print(pool.status_text())
    print()


def print_tasks():
    tasks = get_all_tasks()
    if not tasks:
        print("  没有发现任何任务。")
        return
    print("  可用任务：")
    for i, (name, task) in enumerate(tasks.items(), 1):
        desc = getattr(task, "description", "")
        print(f"    {i}. {name:<10s} - {desc}")
    print()


def run_workflow_task(task, engine: WorkflowEngine):
    user_input = task.collect_input()
    if not user_input:
        print("  输入不能为空。")
        return

    steps = [s.to_dict() for s in task.steps]

    print(f"\n  开始执行任务：{task.description}")
    print(f"  共 {len(steps)} 个步骤")
    print("  " + "-" * 40)

    result = engine.run(
        task_name=task.name,
        steps=steps,
        user_input=user_input,
    )

    print()
    print(task.format_result(result))


def run_chat_task(task):
    task.run()


def main():
    pool = LLMPool()
    engine = WorkflowEngine(pool)

    print_banner(pool)

    # 检查连接状态
    status = pool.check_all()
    disconnected = [r for r, ok in status.items() if not ok]
    if disconnected:
        print("  [警告] 以下模型未连接：")
        for role in disconnected:
            cfg_label = {"translator": "翻译模型", "executor": "执行模型", "reviewer": "评分模型"}.get(role, role)
            print(f"    - {cfg_label}（请确认对应的 llama-server 已启动）")
        print()

    # 发现任务
    discover_tasks()

    while True:
        print_tasks()
        print("  输入任务编号或名称选择任务，输入 '退出' 结束")
        print("  " + "-" * 56)

        choice = input("\n选择: ").strip()

        if choice in ("退出", "quit", "exit", "q"):
            print("\n再见！\n")
            break

        if not choice:
            continue

        tasks = get_all_tasks()
        task = None

        if choice.isdigit():
            idx = int(choice) - 1
            task_list = list(tasks.values())
            if 0 <= idx < len(task_list):
                task = task_list[idx]
        else:
            task = tasks.get(choice)

        if not task:
            print(f"  未找到任务: {choice}")
            continue

        print(f"\n  已选择: {task.name} - {task.description}\n")

        try:
            if hasattr(task, "steps") and isinstance(task.steps, list) and len(task.steps) > 0:
                run_workflow_task(task, engine)
            elif hasattr(task, "run"):
                run_chat_task(task)
            else:
                print(f"  任务 '{task.name}' 格式不正确。")
        except KeyboardInterrupt:
            print("\n  [已中断]")
        except Exception as e:
            print(f"\n  [错误] {e}")

        print("\n" + "=" * 56 + "\n")


if __name__ == "__main__":
    main()
