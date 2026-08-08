#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""江浙沪皖 V2.1 信源发现与覆盖审计。

目标：
1. 以四省市官方政府门户为起点递归发现市/区/县政府官网；
2. 用行政区划代码对候选政府站点做严格校验，避免把“中央人民政府”等误认成本地站点；
3. 从已验证政府门户继续发现人社、国资、公共就业/人才服务等官方站点；
4. 从高校官网/已知就业入口发现高校就业网，作为校招补漏；
5. 生成 discovered_sources.csv、discovered_universities.csv、coverage_report.csv、coverage_summary.md；
6. full 模式对尚未覆盖的市县使用搜索引擎做兜底，但只有通过严格验证才会入库。

说明：
- 行政区划核对使用公开的 2023 统计区划快照，仅作为“应该覆盖哪些市县”的审计清单；
- 自动入库的政府站点必须是 gov.cn 且通过名称/网站标识码验证；
- 搜索引擎结果从不直接当作招聘来源，只用于定位候选官方站点。
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html import unescape
from urllib.parse import urljoin, urlparse, urldefrag

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config")
DATA = os.path.join(ROOT, "data")
SEEDS = os.path.join(CONFIG, "discovery_seeds.csv")
UNIVERSITY_SEEDS = os.path.join(CONFIG, "university_seeds.csv")
BASE_SOURCES = os.path.join(CONFIG, "sources.csv")
OUT = os.path.join(CONFIG, "discovered_sources.csv")
UNIV_OUT = os.path.join(CONFIG, "discovered_universities.csv")
COVERAGE_OUT = os.path.join(CONFIG, "coverage_report.csv")
UNIV_COVERAGE_OUT = os.path.join(CONFIG, "university_coverage.csv")
SUMMARY_OUT = os.path.join(CONFIG, "coverage_summary.md")
CACHE = os.path.join(DATA, "discovery_cache_v21.json")

AREAS_URL = "https://raw.githubusercontent.com/modood/Administrative-divisions-of-China/master/dist/areas.csv"
CITIES_URL = "https://raw.githubusercontent.com/modood/Administrative-divisions-of-China/master/dist/cities.csv"
TARGET_PROVINCES = {"31": "上海", "32": "江苏", "33": "浙江", "34": "安徽"}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

A_TAG = re.compile(r'<a\b([^>]*?)href=["\']([^"\']+)["\']([^>]*?)>(.*?)</a>', re.S | re.I)
TITLE_ATTR = re.compile(r'title=["\']([^"\']{2,180})["\']', re.I)
TAGS = re.compile(r"<[^>]+>")
SCRIPT_STYLE = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.S | re.I)
SP = re.compile(r"\s+")

GOV_LABEL = re.compile(r"(人民政府|政府门户|新区政府|区政府|县政府|市政府|管委会)")
AGENCY_LABEL = re.compile(r"(人力资源和社会保障|人社局|国有资产监督管理|国资委|国资办|公共就业|就业服务|人才服务|人才交流|人才市场)")
NOTICE_NAV = re.compile(r"(招聘|招考|人事|人才|事业单位|国企|国资|就业|通知公告|公示公告|公开招聘)")
UNIV_CAREER = re.compile(r"(就业信息网|就业网|智慧就业|毕业生就业|学生就业|招生就业|就业指导|就业服务|career|job)", re.I)

SITE_CODE_PATTERNS = [
    re.compile(r"政府网站标识码\s*[:：]?\s*([a-zA-Z0-9]{8,16})", re.I),
    re.compile(r"网站标识码\s*[:：]?\s*([a-zA-Z0-9]{8,16})", re.I),
    re.compile(r"\b((?:31|32|33|34)\d{8})\b"),
]

KNOWN_CAREER_HOST_HINTS = (
    "91job.org.cn", "yunjiuye.com", "cailifang", "career", "job.", "jobs.", "jyb.", "jy.", "zbb.",
)


@dataclass(frozen=True)
class Unit:
    code: str
    name: str
    province: str
    city: str
    level: str


def _get_bytes(url: str, timeout: int = 15, max_bytes: int = 1_200_000) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        raw = r.read(max_bytes)
        return raw, (r.headers.get("Content-Type") or "")


def _get(url: str, timeout: int = 15, max_bytes: int = 1_200_000) -> str:
    raw, ctype = _get_bytes(url, timeout=timeout, max_bytes=max_bytes)
    enc = "utf-8"
    m = re.search(r"charset=([\w-]+)", ctype, re.I)
    if m:
        enc = m.group(1)
    for candidate in (enc, "utf-8", "gb18030"):
        try:
            return raw.decode(candidate, "replace")
        except Exception:
            continue
    return raw.decode("utf-8", "replace")


def _download_csv(url: str) -> list[dict[str, str]]:
    text = _get(url, timeout=25, max_bytes=4_000_000)
    return list(csv.DictReader(text.splitlines()))


def _links(html: str, base: str):
    for pre, href, post, inner in A_TAG.findall(html):
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        mt = TITLE_ATTR.search(pre) or TITLE_ATTR.search(post)
        text = unescape(mt.group(1)).strip() if mt else SP.sub(" ", unescape(TAGS.sub(" ", inner))).strip()
        if not text:
            continue
        url = urldefrag(urljoin(base, href))[0]
        if url.startswith(("http://", "https://")):
            yield text, url


def _page_text(html: str) -> str:
    html = SCRIPT_STYLE.sub(" ", html)
    return SP.sub(" ", unescape(TAGS.sub(" ", html))).strip()


def _root(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme or 'https'}://{p.netloc}/"


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _is_gov_url(url: str) -> bool:
    h = _host(url)
    return h.endswith("gov.cn") or ".gov.cn" in h


def _same_registrable(a: str, b: str) -> bool:
    pa = _host(a).split(".")
    pb = _host(b).split(".")
    return bool(pa and pb and (pa == pb or (len(pa) >= 3 and len(pb) >= 3 and pa[-3:] == pb[-3:])))


def _clean_label(text: str) -> str:
    text = SP.sub("", text)
    text = re.sub(r"[›>→\-—|｜·•【】\[\]（）()]", "", text)
    return text[:80]


def _source_id(prefix: str, url: str) -> str:
    h = (_host(url) or url).lower()
    return prefix + hashlib.sha1(h.encode("utf-8")).hexdigest()[:10]


def _read_csv_file(path: str) -> list[dict[str, str]]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    return list(csv.DictReader(lines)) if lines else []


def _load_cache() -> dict:
    if os.path.exists(CACHE):
        try:
            with open(CACHE, encoding="utf-8") as f:
                v = json.load(f)
                if isinstance(v, dict):
                    return v
        except Exception:
            pass
    return {"government": {}, "universities": {}}


def _save_cache(cache: dict) -> None:
    os.makedirs(DATA, exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
        f.write("\n")


def expected_units() -> list[Unit]:
    """获取江浙沪皖地市+区县审计清单。下载失败时返回空，发现流程仍可运行。"""
    try:
        cities = _download_csv(CITIES_URL)
        areas = _download_csv(AREAS_URL)
    except Exception as e:
        print(f"⚠ 行政区划审计数据下载失败：{e}")
        return []

    city_map: dict[str, dict[str, str]] = {}
    out: list[Unit] = []
    for c in cities:
        pcode = str(c.get("provinceCode", ""))
        if pcode not in TARGET_PROVINCES:
            continue
        ccode = str(c.get("code", ""))
        cname = c.get("name", "").strip()
        if not ccode or not cname:
            continue
        city_map[ccode] = c
        out.append(Unit(code=ccode, name=cname, province=TARGET_PROVINCES[pcode], city=cname, level="city"))

    for a in areas:
        pcode = str(a.get("provinceCode", ""))
        if pcode not in TARGET_PROVINCES:
            continue
        code = str(a.get("code", ""))
        name = a.get("name", "").strip()
        city_code = str(a.get("cityCode", ""))
        city = city_map.get(city_code, {}).get("name", "")
        if not code or not name:
            continue
        # 开发区/管理区也可能发布招聘，但不计入正式“区县覆盖率”分母；单独标为 functional。
        level = "functional" if re.search(r"开发区|新区|管理区|示范区|园区", name) else "county"
        out.append(Unit(code=code, name=name, province=TARGET_PROVINCES[pcode], city=city, level=level))
    return out


def _unit_name_tokens(name: str) -> list[str]:
    variants = [name]
    core = re.sub(r"(壮族自治区|回族自治区|维吾尔自治区|自治州|自治县|市|区|县)$", "", name)
    if len(core) >= 2:
        variants.append(core)
    return sorted(set(v for v in variants if v), key=len, reverse=True)


def _extract_site_codes(text: str) -> list[str]:
    out: list[str] = []
    for pattern in SITE_CODE_PATTERNS:
        for m in pattern.finditer(text):
            code = m.group(1).strip()
            if code not in out:
                out.append(code)
    return out


def _sitecode_matches(unit: Unit, code: str) -> bool:
    if not code or not code[0].isdigit():
        return False
    if unit.level == "city":
        return code.startswith(unit.code[:4])
    return code.startswith(unit.code[:6])


def verify_government_candidate(unit: Unit, url: str) -> tuple[bool, str, str]:
    """严格验证候选政府门户，返回 (是否通过, 验证方式, 根URL)。"""
    root = _root(url)
    if not _is_gov_url(root):
        return False, "not-gov-cn", root
    try:
        html = _get(root, timeout=12)
    except Exception as e:
        return False, f"unreadable:{type(e).__name__}", root
    text = _page_text(html[:900000])
    codes = _extract_site_codes(text)
    if any(_sitecode_matches(unit, c) for c in codes):
        return True, "sitecode", root

    # 没暴露网站标识码时，必须同时满足“行政区名称 + 政府”并尽量包含省份/城市语境。
    top = text[:12000]
    name_ok = any(tok in top for tok in _unit_name_tokens(unit.name))
    gov_ok = bool(re.search(r"人民政府|政府门户|政府网站", top))
    context_ok = unit.province in top or unit.city in top or unit.name in top
    if name_ok and gov_ok and context_ok:
        return True, "strict-name", root
    return False, "name/sitecode-mismatch", root


def _match_unit_by_label(units: list[Unit], province: str, label: str) -> Unit | None:
    clean = _clean_label(label)
    candidates = [u for u in units if u.province == province and any(t in clean for t in _unit_name_tokens(u.name))]
    if not candidates:
        return None
    candidates.sort(key=lambda u: (len(u.name), u.level == "county"), reverse=True)
    return candidates[0]


def discover_from_portals(units: list[Unit], max_pages: int = 100) -> dict[str, dict]:
    """从省级门户递归发现官方市县门户；只收录能映射到行政区并通过校验的站点。"""
    found: dict[str, dict] = {}
    seeds = _read_csv_file(SEEDS)
    q = deque((s.get("url", ""), s.get("location", ""), 0) for s in seeds if s.get("url"))
    visited: set[str] = set()

    while q and len(visited) < max_pages:
        url, province, depth = q.popleft()
        root = _root(url)
        if root in visited:
            continue
        visited.add(root)
        try:
            html = _get(url, timeout=14)
        except Exception as e:
            print(f"  ⚠ 无法读取 {url}: {e}")
            continue

        for text, link in _links(html, url):
            if not _is_gov_url(link):
                continue
            unit = _match_unit_by_label(units, province, text)
            if unit and GOV_LABEL.search(text):
                ok, method, verified_root = verify_government_candidate(unit, link)
                if ok:
                    found[unit.code] = {
                        "unit_code": unit.code,
                        "unit_name": unit.name,
                        "province": unit.province,
                        "city": unit.city,
                        "level": unit.level,
                        "url": verified_root,
                        "label": f"{unit.name}人民政府",
                        "verification": method,
                    }
                    if depth < 2:
                        q.append((verified_root, province, depth + 1))
            # 省/市门户常有“市县政府/政府网站”导航页，继续深入同一官方站点。
            if depth < 2 and re.search(r"市县|区县|各市|各区|各县|地方政府|政府网站|网站导航|友情链接", text):
                if _same_registrable(url, link):
                    q.append((link, province, depth + 1))
    return found


def _bing_candidates(unit: Unit, limit: int = 6) -> list[str]:
    queries = [
        f'"{unit.name}人民政府" "{unit.province}" site:gov.cn',
        f'"{unit.name}" "人民政府" site:gov.cn',
    ]
    results: list[str] = []
    for query in queries:
        url = "https://www.bing.com/search?format=rss&q=" + urllib.parse.quote(query)
        try:
            xml = _get(url, timeout=12, max_bytes=500000)
            root = ET.fromstring(xml)
        except Exception:
            continue
        for item in root.findall(".//item"):
            link = (item.findtext("link") or "").strip()
            title = (item.findtext("title") or "").strip()
            if not link or not _is_gov_url(link):
                continue
            if not any(t in title for t in _unit_name_tokens(unit.name)):
                continue
            r = _root(link)
            if r not in results:
                results.append(r)
            if len(results) >= limit:
                return results
    return results


def _search_and_verify(unit: Unit) -> tuple[str, dict | None]:
    for candidate in _bing_candidates(unit):
        ok, method, root = verify_government_candidate(unit, candidate)
        if ok:
            return unit.code, {
                "unit_code": unit.code,
                "unit_name": unit.name,
                "province": unit.province,
                "city": unit.city,
                "level": unit.level,
                "url": root,
                "label": f"{unit.name}人民政府",
                "verification": f"search+{method}",
            }
    return unit.code, None


def enrich_missing(found: dict[str, dict], units: list[Unit], *, full: bool) -> dict[str, dict]:
    missing = [u for u in units if u.level in {"city", "county", "functional"} and u.code not in found]
    print(f"📍 行政区划审计：应检查 {len(units)} 个地市/区县/功能区；当前严格验证 {len(found)} 个；缺口 {len(missing)} 个")
    if not full or not missing:
        return found

    # 并行但保持保守并发，避免搜索端限流。
    workers = 4
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_search_and_verify, u): u for u in missing}
        done = 0
        for fut in as_completed(futs):
            done += 1
            u = futs[fut]
            try:
                code, row = fut.result()
            except Exception as e:
                print(f"  ⚠ {u.province} {u.city} {u.name}: {e}")
                continue
            if row:
                found[code] = row
                print(f"  ✅ {done}/{len(missing)} {u.province} {u.city} {u.name} -> {row['url']}")
            elif done % 20 == 0:
                print(f"  … 已核对 {done}/{len(missing)} 个缺口")
            time.sleep(0.03)
    return found


def _find_notice_url(site_url: str) -> str:
    try:
        html = _get(site_url, timeout=10)
    except Exception:
        return site_url
    for text, link in _links(html, site_url):
        if NOTICE_NAV.search(text) and (_same_registrable(site_url, link) or _is_gov_url(link)):
            return link
    return site_url


def discover_agencies(found: dict[str, dict], max_sites: int = 260) -> list[dict]:
    """从已验证政府门户发现人社/国资/公共就业等官方站点。"""
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for site in list(found.values())[:max_sites]:
        url = site["url"]
        try:
            html = _get(url, timeout=10)
        except Exception:
            continue
        for text, link in _links(html, url):
            if not AGENCY_LABEL.search(text):
                continue
            if not _is_gov_url(link):
                continue
            agency_root = _root(link)
            label = _clean_label(text)
            key = (agency_root, label)
            if key in seen:
                continue
            seen.add(key)
            if re.search(r"国资|国有资产", label):
                prefix, org_hint = "auto-sasac-", "国资"
            elif re.search(r"人力资源|人社", label):
                prefix, org_hint = "auto-hrss-", "人社"
            else:
                prefix, org_hint = "auto-job-", "公共就业"
            rows.append({
                "source_id": _source_id(prefix, agency_root),
                "company_name": f"{site['unit_name']}·{label}",
                "org_type": "public_institution",
                "source_type": "official",
                "adapter": "regional_notice",
                "endpoint": f"{link}||{site['province']}·{site['city']}·{site['unit_name']}||{label}||government",
                "priority": "1" if org_hint == "国资" else "2",
                "fetch_method": "html",
                "requires_login": "no",
                "city_scope": f"{site['province']}·{site['city']}·{site['unit_name']}",
                "poll_interval_minutes": "720",
                "status": "active",
                "notes": f"从严格验证政府门户发现的{org_hint}官方站点",
                "verification": "linked-from-verified-government",
                "unit_code": site["unit_code"],
            })
    return rows


def write_government_sources(found: dict[str, dict], agencies: list[dict]) -> None:
    fields = [
        "source_id", "company_name", "org_type", "source_type", "adapter", "endpoint", "priority", "fetch_method",
        "requires_login", "city_scope", "poll_interval_minutes", "status", "notes", "verification", "unit_code",
    ]
    rows: list[dict] = []
    for site in sorted(found.values(), key=lambda x: (x.get("province", ""), x.get("city", ""), x.get("unit_name", ""))):
        url = site["url"]
        notice = _find_notice_url(url)
        rows.append({
            "source_id": _source_id("auto-gov-", url),
            "company_name": f"{site['unit_name']}人民政府",
            "org_type": "public_institution",
            "source_type": "official",
            "adapter": "regional_notice",
            "endpoint": f"{notice}||{site['province']}·{site['city']}·{site['unit_name']}||{site['unit_name']}人民政府||government",
            "priority": "2",
            "fetch_method": "html",
            "requires_login": "no",
            "city_scope": f"{site['province']}·{site['city']}·{site['unit_name']}",
            "poll_interval_minutes": "1440",
            "status": "active",
            "notes": "V2.1严格校验的市/区/县政府官方源",
            "verification": site.get("verification", ""),
            "unit_code": site.get("unit_code", ""),
        })
    rows.extend(agencies)
    # 按 source_id 去重
    unique = {r["source_id"]: r for r in rows if r.get("source_id")}
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(unique.values())
    print(f"✅ 政府/人社/国资自动信源：{len(unique)} 条 -> {OUT}")


def _load_base_source_hosts() -> set[str]:
    hosts: set[str] = set()
    for row in _read_csv_file(BASE_SOURCES):
        endpoint = row.get("endpoint", "").split("||", 1)[0]
        h = _host(endpoint)
        if h:
            hosts.add(h)
    return hosts


def _career_candidate_ok(root_url: str, link: str, text: str) -> bool:
    if not UNIV_CAREER.search(text) and not re.search(r"career|job|jy|jyb|zbb", link, re.I):
        return False
    h = _host(link)
    if not h:
        return False
    if _same_registrable(root_url, link):
        return True
    return any(k in h for k in KNOWN_CAREER_HOST_HINTS)


def discover_universities() -> tuple[list[dict], list[dict]]:
    seeds = _read_csv_file(UNIVERSITY_SEEDS)
    base_hosts = _load_base_source_hosts()
    rows: list[dict] = []
    coverage: list[dict] = []
    for s in seeds:
        name = s.get("name", "").strip()
        location = s.get("location", "").strip()
        root_url = s.get("root_url", "").strip()
        known = s.get("career_url", "").strip()
        fetch_method = s.get("fetch_method", "html").strip() or "html"
        candidate = known
        method = "configured" if known else ""
        if not candidate and root_url:
            try:
                html = _get(root_url, timeout=12)
                ranked: list[tuple[int, str, str]] = []
                for text, link in _links(html, root_url):
                    if not _career_candidate_ok(root_url, link, text):
                        continue
                    score = 0
                    if re.search(r"就业信息网|智慧就业|毕业生就业|就业服务", text):
                        score += 5
                    if re.search(r"career|job", link, re.I):
                        score += 3
                    if _same_registrable(root_url, link):
                        score += 2
                    ranked.append((score, link, text))
                if ranked:
                    ranked.sort(reverse=True)
                    candidate = ranked[0][1]
                    method = "discovered-from-university-homepage"
            except Exception:
                pass

        if candidate:
            h = _host(candidate)
            duplicate = h in base_hosts
            status = "covered-static" if duplicate else "discovered"
            coverage.append({"name": name, "location": location, "root_url": root_url, "career_url": candidate, "status": status, "verification": method})
            if not duplicate:
                adapter = "regional_spa" if fetch_method == "playwright" else "regional_notice"
                rows.append({
                    "source_id": _source_id("auto-edu-", candidate),
                    "company_name": f"{name}就业网",
                    "org_type": "research",
                    "source_type": "public_notice",
                    "adapter": adapter,
                    "endpoint": f"{candidate}||{location}||{name}就业网||career",
                    "priority": "2",
                    "fetch_method": fetch_method,
                    "requires_login": "no",
                    "city_scope": location,
                    "poll_interval_minutes": "720",
                    "status": "active",
                    "notes": "V2.1高校就业网补漏",
                    "verification": method,
                    "unit_code": "",
                })
        else:
            coverage.append({"name": name, "location": location, "root_url": root_url, "career_url": "", "status": "unresolved", "verification": ""})
    return rows, coverage


def write_university_sources(rows: list[dict], coverage: list[dict]) -> None:
    fields = [
        "source_id", "company_name", "org_type", "source_type", "adapter", "endpoint", "priority", "fetch_method",
        "requires_login", "city_scope", "poll_interval_minutes", "status", "notes", "verification", "unit_code",
    ]
    with open(UNIV_OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    cfields = ["name", "location", "root_url", "career_url", "status", "verification"]
    with open(UNIV_COVERAGE_OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cfields)
        w.writeheader()
        w.writerows(coverage)
    print(f"✅ 新发现高校就业源：{len(rows)} 条；高校审计：{len(coverage)} 所")


def write_coverage(units: list[Unit], found: dict[str, dict], univ_coverage: list[dict]) -> None:
    fields = ["province", "city", "unit_code", "unit_name", "level", "status", "source_url", "verification"]
    rows = []
    for u in units:
        site = found.get(u.code)
        rows.append({
            "province": u.province,
            "city": u.city,
            "unit_code": u.code,
            "unit_name": u.name,
            "level": u.level,
            "status": "covered" if site else "missing",
            "source_url": site.get("url", "") if site else "",
            "verification": site.get("verification", "") if site else "",
        })
    with open(COVERAGE_OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    formal = [r for r in rows if r["level"] in {"city", "county"}]
    covered = [r for r in formal if r["status"] == "covered"]
    missing = [r for r in formal if r["status"] == "missing"]
    pct = (100.0 * len(covered) / len(formal)) if formal else 0.0
    u_ok = [r for r in univ_coverage if r.get("status") != "unresolved"]
    u_missing = [r for r in univ_coverage if r.get("status") == "unresolved"]

    by_province = []
    for p in ("浙江", "江苏", "上海", "安徽"):
        pp = [r for r in formal if r["province"] == p]
        pc = [r for r in pp if r["status"] == "covered"]
        ppct = 100.0 * len(pc) / len(pp) if pp else 0.0
        by_province.append(f"- {p}: {len(pc)}/{len(pp)}（{ppct:.1f}%）")

    md = [
        "# 江浙沪皖招聘信源覆盖审计 V2.1",
        "",
        f"- 市/区/县正式行政单位：{len(formal)}",
        f"- 已严格验证政府门户：{len(covered)}",
        f"- 尚未验证：{len(missing)}",
        f"- 当前政府门户覆盖率：{pct:.1f}%",
        f"- 高校就业网审计：{len(u_ok)}/{len(univ_coverage)} 已覆盖，{len(u_missing)} 待解析",
        "",
        "## 分省覆盖",
        *by_province,
        "",
        "## 尚未验证的市/区/县（前100个）",
    ]
    md.extend(f"- {r['province']} · {r['city']} · {r['unit_name']}（{r['unit_code']}）" for r in missing[:100])
    if len(missing) > 100:
        md.append(f"- ……另有 {len(missing)-100} 个，完整列表见 config/coverage_report.csv")
    md += [
        "",
        "> 说明：覆盖率是“官方政府门户已严格验证”的覆盖率，不等于招聘零遗漏率。招聘还会叠加省/市国资、人社、高校就业网、国聘、24365等多源补漏。",
    ]
    with open(SUMMARY_OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print(f"✅ 覆盖审计：{len(covered)}/{len(formal)} = {pct:.1f}% -> {SUMMARY_OUT}")


def main() -> None:
    p = argparse.ArgumentParser(description="江浙沪皖 V2.1 官方信源发现与覆盖审计")
    p.add_argument("--full", action="store_true", help="对未覆盖市县执行严格搜索兜底")
    p.add_argument("--max-pages", type=int, default=80, help="省/市门户递归发现最大页面数")
    a = p.parse_args()

    os.makedirs(CONFIG, exist_ok=True)
    os.makedirs(DATA, exist_ok=True)
    units = expected_units()
    found = discover_from_portals(units, max_pages=max(10, a.max_pages)) if units else {}

    cache = _load_cache()
    # 复用上次已经严格验证并仍包含在行政区划审计清单中的结果。
    valid_codes = {u.code for u in units}
    for code, row in (cache.get("government") or {}).items():
        if code in valid_codes and code not in found and isinstance(row, dict) and row.get("url"):
            found[code] = row

    found = enrich_missing(found, units, full=a.full)
    agencies = discover_agencies(found)
    univ_rows, univ_coverage = discover_universities()

    write_government_sources(found, agencies)
    write_university_sources(univ_rows, univ_coverage)
    write_coverage(units, found, univ_coverage)

    cache["government"] = found
    cache["universities"] = {r.get("name", ""): r for r in univ_coverage}
    cache["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_cache(cache)


if __name__ == "__main__":
    main()
