"""飞书表单链接 —— **按人预填**。

## 为什么要有这一层

【队友画像】表里有一个 `姓名` 文本题，让用户自己打名字有三个毛病：

1. 会打错（错别字、英文名、微信昵称）
2. 会填成别人（"帮我室友也填一个"）
3. 和 `飞书账号` 那个人员字段**天然重复** —— 人员字段已经带着 `name` 了

飞书表单支持 **URL 预填**，格式是：

```
https://…/share/base/shrcnXXXX?prefill_姓名=谢国辉
```

题目名**必须和表单里完全一致**（改了题目就要改这里）。
特殊字符要 URL 编码 —— 中文名字、空格、`&` 都算。

### 所以

发链接之前，用**收件人自己的名字**拼一条专属链接。用户打开表单时
姓名那一栏已经是 TA 自己的，改都不用改。

> ⚠️ **预填不是只读**，用户仍然可以改。真要"只允许本人"，表单做不到 ——
> 那是产品限制，别在代码里假装能拦住。
> 但预填把"默认正确"变成了常态，"故意冒充"才需要额外动作。

## 什么时候预填不了

**不知道这个人叫什么。** 两种来源，按顺序取：

1. 【队友画像】表里的 `姓名`（已经有了画像的人）
2. 飞书通讯录接口（第一次用的人）—— **需要
   `contact:contact.base:readonly` 权限**，没开就返回 `99991672`

两样都拿不到就不预填，链接原样发出去 —— 别为了预填把消息发失败。
"""

from __future__ import annotations

from typing import Mapping
from urllib.parse import quote, urlsplit, urlunsplit

# 题目名（**必须和表单里的题干逐字一致**）
PROFILE_NAME_QUESTION = "姓名"
PROFILE_OWNER_QUESTION = "飞书账号"
REQUEST_OWNER_QUESTION = "发起人"


def prefill_form(
    url: str,
    answers: Mapping[str, str],
    *,
    hidden: tuple[str, ...] = (),
) -> str:
    """给表单链接加上 `prefill_<题目>=<值>`（可选：把它**隐藏**起来让人改不了）。

    - 链接**已经带查询串**时用 `&` 接上（分享链接常常带着 `?from=…`）
    - 空值跳过（预填空字符串会把题目清空）
    - 已经含 `prefill_` 的不重复加（幂等，避免 `?prefill_a=1&prefill_a=1`）

    ## `hide_<题目>=1`

    飞书表单的题目**没有"只读"** —— 预填之后用户照样能改。
    唯一的办法是**把题目藏起来**：值照样带进去，但界面上不出现。

    > ⚠️ **待验证**（2026-10-17）：官方帮助页是 JS 渲染的，正文抓不到，
    > "隐藏的题目会不会**照常提交**"没有白纸黑字的说法。
    > 已知的风险面：隐藏 + 必填 时，如果值没提交，表单**可能提交不了**。
    > 第一次用这条链接必须**真提交一条**、再回表里看那几格有没有值。
    """
    base = (url or "").strip()
    if not base:
        return base
    parts = urlsplit(base)
    existing = parts.query or ""
    if "prefill_" in existing:
        return base
    params = [
        f"prefill_{quote(str(key), safe='')}={quote(str(value), safe='')}"
        for key, value in answers.items()
        if value
    ]
    # 只隐藏**确实预填了值**的题目 —— 藏一个空题等于让用户无从填写。
    params += [
        f"hide_{quote(str(key), safe='')}=1"
        for key in hidden
        if answers.get(key)
    ]
    extra = "&".join(params)
    if not extra:
        return base
    query = f"{existing}&{extra}" if existing else extra
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def personalize_links(
    text: str,
    *,
    name: str | None,
    profile_form_url: str = "",
    request_form_url: str = "",
) -> str:
    """把回复里的表单链接换成**带这个人姓名的**版本。

    ⚠️ **只做字符串替换，不做任何判断** —— 判断"该不该发链接"是智能体的事，
    gateway 只负责"发出去的时候把名字填对"（铁律 1）。

    身份类题目**预填但保持可见** —— 用户要能看见"这是我自己"。

    - 【队友画像】`姓名`（文本）+ `飞书账号`（人员）
    - 【发布组队需求】`发起人`（人员）

    ## ⚠️ 预填 ≠ 不可改

    **飞书表单没有只读字段**：题目只要可见，人就能改。
    所以"不能自选"**不是**靠这里保证的 —— 靠服务端的**系统字段 `创建人`**
    （飞书自动填提交人，谁都改不了）。见 `bitable.identity_open_ids`。

    这里只负责**把默认值填对**，让绝大多数人根本不用动那一题。

    > 人员字段的预填值按飞书要求是**完整姓名**（需是飞书联系人），**不是 open_id**。
    """
    if not text or not name:
        return text
    for url, answers in (
        (profile_form_url, {PROFILE_NAME_QUESTION: name, PROFILE_OWNER_QUESTION: name}),
        (request_form_url, {REQUEST_OWNER_QUESTION: name}),
    ):
        base = (url or "").strip()
        if not base or base not in text:
            continue
        text = text.replace(base, prefill_form(base, answers))
    return text
