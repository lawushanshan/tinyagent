# tasks/translate.py — 翻译任务（翻译→校对）
#
# 模型分配：translator(HY-MT1.5 翻译专用) 执行翻译，reviewer(深度思考) 做校对评分

from pydantic import BaseModel, Field

from .base import WorkflowTask, StepDef
from .languages import get_lang_name, get_lang_code, get_lang_options


class TranslationOutput(BaseModel):
    translated_text: str = Field(description="翻译结果")


class ReviewOutput(BaseModel):
    final_text: str = Field(description="最终翻译")
    quality_score: int = Field(description="质量评分1-5", ge=1, le=5)
    corrections: list[str] = Field(description="修改说明，没有则为空")
    issues: list[str] = Field(description="发现的问题，没有则为空")


TRANSLATE_TASK = WorkflowTask()
TRANSLATE_TASK.name = "翻译"
TRANSLATE_TASK.description = "多步骤翻译：翻译 → 校对"

TRANSLATE_TASK.steps = [
    StepDef(
        name="翻译",
        description="执行翻译",
        system_prompt="""你是专业翻译。将用户提供的文本翻译为指定的目标语言，保持原文的语气、风格和格式。""",
        output_model=TranslationOutput,
        model_role="translator",
    ),
    StepDef(
        name="校对",
        description="校对评分 [深度思考]",
        system_prompt="""你是资深翻译审校专家。仔细审查翻译质量，逐项检查：
1. 是否有漏译、误译
2. 语句是否通顺自然
3. 术语是否准确一致
4. 语气风格是否与原文匹配

给出最终定稿、质量评分和详细审查意见。""",
        output_model=ReviewOutput,
        model_role="reviewer",
    ),
]


def collect_input() -> str:
    # 显示支持的语言
    print("\n  支持的语言：")
    langs = get_lang_options()
    line = "    "
    for code, name in langs:
        entry = f"{name}({code})"
        if len(line) + len(entry) + 2 > 60:
            print(line)
            line = "    "
        line += entry + "  "
    if line.strip():
        print(line)
    print()

    text = input("  请输入要翻译的文本: ").strip()
    target_raw = input("  目标语言（code或中文名，默认：英文）: ").strip() or "en"
    target_name = get_lang_name(target_raw)
    target_code = get_lang_code(target_raw)
    return f"请将以下文本翻译为{target_name}（{target_code}）：\n\n{text}"


TRANSLATE_TASK.collect_input = collect_input


def format_result(result) -> str:
    if not result.success:
        return f"[错误] {result.error}"

    review = result.step_outputs.get("校对", {})
    final = review.get("final_text", "")
    score = review.get("quality_score", "?")
    corrections = review.get("corrections", [])
    issues = review.get("issues", [])

    output = f"\n{'='*50}\n  翻译结果\n{'='*50}\n\n{final}\n"

    if issues:
        output += f"\n发现问题：\n"
        for issue in issues:
            output += f"  ! {issue}\n"

    if corrections:
        output += f"\n校对修改：\n"
        for c in corrections:
            output += f"  - {c}\n"

    output += f"\n质量评分：{'★' * score}{'☆' * (5 - score)} ({score}/5)\n{'='*50}"
    return output


TRANSLATE_TASK.format_result = format_result
