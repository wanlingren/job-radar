#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动发现江浙沪皖市/区/县政府官网，生成 config/discovered_sources.csv。

策略：
1) 从四省市政府官网递归寻找“人民政府/区县政府/市县政府”官方链接；
2) 下载公开行政区划数据，仅用于核对“哪些市县还没发现”；
3) --full 时，对未发现的行政区用 Bing RSS 做一次官方 gov.cn 兜底查找；
4) 结果缓存到 discovered_sources.csv，日常 fast 直接复用，不重复搜索。

绝不把搜索结果当成招聘本身，只把它用于定位官方 gov.cn 门户。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import deque
from html import unescape
from urllib.parse import urljoin, urlparse, urldefrag

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config")
SEEDS = os.path.join(CONFIG, "discovery_seeds.csv")
OUT = os.path.join(CONFIG, "discovered_sources.csv")
CACHE = os.path.join(ROOT, "data", "discovery_cache.json")

TARGET_PROVINCE_CODES = {"31": "上海", "32": "江苏", "33": "浙江", "34": "安徽"}
AREAS_URL = "https://raw.githubusercontent.com/modood/Administrative-divisions-of-China/master/dist/areas.json"
CITIES_URL = "https://raw.githubusercontent.com/modood/Administrative-divisions-of-China/master/dist/cities.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
A_TAG = re.compile(r'<a\b([^>]*?)href=["\']([^"\']+)["\']([^>]*?)>(.*?)</a>', re.S | re.I)
TAGS = re.compile(r"<[^>]+>")
SP = re.compile(r"\s+")
GOV_LABEL = re.compile(r"(人民政府|政府门户|管委会|新区政府|区政府|县政府|市政府)")
NAV = re.compile(r"(市县|区县|各市|各区|各县|地方政府|政府网站|友情链接|网站导航)")
NOTICE_NAV = re.compile(r"(招聘|招考|人事|人才|事业单位|国企|国资|就业|通知公告|公示公告)")


def _get(url: str, timeout: int = 12) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        raw = r.read(900000)
        ctype = (r.headers.get("Content-Type") or "").lower()
        enc = "utf-8"
        m = re.search(r"charset=([\w-]+)", ctype)
        if m:
            enc = m.group(1)
        try:
            return raw.decode(enc, "replace")
        except Exception:
            return raw.decode("utf-8", "replace")


def _json(url: str):
    return json.loads(_get(url, timeout=20))


def _links(html: str, base: str):
    for _, href, _, inner in A_TAG.findall(html):
        text = SP.sub(" ", unescape(TAGS.sub(" ", inner))).strip()
        if not text or href.startswith(("javascript:", "#", "mailto:", "tel:")):
            continue
        url = urldefrag(urljoin(base, href))[0]
        if url.startswith(("http://", "https://")):
            yield text, url


def _is_gov_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("gov.cn") or ".gov.cn" in host


def _root(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme or 'https'}://{p.netloc}/"


def _clean_label(text: str) -> str:
    text = SP.sub("", text)
    text = re.sub(r"[›>→\-—|｜·•【】\[\]（）()]", "", text)
    return text[:40]


def _source_id(url: str) -> str:
    host = (urlparse(url).hostname or url).lower()
    return "auto-gov-" + hashlib.sha1(host.encode("utf-8")).hexdigest()[:10]


def _load_seeds():
    with open(SEEDS, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_cache() -> dict:
    if os.path.exists(CACHE):
        try:
            with open(CACHE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"sites": {}}


def _save_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
        f.write("\n")


def discover_from_portals(max_pages: int = 80) -> dict[str, dict]:
    """省 -> 市 -> 区县：递归发现 gov.cn 门户。"""
    found: dict[str, dict] = {}
    q = deque()
    for s in _load_seeds():
        q.append((s["url"], s["location"], s["name"], 0))

    visited = set()
    while q and len(visited) < max_pages:
        url, province, label, generation = q.popleft()
        root = _root(url)
        if root in visited:
            continue
        visited.add(root)
        found[root] = {"url": root, "province": province, "label": label}

        try:
            html = _get(url)
        except Exception as e:
            print(f"  ⚠ 无法读取 {url}: {e}")
            continue

        # 先找“市县政府/友情链接”等导航，再找直接出现的人民政府链接
        nav_pages = []
        for text, link in _links(html, url):
            if NOTICE_NAV.search(text) and _root(link) == root:
                found[root].setdefault("notice_url", link)
            if _is_gov_url(link) and GOV_LABEL.search(text):
                r = _root(link)
                lab = _clean_label(text)
                if r not in found:
                    found[r] = {"url": r, "province": province, "label": lab}
                if generation < 2:
                    q.append((link, province, lab, generation + 1))
            elif NAV.search(text) and (_is_gov_url(link) or _root(link) == root):
                nav_pages.append(link)

        for np in nav_pages[:6]:
            try:
                nhtml = _get(np)
            except Exception:
                continue
            for text, link in _links(nhtml, np):
                if _is_gov_url(link) and GOV_LABEL.search(text):
                    r = _root(link)
                    lab = _clean_label(text)
                    if r not in found:
                        found[r] = {"url": r, "province": province, "label": lab}
                    if generation < 2:
                        q.append((link, province, lab, generation + 1))
    return found


def expected_units() -> list[dict]:
    """用公开行政区划数据核对市/县名称。数据只作发现线索。"""
    try:
        cities = _json(CITIES_URL)
        areas = _json(AREAS_URL)
    except Exception as e:
        print(f"  ⚠ 行政区划核对数据下载失败：{e}")
        return []

    city_map = {str(x.get("code")): x for x in cities if str(x.get("provinceCode")) in TARGET_PROVINCE_CODES}
    out = []
    for c in city_map.values():
        pcode = str(c.get("provinceCode"))
        out.append({"name": c.get("name", ""), "province": TARGET_PROVINCE_CODES[pcode], "city": c.get("name", "")})
    for a in areas:
        pcode = str(a.get("provinceCode"))
        if pcode not in TARGET_PROVINCE_CODES:
            continue
        city = city_map.get(str(a.get("cityCode")), {}).get("name", "")
        out.append({"name": a.get("name", ""), "province": TARGET_PROVINCE_CODES[pcode], "city": city})
    return [x for x in out if x["name"]]


def _bing_find(unit: dict) -> str:
    """无 API Key 的一次性兜底。失败就返回空，不影响主流程。"""
    name = unit["name"]
    province = unit["province"]
    query = f'"{name}人民政府" {province} site:gov.cn'
    url = "https://www.bing.com/search?format=rss&q=" + urllib.parse.quote(query)
    try:
        xml = _get(url, timeout=10)
        root = ET.fromstring(xml)
    except Exception:
        return ""
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if name.replace("市", "").replace("区", "").replace("县", "")[:2] not in title:
            continue
        if _is_gov_url(link):
            return _root(link)
    return ""


def enrich_missing(found: dict[str, dict], *, full: bool) -> tuple[dict[str, dict], list[str]]:
    units = expected_units()
    labels = " ".join(x.get("label", "") for x in found.values())
    missing = [u for u in units if u["name"] not in labels]
    print(f"📍 行政区划核对：{len(units)} 个市/县级单位；当前名称匹配缺口 {len(missing)} 个")
    unresolved = []
    if not full:
        return found, [u["name"] for u in missing]

    for i, u in enumerate(missing, 1):
        print(f"  🔎 兜底查找 {i}/{len(missing)}：{u['province']} {u['city']} {u['name']}")
        url = _bing_find(u)
        if url:
            found[url] = {"url": url, "province": u["province"], "label": f"{u['name']}人民政府"}
        else:
            unresolved.append(u["name"])
        time.sleep(0.35)
    return found, unresolved


def write_sources(found: dict[str, dict]) -> None:
    fields = ["source_id", "company_name", "org_type", "source_type", "adapter", "endpoint", "priority", "fetch_method", "requires_login", "city_scope", "poll_interval_minutes", "status", "notes"]
    rows = []
    for site in sorted(found.values(), key=lambda x: (x.get("province", ""), x.get("label", ""))):
        label = site.get("label") or "地方政府"
        province = site.get("province") or ""
        url = site["url"]
        endpoint_url = site.get("notice_url") or url
        rows.append({
            "source_id": _source_id(url),
            "company_name": label,
            "org_type": "public_institution",
            "source_type": "official",
            "adapter": "regional_notice",
            "endpoint": f"{endpoint_url}||{province}·{label.replace('人民政府', '').replace('政府门户', '').strip()}||{label}||government",
            "priority": "2",
            "fetch_method": "html",
            "requires_login": "no",
            "city_scope": f"{province}·{label}",
            "poll_interval_minutes": "1440",
            "status": "active",
            "notes": "自动发现的市/区/县政府官方门户；用于招聘公告下沉补漏",
        })
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"✅ 自动发现官方门户 {len(rows)} 个，写入 {OUT}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--full", action="store_true", help="对未发现的市县使用 Bing RSS 兜底查找；建议每周运行")
    p.add_argument("--max-pages", type=int, default=90)
    args = p.parse_args()

    cache = _load_cache()
    found = {k: v for k, v in cache.get("sites", {}).items()}
    newly = discover_from_portals(args.max_pages)
    found.update(newly)
    found, unresolved = enrich_missing(found, full=args.full)
    cache["sites"] = found
    cache["unresolved"] = unresolved
    cache["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_cache(cache)
    write_sources(found)
    if unresolved:
        print(f"⚠ 仍有 {len(unresolved)} 个行政区名称未自动定位；不会阻断任务，后续每周继续补全。")
        print("   示例：" + "、".join(unresolved[:20]))


if __name__ == "__main__":
    main()
