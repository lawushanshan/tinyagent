# core/memory.py — 持久化记忆系统

import json
import os
from datetime import datetime


class Memory:
    """基于 JSON 文件的持久化记忆"""

    def __init__(self, file_path: str = "data/memory.json"):
        self.file_path = file_path
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        self._memories = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self._memories, f, ensure_ascii=False, indent=2)

    def remember(self, key: str, value: str, category: str = "general") -> str:
        """记住一条信息"""
        self._memories[key] = {
            "value": value,
            "category": category,
            "created_at": datetime.now().isoformat(),
        }
        self._save()
        return f"已记住：{key} = {value}"

    def recall(self, key: str = None, category: str = None) -> dict:
        """回忆信息"""
        results = {}
        for k, v in self._memories.items():
            if key and k != key:
                continue
            if category and v.get("category") != category:
                continue
            results[k] = v
        return results

    def forget(self, key: str) -> bool:
        """删除一条记忆"""
        if key in self._memories:
            del self._memories[key]
            self._save()
            return True
        return False

    def get_context(self) -> str:
        """获取所有记忆作为上下文文本（注入 system prompt）"""
        if not self._memories:
            return "暂无用户记忆。"
        lines = []
        for key, data in self._memories.items():
            lines.append(f"- {key}: {data['value']}")
        return "已知用户信息：\n" + "\n".join(lines)
