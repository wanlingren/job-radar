#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重点国企 + 微信公众号/转载线索补漏发现。

不依赖付费 API。默认使用 Bing RSS 的公开搜索结果作为“线索发现”，随后由
web_article / wechat_article 适配器解析正文并继续进入原 Job Radar 去重流程。

注意：它不是微信官方全量 API，所以微信补漏仍是辅助层；官方企业/国资网站是主层。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import os
import re
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config")
WATCH = os.path.join(CONFIG, "watchlist_companies.csv")
OUT = os.path.join(CONFIG, "discovered_watchlist_sources.csv")

FIELDS = ['source_id','company_name','org_type','source_type','adapter','endpoint','priority','fetch_method','requires_login','city_scope','poll_interval_minutes','status','notes']
RECRUIT = re.compile(r"招聘|校招|校园招聘|秋招|春招|应届|2027|27届|公开招|社会招聘|社招|人才引进|招录|工作人员")
BAD_DOMAINS = {"baidu.com", "google.com", "bing.com"}
_SSL = ssl.create_default_context(); _SSL.check_hostname=False; _SSL.verify_mode=ssl.CERT_NONE


def _read(path):
    if not os.path.exists(path): return []
    with open(path,encoding='utf-8-sig') as f:
        return [{k:(v or '').strip() for k,v in r.items()} for r in csv.DictReader(ln for ln in f if ln.strip() and not ln.lstrip().startswith('#'))]


def _rss(query: str, timeout=12):
    url = "https://www.bing.com/search?format=rss&q=" + urllib.parse.quote(query)
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept-Language':'zh-CN,zh;q=0.9'})
    with urllib.request.urlopen(req,timeout=timeout,context=_SSL) as r:
        data=r.read(800000)
    root=ET.fromstring(data)
    out=[]
    for item in root.findall('.//item'):
        title=(item.findtext('title') or '').strip()
        link=(item.findtext('link') or '').strip()
        desc=re.sub(r'<[^>]+>',' ',item.findtext('description') or '')
        if title and link: out.append((title,link,re.sub(r'\s+',' ',desc).strip()))
    return out


def _domain(url): return (urlparse(url).hostname or '').lower().removeprefix('www.')

def _sid(company,url): return 'watch-'+hashlib.sha1((company+'|'+url).encode()).hexdigest()[:14]


def _source(company, region, title, url, official_domain=''):
    dom=_domain(url)
    is_wechat=dom=='mp.weixin.qq.com'
    official = bool(official_domain and (dom==official_domain.removeprefix('www.') or dom.endswith('.'+official_domain.removeprefix('www.'))))
    adapter='wechat_article' if is_wechat else 'web_article'
    source_type='official' if official else ('community' if is_wechat else 'aggregator')
    return {
        'source_id':_sid(company,url),'company_name':company,'org_type':'soe','source_type':source_type,'adapter':adapter,
        'endpoint':f'{url}||{region}||{company}','priority':'1' if official or is_wechat else '2','fetch_method':'html','requires_login':'no',
        'city_scope':region,'poll_interval_minutes':'720','status':'active','notes':f'V2.3重点企业补漏；搜索标题：{title[:100]}'
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--max-companies',type=int,default=55)
    ap.add_argument('--max-results',type=int,default=8)
    ap.add_argument('--deep',action='store_true')
    a=ap.parse_args()
    rows=sorted(_read(WATCH), key=lambda r:int(r.get('priority') or 9))
    limit=len(rows) if a.deep else min(len(rows),a.max_companies)
    existing={r.get('endpoint','').split('||')[0]:r for r in _read(OUT)}
    year=str(dt.date.today().year)
    terms='招聘 校园招聘 秋招 公开招聘 2027届'
    for i,r in enumerate(rows[:limit],1):
        company=r.get('company',''); aliases=r.get('aliases',''); region=r.get('region',''); domain=r.get('official_domain','')
        if not company: continue
        queries=[f'"{company}" 招聘 {year}', f'"{company}" 2027届 秋招', f'site:mp.weixin.qq.com "{company}" 招聘']
        if domain: queries.insert(0, f'site:{domain} "{company}" 招聘')
        print(f'🔎 [{i}/{limit}] {company}')
        for q in queries:
            try: results=_rss(q)
            except Exception as e:
                print(f'  ⚠ 搜索失败: {e}'); continue
            for title,url,desc in results[:a.max_results]:
                if url in existing: continue
                dom=_domain(url)
                if any(dom==b or dom.endswith('.'+b) for b in BAD_DOMAINS): continue
                hay=title+' '+desc
                names=[company]+[x for x in aliases.split('|') if x]
                if not any(n in hay for n in names): continue
                if not RECRUIT.search(hay): continue
                existing[url]=_source(company,region,title,url,domain)
    out=list(existing.values())
    out.sort(key=lambda r:(r.get('city_scope',''),r.get('company_name',''),r.get('source_id','')))
    with open(OUT,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerows(out)
    print(f'✅ 重点企业补漏线索累计 {len(out)} 条 → {OUT}')

if __name__=='__main__': main()
