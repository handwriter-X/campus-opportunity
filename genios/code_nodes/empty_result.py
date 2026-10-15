"""GeniOS 非机会分支的统一空结果节点。

把意图识别判为“非机会”的文章转换为与抽取/校验分支相同的 End 输出契约。
该节点只负责结果形状，不重新判断文章内容，也不写入数据库。
"""

import json


def _collect(obj, keys, found=None):
    """递归读取 GeniOS 连线输入，兼容平铺字典和字符串 JSON 信封。"""
    if found is None:
        found = {}
    if isinstance(obj, str):
        text = obj.strip()
        if text[:1] in "{[":
            try:
                _collect(json.loads(text), keys, found)
            except (TypeError, ValueError):
                pass
        return found
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in keys and key not in found:
                found[key] = value
            _collect(value, keys, found)
    elif isinstance(obj, list):
        for value in obj:
            _collect(value, keys, found)
    return found


def handler(inputs):
    """GeniOS 代码节点入口：返回非机会文章的结构化空结果。"""
    collected = _collect(inputs, {"article_id"})
    result = {
        "ok": False,
        "is_opportunity": False,
        "article_id": collected.get("article_id"),
        "items": [],
        "first_item": None,
        "issues": [],
        "item_count": 0,
    }
    result["result"] = {
        key: result[key]
        for key in ("ok", "is_opportunity", "article_id", "items", "issues", "item_count")
    }
    return result
