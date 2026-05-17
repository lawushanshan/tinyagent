# tasks/writer.py — 文档/邮件编写任务（需求分析→模板规划→分段起草→质检）
#
# 模型分配：executor(快速) 执行分析、规划要点、起草，reviewer(深度) 做质检评分
# 结构生成：代码模板（不依赖 LLM），消除大纲步骤的幻觉和不稳定

import re
import uuid
from typing import Annotated
from pydantic import BaseModel, Field, model_validator

from .base import WorkflowTask, StepDef


# ── 文档模板（代码生成结构，非 LLM） ──

DOC_TEMPLATES = {
    "邮件": [
        {"title": "称呼", "max_tokens": 150},
        {"title": "正文", "max_tokens": 400},
        {"title": "祝语", "max_tokens": 150},
        {"title": "署名", "max_tokens": 150},
    ],
    "通知": [
        {"title": "事项说明", "max_tokens": 400},
        {"title": "注意事项", "max_tokens": 350},
    ],
    "报告": [
        {"title": "引言", "max_tokens": 250},
        {"title": "主体", "max_tokens": 500},
        {"title": "结论", "max_tokens": 250},
    ],
    "总结": [
        {"title": "概述", "max_tokens": 250},
        {"title": "具体内容", "max_tokens": 500},
        {"title": "展望", "max_tokens": 200},
    ],
    "方案": [
        {"title": "目标", "max_tokens": 250},
        {"title": "实施步骤", "max_tokens": 450},
        {"title": "预期成果", "max_tokens": 250},
    ],
}


# ── Pydantic 输出模型 ──

class RequirementOutput(BaseModel):
    doc_type: str = Field(description="文档类型", max_length=20)
    tone: str = Field(description="语气风格", max_length=20)
    audience: str = Field(description="目标读者", max_length=30)
    key_points: Annotated[list[str], Field(description="关键要点", max_length=5)] = []
    length_hint: str = Field(description="建议篇幅", max_length=30)


class PlanOutput(BaseModel):
    title: str = Field(description="文档标题", max_length=50)
    key_points: Annotated[list[str], Field(description="每段的写作要点，按顺序对应各段落，每条不超过50字", max_length=5)] = []

    @model_validator(mode='after')
    def key_points_required(self):
        if not self.key_points:
            raise ValueError("必须为每个段落生成写作要点，不能为空")
        return self


class SectionOutput(BaseModel):
    section_title: str = Field(description="当前段落标题", max_length=30)
    content: str = Field(description="当前段落正文", max_length=1500)


class QualityCheckOutput(BaseModel):
    quality_score: int = Field(description="质量评分1-5", ge=1, le=5)
    issues: Annotated[list[str], Field(description="发现的问题，没有则为空", max_length=5)] = []


# ── Handler ──

def _template_plan_handler(engine, step: dict, state: dict) -> dict:
    """模板规划 handler：代码确定段落结构，一次 LLM 调用生成 per-section 要点"""
    analysis = state["steps"].get("需求分析", {})
    doc_type = analysis.get("doc_type", "邮件")
    user_key_points = analysis.get("key_points", [])
    user_input = state["input"]

    # 代码查表确定段落结构
    template = DOC_TEMPLATES.get(doc_type, DOC_TEMPLATES["邮件"])

    section_list = "\n".join(f"{i+1}. {s['title']}" for i, s in enumerate(template))
    kp_text = "、".join(user_key_points) if user_key_points else user_input

    rid = uuid.uuid4().hex[:8]
    messages = [
        {"role": "system", "content": f"[rid:{rid}]\n你是写作规划师。为每个段落生成简短的写作要点，并拟定文档标题。所有字段用中文输出。"},
        {"role": "user", "content": f"文档类型：{doc_type}\n用户需求：{kp_text}\n\n段落结构：\n{section_list}\n\n请为每个段落生成要点（按顺序，每条不超过50字），并拟定文档标题。"},
    ]

    result = engine.call_llm(step["model_role"], messages, PlanOutput, max_tokens=300)

    # 将模板段落名与 LLM 生成的 key_points 组装
    sections = []
    for i, tpl in enumerate(template):
        kp = result["key_points"][i] if i < len(result.get("key_points", [])) else ""
        sections.append({"title": tpl["title"], "key_point": kp, "max_tokens": tpl.get("max_tokens", 300)})

    return {
        "title": result.get("title", ""),
        "sections": sections,
    }


def _build_section_messages(section_index: int, total_sections: int,
                            section: dict, prev_sections: list[dict],
                            plan: dict, user_input: str,
                            prev_tail: str = "") -> list[dict]:
    """为分段起草构建 messages，只传当前段所需信息，减少对 3B 模型的干扰"""
    rid = uuid.uuid4().hex[:8]
    system = f"[rid:{rid}]\n你是专业写手。根据给定的主题和要求，撰写当前段落。\n只撰写当前段落，不要重复其他段落已覆盖的内容。"
    messages = [{"role": "system", "content": system}]

    content = (f"文档主题：{plan.get('title', '')}\n"
               f"用户需求：{user_input}\n\n"
               f"请撰写第 {section_index + 1}/{total_sections} 段：{section.get('title', '')}\n"
               f"要点：{section.get('key_point', '')}")
    if prev_tail:
        content += f"\n\n前文末尾：{prev_tail}"
    messages.append({"role": "user", "content": content})
    return messages


def _segmented_draft_handler(engine, step: dict, state: dict) -> dict:
    """分段起草 handler：按规划逐段生成，传递前文上下文避免重复"""
    plan = state["steps"].get("规划", {})
    sections = plan.get("sections", [])
    user_input = state["input"]

    if not sections:
        messages = engine._build_messages(step, state, 0, 1)
        return engine.call_llm(step["model_role"], messages, step["output_model"])

    prev_sections = []
    prev_tail = ""
    for i, sec in enumerate(sections):
        max_tok = sec.get("max_tokens", 300)
        print(f"\n    → [{i+1}/{len(sections)}] {sec.get('title', '')}", end="", flush=True)
        messages = _build_section_messages(i, len(sections), sec, prev_sections, plan, user_input, prev_tail)
        section_data = engine.call_llm(step["model_role"], messages, SectionOutput, max_tokens=max_tok)
        prev_sections.append(section_data)
        content = section_data.get("content", "")
        prev_tail = content[-200:] if len(content) > 200 else content

    merged_content = "\n\n".join(
        f"【{sec.get('section_title', '')}】\n{sec.get('content', '')}" for sec in prev_sections
    )
    return {
        "title": plan.get("title", ""),
        "content": merged_content,
        "word_count": len(merged_content),
        "sections": prev_sections,
    }


# ── Task Definition ──

WRITER_TASK = WorkflowTask()
WRITER_TASK.name = "编写"
WRITER_TASK.description = "文档/邮件编写：需求分析 → 模板规划 → 分段起草 → 质检"

WRITER_TASK.steps = [
    StepDef(
        name="需求分析",
        description="分析写作需求",
        system_prompt="""你是写作需求分析师。分析用户需求，提取写作要素。所有字段用中文输出。

示例：
用户：写一封邮件通知客户服务器升级时间
输出：doc_type=邮件, tone=正式, audience=客户, key_points=[升级时间和原因, 升级期间的影响, 联系方式], length_hint=短""",
        output_model=RequirementOutput,
        model_role="executor",
    ),
    StepDef(
        name="规划",
        description="模板规划要点",
        system_prompt="",
        output_model=PlanOutput,
        model_role="executor",
        handler=_template_plan_handler,
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
        name="质检",
        description="质检评分 [深度思考]",
        system_prompt="""你是独立的质量审查专家。对文档进行客观评分。

逐项检查：
1. 字词重复（如"的的"、"了了"、"系统系统"、"问题问题"等连续重复）
2. 段落间内容重复（不同段落是否说了相同的话）
3. 语法和用词是否正确
4. 逻辑是否通顺连贯
5. 是否完成了用户的写作需求

只要发现上述任何问题，quality_score 不超过3分。只给出质量评分和发现的问题。""",
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

    plan = result.step_outputs.get("规划", {})
    draft = result.step_outputs.get("起草", {})
    check = result.step_outputs.get("质检", {})
    title = plan.get("title", "")
    content = draft.get("content", "")
    score = check.get("quality_score", "?")
    issues = check.get("issues", [])

    output = f"\n{'='*50}\n  {title}\n{'='*50}\n\n{content}\n"

    if issues:
        output += f"\n发现问题：\n"
        for issue in issues:
            output += f"  ! {issue}\n"

    output += f"\n质量评分：{'★' * score}{'☆' * (5 - score)} ({score}/5)\n{'='*50}"
    return output


WRITER_TASK.format_result = format_result
