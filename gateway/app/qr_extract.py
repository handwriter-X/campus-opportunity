"""从公众号正文的图片里**解出**报名链接。

## 为什么是"解"，不是"猜"

公众号经常只放一张二维码，没有可点的链接。一开始的想法是把图片列表交给大模型，
让它挑出"报名二维码"——实测**走不通**（`docs/findings.md` Q20）：

- 微信 `<img>` 的 `alt` **全是空的**
- 图片前后的文字常常是空标签，或者只有「供稿：某某」

模型没有任何可依据的信号。而二维码本身就是**可以解码**的：
`zxing-cpp` 直接读出码里的文本，是确定性测量，不是语义判断。

> 这也是它放在 gateway 而不是 GeniOS 的原因：**解码是测量**（和解析日期同类），
> 而且 GeniOS 的代码节点跑不了图片下载和解码。

## 实测出来的三条规则（见 Q20）

| 规则 | 依据 |
| --- | --- |
| **丢掉 `weixin.qq.com/r/`** | 那是文章末尾的「关注公众号」码，每篇都有 |
| **表单类优先** | 飞书表单 / 问卷星 / 腾讯文档 —— 这些才是"报名" |
| **加群链接不算报名** | `applink.feishu.cn/client/chat/…` 是咨询群，写进报名链接就是骗人 |

⚠️ **微信小程序码不是标准 QR**（圆形的「向日葵」码），解不出来。
`qr=0` 不等于"没有报名入口"。

## 失败时怎么办

**一律返回空。** 解码失败、图片下载失败、没装依赖 —— 都只是"没找到"，
绝不能因为它把一篇文章的处理链断掉。
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html import unescape

logger = logging.getLogger("gateway.qr")

try:  # 可选依赖：没装就退化成"不找"，不影响主链路
    import zxingcpp
    from PIL import Image
except ImportError:  # pragma: no cover - 生产环境应安装
    zxingcpp = None
    Image = None

# 一张海报可能印两个码；但文章动辄几十张图，全解太慢。
# 实测（2026-10-18）：某篇 22 张图的文章，报名二维码排在**第 13 张之后** ——
# 所以 12 张不够，20 张能覆盖到。再往上收益很低。
MAX_IMAGES = 20
MAX_BYTES = 5 * 1024 * 1024
DEFAULT_TIMEOUT = 5.0
MAX_WORKERS = 4

_IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
_SRC_RE = re.compile(r"""\b(?:data-src|src)\s*=\s*["']([^"']+)["']""", re.I)
_IMAGE_HOSTS = ("mmbiz.qpic.cn", "mmbiz.qlogo.cn")

# 「关注公众号」码 —— 每篇文章都有，和报名无关
FOLLOW_MARKERS = ("weixin.qq.com/r/",)

# 表单类：优先级最高（这些点下去真的能报名）
FORM_HOSTS = (
    "feishu.cn/share/base/form",
    "wjx.cn",
    "wj.qq.com",
    "docs.qq.com/form",
    "jinshuju.net",
    "wenjuan.com",
)

# 加群类：能点，但**不是报名**。只用来解释"报名方式"。
CHAT_HOSTS = ("applink.feishu.cn/client/chat",)

_warned = False


def image_urls(html: str, limit: int = MAX_IMAGES) -> list[str]:
    """正文 HTML → 图片 URL（去重、保序、只用公众号图床）。"""
    out: list[str] = []
    for tag in _IMG_RE.findall(html or ""):
        for src in _SRC_RE.findall(tag):
            url = unescape(src).strip()
            if not url.startswith(("http://", "https://")):
                continue
            if not any(host in url for host in _IMAGE_HOSTS):
                continue
            if url not in out:
                out.append(url)
            if len(out) >= limit:
                return out
    return out


def collect(codes: list[str]) -> tuple[list[str], list[str]]:
    """码文本 → `(表单候选, 加群候选)`，保持文章里的先后顺序。"""
    usable = [
        (code or "").strip()
        for code in codes
        if (code or "").strip().startswith(("http://", "https://"))
        and not any(marker in code for marker in FOLLOW_MARKERS)
    ]
    forms = [u for u in usable if any(host in u for host in FORM_HOSTS)]
    chats = [u for u in usable if any(host in u for host in CHAT_HOSTS)]
    return forms, chats


def choose_signup(codes: list[str]) -> tuple[str, str]:
    """从解出来的码文本里挑报名入口。返回 `(signup_url, 报名方式提示)`。

    纯函数 —— 不联网，方便用真实样本做测试。
    多个表单候选时这里只取第一个；真正的取舍见 `pick_form`。
    """
    forms, chats = collect(codes)
    if forms:
        return forms[0], ""
    if chats:
        return "", "扫描二维码加入咨询群"
    return "", ""


# 标题里出现这些词，说明它是**报名**表；出现后一组，说明是别的用途。
SIGNUP_WORDS = ("报名", "登记", "申请", "入群")
OTHER_WORDS = ("征集", "调研", "反馈", "满意度", "评价", "投票", "签到")


def title_score(title: str) -> int:
    """给表单标题打分。读不到标题就是 0（中性），**绝不因为读不到就扣分**。"""
    text = title or ""
    score = 0
    if any(word in text for word in SIGNUP_WORDS):
        score += 3
    if any(word in text for word in OTHER_WORDS):
        score -= 2
    return score


def _fetch_title(url: str, timeout: float = 5.0) -> str:
    """抓表单页面读标题。读不到就返回空串。

    - **问卷星**：`<title>` 就是问卷名（实测可用）
    - **飞书表单**：分享页的 `<title>` 是空的，页面里的「活动报名登记表」是
      **模板文案**（每个表单页面都有，实测两页完全相同）—— 所以读不到真名，返回空。
    """
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            html = response.read(400_000).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        logger.debug("读表单标题失败 %s：%s", url[:60], exc)
        return ""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    return unescape(match.group(1)).strip() if match else ""


async def pick_form(forms: list[str]) -> str:
    """多个表单候选时，按标题挑最像"报名"的那个。

    ⚠️ **只在候选 ≥2 时才联网读标题** —— 绝大多数文章只有一个问卷，
    那条路径一次请求都不该多发。
    """
    if not forms:
        return ""
    if len(forms) == 1:
        return forms[0]
    titles = await asyncio.gather(
        *(asyncio.to_thread(_fetch_title, url) for url in forms[:3])
    )
    best = max(range(len(titles)), key=lambda i: (title_score(titles[i]), -i))
    logger.info(
        "多个表单候选，按标题选择：%s",
        ", ".join(f"{t or '(读不到)'}={title_score(t)}" for t in titles),
    )
    return forms[best]


def _decode_one(url: str, timeout: float) -> list[str]:
    """下载一张图并解码，返回码里的文本。**任何失败都只返回空。**"""
    global _warned
    if zxingcpp is None or Image is None:
        if not _warned:
            logger.warning("没装 zxing-cpp / pillow，跳过二维码识别（pip install zxing-cpp pillow）")
            _warned = True
        return []
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            return []
        image = Image.open(io.BytesIO(payload))
        return [code.text for code in zxingcpp.read_barcodes(image) if code.text]
    except Exception as exc:  # noqa: BLE001 —— 一张图失败不能影响整篇
        logger.debug("解码失败 %s：%s", url[:60], exc)
        return []


def _decode_all(urls: list[str], timeout: float) -> list[str]:
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        chunks = pool.map(lambda u: _decode_one(u, timeout), urls)
        return [code for chunk in chunks for code in chunk]


async def find_signup_link(
    html: str, *, timeout: float = DEFAULT_TIMEOUT, limit: int = MAX_IMAGES
) -> tuple[str, str]:
    """从正文 HTML 里找报名入口。永远返回二元组，永远不抛异常。"""
    urls = image_urls(html, limit=limit)
    if not urls:
        return "", ""
    try:
        # 下载 + 解码是阻塞 IO，丢到线程里，别卡住事件循环
        codes = await asyncio.to_thread(_decode_all, urls, timeout)
    except Exception as exc:  # noqa: BLE001
        logger.warning("二维码识别失败（跳过）：%s", exc)
        return "", ""
    forms, chats = collect(codes)
    if forms:
        url = await pick_form(forms)
        if url:
            logger.info("从正文图片里解出报名入口：%s", url)
            return url, ""
    if chats:
        logger.info("解出的入口是加群链接（不是报名表单）")
        return "", "扫描二维码加入咨询群"
    return "", ""


def html_of(raw_payload: object) -> str:
    """从存下来的原始载荷里取出正文 HTML。

    We-MP-RSS 的 `content` 被 JSON 转义过一次（`\"`），这里顺手还原。
    """
    if not isinstance(raw_payload, dict):
        return ""
    content = raw_payload.get("content")
    if content is None and isinstance(raw_payload.get("articles"), list):
        first = raw_payload["articles"][0] if raw_payload["articles"] else {}
        content = first.get("content") if isinstance(first, dict) else None
    if not isinstance(content, str):
        return ""
    # 采集器把 content 做了一次 json.dumps 再掐掉首尾引号，所以正文里是 \" 和 \n。
    # 逆操作就是**再包一层引号**解析回去；解析不了说明本来就没转义，原样用。
    if '\\"' in content or "\\n" in content:
        try:
            content = json.loads('"' + content + '"')
        except ValueError:
            pass
    return content


async def enrich_payload(payload: dict, raw_payload: object) -> bool:
    """把「从正文图片里解出的报名入口」并进抽取结果。返回是否改了东西。

    worker 只需要调这一个函数 —— 取 HTML、解码、合并都在这里，
    而且**任何一步失败都只是返回 False**，不影响文章入库。
    """
    html = html_of(raw_payload)
    if not html or not payload.get("items"):
        return False
    signup_url, method_hint = await find_signup_link(html)
    return apply_signup(payload, signup_url, method_hint)


def apply_signup(payload: dict, signup_url: str, method_hint: str) -> bool:
    """把解出来的入口并进抽取结果。返回是否真的改了。

    ⚠️ **只在"一篇文章一个机会"时并入** —— 一篇文章多个机会时，
    没人知道那张二维码属于哪一个，宁可不填，也不能张冠李戴。
    """
    items = [i for i in (payload.get("items") or []) if isinstance(i, dict)]
    if len(items) != 1:
        return False
    item = items[0]
    changed = False
    if signup_url and not item.get("signup_url"):
        item["signup_url"] = signup_url
        changed = True
    if method_hint and not item.get("signup_method_text"):
        item["signup_method_text"] = method_hint
        changed = True
    return changed
