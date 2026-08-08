#!/usr/bin/env python3

"""
27届国央企招聘雷达
================

fast:
    每日扫描国聘、国资委、央企应届招聘专栏、
    24365、人社部，以及无需浏览器的高校就业网。

slow:
    补扫需要 Playwright 的高校就业网。

full:
    fast + slow。

本版本不再扫描互联网公司、外企、实习僧、牛客等普通招聘源。
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from job_radar import sync
from scripts import export_html


# ==============================
# 国央企招聘核心信源
# ==============================

CORE_SOURCE_IDS = {
    "cn-iguopin",   # 国聘
    "gov-sasac",    # 国务院国资委
    "gov-qyzp",     # 中央企业招聘应届高校毕业生信息公开
    "gov-ncss",     # 国家大学生就业服务平台 24365
    "gov-mohrss",   # 中国公共招聘网 / 人社部
}


def _active_sources() -> list[dict[str, str]]:
    """读取当前可运行信源。"""
    return [
        s
        for s in sync.read_sources()
        if s.get("status") in ("active", "unstable")
    ]


def _fast_source_ids() -> set[str]:
    """
    每日快扫。

    包括：
    1. 国聘
    2. 国务院国资委
    3. 央企应届生招聘专栏
    4. 24365
    5. 人社部公共招聘
    6. 无需 Playwright 的高校就业网
    7. 已接入且可直接抓取的央国企官方源
    """

    ids = set(CORE_SOURCE_IDS)

    for src in _active_sources():
        sid = src.get("source_id", "")
        method = src.get("fetch_method", "")
        org_type = src.get("org_type", "")

        # 高校就业网
        if sid.startswith("edu-") and method != "playwright":
            ids.add(sid)

        # 已接入且正常工作的央国企官方源
        if org_type == "soe" and method != "playwright":
            ids.add(sid)

    return ids


def _slow_source_ids() -> set[str]:
    """
    慢源补扫。

    只运行需要 Playwright 的高校就业网
    和已接入的央国企浏览器源。
    """

    ids: set[str] = set()

    for src in _active_sources():
        sid = src.get("source_id", "")
        method = src.get("fetch_method", "")
        org_type = src.get("org_type", "")

        if sid.startswith("edu-") and method == "playwright":
            ids.add(sid)

        if org_type == "soe" and method == "playwright":
            ids.add(sid)

    return ids


def _run_sources(label: str, ids: set[str]) -> None:
    if not ids:
        raise SystemExit(f"{label}：没有可运行信源")

    print("=" * 60)
    print(f"🚦 {label}")
    print(f"信源数量：{len(ids)}")
    print("=" * 60)

    for sid in sorted(ids):
        print(f"  - {sid}")

    sync.run(
        only_source_ids=ids,
        preserve_unselected=True,
    )

    export_html.main()


def run_plan(plan: str) -> None:

    if plan == "fast":
        _run_sources(
            "27届国央企招聘雷达｜每日快扫",
            _fast_source_ids(),
        )
        return

    if plan == "slow":
        _run_sources(
            "27届国央企招聘雷达｜高校就业网补扫",
            _slow_source_ids(),
        )
        return

    if plan == "full":
        ids = _fast_source_ids() | _slow_source_ids()

        _run_sources(
            "27届国央企招聘雷达｜完整扫描",
            ids,
        )
        return

    raise SystemExit(f"未知扫描计划：{plan}")


def main() -> None:

    parser = argparse.ArgumentParser(
        description="27届国央企招聘雷达"
    )

    parser.add_argument(
        "plan",
        choices=[
            "fast",
            "slow",
            "full",
        ],
    )

    args = parser.parse_args()

    run_plan(args.plan)


if __name__ == "__main__":
    main()
