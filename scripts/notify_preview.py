#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成“每天一条”的企业微信摘要，并维护去重状态。"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from job_radar.target_rules import clean, region_name, recruitment_kind, parse_date, priority, today

DATA = os.path.join(ROOT, "data")
JOBS = os.path.join(DATA, "target_jobs.json")
OUT = os.path.join(DATA, "notify_preview.md")
STATE = os.path.join(DATA, "notify_state.json")
DEFAULT_WORKBENCH_URL = os.getenv("WORKBENCH_URL", "").strip()


def job_key(job: dict) -> str:
    return clean(job.get("dedup_key") or job.get("job_id") or job.get("official_url") or f"{job.get('company_name','')}|{job.get('title','')}|{job.get('location','')}")


def semantic_key(job: dict) -> str:
    return "|".join([
        clean(job.get("company_name")).lower(),
        clean(job.get("title")).lower().replace(" ", ""),
        clean(job.get("location")).lower(),
    ])


def load_state(path: str = STATE) -> dict:
    default = {"version": 3, "pushed_keys": {}, "semantic_keys": {}}
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
    except Exception:
        return default
    s.setdefault("pushed_keys", {})
    s.setdefault("semantic_keys", {})
    s["version"] = 3
    return s


def is_pushed(job: dict, state: dict) -> bool:
    return job_key(job) in state.get("pushed_keys", {}) or semantic_key(job) in state.get("semantic_keys", {})


def mark_pushed(path: str, jobs: list[dict]) -> int:
    s = load_state(path)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    added = 0
    for j in jobs:
        k, sk = job_key(j), semantic_key(j)
        if k and k not in s["pushed_keys"]:
            s["pushed_keys"][k] = {
                "pushed_at": now,
                "company": clean(j.get("company_name")),
                "title": clean(j.get("title")),
                "source_id": clean(j.get("source_id")),
            }
            added += 1
        if sk:
            s["semantic_keys"][sk] = now
    s["last_marked_at"] = now
    s["last_marked_count"] = added
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return added


def _urgent(job: dict) -> int:
    d = parse_date(job.get("deadline", ""))
    if not d:
        return 9999
    return (d - today()).days


def _short_line(job: dict) -> str:
    company = clean(job.get("company_name")) or "未知单位"
    title = clean(job.get("title")) or "招聘公告"
    url = clean(job.get("official_url"))
    left = _urgent(job)
    ddl = f"｜{left}天后截止" if 0 <= left <= 7 else ""
    text = f"{company}｜{title}{ddl}"
    if len(text) > 58:
        text = text[:56] + "…"
    return f"- [{text}]({url})" if url else f"- {text}"


def build(
    limit: int = 0,
    min_focus: int = 0,
    min_match: int = 0,
    mode: str = "new",
    since: str = "",
    include_existing_due: bool = False,
    state_path: str = STATE,
    ignore_state: bool = False,
    workbench_url: str = DEFAULT_WORKBENCH_URL,
) -> tuple[str, list[dict]]:
    _ = limit, min_focus, min_match, include_existing_due
    if os.path.exists(JOBS):
        with open(JOBS, encoding="utf-8") as f:
            jobs = json.load(f)
    else:
        jobs = []
    jobs.sort(key=priority, reverse=True)
    state = load_state(state_path) if not ignore_state else {"pushed_keys": {}, "semantic_keys": {}}
    selected = jobs if mode == "all" else [j for j in jobs if not is_pushed(j, state)]
    if since:
        selected = [j for j in selected if clean(j.get("first_seen"))[:10] >= since]

    region_counts = {k: 0 for k in ["浙江", "江苏", "上海", "安徽", "其他地区"]}
    kind_counts: dict[str, int] = {}
    for j in selected:
        region_counts[region_name(j)] = region_counts.get(region_name(j), 0) + 1
        k = recruitment_kind(j)
        kind_counts[k] = kind_counts.get(k, 0) + 1

    urgent = [j for j in selected if 0 <= _urgent(j) <= 7]
    urgent.sort(key=lambda j: (_urgent(j), priority(j)), reverse=False)
    featured = urgent[:6]
    for j in selected:
        if len(featured) >= 10:
            break
        if j not in featured:
            featured.append(j)

    lines = [
        f"# 🎯 江浙沪皖国资招聘雷达｜{today().isoformat()}",
        "",
        f"> 今日待提醒：**{len(selected)} 条**｜7天内截止：**{len(urgent)} 条**",
        "",
        f"> 📍 浙江 {region_counts.get('浙江',0)}｜江苏 {region_counts.get('江苏',0)}｜上海 {region_counts.get('上海',0)}｜安徽 {region_counts.get('安徽',0)}",
        "",
    ]
    preferred_kinds = ["⭐27届校园招聘", "🟦校园招聘/应届生", "🟨国企公开招聘", "🟧国企社会招聘", "🟩事业单位/人才引进", "🟪事业单位/编外", "⬜政府官方招聘公告"]
    kind_text = "｜".join(f"{k} {kind_counts[k]}" for k in preferred_kinds if kind_counts.get(k))
    if kind_text:
        lines += [f"> {kind_text}", ""]
    if workbench_url:
        lines += [f"[📋 一次查看全部 {len(selected)} 条招聘信息]({workbench_url})", ""]
    if featured:
        lines += ["## 🔥 优先查看", ""]
        lines += [_short_line(j) for j in featured]
        lines.append("")
    if not selected:
        lines += ["今天没有新的未提醒招聘。", ""]
    lines += ["> 官方政府/国资/人社 + 企业官网 + 高校就业网 + 国家招聘平台多源交叉；已提醒公告自动去重。"]
    return "\n".join(lines), selected


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=OUT)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--min-focus", type=int, default=0)
    p.add_argument("--min-match", type=int, default=0)
    p.add_argument("--mode", choices=("new", "all"), default="new")
    p.add_argument("--since", default="")
    p.add_argument("--include-existing-due", action="store_true")
    p.add_argument("--state", default=STATE)
    p.add_argument("--ignore-state", action="store_true")
    p.add_argument("--mark-pushed", action="store_true")
    p.add_argument("--workbench-url", default=DEFAULT_WORKBENCH_URL)
    a = p.parse_args()
    md, selected = build(a.limit, a.min_focus, a.min_match, a.mode, a.since, a.include_existing_due, a.state, a.ignore_state, a.workbench_url)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"✅ 单条摘要已生成：{a.out}；待提醒 {len(selected)} 条")
    if a.mark_pushed:
        print(f"✅ 标记 {mark_pushed(a.state, selected)} 条")


if __name__ == "__main__":
    main()
