"""江浙沪皖政府/国资/人社/高校就业网通用深度公告抓取器。

endpoint 约定：
    URL||LOCATION||LABEL||MODE

例如：
    https://gzw.ah.gov.cn/ssqy/qyzp/index.html||安徽||安徽省国资委||government
    https://career.ecust.edu.cn/||上海||华东理工大学就业网||career

MODE:
    government  政府、国资、人社、事业单位、公共就业等
    career      高校就业网/校园招聘平台
    company     国企官网人才招聘栏目

本模块注册两个 adapter：
    regional_notice   普通 HTML
    regional_spa      Playwright 渲染后再解析
"""
from __future__ import annotations

import re
import ssl
from collections import deque
from dataclasses import dataclass
from html import unescape
from typing import Iterable, List
from urllib.parse import urljoin, urlparse, urldefrag

from ..models import RawJob
from . import register
from .http import get_text

# ------------------------- 基础参数 -------------------------
MAX_PAGES = 7
MAX_JOBS = 70
MAX_DETAILS = 6
MAX_DEPTH = 1

_SIGNAL_GOV = re.compile(
    r"(招聘|公开招|招考|招录|招用|选聘|引才|人才引进|劳务派遣|编外|"
    r"事业单位|国企|国有企业|区属企业|市属企业|省属企业|招聘会|用工)"
)
_SIGNAL_CAREER = re.compile(
    r"(招聘|校招|校园招聘|秋招|春招|提前批|实习|宣讲|双选|招聘会|专场|引才|就业信息)"
)
_SIGNAL_COMPANY = re.compile(
    r"(招聘|校招|校园招聘|社会招聘|社招|人才招聘|招聘公告|招聘启事|实习)"
)

_SPECIFIC = re.compile(
    r"(20\d{2}|\d{4}年|届|有限公司|集团|公司|银行|研究院|研究所|中心|"
    r"委员会|管理处|事业单位|国企|国有|岗位|工作人员|人才|校园招聘|公开招聘)"
)

_NAV = re.compile(
    r"(招聘|招考|招录|人才|就业|国资|人社|事业单位|通知公告|公示公告|"
    r"人事信息|公开招聘|招聘信息|人才招聘|招聘公告|就业信息|宣讲|双选|"
    r"市县政府|区县政府|各区|各县|政府网站|友情链接)"
)

_BAD = re.compile(
    r"^(首页|返回|更多|下一页|上一页|尾页|登录|注册|联系我们|网站地图|"
    r"政务服务|无障碍|繁體|English)$",
    re.I,
)

_DATE = re.compile(r"(20\d{2})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})\s*日?")
_PUBLISH_CTX = re.compile(r"(发布时间|发布日期|发布于|时间|日期)\D{0,20}" + _DATE.pattern)
_DEADLINE_CTX = re.compile(
    r"(报名截止|投递截止|申请截止|网申截止|截止时间|截至|截止日期|报名时间|"
    r"投递时间|简历接收时间|报名期限)\D{0,180}" + _DATE.pattern,
    re.S,
)

_A_TAG = re.compile(r'<a\b([^>]*?)href=["\']([^"\']+)["\']([^>]*?)>(.*?)</a>', re.S | re.I)
_TITLE_ATTR = re.compile(r'title=["\']([^"\']{2,160})["\']', re.I)
_TAGS = re.compile(r"<[^>]+>")
_SCRIPT_STYLE = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.S | re.I)
_SPACE = re.compile(r"\s+")

_LAX_SSL = ssl.create_default_context()
_LAX_SSL.check_hostname = False
_LAX_SSL.verify_mode = ssl.CERT_NONE


@dataclass
class EndpointMeta:
    url: str
    location: str
    label: str
    mode: str


def _parse_endpoint(endpoint: str) -> EndpointMeta:
    parts = [p.strip() for p in endpoint.split("||")]
    url = parts[0]
    location = parts[1] if len(parts) > 1 else ""
    label = parts[2] if len(parts) > 2 else ""
    mode = (parts[3] if len(parts) > 3 else "government").lower()
    if mode not in {"government", "career", "company"}:
        mode = "government"
    return EndpointMeta(url=url, location=location, label=label, mode=mode)


def _clean_text(html_fragment: str) -> str:
    return _SPACE.sub(" ", unescape(_TAGS.sub(" ", html_fragment))).strip()


def _page_text(html: str) -> str:
    html = _SCRIPT_STYLE.sub(" ", html)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"</(p|div|li|tr|h\d|section|article)>", "\n", html, flags=re.I)
    return _SPACE.sub(" ", unescape(_TAGS.sub(" ", html))).strip()


def _norm_date(parts: Iterable[str]) -> str:
    y, m, d = [int(x) for x in parts]
    return f"{y:04d}-{m:02d}-{d:02d}"


def _http_get(url: str, timeout: int = 7) -> str:
    """地方站点数量很多，采用一次短超时请求；失败交给健康度闭环次日重试。"""
    import urllib.request
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_LAX_SSL) as r:
        raw = r.read(650000)
        ctype = (r.headers.get("Content-Type") or "").lower()
        enc = "utf-8"
        m = re.search(r"charset=([\w-]+)", ctype)
        if m:
            enc = m.group(1)
        try:
            return raw.decode(enc, "replace")
        except LookupError:
            return raw.decode("utf-8", "replace")


def _spa_get(url: str, timeout_ms: int = 15000) -> str:
    from . import _pw
    page = _pw.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_timeout(1200)
        except Exception:
            pass
        return page.content()
    finally:
        page.close()


def _same_site(a: str, b: str) -> bool:
    ha = (urlparse(a).hostname or "").lower()
    hb = (urlparse(b).hostname or "").lower()
    if not ha or not hb:
        return False
    if ha == hb:
        return True
    # 同一政府站点常有 www / 子域差异；只允许同一注册域内的简单放宽
    pa = ha.split(".")
    pb = hb.split(".")
    return len(pa) >= 3 and len(pb) >= 3 and pa[-3:] == pb[-3:]


def _links(html: str, base: str):
    for pre, href, post, inner in _A_TAG.findall(html):
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        mt = _TITLE_ATTR.search(pre) or _TITLE_ATTR.search(post)
        text = unescape(mt.group(1)).strip() if mt else _clean_text(inner)
        text = _SPACE.sub(" ", text).strip()
        if not text or _BAD.match(text):
            continue
        url = urldefrag(urljoin(base, href))[0]
        if not url.startswith(("http://", "https://")):
            continue
        yield text, url


def _signal(mode: str):
    if mode == "career":
        return _SIGNAL_CAREER
    if mode == "company":
        return _SIGNAL_COMPANY
    return _SIGNAL_GOV


def _is_candidate(title: str, mode: str) -> bool:
    if len(title) < 5 or len(title) > 180:
        return False
    if not _signal(mode).search(title):
        return False
    # 高校就业网里很多职位标题不含年份，但含公司名；允许更宽
    if mode == "career":
        return True
    return bool(_SPECIFIC.search(title))


def _company_from_title(title: str, fallback: str) -> str:
    t = re.sub(r"^[【\[（(]?20\d{2}[年届]?[-—·：:\s]*", "", title).strip()
    # 常见 “XX公司2027届...” / “XX集团公开招聘...”
    cut = re.search(
        r"(20\d{2}\s*届|\d{2}\s*届|校园招聘|校招|秋招|春招|社会招聘|社招|"
        r"公开招聘|招聘公告|招聘启事|招聘简章|招聘工作人员|工作人员公开招聘|"
        r"面向社会招聘|人才招聘|招聘岗位|招聘信息)",
        t,
    )
    if cut and cut.start() >= 2:
        name = t[:cut.start()].strip(" -—·:：｜|【】[]（）()")
        if 2 <= len(name) <= 80:
            return name
    # “关于XX公司公开招聘...”
    m = re.search(r"关于(.{2,60}?)(?:公开招聘|招聘公告|招聘启事|招聘工作人员)", t)
    if m:
        return m.group(1).strip(" -—·:：｜|【】[]（）()")
    return fallback or t[:60]


def _detail(url: str, getter, mode: str) -> tuple[str, str, str]:
    try:
        html = getter(url)
        text = _page_text(html)
    except Exception:
        return "", "", ""

    publish = ""
    mp = _PUBLISH_CTX.search(text[:2500])
    if mp:
        publish = _norm_date(mp.groups()[-3:])
    elif (m := _DATE.search(text[:800])):
        publish = _norm_date(m.groups())

    deadline = ""
    dates = []
    for md in _DEADLINE_CTX.finditer(text[:12000]):
        dates.extend(_norm_date(m.groups()) for m in _DATE.finditer(md.group(0)))
    if dates:
        deadline = sorted(dates)[-1]
    elif any(k in text[:8000] for k in ("截止", "截至", "报名时间")):
        all_dates = [_norm_date(m.groups()) for m in _DATE.finditer(text[:8000])]
        if all_dates:
            deadline = sorted(all_dates)[-1]

    return publish, deadline, text[:1500]


def _fetch(endpoint: str, *, spa: bool) -> List[RawJob]:
    meta = _parse_endpoint(endpoint)
    getter = _spa_get if spa else _http_get

    queue = deque([(meta.url, 0)])
    visited = set()
    candidate_rows: list[tuple[str, str]] = []
    candidate_seen = set()

    while queue and len(visited) < MAX_PAGES:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        try:
            html = getter(url)
        except Exception:
            continue

        for title, link in _links(html, url):
            if _is_candidate(title, meta.mode):
                key = (title, link)
                if key not in candidate_seen:
                    candidate_seen.add(key)
                    candidate_rows.append(key)
                    if len(candidate_rows) >= MAX_JOBS:
                        break

            if depth < MAX_DEPTH and _same_site(meta.url, link):
                # 只深入招聘/人事/国资/就业等导航页，避免爬全站
                if _NAV.search(title) or re.search(r"(job|career|recruit|hr|zp|rsj|gzw|jy|notice|gonggao)", link, re.I):
                    if link not in visited:
                        queue.append((link, depth + 1))

        if len(candidate_rows) >= MAX_JOBS:
            break

    jobs: List[RawJob] = []
    for idx, (title, url) in enumerate(candidate_rows):
        if idx < MAX_DETAILS:
            publish, deadline, jd_text = _detail(url, getter, meta.mode)
        else:
            publish, deadline, jd_text = "", "", ""
        jobs.append(
            RawJob(
                company_name=_company_from_title(title, meta.label),
                title=title,
                location=meta.location,
                publish_time=publish,
                deadline=deadline,
                official_url=url,
                jd_text=jd_text or title,
                raw={
                    "platform": "regional_portal",
                    "mode": meta.mode,
                    "source_label": meta.label,
                    "region": meta.location,
                    "needs_ai": not bool(deadline),
                },
            )
        )
    return jobs


@register("regional_notice")
def fetch_notice(endpoint: str) -> List[RawJob]:
    return _fetch(endpoint, spa=False)


@register("regional_spa")
def fetch_spa(endpoint: str) -> List[RawJob]:
    return _fetch(endpoint, spa=True)
