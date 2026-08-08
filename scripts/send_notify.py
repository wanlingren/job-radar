#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""企业微信：每天只发送一条摘要；完整岗位在 GitHub Pages 查看。"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

import notify_preview

MAX_BYTES = 3900


def webhook_from_env() -> str:
    return os.getenv("WECHAT_WEBHOOK_URL", "").strip() or os.getenv("WECOM_WEBHOOK_URL", "").strip()


def _post(url: str, text: str) -> tuple[int, str]:
    payload = {"msgtype": "markdown", "markdown": {"content": text}}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except Exception as e:
        return 0, str(e)


def _ok(status: int, body: str) -> bool:
    if not 200 <= status < 300:
        return False
    try:
        return json.loads(body).get("errcode", -1) == 0
    except Exception:
        return False


def _fit(text: str) -> str:
    if len(text.encode("utf-8")) <= MAX_BYTES:
        return text
    # 摘要理论上很短；极端情况下保留头部并追加信息台提示
    b = text.encode("utf-8")[:MAX_BYTES - 100]
    while True:
        try:
            s = b.decode("utf-8")
            break
        except UnicodeDecodeError:
            b = b[:-1]
    return s + "\n\n> 内容较多，请点击招聘信息台查看全部。"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--state", default=notify_preview.STATE)
    p.add_argument("--webhook", default="")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-mark", action="store_true")
    p.add_argument("--workbench-url", default=os.getenv("WORKBENCH_URL", "").strip())
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--min-focus", type=int, default=0)
    p.add_argument("--min-match", type=int, default=0)
    p.add_argument("--since", default="")
    p.add_argument("--include-existing-due", action="store_true")
    a = p.parse_args()

    text, selected = notify_preview.build(
        mode="new", since=a.since, state_path=a.state, workbench_url=a.workbench_url
    )
    if not selected:
        print("✅ 当前没有新的未提醒招聘，跳过企业微信发送。")
        return
    text = _fit(text)
    print(f"📦 本次新增/未提醒 {len(selected)} 条；企业微信只发 1 条摘要，完整岗位在信息台。")
    if a.dry_run:
        print(text)
        return
    webhook = a.webhook.strip() or webhook_from_env()
    if not webhook:
        raise SystemExit("❌ 未配置 WECHAT_WEBHOOK_URL")
    status, body = _post(webhook, text)
    if not _ok(status, body):
        print(f"❌ 企业微信发送失败：HTTP {status} {body}", file=sys.stderr)
        raise SystemExit(1)
    print("✅ 企业微信单条摘要发送成功")
    if not a.no_mark:
        n = notify_preview.mark_pushed(a.state, selected)
        print(f"✅ 已将 {n} 条公告标记为已提醒（详情可在信息台查看）")


if __name__ == "__main__":
    main()
