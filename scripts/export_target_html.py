#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成江浙沪皖国资招聘雷达静态网页 data/jobs.html。"""
from __future__ import annotations

import html
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from job_radar.target_rules import clean, region_name, recruitment_kind, source_tier, parse_date, today

DATA = os.path.join(ROOT, "data")
SRC = os.path.join(DATA, "target_jobs.json")
OUT = os.path.join(DATA, "jobs.html")


def esc(v) -> str:
    return html.escape(clean(v), quote=True)


def deadline_display(job: dict) -> str:
    raw = clean(job.get("deadline"))
    d = parse_date(raw)
    if not d:
        return raw or "见公告"
    left = (d - today()).days
    if left == 0:
        return f"{d.isoformat()}（今天截止）"
    if 0 < left <= 7:
        return f"{d.isoformat()}（剩{left}天）"
    return d.isoformat()


def card(job: dict) -> str:
    company = esc(job.get("company_name") or "未知单位")
    title = esc(job.get("title") or "招聘公告")
    region = esc(region_name(job))
    loc = esc(job.get("location") or region_name(job))
    kind = esc(recruitment_kind(job))
    source = esc(source_tier(job))
    pub = esc(clean(job.get("publish_time"))[:10] or clean(job.get("first_seen"))[:10] or "见公告")
    ddl = esc(deadline_display(job))
    url = clean(job.get("official_url") or job.get("backup_url"))
    link = f'<a class="open" target="_blank" rel="noopener" href="{esc(url)}">打开招聘公告</a>' if url else ''
    search = esc(" ".join([company, title, region, loc, kind, source]))
    return f'''<article class="card" data-region="{region}" data-kind="{kind}" data-search="{search}">
      <div class="badges"><span>{region}</span><span>{kind}</span></div>
      <h3>{company}</h3>
      <div class="title">{title}</div>
      <div class="meta">地区：{loc}　发布：{pub}　截止：{ddl}</div>
      <div class="source">{source}</div>
      {link}
    </article>'''


def main() -> None:
    os.makedirs(DATA, exist_ok=True)
    if os.path.exists(SRC):
        with open(SRC, encoding="utf-8") as f:
            jobs = json.load(f)
    else:
        jobs = []

    counts = {r: 0 for r in ["浙江", "江苏", "上海", "安徽", "其他地区"]}
    for j in jobs:
        counts[region_name(j)] = counts.get(region_name(j), 0) + 1

    cards = "\n".join(card(j) for j in jobs)
    stats = "".join(f'<button class="chip" data-filter="{r}">{r} {counts.get(r,0)}</button>' for r in ["浙江","江苏","上海","安徽","其他地区"])

    doc = f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>江浙沪皖国资招聘雷达</title>
<style>
body{{font-family:system-ui,-apple-system,"Microsoft YaHei",sans-serif;margin:0;background:#f6f8fa;color:#1f2328}}
.wrap{{max-width:1100px;margin:auto;padding:24px}}h1{{margin:0 0 6px}}.sub{{color:#57606a;margin-bottom:18px}}
.toolbar{{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 18px}}input{{flex:1;min-width:260px;padding:11px 12px;border:1px solid #d0d7de;border-radius:8px;background:white}}
.chip{{border:1px solid #d0d7de;background:white;border-radius:999px;padding:8px 12px;cursor:pointer}}.chip.active{{background:#24292f;color:white}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:12px}}.card{{background:white;border:1px solid #d8dee4;border-radius:12px;padding:15px;box-shadow:0 1px 2px rgba(0,0,0,.03)}}
.card h3{{margin:10px 0 6px;font-size:17px}}.title{{font-weight:600;line-height:1.5}}.meta,.source{{font-size:13px;color:#57606a;margin-top:8px;line-height:1.6}}
.badges span{{display:inline-block;font-size:12px;background:#ddf4ff;border-radius:999px;padding:3px 8px;margin-right:5px}}.open{{display:inline-block;margin-top:11px;text-decoration:none;color:#0969da;font-weight:600}}
.empty{{display:none;text-align:center;padding:50px;color:#57606a}}.topnote{{background:#fff8c5;border:1px solid #d4a72c;border-radius:8px;padding:10px 12px;margin-bottom:14px;font-size:13px}}
</style>
</head><body><div class="wrap">
<h1>🎯 江浙沪皖国资招聘雷达</h1><div class="sub">国央企 + 地方国企 + 事业单位/编外补充｜当前 {len(jobs)} 条</div>
<div class="topnote">信源采用官方政府/国资/人社、企业官网、高校就业网、国家招聘平台多源交叉；同一公告优先保留官方链接。</div>
<div class="toolbar"><input id="q" placeholder="搜索企业、岗位、城市、招聘类型……">{stats}<button class="chip active" data-filter="ALL">全部 {len(jobs)}</button></div>
<div id="grid" class="grid">{cards}</div><div id="empty" class="empty">没有匹配结果</div>
</div>
<script>
const q=document.getElementById('q'), cards=[...document.querySelectorAll('.card')], chips=[...document.querySelectorAll('.chip')];let filter='ALL';
function render(){{let n=0;const text=q.value.trim().toLowerCase();cards.forEach(c=>{{const okf=filter==='ALL'||c.dataset.region===filter;const okt=!text||c.dataset.search.toLowerCase().includes(text);c.style.display=okf&&okt?'':'none';if(okf&&okt)n++;}});document.getElementById('empty').style.display=n?'none':'block';}}
q.addEventListener('input',render);chips.forEach(b=>b.addEventListener('click',()=>{{filter=b.dataset.filter;chips.forEach(x=>x.classList.remove('active'));b.classList.add('active');render();}}));
</script></body></html>'''

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"✅ 已生成招聘信息台：{OUT}（{len(jobs)} 条）")


if __name__ == "__main__":
    main()
