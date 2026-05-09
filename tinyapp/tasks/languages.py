# tasks/languages.py — 支持的语言注册表

# (code, 原生名称) — 按常用程度排序，默认英语
SUPPORTED_LANGUAGES: list[tuple[str, str]] = [
    # 默认
    ("en", "English"),
    # 东亚
    ("zh", "中文"),
    ("ja", "日本語"),
    ("ko", "한국어"),
    ("yue", "粵語"),
    # 欧洲
    ("fr", "Français"),
    ("de", "Deutsch"),
    ("es", "Español"),
    ("pt", "Português"),
    ("it", "Italiano"),
    ("ru", "Русский"),
    ("nl", "Nederlands"),
    ("pl", "Polski"),
    ("cs", "Čeština"),
    ("uk", "Українська"),
    ("tr", "Türkçe"),
    ("he", "עברית"),
    # 南亚 / 东南亚
    ("th", "ไทย"),
    ("vi", "Tiếng Việt"),
    ("ms", "Bahasa Melayu"),
    ("id", "Bahasa Indonesia"),
    ("tl", "Filipino"),
    ("hi", "हिन्दी"),
    ("bn", "বাংলা"),
    ("ta", "தமிழ்"),
    ("te", "తెలుగు"),
    ("mr", "मराठी"),
    ("gu", "ગુજરાતી"),
    ("ur", "اردو"),
    # 中东 / 中亚
    ("ar", "العربية"),
    ("fa", "فارسی"),
    ("km", "ភាសាខ្មែរ"),
    ("my", "မြန်မာစာ"),
    # 其他
    ("zh-Hant", "繁體中文"),
    ("bo", "བོད་ཡིག"),
    ("kk", "Қазақша"),
    ("mn", "Монгол"),
    ("ug", "ئۇيغۇرچە"),
]

# 快速查找表
_code_map: dict[str, str] = {code: name for code, name in SUPPORTED_LANGUAGES}
_name_map: dict[str, str] = {name: code for code, name in SUPPORTED_LANGUAGES}


def get_lang_name(query: str) -> str:
    """输入 code 或中文名，返回规范中文名。找不到返回原值。"""
    if query in _code_map:
        return _code_map[query]
    if query in _name_map:
        return query
    return query


def get_lang_code(query: str) -> str:
    """输入 code 或中文名，返回语言 code。找不到返回原值。"""
    if query in _name_map:
        return _name_map[query]
    if query in _code_map:
        return query
    return query


def get_lang_options() -> list[tuple[str, str]]:
    """返回 [(code, name), ...] 供 UI 使用"""
    return SUPPORTED_LANGUAGES.copy()
