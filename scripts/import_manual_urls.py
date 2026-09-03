#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 config/manual_urls.txt 中的公开文章链接转换成抓取源。"""
from __future__ import annotations
import csv, hashlib, os
from urllib.parse import urlparse

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG=os.path.join(ROOT,'config')
IN=os.path.join(CONFIG,'manual_urls.txt')
OUT=os.path.join(CONFIG,'discovered_manual_sources.csv')
FIELDS=['source_id','company_name','org_type','source_type','adapter','endpoint','priority','fetch_method','requires_login','city_scope','poll_interval_minutes','status','notes']

def main():
    rows=[]
    if os.path.exists(IN):
        for raw in open(IN,encoding='utf-8'):
            line=raw.strip()
            if not line or line.startswith('#'): continue
            parts=[p.strip() for p in line.split('|')]
            if len(parts)>=3:
                company,region,url=parts[0],parts[1],parts[2]
            elif len(parts)==2:
                company,region,url=parts[0],'',parts[1]
            else:
                company,region,url='手工补录','',parts[0]
            if not url.startswith(('http://','https://')): continue
            dom=(urlparse(url).hostname or '').lower()
            adapter='wechat_article' if dom=='mp.weixin.qq.com' else 'web_article'
            sid='manual-'+hashlib.sha1(url.encode()).hexdigest()[:14]
            rows.append({'source_id':sid,'company_name':company,'org_type':'soe' if company!='手工补录' else 'unknown','source_type':'community' if adapter=='wechat_article' else 'public_notice','adapter':adapter,'endpoint':f'{url}||{region}||{company}','priority':'1','fetch_method':'html','requires_login':'no','city_scope':region or '待识别','poll_interval_minutes':'1440','status':'active','notes':'V2.3手工补录公开招聘链接'})
    with open(OUT,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
    print(f'✅ 手工补录源 {len(rows)} 条 → {OUT}')
if __name__=='__main__': main()
