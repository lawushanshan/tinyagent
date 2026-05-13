# tools/file_tools.py — 文件操作工具

import os

from tinyagent.tools import register


@register(
    name="list_files",
    description="列出目录下的文件。当需要查看文件夹内容时使用。",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目录路径，默认当前目录", "default": "."},
        },
    },
)
def tool_list_files(path: str = ".") -> dict:
    try:
        items = os.listdir(path)
        if not items:
            return {"result": "目录为空"}
        files = [i for i in items[:50] if not i.startswith(".")]
        return {"result": "\n".join(sorted(files))}
    except FileNotFoundError:
        return {"error": f"目录不存在：{path}", "suggestion": "请检查路径是否正确"}
    except Exception as e:
        return {"error": str(e)}


@register(
    name="read_file",
    description="读取文件内容。当需要查看文件内容时使用。",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
        },
        "required": ["path"],
    },
)
def tool_read_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read(3000)
            if len(content) >= 3000:
                content += "\n...（已截断，共 3000 字符）"
            return {"result": content, "char_count": len(content)}
    except FileNotFoundError:
        return {"error": f"文件不存在：{path}", "suggestion": "请先用 list_files 查看可用文件"}
    except Exception as e:
        return {"error": str(e)}


@register(
    name="write_file",
    description="将内容写入文件。当需要保存或创建文件时使用。",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "要写入的内容"},
        },
        "required": ["path", "content"],
    },
)
def tool_write_file(path: str, content: str) -> dict:
    try:
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"result": f"已写入 {path}（{len(content)} 字符）"}
    except Exception as e:
        return {"error": str(e)}
