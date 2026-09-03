#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动扩充江浙沪皖国企主体库。

数据源：
1. 国务院国资委央企名录；
2. 江浙沪皖省/市/区县国资监管官方页面（含 discover_sources 已发现的国资源）；
3. 现有官方国资招聘公告中实际出现的企业；
4. 人工 seed registry。

输出：
- config/soe_registry_generated.csv    自动发现主体
- config/discovered_company_sources.csv 有官网链接时生成公司官网抓取源
- data/soe_registry.json               seed + generated 合并后的 AI/审计友好版本

自动发现只做“高置信补充”，不会删除人工 seed。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import ssl
import sys
import urllib.request
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from job_radar.soe_matcher import normalize_name, reload_registry, match_company

CONFIG = os.path.join(ROOT, "config")
DATA = os.path.join(ROOT, "data")
SEED = os.path.join(CONFIG, "soe_registry.csv")
GENERATED = os.path.join(CONFIG, "soe_registry_generated.csv")
REGISTRY_SOURCES = os.path.join(CONFIG, "soe_registry_sources.csv")
COMPANY_SOURCES = os.path.join(CONFIG, "discovered_company_sources.csv")
COMBINED_JSON = os.path.join(DATA, "soe_registry.json")

REG_COLS = ['entity_id','canonical_name','short_name','aliases','level','parent_group','province','city','district','org_type','regulator','website','recruit_url','wechat','source_url','confidence','last_verified']
SRC_COLS = ['source_id','company_name','org_type','source_type','adapter','endpoint','priority','fetch_method','requires_login','city_scope','poll_interval_minutes','status','notes']

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

LIST_HINT_RE = re.compile(r"监管企业|监管单位|省属企业|市属企业|区属企业|县属企业|所属企业|出资企业|企业名录|国企名录|企业名单|成员企业|集团成员")
COMPANY_SUFFIX_RE = re.compile(r"(?:有限责任公司|股份有限公司|集团有限公司|控股有限公司|有限公司|集团|银行|证券|研究院|研究所)$")
COMPANY_FIND_RE = re.compile(
    r"([\u4e00-\u9fffA-Za-z0-9（）()·&—\-]{3,70}?(?:有限责任公司|股份有限公司|集团有限公司|控股有限公司|有限公司))"
)
RECRUIT_HINT = re.compile(r"招聘|人才招聘|加入我们|招贤纳士|校园招聘|社会招聘|人力资源")
REGION_MAP = {"浙江": "浙江", "江苏": "江苏", "上海": "上海", "安徽": "安徽"}


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.texts: list[str] = []
        self._href = ""
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = dict(attrs).get("href", "")
            self._buf = []

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href:
            text = re.sub(r"\s+", " ", " ".join(self._buf)).strip()
            if text:
                self.links.append((text, self._href))
            self._href = ""
            self._buf = []

    def handle_data(self, data):
        s = re.sub(r"\s+", " ", data or "").strip()
        if not s:
            return
        self.texts.append(s)
        if self._href:
            self._buf.append(s)


def _read_csv(path: str) -> list[dict[str, str]]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return []
    return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(lines)]


def _write_csv(path: str, rows: list[dict], fields: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _get(url: str, timeout: int = 12) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
        raw = r.read(900000)
        ctype = (r.headers.get("Content-Type") or "").lower()
        m = re.search(r"charset=([\w-]+)", ctype)
        enc = m.group(1) if m else "utf-8"
        try:
            return raw.decode(enc, "replace")
        except LookupError:
            return raw.decode("utf-8", "replace")


def _parse(html: str, base: str) -> tuple[str, list[tuple[str, str]]]:
    p = LinkParser()
    p.feed(html)
    text = re.sub(r"\s+", " ", " ".join(p.texts)).strip()
    links = []
    for t, h in p.links:
        if h.startswith(("javascript:", "#", "mailto:", "tel:")):
            continue
        u = urljoin(base, h)
        if u.startswith(("http://", "https://")):
            links.append((unescape(t).strip(), u))
    return text, links


def _same_domain(a: str, b: str) -> bool:
    ha = (urlparse(a).hostname or "").lower()
    hb = (urlparse(b).hostname or "").lower()
    if ha == hb:
        return True
    aa, bb = ha.split("."), hb.split(".")
    return len(aa) >= 3 and len(bb) >= 3 and aa[-3:] == bb[-3:]


def _clean_company_text(s: str) -> str:
    s = re.sub(r"^[\d一二三四五六七八九十]+[.、．\s]+", "", s.strip())
    s = s.strip("【】[]（）()<>《》：:，,。;；|｜-— ")
    return re.sub(r"\s+", "", s)


def _looks_company(s: str, on_official_list: bool = False) -> bool:
    s = _clean_company_text(s)
    if not (3 <= len(s) <= 80):
        return False
    bad = ("国资委", "人民政府", "人力资源", "通知公告", "政策", "新闻", "招聘", "名录", "名单", "监管单位", "监管企业")
    if any(x in s for x in bad):
        return False
    if COMPANY_SUFFIX_RE.search(s):
        return True
    if on_official_list and re.search(r"集团$|银行$|证券$|机场$|港口$|铁路$|农垦$|国信$|国投$|交控$|环保$|数据集团$", s):
        return True
    return False


def _region_from_source(row: dict) -> tuple[str, str, str]:
    scope = row.get("city_scope", "") or row.get("region", "")
    province = next((p for p in REGION_MAP if p in scope), "")
    city = ""
    if "·" in scope:
        parts = scope.split("·")
        if len(parts) > 1:
            city = parts[1]
    return province, city, ""


def _level_from_source(row: dict, province: str, city: str) -> str:
    sid = row.get("source_id", "")
    name = row.get("name", "") or row.get("company_name", "")
    if sid == "registry-central":
        return "央企集团"
    if city:
        return "市县属国企"
    if province == "上海":
        return "市属国企"
    if province:
        return "省属国企"
    if "央企" in name:
        return "央企集团"
    return "地方国企"


def _entity_id(name: str, prefix: str = "auto") -> str:
    return f"{prefix}-{hashlib.sha1(normalize_name(name).encode('utf-8')).hexdigest()[:12]}"


def _row(name: str, *, level: str, province: str = "", city: str = "", district: str = "", regulator: str = "", website: str = "", source_url: str = "", confidence: str = "official_discovered", parent: str = "") -> dict:
    canonical = _clean_company_text(name)
    return {
        "entity_id": _entity_id(canonical),
        "canonical_name": canonical,
        "short_name": "",
        "aliases": "",
        "level": level,
        "parent_group": parent,
        "province": province,
        "city": city,
        "district": district,
        "org_type": "soe",
        "regulator": regulator,
        "website": website,
        "recruit_url": "",
        "wechat": "",
        "source_url": source_url,
        "confidence": confidence,
        "last_verified": dt.date.today().isoformat(),
    }


def _discover_page(url: str, *, row: dict, max_child_pages: int = 4) -> list[dict]:
    province, city, district = _region_from_source(row)
    level = _level_from_source(row, province, city)
    regulator = row.get("name") or row.get("company_name") or "国资监管官方页面"
    out: dict[str, dict] = {}
    try:
        html = _get(url)
    except Exception as e:
        print(f"  ⚠ registry fetch failed {url}: {e}")
        return []
    text, links = _parse(html, url)

    # 中央名录和直接企业列表页：正文中直接抽完整公司名
    for name in COMPANY_FIND_RE.findall(text):
        if _looks_company(name):
            r = _row(name, level=level, province=province, city=city, district=district, regulator=regulator, source_url=url)
            out[normalize_name(r["canonical_name"])] = r

    # 链接文本通常能拿到简称或完整名，并能捕获企业官网 URL
    for title, link in links:
        if _looks_company(title, on_official_list=True):
            name = _clean_company_text(title)
            r = _row(name, level=level, province=province, city=city, district=district, regulator=regulator, website=link if not _same_domain(url, link) else "", source_url=url)
            out[normalize_name(name)] = r

    # 若首页不是直接名单，自动进入“监管企业/省属企业/市属企业”等页面
    child = [(t, u) for t, u in links if LIST_HINT_RE.search(t) and _same_domain(url, u)]
    for title, child_url in child[:max_child_pages]:
        try:
            h2 = _get(child_url)
            text2, links2 = _parse(h2, child_url)
        except Exception:
            continue
        for name in COMPANY_FIND_RE.findall(text2):
            if _looks_company(name):
                r = _row(name, level=level, province=province, city=city, district=district, regulator=regulator, source_url=child_url)
                out[normalize_name(r["canonical_name"])] = r
        for t, u in links2:
            if _looks_company(t, on_official_list=True):
                name = _clean_company_text(t)
                # 官方企业名单通常直接链接企业官网
                website = u if not _same_domain(child_url, u) else ""
                r = _row(name, level=level, province=province, city=city, district=district, regulator=regulator, website=website, source_url=child_url)
                out[normalize_name(name)] = r
    return list(out.values())


def _source_rows() -> list[dict]:
    rows = _read_csv(REGISTRY_SOURCES)
    # 利用现有已验证国资源把市/区县层一起纳入主体发现
    for fn in ("sources.csv", "discovered_sources.csv"):
        for r in _read_csv(os.path.join(CONFIG, fn)):
            sid = r.get("source_id", "")
            if "sasac" not in sid and "国资" not in (r.get("company_name", "") + r.get("notes", "")):
                continue
            endpoint = (r.get("endpoint", "") or "").split("||")[0]
            if not endpoint:
                continue
            rows.append({
                "source_id": sid,
                "name": r.get("company_name", ""),
                "region": r.get("city_scope", ""),
                "level": "local",
                "url": endpoint,
                "parser_hint": "discover_list",
                "status": r.get("status", "active"),
                "notes": r.get("notes", ""),
                "city_scope": r.get("city_scope", ""),
                "company_name": r.get("company_name", ""),
            })
    # 去 URL 重复
    seen, out = set(), []
    for r in rows:
        u = r.get("url", "")
        if not u or u in seen or r.get("status") == "blocked":
            continue
        seen.add(u)
        out.append(r)
    return out


def _from_existing_jobs() -> list[dict]:
    path = os.path.join(DATA, "jobs.json")
    if not os.path.exists(path):
        return []
    try:
        jobs = json.load(open(path, encoding="utf-8"))
    except Exception:
        return []
    out = []
    for j in jobs:
        sid = str(j.get("source_id") or "")
        name = _clean_company_text(str(j.get("company_name") or ""))
        text = " ".join(str(j.get(k) or "") for k in ("title", "jd_text", "org_type"))
        official_sasac = sid.startswith(("reg-sasac-", "auto-sasac-"))
        explicit_soe = re.search(r"国企|国有企业|国有控股|省属企业|市属企业|区属企业|县属企业|央企", text)
        if not name or not _looks_company(name, on_official_list=official_sasac):
            continue
        if not (official_sasac or explicit_soe or match_company(name)):
            continue
        province = next((p for p in REGION_MAP if p in str(j.get("location") or "") + text), "")
        level = "地方国企"
        if match_company(name):
            continue
        out.append(_row(name, level=level, province=province, regulator="官方招聘公告反向核验", source_url=str(j.get("official_url") or ""), confidence="official_job_observed"))
    return out


def _merge(seed: list[dict], generated: list[dict]) -> list[dict]:
    by_name = {normalize_name(r.get("canonical_name", "")): dict(r) for r in seed if r.get("canonical_name")}
    for r in generated:
        k = normalize_name(r.get("canonical_name", ""))
        if not k:
            continue
        if k in by_name:
            old = by_name[k]
            # 不覆盖人工 level/parent，只补官方链接/核验信息
            for fld in ("website", "recruit_url", "source_url", "last_verified"):
                if r.get(fld):
                    old[fld] = r[fld]
            if old.get("confidence", "").startswith("curated") and r.get("confidence", "").startswith("official"):
                old["confidence"] = r["confidence"]
        else:
            by_name[k] = r
    return list(by_name.values())


def _company_sources(combined: list[dict]) -> list[dict]:
    out = []
    seen = set()
    for r in combined:
        url = r.get("recruit_url") or r.get("website")
        if not url or not url.startswith(("http://", "https://")):
            continue
        key = (normalize_name(r.get("canonical_name", "")), url)
        if key in seen:
            continue
        seen.add(key)
        region = "·".join(x for x in (r.get("province", ""), r.get("city", ""), r.get("district", "")) if x)
        sid = "soe-company-" + hashlib.sha1((key[0] + url).encode()).hexdigest()[:12]
        out.append({
            "source_id": sid,
            "company_name": r.get("canonical_name", ""),
            "org_type": "soe",
            "source_type": "official",
            "adapter": "regional_notice",
            "endpoint": f"{url}||{region}||{r.get('canonical_name','')}||company",
            "priority": "2",
            "fetch_method": "html",
            "requires_login": "no",
            "city_scope": region or r.get("province", "") or "全国",
            "poll_interval_minutes": "720",
            "status": "active",
            "notes": f"V2.3国企主体库自动生成；{r.get('level','')}；{r.get('parent_group','')}",
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-sources", type=int, default=80)
    args = ap.parse_args()

    seed = _read_csv(SEED)
    discovered: dict[str, dict] = {}
    sources = _source_rows()[: max(1, args.max_sources)]
    print(f"🏢 V2.3 国企主体库：扫描 {len(sources)} 个官方监管入口")
    for s in sources:
        url = s.get("url", "")
        print(f"  → {s.get('name') or s.get('source_id')}: {url}")
        for r in _discover_page(url, row=s):
            k = normalize_name(r.get("canonical_name", ""))
            if k:
                discovered[k] = r
    for r in _from_existing_jobs():
        k = normalize_name(r.get("canonical_name", ""))
        if k and k not in discovered:
            discovered[k] = r

    generated = list(discovered.values())
    generated.sort(key=lambda r: (r.get("province", ""), r.get("city", ""), r.get("canonical_name", "")))
    _write_csv(GENERATED, generated, REG_COLS)
    combined = _merge(seed, generated)
    combined.sort(key=lambda r: (r.get("level", ""), r.get("province", ""), r.get("city", ""), r.get("canonical_name", "")))
    os.makedirs(DATA, exist_ok=True)
    with open(COMBINED_JSON, "w", encoding="utf-8") as f:
        json.dump({"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "total": len(combined), "entities": combined}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    _write_csv(COMPANY_SOURCES, _company_sources(combined), SRC_COLS)
    reload_registry()
    print(f"✅ seed {len(seed)} + 自动发现 {len(generated)} → 合并主体 {len(combined)}")
    print(f"✅ {GENERATED}")
    print(f"✅ {COMBINED_JSON}")
    print(f"✅ 官网抓取源 {len(_company_sources(combined))} → {COMPANY_SOURCES}")


if __name__ == "__main__":
    main()
