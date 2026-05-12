# tasks/writer.py — 文档/邮件编写任务（需求分析→大纲→分段起草→润色）
#
# 模型分配：executor(快速) 执行分析、大纲、分段起草，reviewer(深度) 做润色评分

import uuid
from typing import Annotated
from pydantic import BaseModel, Field

from .base import WorkflowTask, StepDef


class RequirementOutput(BaseModel):
    doc_type: str = Field(description="文档类型", max_length=20)
    tone: str = Field(description="语气风格", max_length=20)
    audience: str = Field(description="目标读者", max_length=30)
    key_points: Annotated[list[str], Field(description="关键要点", max_length=5)] = []
    length_hint: str = Field(description="建议篇幅", max_length=30)


class SectionItem(BaseModel):
    title: str = Field(description="段落标题", max_length=30)
    key_point: str = Field(description="段落要点", max_length=100)


class OutlineOutput(BaseModel):
    title: str = Field(description="文档标题", max_length=50)
    sections: Annotated[list[SectionItem], Field(description="段落大纲", max_length=5)] = []


class SectionOutput(BaseModel):
    section_title: str = Field(description="当前段落标题", max_length=30)
    content: str = Field(description="当前段落正文", max_length=500)


class PolishOutput(BaseModel):
    final_title: str = Field(description="最终标题", max_length=100)
    final_content: str = Field(description="最终正文")
    quality_score: int = Field(description="质量评分1-5", ge=1, le=5)
    improvements: Annotated[list[str], Field(description="润色改进说明，没有则为空", max_length=5)] = []


def _build_section_messages(section_index: int, total_sections: int,
                            section: dict, prev_sections: list[dict],
                            outline: dict, user_input: str) -> list[dict]:
    """为分段起草构建 messages，包含大纲和前文上下文"""
    rid = uuid.uuid4().hex[:8]
    system = f"[rid:{rid}]\n你是专业写手。根据大纲和前文，撰写当前段落的正文。\n\n要求：只输出当前段落的标题和正文，不要输出其他段落的内容。"
    messages = [{"role": "system", "content": system}]

    # 大纲
    outline_parts = [f"文档标题：{outline.get('title', '')}"]
    for i, sec in enumerate(outline.get("sections", [])):
        marker = " ← 当前" if i == section_index else ""
        outline_parts.append(f"  {i+1}. {sec.get('title', '')}：{sec.get('key_point', '')}{marker}")
    messages.append({"role": "user", "content": f"大纲：\n{''.join(outline_parts)}"})
    messages.append({"role": "assistant", "content": "已了解大纲。"})
    messages.append({"role": "user", "content": f"用户需求：{user_input}"})
    messages.append({"role": "assistant", "content": "已了解需求。"})

    # 前文上下文（只传摘要，避免 prompt 过长）
    if prev_sections:
        prev_parts = []
        for sec in prev_sections:
            title = sec.get("section_title", "")
            content = sec.get("content", "")
            tail = content[-150:] if len(content) > 150 else content
            prev_parts.append(f"【{title}】...{tail}")
        messages.append({"role": "user", "content": f"前文摘要：\n{''.join(prev_parts)}"})
        messages.append({"role": "assistant", "content": "已了解前文，保持连贯。"})

    # 当前任务
    messages.append({
        "role": "user",
        "content": f"请撰写第 {section_index + 1}/{total_sections} 段：{section.get('title', '')}\n要点：{section.get('key_point', '')}",
    })
    return messages


def _segmented_draft_handler(engine, step: dict, state: dict) -> dict:
    """分段起草 handler：按大纲逐段生成"""
    outline = state["steps"].get("大纲", {})
    sections = outline.get("sections", [])
    user_input = state["input"]

    if not sections:
        # 无大纲时退化为单次生成
        messages = engine._build_messages(step, state, 0, 1)
        return engine.call_llm(step["model_role"], messages, step["output_model"])

    prev_sections = []
    for i, sec in enumerate(sections):
        print(f"\n    → [{i+1}/{len(sections)}] {sec.get('title', '')}", end="", flush=True)
        messages = _build_section_messages(i, len(sections), sec, prev_sections, outline, user_input)
        section_data = engine.call_llm(step["model_role"], messages, SectionOutput)
        prev_sections.append(section_data)

    # 合并所有段落
    merged_content = "\n\n".join(
        f"【{sec.get('section_title', '')}】\n{sec.get('content', '')}" for sec in prev_sections
    )
    return {
        "title": outline.get("title", ""),
        "content": merged_content,
        "word_count": len(merged_content),
    }


WRITER_TASK = WorkflowTask()
WRITER_TASK.name = "编写"
WRITER_TASK.description = "文档/邮件编写：需求分析 → 大纲 → 分段起草 → 润色"

WRITER_TASK.steps = [
    StepDef(
        name="需求分析",
        description="分析写作需求",
        system_prompt="""你是写作需求分析师。分析用户需求，提取写作要素。""",
        output_model=RequirementOutput,
        model_role="executor",
    ),
    StepDef(
        name="大纲",
        description="生成写作大纲",
        system_prompt="""你是写作规划师。根据需求分析，生成文档大纲。

要求：
- 为文档设计一个标题
- 将内容拆分为 2-5 个段落，每段有明确的标题和要点
- 邮件类：称呼/正文/祝语/署名
- 报告/总结类：引言/主体分段/结论
- 通知类：标题/正文/落款
- 方案类：目标/步骤/预期成果""",
        output_model=OutlineOutput,
        model_role="executor",
    ),
    StepDef(
        name="起草",
        description="分段起草文档",
        system_prompt="",  # 由 handler 自行构建 messages
        output_model=SectionOutput,  # 每段输出的模型
        model_role="executor",
        handler=_segmented_draft_handler,
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
