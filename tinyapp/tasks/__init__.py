# tasks/__init__.py — 任务自动发现 + 注册

import os
import importlib


_task_registry: dict[str, object] = {}


def discover_tasks():
    """自动发现 tasks/ 目录下的任务模块并注册"""
    tasks_dir = os.path.dirname(__file__)
    _task_registry.clear()

    for filename in os.listdir(tasks_dir):
        if filename.startswith("_") or not filename.endswith(".py"):
            continue
        module_name = filename[:-3]

        try:
            module = importlib.import_module(f".{module_name}", package=__name__)
            # 查找模块中定义的任务实例（以 TASK 或 task 结尾的属性）
            for attr_name in dir(module):
                if attr_name.startswith("_"):
                    continue
                attr = getattr(module, attr_name)
                # 检查是否是 WorkflowTask 实例（有 name, steps 属性）
                if hasattr(attr, "name") and hasattr(attr, "steps") and attr.name:
                    _task_registry[attr.name] = attr
        except Exception as e:
            print(f"  [警告] 加载任务模块 {module_name} 失败: {e}")


def get_all_tasks() -> dict[str, object]:
    """获取所有已注册的任务"""
    return _task_registry


def get_task(name: str) -> object:
    """按名称获取任务"""
    return _task_registry.get(name)


def register_task(task: object):
    """手动注册一个任务"""
    _task_registry[task.name] = task
