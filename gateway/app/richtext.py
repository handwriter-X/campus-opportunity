"""把大模型返回的 **Markdown** 转成飞书**富文本消息**（`msg_type=post`）。

## 为什么必须转

GeniOS 的回复是 Markdown：

```
你这条件挺全能的，推荐这几个：

- **智能体应用创新大赛**（编程+设计都能用上）：https://…
```

而 `msg_type=text` 里 **`**` 会原样显示** —— 用户看到的是满屏星号。
（这是实测踩过的：机器人回复里带着 `- **活动名**`。）

飞书虽然也支持 `msg_type=post`（富文本），但它的结构是**段落数组 + 行内片段**，
不是 Markdown，所以要在 gateway 里翻一次。

## 支持的范围（**刻意只做这些**）

| Markdown | 转成 |
| --- | --- |
| `**加粗**` | 行内 `bold` |
| `[文字](链接)` | 行内 `a` |
| `- 项目` / `* 项目` | `• 项目` |
| `### 标题` | 整行加粗（去掉 `#`） |
| `` `代码` `` | 去掉反引号（纯文本） |
| `> 引用` | 去掉 `>` |
| ```` ``` ```` 围栏 | 只保留围栏里的内容 |

**长表格、图片、嵌套列表都不管** —— 模型本来也不该在聊天里输出那些。
转不了的内容**原样保留**，宁可丑一点，不能丢信息。
"""

from __future__ import annotations

import re
from typing import Any

# 行内 token：先认加粗，再认链接（顺序会影响 `**[x](y)**` 的切分）
_INLINE_RE = re.compile(r"(\*\*.+?\*\*|\[[^\]]*\]\([^)]*\))")
_BOLD_RE = re.compile(r"^\*\*(.+)\*\*$", re.S)
_LINK_RE = re.compile(r"^\[([^\]]*)\]\(([^)]*)\)$")
_HEADING_RE = re.compile(r"^#{1,6}\s+")
_BULLET_RE = re.compile(r"^[-*+]\s+")
_FENCE_RE = re.compile(r"^\s*```")


def _inline(text: str) -> list[dict[str, Any]]:
    """一行文本 → 飞书行内片段数组。"""
    parts: list[dict[str, Any]] = []
    for chunk in _INLINE_RE.split(text):
        if not chunk:
            continue
        bold = _BOLD_RE.match(chunk)
        if bold:
            parts.append({"tag": "text", "text": bold.group(1), "style": ["bold"]})
            continue
        link = _LINK_RE.match(chunk)
        if link:
            parts.append({"tag": "a", "text": link.group(1) or link.group(2),
                          "href": link.group(2)})
            continue
        parts.append({"tag": "text", "text": chunk})
    return parts


def markdown_to_post(markdown: str) -> dict[str, Any] | None:
    """Markdown → `msg_type=post` 的 content。

    没有任何可用内容时返回 `None`（调用方退回纯文本，别发一条空消息）。
    """
    lines = (markdown or "").replace("\r\n", "\n").split("\n")
    paragraphs: list[list[dict[str, Any]]] = []
    in_fence = False

    for raw in lines:
        line = raw.rstrip()
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue

        stripped = line.strip()
        if not stripped:
            continue                      # 空行只当分隔，不产生空段落

        if not in_fence:
            if stripped.startswith(">"):
                stripped = stripped.lstrip(">").strip()
            heading = _HEADING_RE.match(stripped)
            if heading:
                stripped = stripped[heading.end():].strip()
                if stripped:
                    paragraphs.append([{"tag": "text", "text": stripped, "style": ["bold"]}])
                continue
            bullet = _BULLET_RE.match(stripped)
            if bullet:
                stripped = "• " + stripped[bullet.end():]

        # 行内代码去掉反引号：飞书 post 没有等宽字体，留着反而难看
        stripped = stripped.replace("`", "")

        parts = _inline(stripped)
        if parts:
            paragraphs.append(parts)

    if not paragraphs:
        return None
    return {"zh_cn": {"content": paragraphs}}
