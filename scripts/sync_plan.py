#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""江浙沪皖国资招聘雷达同步计划。

fast: 每天运行，HTML/API 信源 + 自动发现的市县政府门户。
slow: Playwright 高校就业网等慢源。
full: fast + slow。
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from job_radar import sync
from scripts import filter_target_jobs, export_target_html

DISCOVERED = os.path.join(ROOT, "config", "discovered_sources.csv")


def _read_csv(path: str) -> list[dict[str, str]]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(lines)]


def _install_merged_sources() -> None:
    """让 sync.run() 同时读取基础 sources.csv 与自动发现的 discovered_sources.csv。"""
    base_reader = sync.read_sources

    def merged(path=None):
        base = base_reader(sync.SOURCES_CSV if path is None else path)
        if path is not None and path != sync.SOURCES_CSV:
            return base
        extra = _read_csv(DISCOVERED)
        seen = {r.get("source_id") for r in base}
        base.extend(r for r in extra if r.get("source_id") not in seen)
        return base

    sync.read_sources = merged  # type: ignore[assignment]


_install_merged_sources()

CORE_SOURCE_IDS = {"cn-iguopin", "gov-sasac", "gov-qyzp", "gov-ncss", "gov-mohrss"}


def _active_sources() -> list[dict[str, str]]:
    return [s for s in sync.read_sources() if s.get("status") in ("active", "unstable")]


def _fast_source_ids() -> set[str]:
    ids = set(CORE_SOURCE_IDS)
    for src in _active_sources():
        sid = src.get("source_id", "")
        method = src.get("fetch_method", "")
        # 区域官方源、自动发现市县源、非Playwright高校源、企业官网源
        if sid.startswith(("reg-", "auto-gov-")) and method != "playwright":
            ids.add(sid)
        if sid.startswith("edu-") and method != "playwright":
            ids.add(sid)
        if src.get("org_type") == "soe" and method != "playwright":
            ids.add(sid)
    return ids


def _slow_source_ids() -> set[str]:
    ids: set[str] = set()
    for src in _active_sources():
        sid = src.get("source_id", "")
        if src.get("fetch_method") == "playwright" and (
            sid.startswith(("edu-", "reg-", "auto-gov-")) or src.get("org_type") == "soe"
        ):
            ids.add(sid)
    return ids


def _postprocess() -> None:
    filter_target_jobs.main()
    export_target_html.main()


def _run(label: str, ids: set[str]) -> None:
    print("=" * 70)
    print(f"🚦 {label}")
    print(f"信源数量：{len(ids)}")
    print("=" * 70)
    for sid in sorted(ids):
        print(f"  - {sid}")
    if ids:
        sync.run(only_source_ids=ids, preserve_unselected=True)
    _postprocess()


def run_plan(plan: str) -> None:
    if plan == "fast":
        _run("江浙沪皖国资招聘雷达｜每日快扫", _fast_source_ids())
    elif plan == "slow":
        _run("江浙沪皖国资招聘雷达｜慢源补扫", _slow_source_ids())
    elif plan == "full":
        _run("江浙沪皖国资招聘雷达｜完整扫描", _fast_source_ids() | _slow_source_ids())
    else:
        raise SystemExit(f"未知计划：{plan}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("plan", choices=["fast", "slow", "full"])
    a = p.parse_args()
    run_plan(a.plan)


if __name__ == "__main__":
    main()
