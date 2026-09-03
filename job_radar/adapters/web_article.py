"""任意公开招聘文章解析器（官网/转载站/手工补录）。

endpoint 可以是 URL，也可以是：URL||LOCATION||LABEL
输出一条 RawJob；公司名优先用国企主体库从标题/正文中识别。
"""
from __future__ import annotations

import re
import ssl
import urllib.request
from html import unescape
from html.parser import HTMLParser
from typing import List

from ..models import RawJob
from ..soe_matcher import match_text
from . import register

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

DATE_RE = re.compile(r"(20\d{2})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})\s*日?")
DEADLINE_HINT = re.compile(r"(?:报名截止|投递截止|申请截止|网申截止|截止时间|截至|截止日期|报名时间)[^。；;\n]{0,180}")
RECRUIT_RE = re.compile(r"招聘|校招|校园招聘|秋招|春招|应届|公开招|社会招聘|社招|人才引进|工作人员|编外|劳务派遣")


class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self.texts: list[str] = []
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() == "meta":
            key = (d.get("property") or d.get("name") or "").lower()
            val = d.get("content") or ""
            if key and val:
                self.meta[key] = val

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data):
        s = re.sub(r"\s+", " ", data or "").strip()
        if not s:
            return
        if self._in_title:
            self.title += s
        self.texts.append(s)


def _get(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=15, context=_SSL) as r:
        raw = r.read(1000000)
        ctype = (r.headers.get("Content-Type") or "").lower()
        m = re.search(r"charset=([\w-]+)", ctype)
        enc = m.group(1) if m else "utf-8"
        try:
            return raw.decode(enc, "replace")
        except LookupError:
            return raw.decode("utf-8", "replace")


def _date(text: str) -> str:
    m = DATE_RE.search(text)
    if not m:
        return ""
    y, mo, d = map(int, m.groups())
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _deadline(text: str) -> str:
    found = []
    for h in DEADLINE_HINT.finditer(text):
        found.extend(DATE_RE.findall(h.group(0)))
    if not found:
        return ""
    dates = [f"{int(y):04d}-{int(m):02d}-{int(d):02d}" for y, m, d in found]
    return sorted(dates)[-1]


def _parse(endpoint: str) -> List[RawJob]:
    parts = [p.strip() for p in endpoint.split("||")]
    url = parts[0]
    location = parts[1] if len(parts) > 1 else ""
    fallback = parts[2] if len(parts) > 2 else ""
    html = _get(url)
    p = Parser()
    p.feed(html)
    title = p.meta.get("og:title") or p.meta.get("twitter:title") or p.title
    title = re.sub(r"\s+", " ", unescape(title or "")).strip()
    body = re.sub(r"\s+", " ", " ".join(p.texts)).strip()
    if not RECRUIT_RE.search(title + " " + body[:10000]):
        return []

    reg = match_text(title + " " + body[:10000])
    company = reg.get("canonical_name", "") if reg else ""
    if not company:
        # 常见标题“XX集团2027届秋季招聘”
        m = re.search(r"([^，。；;|｜]{2,60}?(?:集团(?:有限责任公司|股份有限公司|有限公司)?|股份有限公司|有限责任公司|有限公司|银行|研究院|研究所))(?=.{0,12}(?:招聘|校招|秋招|公开招))", title)
        company = m.group(1).strip("【】[]（）() -—·:：") if m else fallback
    if not company:
        company = title[:60] or "招聘公告"

    raw = {
        "article_source": "web",
        "source_label": fallback,
        "registry_match": reg or {},
    }
    return [RawJob(
        company_name=company,
        title=title or f"{company}招聘公告",
        location=location or (reg.get("province", "") if reg else ""),
        publish_time=_date(body[:3000]),
        deadline=_deadline(body[:15000]),
        official_url=url,
        jd_text=body[:5000],
        raw=raw,
    )]


@register("web_article")
def fetch_web_article(endpoint: str) -> List[RawJob]:
    return _parse(endpoint)
