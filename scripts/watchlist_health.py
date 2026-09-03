#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重点企业漏报/沉默监控：展示每家重点企业最后一次抓到招聘的时间。"""
from __future__ import annotations
import csv, datetime as dt, json, os, re

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG=os.path.join(ROOT,'config'); DATA=os.path.join(ROOT,'data')
WATCH=os.path.join(CONFIG,'watchlist_companies.csv'); JOBS=os.path.join(DATA,'jobs.json'); OUT=os.path.join(DATA,'watchlist_status.json')

def read_watch():
    if not os.path.exists(WATCH): return []
    with open(WATCH,encoding='utf-8-sig') as f: return list(csv.DictReader(f))

def dateval(s):
    m=re.search(r'20\d{2}-\d{2}-\d{2}',str(s or ''))
    return m.group(0) if m else ''

def main():
    watch=read_watch(); jobs=json.load(open(JOBS,encoding='utf-8')) if os.path.exists(JOBS) else []
    result=[]; today=dt.date.today()
    for w in watch:
        names=[w.get('company','')]+[x for x in (w.get('aliases','') or '').split('|') if x]
        matched=[j for j in jobs if any(n and n in (str(j.get('company_name',''))+' '+str(j.get('title',''))+' '+str(j.get('jd_text',''))) for n in names)]
        latest=max([dateval(j.get('first_seen')) or dateval(j.get('publish_time')) for j in matched]+[''])
        days=None
        if latest:
            try: days=(today-dt.date.fromisoformat(latest)).days
            except ValueError: pass
        result.append({'company':w.get('company',''),'region':w.get('region',''),'priority':w.get('priority',''),'active_jobs':len(matched),'last_discovered':latest,'days_since_last':days,'status':'⚠️30天未发现招聘，建议人工检查' if days is not None and days>=30 else ('正常' if matched else '尚未发现')})
    os.makedirs(DATA,exist_ok=True)
    json.dump({'generated_at':dt.datetime.now().astimezone().isoformat(),'companies':result},open(OUT,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
    print(f'✅ 重点企业状态 {len(result)} 家 → {OUT}')
    for r in result:
        if r['status'].startswith('⚠'): print('  ',r['company'],r['status'])
if __name__=='__main__': main()
