# tasks/languages.py — 支持的语言注册表

# (code, 中文名) — 按常用程度排序
SUPPORTED_LANGUAGES: list[tuple[str, str]] = [
    # 东亚
    ("zh", "中文"),
    ("en", "英语"),
    ("ja", "日语"),
    ("ko", "韩语"),
    ("yue", "粤语"),
    # 欧洲
    ("fr", "法语"),
    ("de", "德语"),
    ("es", "西班牙语"),
    ("pt", "葡萄牙语"),
    ("it", "意大利语"),
    ("ru", "俄语"),
    ("nl", "荷兰语"),
    ("pl", "波兰语"),
    ("cs", "捷克语"),
    ("uk", "乌克兰语"),
    ("tr", "土耳其语"),
    ("he", "希伯来语"),
    # 南亚 / 东南亚
    ("th", "泰语"),
    ("vi", "越南语"),
    ("ms", "马来语"),
    ("id", "印尼语"),
    ("tl", "菲律宾语"),
    ("hi", "印地语"),
    ("bn", "孟加拉语"),
    ("ta", "泰米尔语"),
    ("te", "泰卢固语"),
    ("mr", "马拉地语"),
    ("gu", "古吉拉特语"),
    ("ur", "乌尔都语"),
    # 中东 / 中亚
    ("ar", "阿拉伯语"),
    ("fa", "波斯语"),
    ("km", "高棉语"),
    ("my", "缅甸语"),
    # 其他
    ("zh-Hant", "繁体中文"),
    ("bo", "藏语"),
    ("kk", "哈萨克语"),
    ("mn", "蒙古语"),
    ("ug", "维吾尔语"),
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
