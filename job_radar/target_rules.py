"""江浙沪皖国资招聘雷达：统一目标筛选、地区识别、招聘类型与优先级规则。"""
from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
CORE_REGIONS = {"浙江", "江苏", "上海", "安徽"}

REGION_KEYWORDS = {
    "浙江": (
        "浙江", "杭州", "宁波", "温州", "嘉兴", "湖州", "绍兴", "金华", "衢州", "舟山", "台州", "丽水",
    ),
    "江苏": (
        "江苏", "南京", "无锡", "徐州", "常州", "苏州", "南通", "连云港", "淮安", "盐城", "扬州", "镇江", "泰州", "宿迁",
    ),
    "上海": ("上海",),
    "安徽": (
        "安徽", "合肥", "芜湖", "蚌埠", "淮南", "马鞍山", "淮北", "铜陵", "安庆", "黄山", "滁州", "阜阳", "宿州", "六安", "亳州", "池州", "宣城",
    ),
}

CENTRAL_SOE_KEYWORDS = (
    "国家电网", "南方电网", "中核", "中国核工业", "中广核", "航天科技", "航天科工", "航空工业", "中国航发",
    "中国船舶", "兵器工业", "兵器装备", "中国电科", "中电科", "中国电子", "中国石油", "中石油", "中国石化", "中石化",
    "中国海油", "中海油", "国家管网", "国家能源", "华能", "大唐", "华电", "国家电投", "三峡集团", "中国移动", "中国电信",
    "中国联通", "中国一汽", "东风汽车", "中国中车", "中国商飞", "中国宝武", "鞍钢", "中国铝业", "中国远洋海运", "招商局",
    "华润", "中信集团", "中国邮政", "中国中煤", "中国建材", "中国建筑", "中建集团", "中国中铁", "中国铁建", "中国交建",
    "中国能建", "中国电建", "中粮集团", "中国五矿", "中国化学", "国投集团", "国家开发投资集团",
)

LOCAL_SOE_HINTS = (
    "城投", "交投", "产投", "建投", "金控", "国投", "国资", "水务", "燃气", "环境集团", "环保集团", "轨道集团", "地铁集团",
    "公交集团", "机场集团", "港口集团", "文旅集团", "旅游集团", "数据集团", "科创集团", "产业集团", "资本集团", "投资集团", "发展集团",
    "控股集团", "国有资本", "国有资产", "农垦", "盐业", "粮食集团", "供销集团",
)

STATE_OWNED_RE = re.compile(
    r"央企|中央企业|国有企业|国企|国有独资|国有全资|国有控股|国资控股|省属企业|省属国企|市属企业|市属国企|区属国企|县属国企|地方国企",
    re.I,
)
PUBLIC_RE = re.compile(
    r"事业单位|直属事业单位|公益一类|公益二类|编外|劳务派遣|政府雇员|机关事业|工作人员公开招聘|公开招聘工作人员|人才引进|选聘",
    re.I,
)
COHORT_2027 = re.compile(r"2027\s*届|27\s*届|2027\s*校招|2027\s*校园招聘|2027\s*秋招", re.I)
CAMPUS_RE = re.compile(r"校园招聘|校招|秋招|春招|提前批|应届生|应届毕业生|高校毕业生|毕业生招聘|管培生|管理培训生|实习生", re.I)
SOCIAL_RE = re.compile(r"社会招聘|社招|社会人员招聘", re.I)

# 这些来源本身就是国央企强信号
CENTRAL_SOURCE_IDS = {"gov-sasac", "gov-qyzp"}


def clean(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def extra(job: dict) -> dict:
    v = job.get("extra")
    return v if isinstance(v, dict) else {}


def job_text(job: dict) -> str:
    ext = extra(job)
    vals = [
        job.get("company_name"), job.get("title"), job.get("jd_text"), job.get("location"), job.get("org_type"),
        " ".join(job.get("tags") or []), ext.get("nature"), ext.get("nature_cn"), ext.get("company_type"),
        ext.get("recruitment_type"), ext.get("source_label"), ext.get("region"),
    ]
    return " ".join(clean(v) for v in vals if v)


def today() -> dt.date:
    return dt.datetime.now(TZ).date()


def parse_date(value: str) -> dt.date | None:
    value = clean(value)
    m = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", value)
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def region_name(job: dict) -> str:
    text = job_text(job)
    # adapter 明确写入的地区优先
    r = clean(extra(job).get("region"))
    for key in CORE_REGIONS:
        if r.startswith(key):
            return key
    for region, words in REGION_KEYWORDS.items():
        if any(w in text for w in words):
            return region
    return "其他地区"


def is_expired(job: dict) -> bool:
    d = parse_date(job.get("deadline", ""))
    return bool(d and d < today())


def is_state_owned(job: dict) -> bool:
    sid = clean(job.get("source_id"))
    org = clean(job.get("org_type")).lower()
    company = clean(job.get("company_name"))
    text = job_text(job)
    if sid in CENTRAL_SOURCE_IDS:
        return True
    if org in {"soe", "state-owned", "state_owned", "stateowned"}:
        return True
    if STATE_OWNED_RE.search(text):
        return True
    if any(k in company for k in CENTRAL_SOE_KEYWORDS):
        return True
    if any(k in company for k in LOCAL_SOE_HINTS):
        return True
    return False


def is_government_official_source(job: dict) -> bool:
    sid = clean(job.get("source_id"))
    ext = extra(job)
    # reg-/auto-gov- 是我们维护/自动发现的政府官方源
    if sid.startswith(("reg-gov-", "reg-sasac-", "reg-hrss-", "auto-gov-")):
        return True
    if ext.get("mode") == "government" and region_name(job) in CORE_REGIONS:
        return True
    return False


def is_university_source(job: dict) -> bool:
    sid = clean(job.get("source_id"))
    ext = extra(job)
    return sid.startswith("edu-") or ext.get("mode") == "career"


def is_target_job(job: dict) -> bool:
    if job.get("gone") or is_expired(job):
        return False
    region = region_name(job)
    # 全国央企/国企始终保留
    if is_state_owned(job):
        return True
    # 江浙沪皖政府、人社、国资、区县官方招聘公告全部保留，宁可多一点，不因性质识别不全漏掉
    if region in CORE_REGIONS and is_government_official_source(job):
        return True
    # 江浙沪皖事业单位/编外招聘保留
    if region in CORE_REGIONS and PUBLIC_RE.search(job_text(job)):
        return True
    # 高校就业网只作为央国企/公共部门补漏，不把普通民企全部塞入结果
    if is_university_source(job):
        text = job_text(job)
        return bool(STATE_OWNED_RE.search(text) or PUBLIC_RE.search(text) or any(k in text for k in CENTRAL_SOE_KEYWORDS + LOCAL_SOE_HINTS))
    return False


def recruitment_kind(job: dict) -> str:
    text = job_text(job)
    if COHORT_2027.search(text):
        return "⭐27届校园招聘"
    if CAMPUS_RE.search(text):
        return "🟦校园招聘/应届生"
    if PUBLIC_RE.search(text) and not is_state_owned(job):
        if re.search(r"编外|劳务派遣|政府雇员", text, re.I):
            return "🟪事业单位/编外"
        return "🟩事业单位/人才引进"
    if SOCIAL_RE.search(text):
        return "🟧国企社会招聘"
    if is_state_owned(job):
        return "🟨国企公开招聘"
    return "⬜政府官方招聘公告"


def source_tier(job: dict) -> str:
    sid = clean(job.get("source_id"))
    ext = extra(job)
    if sid.startswith(("reg-gov-", "reg-sasac-", "reg-hrss-", "auto-gov-")) or sid in CENTRAL_SOURCE_IDS:
        return "★★★★★ 官方政府/国资"
    if ext.get("mode") == "company" or clean(job.get("org_type")).lower() == "soe":
        return "★★★★★ 企业官网"
    if is_university_source(job):
        return "★★★★☆ 高校就业网"
    if sid in {"cn-iguopin", "gov-ncss", "gov-mohrss"}:
        return "★★★★☆ 国家/招聘平台"
    return "★★★☆☆ 补充来源"


def priority(job: dict) -> tuple:
    region_score = 100 if region_name(job) in CORE_REGIONS else 20
    kind_score = {
        "⭐27届校园招聘": 100,
        "🟦校园招聘/应届生": 90,
        "🟨国企公开招聘": 80,
        "🟧国企社会招聘": 70,
        "🟩事业单位/人才引进": 60,
        "🟪事业单位/编外": 50,
        "⬜政府官方招聘公告": 40,
    }.get(recruitment_kind(job), 0)
    d = parse_date(job.get("deadline", ""))
    urgent = 0
    if d:
        left = (d - today()).days
        if 0 <= left <= 3:
            urgent = 30
        elif left <= 7:
            urgent = 20
        elif left <= 14:
            urgent = 10
    pub = clean(job.get("publish_time"))[:10]
    first = clean(job.get("first_seen"))[:10]
    return region_score, kind_score, urgent, pub, first
