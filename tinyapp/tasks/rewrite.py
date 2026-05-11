# tasks/rewrite.py — 文本改写任务（改写 → 审校）
#
# 支持：扩写、缩写、改写/调语气、纠错、续写
# 模型分配：executor(快速) 执行改写，reviewer(深度) 做审校

from typing import Annotated
from pydantic import BaseModel, Field

from .base import WorkflowTask, StepDef


class RewriteOutput(BaseModel):
    content: str = Field(description="改写后的完整文本")
    word_count: int = Field(description="改写后字数")
    changes: Annotated[list[str], Field(description="主要改动说明", max_length=3)] = []


class ReviewOutput(BaseModel):
    quality_score: int = Field(description="质量评分1-5", ge=1, le=5)
    issues: Annotated[list[str], Field(description="发现的问题，没有则为空", max_length=5)] = []


REWRITE_TASK = WorkflowTask()
REWRITE_TASK.name = "改写"
REWRITE_TASK.description = "文本改写：改写 → 审校"

REWRITE_TASK.steps = [
    StepDef(
        name="改写",
        description="执行改写",
        system_prompt="""你是专业文字编辑。根据用户要求的操作类型对文本进行改写。

操作类型说明：
- 扩写：补充细节和论述，丰富内容，保持原意
- 缩写：精简压缩，保留核心要点，去除冗余
- 改写：换种表达方式重写，可调整语气（正式/亲切/简洁/幽默等），或用于降重
- 纠错：修正语法、拼写、标点、用词错误，保持原文风格
- 续写：基于原文内容和风格继续往下写，自然衔接

必须输出完整的改写后文本。""",
        output_model=RewriteOutput,
        model_role="executor",
    ),
    StepDef(
        name="审校",
        description="审校评分 [深度思考]",
        system_prompt="""你是资深文字审校专家。审查改写后的文本质量，逐项检查：
1. 是否准确完成了用户要求的操作（扩写/缩写/改写/纠错/续写）
2. 语句是否通顺自然，逻辑是否连贯
3. 与原文的关系是否合理（该保留的保留，该调整的调整）

只需给出质量评分和发现的问题，不需要输出完整文本。""",
        output_model=ReviewOutput,
        model_role="reviewer",
    ),
]


def collect_input() -> str:
    print("\n  操作类型：")
    ops = [("扩写", "补充细节，丰富内容"), ("缩写", "精简压缩，保留要点"),
           ("改写", "换说法/调语气"), ("纠错", "修复语法和用词错误"),
           ("续写", "基于原文继续扩展")]
    for i, (name, desc) in enumerate(ops, 1):
        print(f"    {i}. {name} — {desc}")
    op = input("  选择操作（输入名称或编号）: ").strip()
    op_map = {str(i): name for i, (name, _) in enumerate(ops, 1)}
    op_name = op_map.get(op, op)

    tone = ""
    if op_name == "改写":
        print("\n  语气风格：")
        tones = [("正式", "商务、公文、学术"), ("亲切", "日常、社交媒体"),
                 ("简洁", "精炼表达"), ("生动", "比喻和描写"),
                 ("学术", "论文、研究报告"), ("幽默", "轻松诙谐")]
        for i, (name, desc) in enumerate(tones, 1):
            print(f"    {i}. {name} — {desc}")
        tone_input = input("  选择语气（输入名称或编号，回车跳过）: ").strip()
        tone_map = {str(i): name for i, (name, _) in enumerate(tones, 1)}
        tone = tone_map.get(tone_input, tone_input)

    text = input("  请输入要改写的文本: ").strip()
    prompt = f"操作类型：{op_name}"
    if tone:
        prompt += f"\n语气：{tone}"
    prompt += f"\n\n原文：\n{text}"
    return prompt


REWRITE_TASK.collect_input = collect_input


def format_result(result) -> str:
    if not result.success:
        return f"[错误] {result.error}"

    rewrite = result.step_outputs.get("改写", {})
    review = result.step_outputs.get("审校", {})
    content = rewrite.get("content", "")
    score = review.get("quality_score", "?")
    issues = review.get("issues", [])

    output = f"\n{'='*50}\n  改写结果\n{'='*50}\n\n{content}\n"

    if issues:
        output += f"\n发现问题：\n"
        for issue in issues:
            output += f"  ! {issue}\n"

    output += f"\n质量评分：{'★' * score}{'☆' * (5 - score)} ({score}/5)\n{'='*50}"
    return output


REWRITE_TASK.format_result = format_result
