"""卡片断言的小工具 —— 同时兼容 JSON 1.0 与 2.0。

2.0 的按钮**没有 `action` 容器**，直接是 `body.elements` 里的 `tag: button`，
跳转/回调放在 `behaviors` 里；1.0 则是 `action.actions[]` + `url/value`。
测试只关心"有哪些按钮、按钮写了什么、点了会怎样"，所以这里统一抽象。
"""
from __future__ import annotations

from typing import Any, Iterator


def elements(card: dict[str, Any]) -> list[dict[str, Any]]:
    body = card.get("body")
    if isinstance(body, dict) and isinstance(body.get("elements"), list):
        return body["elements"]
    return card.get("elements") or []


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def buttons(card: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in _walk(card):
        if node.get("tag") == "button":
            out.append(node)
        elif node.get("tag") == "action":
            out.extend(a for a in node.get("actions") or [] if isinstance(a, dict))
    return out


def button_label(button: dict[str, Any]) -> str:
    return ((button.get("text") or {}).get("content")) or ""


def button_url(button: dict[str, Any]) -> str:
    if button.get("url"):
        return button["url"]
    for behavior in button.get("behaviors") or []:
        if behavior.get("type") == "open_url":
            return behavior.get("default_url") or ""
    return ""


def button_value(button: dict[str, Any]) -> dict[str, Any]:
    if isinstance(button.get("value"), dict):
        return button["value"]
    for behavior in button.get("behaviors") or []:
        if behavior.get("type") == "callback":
            return behavior.get("value") or {}
    return {}


def all_text(card: dict[str, Any]) -> str:
    import json

    return json.dumps(card, ensure_ascii=False)
