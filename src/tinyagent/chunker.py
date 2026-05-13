# chunker.py — 长文本分段工具


def split_text(text: str, max_chars: int = 3500) -> list[str]:
    """按段落拆分长文本，每段不超过 max_chars。

    优先按换行符分段；单段超长时在句号处断开。
    """
    paragraphs = text.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 1  # +1 for the newline

        if current_len + para_len > max_chars and current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0

        if para_len > max_chars:
            if current:
                chunks.append("\n".join(current))
                current = []
                current_len = 0
            chunks.extend(_split_long_paragraph(para, max_chars))
        else:
            current.append(para)
            current_len += para_len

    if current:
        chunks.append("\n".join(current))

    return chunks


def _split_long_paragraph(para: str, max_chars: int) -> list[str]:
    """对超长单段在句号/逗号处断开。"""
    sentences = []
    start = 0
    for i, ch in enumerate(para):
        if ch in "。！？；\n":
            sentences.append(para[start:i + 1])
            start = i + 1
    if start < len(para):
        sentences.append(para[start:])

    chunks: list[str] = []
    current = ""
    for s in sentences:
        if len(current) + len(s) > max_chars and current:
            chunks.append(current)
            current = s
        else:
            current += s
    if current:
        chunks.append(current)

    return chunks
