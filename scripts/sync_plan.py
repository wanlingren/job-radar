#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""江浙沪皖国资招聘雷达 V2.3 同步计划。

fast: 每天运行，国家平台 + 固定官方源 + 已验证市县政府/人社/国资源 + HTML高校就业源。
slow: Playwright高校就业网/慢源。
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

DISCOVERED_FILES = [
    os.path.join(ROOT, "config", "discovered_sources.csv"),
    os.path.join(ROOT, "config", "discovered_universities.csv"),
    os.path.join(ROOT, "config", "discovered_company_sources.csv"),
    os.path.join(ROOT, "config", "discovered_watchlist_sources.csv"),
    os.path.join(ROOT, "config", "discovered_manual_sources.csv"),
]


def _read_csv(path: str) -> list[dict[str, str]]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return []
    return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(lines)]


def merged_sources() -> list[dict[str, str]]:
    rows = list(sync.read_sources())
    seen = {r.get("source_id") for r in rows}
    for path in DISCOVERED_FILES:
        for r in _read_csv(path):
            sid = r.get("source_id")
            if sid and sid not in seen:
                rows.append(r)
                seen.add(sid)
    return rows


def _install_merged_sources() -> None:
    base_reader = sync.read_sources

    def merged(path=None):
        base = base_reader(sync.SOURCES_CSV if path is None else path)
        if path is not None and path != sync.SOURCES_CSV:
            return base
        seen = {r.get("source_id") for r in base}
        for extra_path in DISCOVERED_FILES:
            for r in _read_csv(extra_path):
                sid = r.get("source_id")
                if sid and sid not in seen:
                    base.append(r)
                    seen.add(sid)
        return base

    sync.read_sources = merged  # type: ignore[assignment]


_install_merged_sources()

CORE_SOURCE_IDS = {"cn-iguopin", "gov-sasac", "gov-qyzp", "gov-ncss", "gov-mohrss"}
AUTO_PREFIXES = ("auto-gov-", "auto-hrss-", "auto-sasac-", "auto-job-", "auto-edu-", "soe-company-", "watch-", "manual-")


def _active_sources() -> list[dict[str, str]]:
    return [s for s in sync.read_sources() if s.get("status") in ("active", "unstable")]


def _fast_source_ids() -> set[str]:
    ids = set(CORE_SOURCE_IDS)
    for src in _active_sources():
        sid = src.get("source_id", "")
        method = src.get("fetch_method", "")
        if method == "playwright":
            continue
        if sid.startswith(("reg-", "edu-") + AUTO_PREFIXES):
            ids.add(sid)
        if src.get("org_type") == "soe":
            ids.add(sid)
    return ids


def _slow_source_ids() -> set[str]:
    ids: set[str] = set()
    for src in _active_sources():
        sid = src.get("source_id", "")
        if src.get("fetch_method") != "playwright":
            continue
        if sid.startswith(("reg-", "edu-") + AUTO_PREFIXES) or src.get("org_type") == "soe":
            ids.add(sid)
    return ids


def _postprocess() -> None:
    filter_target_jobs.main()
    export_target_html.main()


def _run(label: str, ids: set[str]) -> None:
    print("=" * 72)
    print(f"🚦 {label}")
    print(f"信源数量：{len(ids)}")
    print("=" * 72)
    for sid in sorted(ids):
        print(f"  - {sid}")
    if ids:
        sync.run(only_source_ids=ids, preserve_unselected=True)
    else:
        print("⚠ 当前计划没有可执行信源；仍会重建目标库和信息台。")
    _postprocess()


def run_plan(plan: str) -> None:
    if plan == "fast":
        _run("江浙沪皖国资招聘雷达 V2.3｜每日快扫", _fast_source_ids())
    elif plan == "slow":
        _run("江浙沪皖国资招聘雷达 V2.3｜慢源补扫", _slow_source_ids())
    elif plan == "full":
        _run("江浙沪皖国资招聘雷达 V2.3｜完整扫描", _fast_source_ids() | _slow_source_ids())
    else:
        raise SystemExit(f"未知计划：{plan}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("plan", choices=["fast", "slow", "full"])
    a = p.parse_args()
    run_plan(a.plan)


if __name__ == "__main__":
    main()
