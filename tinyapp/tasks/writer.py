# tasks/writer.py — 文档/邮件编写任务（需求分析→起草→润色）
#
# 模型分配：executor(快速) 执行分析和起草，reviewer(深度) 做润色评分

from typing import Annotated
from pydantic import BaseModel, Field

from .base import WorkflowTask, StepDef


class RequirementOutput(BaseModel):
    doc_type: str = Field(description="文档类型", max_length=20)
    tone: str = Field(description="语气风格", max_length=20)
    audience: str = Field(description="目标读者", max_length=30)
    key_points: Annotated[list[str], Field(description="关键要点", max_length=5)] = []
    length_hint: str = Field(description="建议篇幅", max_length=30)


class DraftOutput(BaseModel):
    title: str = Field(description="文档标题")
    content: str = Field(description="文档正文")
    word_count: int = Field(description="正文字数")


class PolishOutput(BaseModel):
    final_title: str = Field(description="最终标题", max_length=100)
    final_content: str = Field(description="最终正文")
    quality_score: int = Field(description="质量评分1-5", ge=1, le=5)
    improvements: Annotated[list[str], Field(description="润色改进说明，没有则为空", max_length=5)] = []


WRITER_TASK = WorkflowTask()
WRITER_TASK.name = "编写"
WRITER_TASK.description = "文档/邮件编写：需求分析 → 起草 → 润色"

WRITER_TASK.steps = [
    StepDef(
        name="需求分析",
        description="分析写作需求",
        system_prompt="""你是写作需求分析师。分析用户需求，提取写作要素。""",
        output_model=RequirementOutput,
        model_role="executor",
    ),
    StepDef(
        name="起草",
        description="起草文档",
        system_prompt="""你是专业写手。根据需求分析起草完整文档。

要求：
- 必须输出完整的文档内容，包括开头、主体、结尾
- 邮件类：必须包含称呼、正文、祝语、署名
- 报告/总结类：必须有标题、分段论述、结论
- 通知类：必须包含标题、正文、落款和日期
- 方案类：必须有目标、步骤、预期成果
- content 字段包含完整排版好的全文，使用换行符分段""",
        output_model=DraftOutput,
        model_role="executor",
    ),
    StepDef(
        name="润色",
        description="润色评分 [深度思考]",
        system_prompt="""你是资深文字编辑。仔细审查文档质量，逐项检查：
1. 语法和用词是否正确
2. 结构是否清晰，逻辑是否通顺
3. 语气风格是否一致
4. 是否遗漏了关键要点

给出最终定稿、质量评分和改进说明。""",
        output_model=PolishOutput,
        model_role="reviewer",
    ),
]


def collect_input() -> str:
    doc_type = input("\n文档类型（邮件/报告/总结/通知/方案，默认：邮件）: ").strip() or "邮件"
    audience = input("目标读者（如：领导、客户、同事，默认：通用）: ").strip() or "通用"
    content = input("请描述你要写的内容: ").strip()
    return f"请写一篇{doc_type}，读者是{audience}。内容要求：{content}"


WRITER_TASK.collect_input = collect_input


def format_result(result) -> str:
    if not result.success:
        return f"[错误] {result.error}"

    polish = result.step_outputs.get("润色", {})
    title = polish.get("final_title", "")
    content = polish.get("final_content", "")
    score = polish.get("quality_score", "?")
    improvements = polish.get("improvements", [])

    output = f"\n{'='*50}\n  {title}\n{'='*50}\n\n{content}\n"

    if improvements:
        output += f"\n润色说明：\n"
        for imp in improvements:
            output += f"  - {imp}\n"

    output += f"\n质量评分：{'★' * score}{'☆' * (5 - score)} ({score}/5)\n{'='*50}"
    return output


WRITER_TASK.format_result = format_result
