# llm.py — LLM 客户端（支持多模型 / LLMPool）

from openai import OpenAI
from typing import Optional
import yaml
import os


def estimate_tokens(text: str) -> int:
    """偏保守地估算 token 数（宁可高估）。

    高估是安全的：max_tokens 偏低 → 最多截断后重试（可恢复）
    低估是危险的：max_tokens 偏高 → context overflow → 服务端直接报错（不可恢复）
    """
    if not text:
        return 0
    chinese = sum(1 for ch in text if '一' <= ch <= '鿿')
    return int(chinese * 2.0 + (len(text) - chinese) * 0.75)


def _resolve_refs(schema: dict, defs: dict) -> dict:
    """递归内联 $ref 引用，将嵌套模型定义展开到 schema 中。"""
    if "$ref" in schema:
        ref_path = schema["$ref"]  # e.g. "#/$defs/SectionItem"
        ref_name = ref_path.split("/")[-1]
        resolved = defs.get(ref_name, {})
        return _resolve_refs({**resolved}, defs)
    result = {}
    for k, v in schema.items():
        if k == "$defs":
            continue
        if k == "properties" and isinstance(v, dict):
            result[k] = {name: _resolve_refs(prop, defs) for name, prop in v.items()}
        elif k == "items" and isinstance(v, dict):
            result[k] = _resolve_refs(v, defs)
        elif isinstance(v, list):
            result[k] = [_resolve_refs(item, defs) if isinstance(item, dict) else item for item in v]
        else:
            result[k] = v
    return result


def _clean_schema(schema: dict) -> dict:
    """清理 Pydantic schema，只保留 llama-server grammar 引擎支持的字段。

    1. 先内联 $ref 引用（Pydantic 嵌套模型会产生 $defs/$ref）
    2. 移除 title/description/default 等字段，补充 additionalProperties: false
    """
    defs = schema.get("$defs", {})
    schema = _resolve_refs(schema, defs)

    allowed = {"type", "properties", "required", "items", "enum",
               "minimum", "maximum", "additionalProperties", "anyOf", "oneOf",
               "maxLength", "maxItems"}
    cleaned = {}
    for k, v in schema.items():
        if k not in allowed:
            continue
        if k == "properties":
            cleaned[k] = {name: _clean_schema(prop) for name, prop in v.items()}
        elif k == "items" and isinstance(v, dict):
            cleaned[k] = _clean_schema(v)
        else:
            cleaned[k] = v
    if schema.get("type") == "object" and "additionalProperties" not in cleaned:
        cleaned["additionalProperties"] = False
    return cleaned


class LLMClient:
    """单个 LLM 客户端"""

    def __init__(self, base_url: str, model: str, timeout: int = 120, no_think: bool = False, context_window: int = 4096):
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.no_think = no_think
        self.context_window = context_window
        self.client = OpenAI(
            base_url=base_url,
            api_key="ollama",
            timeout=timeout,
        )

    def check_connection(self) -> bool:
        try:
            resp = self.client.models.list()
            return len(resp.data) > 0
        except Exception:
            return False

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] = None,
        format_schema: dict = None,
        temperature: float = 0,
        max_tokens: int = None,
    ) -> dict:
        # 如果 no_think 模式，在 system 消息前插入 /no_think 指令
        if self.no_think:
            messages = self._inject_no_think(messages)

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }

        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if format_schema:
            clean_schema = _clean_schema(format_schema)
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "schema": clean_schema,
                    "name": "output",
                    "strict": True,
                },
            }
        if tools:
            kwargs["tools"] = tools

        response = self.client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        result = {
            "content": msg.content or "",
            "tool_calls": None,
        }
        if msg.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
                for tc in msg.tool_calls
            ]
        return result

    def list_models(self) -> list[str]:
        try:
            resp = self.client.models.list()
            return [m.id for m in resp.data]
        except Exception:
            return []

    @staticmethod
    def _inject_no_think(messages: list[dict]) -> list[dict]:
        """在 system 消息前插入 /no_think 指令（Qwen3.5 等支持）"""
        for msg in messages:
            if msg.get("role") == "system":
                msg["content"] = "/no_think\n" + msg["content"]
                break
        return messages


class LLMPool:
    """多模型池，管理 executor / reviewer 等多个 LLM 客户端"""

    def __init__(self, llm_config: dict):
        self._clients: dict[str, LLMClient] = {}
        self._roles: dict[str, str] = {}
        self._context_windows: dict[str, int] = {}

        for role, cfg in llm_config.items():
            ctx = cfg.get("context_window", 4096)
            self._clients[role] = LLMClient(
                base_url=cfg["base_url"],
                model=cfg["model"],
                timeout=cfg.get("timeout", 120),
                no_think=cfg.get("no_think", False),
                context_window=ctx,
            )
            self._roles[role] = cfg["model"]
            self._context_windows[role] = ctx

    @classmethod
    def from_config_file(cls, path: str) -> "LLMPool":
        """从 YAML 配置文件创建 LLMPool"""
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return cls(llm_config=config["llm"])

    def get(self, role: str = "executor") -> LLMClient:
        """按角色获取 LLM 客户端"""
        client = self._clients.get(role)
        if not client:
            raise ValueError(f"未知的模型角色: {role}，可用: {list(self._clients.keys())}")
        return client

    def get_context_window(self, role: str = "executor") -> int:
        """获取指定角色的上下文窗口大小（token 数）。"""
        return self._context_windows.get(role, 4096)

    def check_all(self) -> dict[str, bool]:
        """检查所有模型的连接状态"""
        return {role: client.check_connection() for role, client in self._clients.items()}

    def status_text(self) -> str:
        lines = []
        for role, model in self._roles.items():
            client = self._clients[role]
            connected = client.check_connection()
            tag = "✓" if connected else "✗"
            label = {"translator": "翻译模型", "executor": "执行模型", "reviewer": "评分模型"}.get(role, role)
            think_tag = " [no-think]" if client.no_think else " [thinking]"
            lines.append(f"  {label}: {model}{think_tag} ({'已连接' if connected else '未连接'} {tag})")
        return "\n".join(lines)
