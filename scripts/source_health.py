#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""信源健康检查：避免某个官方站点失效后静默漏报。"""
from __future__ import annotations

import argparse
import csv
import json
import os
import ssl
import time
import urllib.request
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config")
DATA = os.path.join(ROOT, "data")
FILES = [
    os.path.join(CONFIG, "sources.csv"),
    os.path.join(CONFIG, "discovered_sources.csv"),
    os.path.join(CONFIG, "discovered_universities.csv"),
]
OUT = os.path.join(DATA, "source_health_v21.json")
SUMMARY = os.path.join(DATA, "source_health_v21.md")
UA = "Mozilla/5.0 Chrome/124 Safari/537.36"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def read_rows() -> list[dict[str, str]]:
    out = []
    seen = set()
    for path in FILES:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
        if not lines:
            continue
        for r in csv.DictReader(lines):
            sid = (r.get("source_id") or "").strip()
            if not sid or sid in seen:
                continue
            seen.add(sid)
            out.append({k: (v or "").strip() for k, v in r.items()})
    return out


def root_endpoint(row: dict[str, str]) -> str:
    return (row.get("endpoint") or "").split("||", 1)[0].strip()


def probe(url: str, timeout: int = 8) -> tuple[bool, int, str]:
    if not url.startswith(("http://", "https://")):
        return False, 0, "bad-url"
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return 200 <= r.status < 400, r.status, "ok"
    except Exception as e:
        code = getattr(e, "code", 0) or 0
        return False, int(code), type(e).__name__


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0, help="0=全部；日常可设80减少耗时")
    a = p.parse_args()
    rows = [r for r in read_rows() if r.get("status") in ("active", "unstable")]
    if a.limit > 0:
        rows = rows[:a.limit]
    results = []
    for i, r in enumerate(rows, 1):
        url = root_endpoint(r)
        ok, status, err = probe(url)
        results.append({
            "source_id": r.get("source_id"),
            "name": r.get("company_name"),
            "url": url,
            "ok": ok,
            "http_status": status,
            "error": err,
        })
        print(f"{'✅' if ok else '⚠'} {i}/{len(rows)} {r.get('source_id')} HTTP={status} {err}")
        time.sleep(0.02)
    os.makedirs(DATA, exist_ok=True)
    payload = {"checked_at": time.strftime("%Y-%m-%d %H:%M:%S"), "total": len(results), "ok": sum(1 for x in results if x["ok"]), "items": results}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    bad = [x for x in results if not x["ok"]]
    lines = ["# 信源健康检查 V2.1", "", f"- 检查：{len(results)}", f"- 正常：{len(results)-len(bad)}", f"- 异常：{len(bad)}", "", "## 异常信源"]
    lines += [f"- {x['source_id']}｜{x['name']}｜HTTP {x['http_status']}｜{x['error']}｜{x['url']}" for x in bad]
    with open(SUMMARY, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"✅ 健康检查完成：{len(results)-len(bad)}/{len(results)} 正常")


if __name__ == "__main__":
    main()
