# tasks/base.py — 任务基类

from typing import Type, Callable, Optional
from pydantic import BaseModel


# 自定义 handler 签名：(engine, step_dict, state, on_sub_step) -> step_data_dict
# on_sub_step: callable(sub_index, total, status) 用于报告子步骤进度
StepHandler = Callable


class StepDef:
    """Workflow 步骤定义"""

    def __init__(
        self,
        name: str,
        description: str,
        system_prompt: str,
        output_model: Type[BaseModel],
        model_role: str = "executor",
        max_tokens: int = None,
        handler: StepHandler = None,
    ):
        self.name = name
        self.description = description
        self.system_prompt = system_prompt
        self.output_model = output_model
        self.model_role = model_role
        self.max_tokens = max_tokens
        self.handler = handler  # 自定义步骤处理函数，None 则走默认 reliable_call

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "output_model": self.output_model,
            "model_role": self.model_role,
            "max_tokens": self.max_tokens,
            "handler": self.handler,
        }


class WorkflowTask:
    """Workflow 任务基类"""

    name: str = ""
    description: str = ""
    steps: list[StepDef] = []

    def collect_input(self) -> str:
        return input("\n请输入内容: ").strip()

    def format_result(self, result) -> str:
        return result.get_final_text()
