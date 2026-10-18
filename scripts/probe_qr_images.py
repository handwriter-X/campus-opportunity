"""探针：公众号正文里到底有几张图、几张**真的能解出二维码**。

## 为什么要先做这个

"把图片列表交给大模型，让它挑出报名二维码"这条路，实测站不住：

- 微信 `<img>` 的 `alt` **全是空的**
- 图片前后的文字经常是空标签，或者只有"供稿：某某"

⇒ 模型没有任何可依据的信号。**二维码应该"解"，不是"猜"。**

这个脚本只做测量，不写任何业务数据：把每篇文章的 `<img>` 抽出来、下载、解码，
打印「几张图 / 几张是二维码 / 解出什么内容」。

## 判断标准（诚实的边界）

| 码型 | 能不能解 |
| --- | --- |
| 标准二维码（问卷星、腾讯文档、飞书表单…） | ✅ |
| Micro QR / DataMatrix | ✅（同样用 zxing） |
| **微信小程序码（圆形的「向日葵」码）** | ❌ **不是 QR，解不出来** |

所以输出里 **`qr=0` 不代表"没有报名入口"**，只代表"没有标准二维码"。

## 用法

```bash
# 先把 We-MP-RSS 的库拷出来（见 docs/findings.md）
python scripts/probe_qr_images.py --db /tmp/wx.db --limit 15

# 只看统计
python scripts/probe_qr_images.py --db /tmp/wx.db --limit 15 --quiet
```

依赖：`pip install zxing-cpp pillow`
"""

from __future__ import annotations

import argparse
import io
import re
import sqlite3
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from typing import Any

try:
    import zxingcpp
    from PIL import Image
except ImportError:  # pragma: no cover - 只在没装依赖时走到
    zxingcpp = None
    Image = None

IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
SRC_RE = re.compile(r"""\b(?:data-src|src)\s*=\s*["']([^"']+)["']""", re.I)
ALT_RE = re.compile(r"""\balt\s*=\s*["']([^"']*)["']""", re.I)

# 只认真正的图片 CDN；公众号正文里还有大量 data: 占位和表情图
IMAGE_HOSTS = ("mmbiz.qpic.cn", "mmbiz.qlogo.cn", "mmbiz.qpic.cn/")
MAX_BYTES = 5 * 1024 * 1024


def image_urls(html: str) -> list[str]:
    """正文 HTML → 图片 URL 列表（去重、保持顺序）。"""
    out: list[str] = []
    for tag in IMG_RE.findall(html or ""):
        for src in SRC_RE.findall(tag):
            url = unescape(src).strip()
            if not url.startswith(("http://", "https://")):
                continue
            if not any(host in url for host in IMAGE_HOSTS):
                continue
            if url not in out:
                out.append(url)
    return out


def alts(html: str) -> list[str]:
    return [unescape(a).strip() for a in ALT_RE.findall(html or "")]


def decode(url: str, timeout: float) -> dict[str, Any]:
    """下载一张图并解码。**任何失败都只记原因，不抛异常。**"""
    result: dict[str, Any] = {"url": url, "codes": [], "error": ""}
    if zxingcpp is None:
        result["error"] = "缺少 zxing-cpp"
        return result
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            result["error"] = "图片过大"
            return result
        image = Image.open(io.BytesIO(payload))
        result["size"] = image.size
        for code in zxingcpp.read_barcodes(image):
            result["codes"].append({"format": code.format.name, "text": code.text})
    except Exception as exc:  # noqa: BLE001 —— 探针不该因为一张图崩掉
        result["error"] = f"{type(exc).__name__}: {exc}"[:80]
    return result


def fetch_article(url: str, timeout: float = 20.0) -> tuple[str, str]:
    """直接抓一篇公众号文章（不经过采集器）。返回 `(标题, HTML)`。"""
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", "replace")
    match = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    title = unescape(match.group(1)).strip() if match else url
    return title, html


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", help="We-MP-RSS 的 sqlite 路径（和 --url 二选一）")
    parser.add_argument("--url", action="append", default=[],
                        help="直接给一篇文章的 URL，可重复")
    parser.add_argument("--limit", type=int, default=15, help="看最近几篇")
    parser.add_argument("--max-images", type=int, default=20, help="每篇最多看几张图")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--quiet", action="store_true", help="只打统计")
    args = parser.parse_args()

    if zxingcpp is None or Image is None:
        print("❌ 缺依赖：pip install zxing-cpp pillow")
        return 1

    if args.url:
        articles = []
        for url in args.url:
            try:
                title, html = fetch_article(url, timeout=max(args.timeout, 20.0))
            except Exception as exc:  # noqa: BLE001
                print(f"❌ 抓取失败 {url}：{type(exc).__name__}: {exc}")
                continue
            articles.append((title, html))
        if not articles:
            print("❌ 一篇都没抓到")
            return 1
        print(f"直接抓取 {len(articles)} 篇文章\n")
    elif args.db:
        con = sqlite3.connect(args.db)
        cur = con.cursor()
        cur.execute(
            "select title, content from articles "
            "where content is not null and content != '' "
            "order by id desc limit ?",
            (args.limit,),
        )
        articles = cur.fetchall()
        print(f"扫描 {len(articles)} 篇文章\n")
    else:
        print("❌ 要么给 --db，要么给 --url")
        return 1

    total_images = 0
    total_with_qr = 0
    total_articles_with_qr = 0

    for title, content in articles:
        urls = image_urls(content)
        sample = urls[: args.max_images]
        total_images += len(sample)
        if not sample:
            print(f"— {str(title)[:38]}｜0 张图")
            continue

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(lambda u: decode(u, args.timeout), sample))

        hits = [r for r in results if r["codes"]]
        total_with_qr += len(hits)
        if hits:
            total_articles_with_qr += 1

        print(f"— {str(title)[:38]}｜图片 {len(urls)} 张"
              f"（看了 {len(sample)}）｜**二维码 {len(hits)} 张**")
        if not args.quiet:
            for r in hits:
                for code in r["codes"]:
                    print(f"     ✅ {code['format']}  {code['text'][:80]}")
            errors = [r for r in results if r["error"]]
            if errors and len(errors) < len(results):
                print(f"     （{len(errors)} 张下载失败，已跳过）")

    print("\n" + "=" * 60)
    print(f"合计：图片 {total_images} 张，其中二维码 {total_with_qr} 张，"
          f"涉及 {total_articles_with_qr} 篇文章")
    print("⚠️ 小程序码不是标准 QR，解不出来 —— qr=0 不等于没有报名入口")
    return 0


if __name__ == "__main__":
    sys.exit(main())
