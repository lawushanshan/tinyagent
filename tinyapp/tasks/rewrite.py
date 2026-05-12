# tasks/rewrite.py — 文本改写任务（分析 → 分段改写 → 审校）
#
# 支持：扩写、缩写、改写/调语气、纠错、续写
# 模型分配：executor(快速) 执行分析和改写，reviewer(深度) 做审校

import uuid
from typing import Annotated
from pydantic import BaseModel, Field

from .base import WorkflowTask, StepDef
from core.chunker import split_text


class AnalysisOutput(BaseModel):
    operation: str = Field(description="操作类型：扩写/缩写/改写/纠错/续写", max_length=10)
    tone: str = Field(description="目标语气风格，没有要求则填'保持原文'", max_length=20)
    key_points: Annotated[list[str], Field(description="原文核心要点，改写时必须保留", max_length=5)] = []
    strategy: str = Field(description="改写策略：如何执行本次操作的具体方案", max_length=100)


class ChunkOutput(BaseModel):
    content: str = Field(description="改写后的当前片段文本")


class ReviewOutput(BaseModel):
    quality_score: int = Field(description="质量评分1-5", ge=1, le=5)
    issues: Annotated[list[str], Field(description="发现的问题，没有则为空", max_length=5)] = []


def _extract_original_text(user_input: str) -> str:
    marker = "\n\n原文：\n"
    idx = user_input.find(marker)
    return user_input[idx + len(marker):] if idx >= 0 else user_input


def _extract_rewrite_header(user_input: str) -> str:
    marker = "\n\n原文：\n"
    idx = user_input.find(marker)
    return user_input[:idx] if idx >= 0 else ""


REWRITE_SYSTEM = """你是专业文字编辑。根据分析结果和用户要求对文本进行改写。

输出要求：
- 只输出改写后的文本，不要输出原文或解释说明
- 保持语意完整，自然收尾，不要重复输出同一内容"""


def _segmented_rewrite_handler(engine, step: dict, state: dict) -> dict:
    """分段改写 handler：基于分析结果，按片段逐段改写，保持上下文连贯"""
    analysis = state["steps"].get("分析", {})
    user_input = state["input"]
    original_text = _extract_original_text(user_input)
    header = _extract_rewrite_header(user_input)

    # 从分析结果提取结构化信息
    operation = analysis.get("operation", "")
    tone = analysis.get("tone", "")
    key_points = analysis.get("key_points", [])
    strategy = analysis.get("strategy", "")

    chunks = split_text(original_text, max_chars=1500)
    rewritten_parts = []
    prev_tail = ""

    for i, chunk in enumerate(chunks):
        rid = uuid.uuid4().hex[:8]

        # 构建包含分析结果的 system prompt
        system = f"[rid:{rid}]\n{REWRITE_SYSTEM}"
        if operation:
            system += f"\n操作类型：{operation}"
        if tone and tone != "保持原文":
            system += f"\n目标语气：{tone}"
        if strategy:
            system += f"\n改写策略：{strategy}"
        if key_points:
            system += f"\n必须保留的要点：{'、'.join(key_points)}"

        messages = [{"role": "system", "content": system}]

        # 根据操作类型注入长度锚点
        chunk_len = len(chunk)
        length_hint = ""
        if "扩写" in operation or "扩写" in header:
            length_hint = f"\n原文约{chunk_len}字，扩写至约{int(chunk_len*1.5)}-{int(chunk_len*2)}字。"
        elif "缩写" in operation or "缩写" in header:
            length_hint = f"\n原文约{chunk_len}字，压缩至约{int(chunk_len*0.3)}-{int(chunk_len*0.5)}字。"

        context_hint = f"\n\n前文末尾：{prev_tail}" if prev_tail else ""
        messages.append({
            "role": "user",
            "content": f"{header}{length_hint}\n\n原文：\n{chunk}{context_hint}",
        })

        chunk_data = engine.call_llm("executor", messages, ChunkOutput)
        rewritten = chunk_data.get("content", "")
        rewritten_parts.append(rewritten)
        prev_tail = rewritten[-200:] if len(rewritten) > 200 else rewritten
        print(f"\n    → [{i+1}/{len(chunks)}] 已改写", end="", flush=True)

    merged = "\n".join(rewritten_parts)
    return {
        "content": merged,
        "word_count": len(merged),
        "changes": [],
    }


REWRITE_TASK = WorkflowTask()
REWRITE_TASK.name = "改写"
REWRITE_TASK.description = "文本改写：分析 → 分段改写 → 审校"

REWRITE_TASK.steps = [
    StepDef(
        name="分析",
        description="分析原文和改写需求",
        system_prompt="""你是文本分析专家。分析原文内容和用户的改写要求，提取改写所需的关键信息。

要求：
1. 准确识别操作类型
2. 提取原文的核心要点（改写时必须保留的内容）
3. 制定具体的改写策略""",
        output_model=AnalysisOutput,
        model_role="executor",
    ),
    StepDef(
        name="改写",
        description="分段改写",
        system_prompt="",  # 由 handler 自行构建 messages
        output_model=ChunkOutput,
        model_role="executor",
        handler=_segmented_rewrite_handler,
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
