# tasks/base.py — 任务基类

from typing import Type
from pydantic import BaseModel


class StepDef:
    """Workflow 步骤定义"""

    def __init__(
        self,
        name: str,
        description: str,
        system_prompt: str,
        output_model: Type[BaseModel],
        model_role: str = "executor",
    ):
        self.name = name
        self.description = description
        self.system_prompt = system_prompt
        self.output_model = output_model
        self.model_role = model_role  # "executor" 或 "reviewer"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "output_model": self.output_model,
            "model_role": self.model_role,
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
