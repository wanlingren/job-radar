"""微信公众号公开文章适配器。

注意：微信没有供任意第三方搜索全部公众号文章的开放 API。
本适配器只处理已经发现/人工提供的公开 mp.weixin.qq.com 文章 URL。
"""
from __future__ import annotations

import re
from html import unescape
from typing import List

from ..models import RawJob
from ..soe_matcher import match_text
from . import register
from .web_article import Parser, _get, _date, _deadline, RECRUIT_RE


@register("wechat_article")
def fetch_wechat_article(endpoint: str) -> List[RawJob]:
    parts = [p.strip() for p in endpoint.split("||")]
    url = parts[0]
    location = parts[1] if len(parts) > 1 else ""
    fallback = parts[2] if len(parts) > 2 else ""
    html = _get(url)
    p = Parser()
    p.feed(html)

    title = p.meta.get("og:title") or p.title
    title = re.sub(r"\s+", " ", unescape(title or "")).strip()
    body = re.sub(r"\s+", " ", " ".join(p.texts)).strip()
    if not RECRUIT_RE.search(title + " " + body[:10000]):
        return []

    # 微信正文常把发布时间放在 JS 中
    publish = _date(body[:3000])
    if not publish:
        m = re.search(r"(?:publish_time|ct)\s*[:=]\s*[\"']?(\d{10})", html)
        if m:
            import datetime as dt
            publish = dt.datetime.fromtimestamp(int(m.group(1)), tz=dt.timezone.utc).date().isoformat()

    reg = match_text(title + " " + body[:12000])
    company = reg.get("canonical_name", "") if reg else ""
    if not company:
        m = re.search(r"([^，。；;|｜]{2,60}?(?:集团(?:有限责任公司|股份有限公司|有限公司)?|股份有限公司|有限责任公司|有限公司|银行|研究院|研究所))(?=.{0,12}(?:招聘|校招|秋招|公开招))", title)
        company = m.group(1).strip("【】[]（）() -—·:：") if m else fallback
    if not company:
        company = fallback or title[:60] or "微信公众号招聘"

    # 尝试识别公众号名称
    account = p.meta.get("author") or p.meta.get("og:site_name") or ""
    raw = {
        "article_source": "wechat",
        "wechat_account": account,
        "source_label": fallback or account,
        "registry_match": reg or {},
    }
    return [RawJob(
        company_name=company,
        title=title or f"{company}招聘公告",
        location=location or (reg.get("province", "") if reg else ""),
        publish_time=publish,
        deadline=_deadline(body[:16000]),
        official_url=url,
        jd_text=body[:5000],
        raw=raw,
    )]
