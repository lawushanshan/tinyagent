# tasks/writer.py — 文档/邮件编写任务（需求分析→大纲→分段起草→润色→质检）
#
# 模型分配：executor(快速) 执行分析、大纲、起草、润色，reviewer(深度) 做质检评分

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
    key_point: str = Field(description="段落要点", max_length=200)


class OutlineOutput(BaseModel):
    title: str = Field(description="文档标题", max_length=50)
    sections: Annotated[list[SectionItem], Field(description="段落大纲", max_length=5)] = []


class SectionOutput(BaseModel):
    section_title: str = Field(description="当前段落标题", max_length=30)
    content: str = Field(description="当前段落正文", max_length=1500)


class SectionPolishOutput(BaseModel):
    section_title: str = Field(description="段落标题", max_length=30)
    content: str = Field(description="润色后的段落正文", max_length=1500)
    changes: str = Field(description="本段主要改动说明", max_length=100)


class TitlePolishOutput(BaseModel):
    final_title: str = Field(description="最终标题", max_length=100)


class PolishOutput(BaseModel):
    final_title: str = Field(description="最终标题", max_length=100)
    final_content: str = Field(description="最终正文")
    improvements: Annotated[list[str], Field(description="润色改进说明，没有则为空", max_length=5)] = []


class QualityCheckOutput(BaseModel):
    quality_score: int = Field(description="质量评分1-5", ge=1, le=5)
    issues: Annotated[list[str], Field(description="发现的问题，没有则为空", max_length=5)] = []


def _build_section_messages(section_index: int, total_sections: int,
                            section: dict, prev_sections: list[dict],
                            outline: dict, user_input: str) -> list[dict]:
    """为分段起草构建 messages，只传当前段所需信息，减少对 3B 模型的干扰"""
    rid = uuid.uuid4().hex[:8]
    system = f"[rid:{rid}]\n你是专业写手。根据给定的主题和要求，撰写当前段落。"
    messages = [{"role": "system", "content": system}]

    # 只传当前段的信息，不传大纲全文和前文
    messages.append({
        "role": "user",
        "content": f"文档主题：{outline.get('title', '')}\n"
                   f"用户需求：{user_input}\n\n"
                   f"请撰写第 {section_index + 1}/{total_sections} 段：{section.get('title', '')}\n"
                   f"要点：{section.get('key_point', '')}",
    })
    return messages


def _segmented_draft_handler(engine, step: dict, state: dict) -> dict:
    """分段起草 handler：按大纲逐段生成"""
    outline = state["steps"].get("大纲", {})
    sections = outline.get("sections", [])
    user_input = state["input"]

    if not sections:
        messages = engine._build_messages(step, state, 0, 1)
        return engine.call_llm(step["model_role"], messages, step["output_model"])

    prev_sections = []
    for i, sec in enumerate(sections):
        print(f"\n    → [{i+1}/{len(sections)}] {sec.get('title', '')}", end="", flush=True)
        messages = _build_section_messages(i, len(sections), sec, prev_sections, outline, user_input)
        section_data = engine.call_llm(step["model_role"], messages, SectionOutput, max_tokens=800)
        prev_sections.append(section_data)

    merged_content = "\n\n".join(
        f"【{sec.get('section_title', '')}】\n{sec.get('content', '')}" for sec in prev_sections
    )
    return {
        "title": outline.get("title", ""),
        "content": merged_content,
        "word_count": len(merged_content),
        "sections": prev_sections,
    }


def _segmented_polish_handler(engine, step: dict, state: dict) -> dict:
    """分段润色 handler：逐段润色 + 标题优化"""
    draft = state["steps"].get("起草", {})
    sections = draft.get("sections", [])
    outline = state["steps"].get("大纲", {})
    user_input = state["input"]

    if not sections:
        messages = engine._build_messages(step, state, 0, 1)
        return engine.call_llm(step["model_role"], messages, PolishOutput)

    rid = uuid.uuid4().hex[:8]
    improvements = []
    polished_sections = []

    for i, sec in enumerate(sections):
        print(f"\n    → [{i+1}/{len(sections)}] 润色: {sec.get('section_title', '')}", end="", flush=True)
        system = f"[rid:{rid}]\n你是资深文字编辑。对当前段落进行润色优化。\n\n要求：只润色当前段落，检查语法用词、逻辑通顺、语气一致，去除重复冗余。"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"文档主题：{outline.get('title', '')}\n用户需求：{user_input}"},
            {"role": "assistant", "content": "已了解。"},
            {"role": "user", "content": f"请润色第 {i+1}/{len(sections)} 段：\n【{sec.get('section_title', '')}】\n{sec.get('content', '')}"},
        ]
        result = engine.call_llm(step["model_role"], messages, SectionPolishOutput, max_tokens=800)
        polished_sections.append(result)
        if result.get("changes"):
            improvements.append(f"段落{i+1}：{result['changes']}")

    # 标题优化（单独调用，很短）
    print(f"\n    → 优化标题", end="", flush=True)
    system = f"[rid:{rid}]\n你是标题优化专家。根据文档内容，优化标题使其更准确、简洁。"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"原标题：{outline.get('title', '')}\n段落标题：{', '.join(s.get('section_title', '') for s in sections)}\n用户需求：{user_input}"},
    ]
    title_result = engine.call_llm(step["model_role"], messages, TitlePolishOutput, max_tokens=100)

    merged = "\n\n".join(
        f"【{sec.get('section_title', '')}】\n{sec.get('content', '')}" for sec in polished_sections
    )

    return {
        "final_title": title_result.get("final_title", ""),
        "final_content": merged,
        "improvements": improvements,
    }


WRITER_TASK = WorkflowTask()
WRITER_TASK.name = "编写"
WRITER_TASK.description = "文档/邮件编写：需求分析 → 大纲 → 分段起草 → 润色 → 质检"

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
        system_prompt="",
        output_model=SectionOutput,
        model_role="executor",
        handler=_segmented_draft_handler,
    ),
    StepDef(
        name="润色",
        description="分段润色优化",
        system_prompt="",
        output_model=SectionPolishOutput,
        model_role="executor",
        handler=_segmented_polish_handler,
    ),
    StepDef(
        name="质检",
        description="质检评分 [深度思考]",
        system_prompt="""你是独立的质量审查专家。对文档进行客观评分。

逐项检查：
1. 是否有重复冗余（同一句话反复出现）
2. 语法和用词是否正确
3. 逻辑是否通顺连贯
4. 是否完成了用户的写作需求

只给出质量评分和发现的问题，不需要输出完整文本。""",
        output_model=QualityCheckOutput,
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
    check = result.step_outputs.get("质检", {})
    title = polish.get("final_title", "")
    content = polish.get("final_content", "")
    score = check.get("quality_score", "?")
    issues = check.get("issues", [])
    improvements = polish.get("improvements", [])

    output = f"\n{'='*50}\n  {title}\n{'='*50}\n\n{content}\n"

    if improvements:
        output += f"\n润色说明：\n"
        for imp in improvements:
            output += f"  - {imp}\n"

    if issues:
        output += f"\n发现问题：\n"
        for issue in issues:
            output += f"  ! {issue}\n"

    output += f"\n质量评分：{'★' * score}{'☆' * (5 - score)} ({score}/5)\n{'='*50}"
    return output


WRITER_TASK.format_result = format_result
