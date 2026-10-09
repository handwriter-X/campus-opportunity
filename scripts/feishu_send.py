"""用飞书自建应用发消息（机会闭环的最后一步）。

## 为什么用自建应用而不是群自定义机器人

PLAN §4 的首选是「群自定义机器人 Webhook」。但本项目最终要跑在校内网、被飞连挡着，
**自建应用 + 长连接**这条通道已经验证过（见 `docs/findings.md` S6），
发消息也走同一套凭据，不用再维护第二套密钥。

## 用法

    # 发给某个用户（open_id 以 ou_ 开头）
    python scripts/feishu_send.py --to ou_xxxxxxxx --text "测试消息"

    # 发给某个群（chat_id 以 oc_ 开头）
    python scripts/feishu_send.py --to oc_xxxxxxxx --text "测试消息"

    # 发富文本卡片（post 格式）
    python scripts/feishu_send.py --to ou_xxx --json @card.json

凭据从 `.env` 读：`FEISHU_APP_ID` / `FEISHU_APP_SECRET`。

⚠️ `tenant_access_token` **只在进程内使用，不落盘、不打印**。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
FEISHU_BASE = "https://open.feishu.cn/open-apis"


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    return values


def id_type_of(identifier: str) -> str:
    if identifier.startswith("oc_"):
        return "chat_id"
    if identifier.startswith("ou_"):
        return "open_id"
    return "open_id"


def build_client() -> httpx.Client:
    """不带代理 —— 本机的 ALL_PROXY 是 socks5，飞书是直连可达的。"""
    return httpx.Client(timeout=20.0, trust_env=False)


def get_tenant_token(client: httpx.Client, app_id: str, app_secret: str) -> str:
    """换取 tenant_access_token。返回值只留在内存里，绝不打印或写文件。"""
    response = client.post(
        f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
    )
    response.raise_for_status()
    data = response.json()
    token = data.get("tenant_access_token")
    if not token:
        raise SystemExit(f"换取 token 失败：code={data.get('code')} msg={data.get('msg')}")
    return token


def send(client: httpx.Client, token: str, to: str, msg_type: str, content: dict) -> dict:
    response = client.post(
        f"{FEISHU_BASE}/im/v1/messages",
        params={"receive_id_type": id_type_of(to)},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "receive_id": to,
            "msg_type": msg_type,
            "content": json.dumps(content, ensure_ascii=False),
        },
    )
    try:
        return response.json()
    except ValueError:
        return {"code": -1, "msg": f"HTTP {response.status_code}: {response.text[:300]}"}


def main() -> int:
    parser = argparse.ArgumentParser(description="飞书自建应用发消息")
    parser.add_argument("--to", required=True, help="open_id（ou_…）或 chat_id（oc_…）")
    parser.add_argument("--text", help="发纯文本")
    parser.add_argument("--json", help="发自定义消息体（JSON 字符串，或以 @ 开头读文件）")
    parser.add_argument("--msg-type", default="text", help="消息类型，默认 text")
    args = parser.parse_args()

    env = load_env()
    app_id = os.environ.get("FEISHU_APP_ID") or env.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET") or env.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        raise SystemExit("缺少 FEISHU_APP_ID / FEISHU_APP_SECRET（应放在 .env）")

    if args.text:
        msg_type, content = "text", {"text": args.text}
    elif args.json:
        raw = Path(args.json[1:]).read_text(encoding="utf-8") if args.json.startswith("@") else args.json
        msg_type, content = args.msg_type, json.loads(raw)
    else:
        raise SystemExit("要么给 --text，要么给 --json")

    with build_client() as client:
        token = get_tenant_token(client, app_id, app_secret)
        result = send(client, token, args.to, msg_type, content)

    print(json.dumps(result, ensure_ascii=False, indent=1)[:800])
    if result.get("code") not in (0, None):
        print("\n⚠️ 发送失败。常见原因：", file=sys.stderr)
        print("  · 应用没有 im:message 权限 → 去开放平台「权限管理」开通并重新发布", file=sys.stderr)
        print("  · 用户还没和机器人说过话 → p2p 消息要求先建立会话", file=sys.stderr)
        print("  · 应用版本没发布 → 权限改了必须重新发布才生效", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
