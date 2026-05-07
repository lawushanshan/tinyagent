# tools/text_tools.py — 文本处理工具

from core.tools import register


@register(
    name="count_words",
    description="统计文本的字数、词数和段落数。当需要分析文本长度时使用。",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要统计的文本"},
        },
        "required": ["text"],
    },
)
def tool_count_words(text: str) -> dict:
    chars = len(text)
    # 中文按字计算，英文按空格分词
    words = len(text.split())
    paragraphs = len([p for p in text.split("\n") if p.strip()])
    sentences = len([s for s in text.replace("！", "!").replace("？", "?").replace("。", ".").split(".") if s.strip()])
    return {
        "result": {
            "characters": chars,
            "words": words,
            "paragraphs": paragraphs,
            "sentences": sentences,
        }
    }


@register(
    name="format_text",
    description="格式化文本：添加标题、调整缩进、统一换行符等。",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要格式化的文本"},
            "mode": {
                "type": "string",
                "description": "格式化模式：title(添加标题标记)、clean(清理多余空行)、indent(添加缩进)",
                "enum": ["title", "clean", "indent"],
            },
        },
        "required": ["text", "mode"],
    },
)
def tool_format_text(text: str, mode: str) -> dict:
    if mode == "title":
        lines = text.strip().split("\n")
        if lines:
            lines[0] = f"# {lines[0]}"
        result = "\n".join(lines)
    elif mode == "clean":
        import re
        result = re.sub(r'\n{3,}', '\n\n', text.strip())
    elif mode == "indent":
        lines = text.strip().split("\n")
        result = "\n".join("  " + line if line.strip() else "" for line in lines)
    else:
        return {"error": f"未知格式化模式：{mode}"}

    return {"result": result}
