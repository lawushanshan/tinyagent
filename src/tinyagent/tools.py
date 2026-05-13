# tools.py — 工具注册系统

_registry: dict[str, dict] = {}


def register(name: str, description: str, parameters: dict):
    """装饰器工厂：注册一个工具"""
    def decorator(func):
        _registry[name] = {
            "func": func,
            "definition": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            },
        }
        return func
    return decorator


def get_definitions() -> list[dict]:
    """获取所有工具的定义列表（给 LLM 看的）"""
    return [item["definition"] for item in _registry.values()]


def get_names() -> list[str]:
    """获取所有已注册工具名称"""
    return list(_registry.keys())


def execute(name: str, args: dict) -> dict:
    """执行工具"""
    tool = _registry.get(name)
    if not tool:
        return {"error": f"未知工具：{name}", "suggestion": f"可用工具：{', '.join(_registry.keys())}"}
    try:
        result = tool["func"](**args)
        if isinstance(result, dict):
            return result
        return {"result": str(result)}
    except Exception as e:
        return {"error": str(e), "suggestion": "请检查参数是否正确"}
