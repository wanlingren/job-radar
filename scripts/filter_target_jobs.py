#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 data/jobs.json 生成仅含目标招聘的 data/target_jobs.json。"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from job_radar.target_rules import is_target_job, priority, clean

DATA = os.path.join(ROOT, "data")
SRC = os.path.join(DATA, "jobs.json")
OUT = os.path.join(DATA, "target_jobs.json")


def _title(job: dict) -> str:
    return clean(job.get("title"))


def _semantic(job: dict) -> str:
    company = clean(job.get("company_name")).lower()
    title = _title(job).lower()
    # 去掉少量来源加上的装饰词，减少同一公告跨来源重复
    title = re.sub(r"[【】\[\]（）()<>《》·•|｜]", "", title)
    title = re.sub(r"\s+", "", title)
    location = clean(job.get("location")).lower()
    return f"{company}|{title}|{location}"


def _source_score(job: dict) -> int:
    sid = clean(job.get("source_id"))
    if sid.startswith(("reg-sasac-", "reg-gov-", "reg-hrss-", "auto-gov-", "auto-hrss-", "auto-sasac-", "auto-job-")):
        return 100
    if sid in {"gov-sasac", "gov-qyzp"}:
        return 98
    if clean(job.get("org_type")).lower() == "soe":
        return 95
    if sid.startswith(("edu-", "auto-edu-")):
        return 80
    if sid in {"cn-iguopin", "gov-ncss", "gov-mohrss"}:
        return 75
    return 60


def main() -> None:
    os.makedirs(DATA, exist_ok=True)
    if not os.path.exists(SRC):
        rows = []
    else:
        with open(SRC, encoding="utf-8") as f:
            rows = json.load(f)

    targets = [r for r in rows if is_target_job(r)]

    # 跨来源语义去重：优先官方来源
    unique: dict[str, dict] = {}
    for row in targets:
        key = _semantic(row)
        old = unique.get(key)
        if old is None or _source_score(row) > _source_score(old):
            unique[key] = row

    result = list(unique.values())
    result.sort(key=priority, reverse=True)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"✅ 目标招聘库：原始 {len(rows)} 条 → 目标 {len(targets)} 条 → 去重后 {len(result)} 条")
    print(f"✅ 已写入 {OUT}")


if __name__ == "__main__":
    main()
