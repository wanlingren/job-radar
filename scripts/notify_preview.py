#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
江浙沪皖国资招聘雷达 - 招聘筛选与推送预览

主要目标：
1. 全国央企、国企招聘保留；
2. 浙江、江苏、上海、安徽招聘优先；
3. 不再只限制“2027届”；
4. 27届校招、普通校招、国企公开招聘、国企社招全部保留；
5. 江浙沪皖事业单位、编外招聘作为补充频道保留；
6. 不再限制只推8条；
7. 不再限制同一家企业最多2条；
8. 只要没有成功推送过，就一直保留在待推送队列；
9. 已截止岗位自动过滤；
10. 自动去重。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from zoneinfo import ZoneInfo


# ============================================================
# 基础路径
# ============================================================

ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

DATA_DIR = os.path.join(
    ROOT,
    "data",
)

JOBS = os.path.join(
    DATA_DIR,
    "jobs.json",
)

OUT = os.path.join(
    DATA_DIR,
    "notify_preview.md",
)

STATE = os.path.join(
    DATA_DIR,
    "notify_state.json",
)

DEFAULT_WORKBENCH_URL = os.getenv(
    "WORKBENCH_URL",
    "",
).strip()

TZ = ZoneInfo("Asia/Shanghai")


# ============================================================
# 国家级核心招聘来源
# ============================================================

CENTRAL_OFFICIAL_SOURCES = {
    "gov-sasac",   # 国务院国资委
    "gov-qyzp",    # 中央企业应届高校毕业生招聘
}


# ============================================================
# 全国重点央企关键词
# ============================================================

CENTRAL_SOE_KEYWORDS = (
    # 电力
    "国家电网",
    "南方电网",
    "中国华能",
    "华能集团",
    "中国大唐",
    "大唐集团",
    "中国华电",
    "华电集团",
    "国家电投",
    "三峡集团",
    "国家能源集团",
    "国家能源",

    # 石油能源
    "中国石油",
    "中石油",
    "中国石化",
    "中石化",
    "中国海油",
    "中海油",
    "国家管网",
    "中国中煤",

    # 核工业
    "中国核工业",
    "中核集团",
    "中核",
    "中广核",

    # 军工
    "中国航天科技",
    "航天科技",
    "中国航天科工",
    "航天科工",
    "航空工业",
    "中国航空工业",
    "中国航发",
    "中国船舶",
    "中国兵器工业",
    "中国兵器装备",
    "中国电子科技",
    "中国电科",
    "中电科",
    "中国电子",

    # 通信
    "中国移动",
    "中国电信",
    "中国联通",

    # 汽车交通
    "中国一汽",
    "东风汽车集团",
    "中国中车",
    "中国商飞",

    # 建筑交通基建
    "中国建筑",
    "中建集团",
    "中国中铁",
    "中国铁建",
    "中国交建",
    "中国能建",
    "中国电建",
    "中国化学",

    # 金属材料
    "中国宝武",
    "鞍钢集团",
    "中国铝业",
    "中国五矿",
    "中国建材",

    # 综合央企
    "招商局集团",
    "华润集团",
    "中信集团",
    "国投集团",
    "国家开发投资集团",
    "中粮集团",
    "中国邮政",
    "中国远洋海运",
)


# ============================================================
# 招聘类型关键词
# ============================================================

COHORT_2027 = re.compile(
    r"2027\s*届|"
    r"27\s*届|"
    r"2027\s*校招|"
    r"2027\s*校园招聘|"
    r"2027\s*秋招|"
    r"2027\s*届校园招聘",
    re.I,
)


CAMPUS_RE = re.compile(
    r"校园招聘|"
    r"校招|"
    r"秋招|"
    r"春招|"
    r"提前批|"
    r"应届生|"
    r"应届毕业生|"
    r"高校毕业生|"
    r"毕业生招聘|"
    r"管培生|"
    r"管理培训生",
    re.I,
)


SOCIAL_RE = re.compile(
    r"社会招聘|"
    r"社招|"
    r"社会人员招聘",
    re.I,
)


STATE_OWNED_RE = re.compile(
    r"央企|"
    r"中央企业|"
    r"国有企业|"
    r"国企|"
    r"国有独资|"
    r"国有全资|"
    r"国有控股|"
    r"国资控股|"
    r"省属企业|"
    r"省属国企|"
    r"市属企业|"
    r"市属国企|"
    r"区属国企|"
    r"地方国企",
    re.I,
)


PROVINCIAL_RE = re.compile(
    r"省属国企|"
    r"省属企业|"
    r"省国资委|"
    r"省属重点企业",
    re.I,
)


LOCAL_RE = re.compile(
    r"市属国企|"
    r"市属企业|"
    r"市国资委|"
    r"区属国企|"
    r"区国资委|"
    r"城投集团|"
    r"交投集团|"
    r"产投集团|"
    r"文旅集团|"
    r"水务集团|"
    r"轨道集团|"
    r"公交集团",
    re.I,
)


# ============================================================
# 江浙沪皖事业单位、编外招聘
# ============================================================

PUBLIC_SECTOR_RE = re.compile(
    r"事业单位|"
    r"直属事业单位|"
    r"公益一类|"
    r"公益二类|"
    r"编外|"
    r"劳务派遣|"
    r"政府雇员|"
    r"机关事业|"
    r"工作人员公开招聘|"
    r"公开招聘工作人员",
    re.I,
)


# ============================================================
# 江浙沪皖地区关键词
# ============================================================

REGION_KEYWORDS = {

    "浙江": (
        "浙江",
        "杭州",
        "宁波",
        "温州",
        "嘉兴",
        "湖州",
        "绍兴",
        "金华",
        "衢州",
        "舟山",
        "台州",
        "丽水",
    ),

    "江苏": (
        "江苏",
        "南京",
        "苏州",
        "无锡",
        "常州",
        "南通",
        "扬州",
        "镇江",
        "泰州",
        "徐州",
        "盐城",
        "淮安",
        "连云港",
        "宿迁",
    ),

    "上海": (
        "上海",
    ),

    "安徽": (
        "安徽",
        "合肥",
        "芜湖",
        "马鞍山",
        "滁州",
        "宣城",
        "铜陵",
        "池州",
        "安庆",
        "黄山",
        "六安",
        "淮南",
        "淮北",
        "宿州",
        "蚌埠",
        "阜阳",
        "亳州",
    ),
}


# ============================================================
# 基础工具
# ============================================================

def today() -> dt.date:
    return dt.datetime.now(TZ).date()


def clean(value) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def extra(job: dict) -> dict:
    value = job.get("extra")

    if isinstance(value, dict):
        return value

    return {}


def job_text(job: dict) -> str:
    ext = extra(job)

    values = [
        job.get("company_name"),
        job.get("title"),
        job.get("jd_text"),
        job.get("location"),
        job.get("org_type"),
        job.get("job_type"),
        " ".join(job.get("tags") or []),
        ext.get("nature"),
        ext.get("nature_cn"),
        ext.get("recruitment_type"),
        ext.get("category"),
        ext.get("company_type"),
    ]

    return " ".join(
        clean(v)
        for v in values
        if v
    ).lower()


def clean_title(job: dict) -> str:
    title = clean(
        job.get("title")
    )

    company = clean(
        job.get("company_name")
    )

    if company and title.startswith(company):
        title = title[
            len(company):
        ].strip(
            " -—·:：、，,"
        )

    return (
        title
        or company
        or "招聘公告"
    )


def first_seen_day(job: dict) -> str:
    return clean(
        job.get("first_seen")
    )[:10]


def publish_day(job: dict) -> str:
    return clean(
        job.get("publish_time")
    )[:10]


def parse_date(
    value: str,
) -> dt.date | None:

    value = clean(value)

    if not value:
        return None

    # ISO日期
    match = re.search(
        r"20\d{2}-\d{1,2}-\d{1,2}",
        value,
    )

    if match:
        try:
            return dt.date.fromisoformat(
                match.group(0)
            )
        except ValueError:
            pass

    # 中文日期
    match = re.search(
        r"(20\d{2})年"
        r"(\d{1,2})月"
        r"(\d{1,2})日",
        value,
    )

    if match:
        try:
            return dt.date(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
            )
        except ValueError:
            pass

    return None


def is_expired(job: dict) -> bool:
    deadline = parse_date(
        job.get(
            "deadline",
            "",
        )
    )

    if deadline is None:
        return False

    return deadline < today()


# ============================================================
# 地区识别
# ============================================================

def region_name(job: dict) -> str:

    ext = extra(job)

    text = " ".join([
        clean(job.get("location")),
        clean(job.get("company_name")),
        clean(job.get("title")),
        clean(job.get("jd_text")),
        clean(ext.get("province")),
        clean(ext.get("city")),
    ])

    for region, keywords in REGION_KEYWORDS.items():

        if any(
            keyword in text
            for keyword in keywords
        ):
            return region

    return "其他地区"


def is_core_region(job: dict) -> bool:
    return region_name(job) in {
        "浙江",
        "江苏",
        "上海",
        "安徽",
    }


# ============================================================
# 判断央国企
# ============================================================

def is_state_owned(job: dict) -> bool:

    sid = clean(
        job.get("source_id")
    )

    org_type = clean(
        job.get("org_type")
    ).lower()

    company = clean(
        job.get("company_name")
    )

    hay = job_text(job)

    # 国务院国资委、央企招聘专栏
    if sid in CENTRAL_OFFICIAL_SOURCES:
        return True

    # source明确标记为国企
    if org_type in {
        "soe",
        "state-owned",
        "state_owned",
        "stateowned",
    }:
        return True

    # 数据中标注国企性质
    if STATE_OWNED_RE.search(hay):
        return True

    # 已知央企集团
    if any(
        keyword in company
        for keyword in CENTRAL_SOE_KEYWORDS
    ):
        return True

    return False


# ============================================================
# 江浙沪皖事业单位/编外补充
# ============================================================

def is_public_supplement(
    job: dict,
) -> bool:

    if not is_core_region(job):
        return False

    return bool(
        PUBLIC_SECTOR_RE.search(
            job_text(job)
        )
    )


# ============================================================
# 目标招聘判断
# ============================================================

def is_target_job(job: dict) -> bool:

    # 全国国央企招聘全部保留
    if is_state_owned(job):
        return True

    # 江浙沪皖事业单位/编外作为补充
    if is_public_supplement(job):
        return True

    return False


# ============================================================
# 招聘类型
# ============================================================

def recruitment_kind(
    job: dict,
) -> str:

    hay = job_text(job)

    # 第一优先级：2027届
    if COHORT_2027.search(hay):
        return "⭐27届校园招聘"

    # 普通校园招聘
    if CAMPUS_RE.search(hay):
        return "🟦校园招聘/应届生"

    # 事业单位/编外
    if is_public_supplement(job):

        if re.search(
            r"编外|劳务派遣|政府雇员",
            hay,
            re.I,
        ):
            return "🟪事业单位/编外"

        return "🟩事业单位招聘"

    # 国企社招
    if SOCIAL_RE.search(hay):
        return "🟧国企社会招聘"

    # 其余国企公告
    return "🟨国企公开招聘"


# ============================================================
# 企业级别
# ============================================================

def enterprise_level(
    job: dict,
) -> str:

    if is_public_supplement(job) and not is_state_owned(job):
        return "事业单位/编外"

    sid = clean(
        job.get("source_id")
    )

    company = clean(
        job.get("company_name")
    )

    hay = job_text(job)

    if sid in CENTRAL_OFFICIAL_SOURCES:
        return "央企"

    if any(
        keyword in company
        for keyword in CENTRAL_SOE_KEYWORDS
    ):
        return "央企"

    if PROVINCIAL_RE.search(hay):
        return "省属国企"

    if LOCAL_RE.search(hay):
        return "地方国企"

    return "国企"


# ============================================================
# 显示信息
# ============================================================

def location_text(job: dict) -> str:

    location = clean(
        job.get("location")
    )

    return (
        location
        or region_name(job)
        or "地区见公告"
    )


def deadline_text(job: dict) -> str:

    raw = clean(
        job.get("deadline")
    )

    if not raw:
        return "截止时间见公告"

    deadline = parse_date(raw)

    if deadline is None:
        return raw

    left = (
        deadline
        - today()
    ).days

    if left == 0:
        return (
            f"{deadline.isoformat()}"
            "（今天截止）"
        )

    if 0 < left <= 7:
        return (
            f"{deadline.isoformat()}"
            f"（剩{left}天）"
        )

    return deadline.isoformat()


def publish_text(job: dict) -> str:

    return (
        publish_day(job)
        or first_seen_day(job)
        or "日期见公告"
    )


def source_name(job: dict) -> str:

    sid = clean(
        job.get("source_id")
    )

    mapping = {
        "cn-iguopin": "国聘",
        "gov-sasac": "国务院国资委",
        "gov-qyzp": "央企招聘专栏",
        "gov-ncss": "国家24365",
        "gov-mohrss": "人社部/公共招聘",
    }

    if sid in mapping:
        return mapping[sid]

    if sid.startswith("edu-"):
        return "高校就业网"

    if sid.startswith("gov-"):
        return "政府官方网站"

    if sid:
        return sid

    return "招聘来源"


def line(job: dict) -> str:

    company = clean(
        job.get("company_name")
    ) or "未知单位"

    title = clean_title(job)

    location = location_text(job)

    deadline = deadline_text(job)

    publish = publish_text(job)

    source = source_name(job)

    kind = recruitment_kind(job)

    url = clean(
        job.get("official_url")
    )

    if not url:
        url = clean(
            job.get("url")
        )

    if url:
        head = (
            f"- [{company}｜{title}]"
            f"({url})"
        )
    else:
        head = (
            f"- {company}｜{title}"
        )

    return (
        f"{head}\n"
        f"> {kind}｜地区：{location}\n"
        f"> 发布：{publish}｜"
        f"截止：{deadline}｜"
        f"来源：{source}"
    )


# ============================================================
# 去重KEY
# ============================================================

def job_key(job: dict) -> str:

    # 保留原项目key，避免之前已经推送的8条重新发送
    return clean(
        job.get("dedup_key")
        or job.get("job_id")
        or job.get("official_url")
        or job.get("url")
        or (
            f"{job.get('source_id', '')}|"
            f"{job.get('company_name', '')}|"
            f"{job.get('title', '')}"
        )
    )


def semantic_key(job: dict) -> str:
    """
    第二层语义去重。
    用于不同网站重复发布同一条公告。
    """

    company = clean(
        job.get("company_name")
    ).lower()

    title = clean_title(
        job
    ).lower()

    location = clean(
        job.get("location")
    ).lower()

    return (
        f"{company}|"
        f"{title}|"
        f"{location}"
    )


# ============================================================
# 推送状态
# ============================================================

def load_state(path: str) -> dict:

    default = {
        "version": 2,
        "pushed_keys": {},
        "semantic_keys": {},
    }

    if (
        not path
        or not os.path.exists(path)
    ):
        return default

    try:
        with open(
            path,
            encoding="utf-8",
        ) as f:
            state = json.load(f)

    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
    ):
        return default

    if not isinstance(
        state.get("pushed_keys"),
        dict,
    ):
        state["pushed_keys"] = {}

    if not isinstance(
        state.get("semantic_keys"),
        dict,
    ):
        state["semantic_keys"] = {}

    state["version"] = 2

    return state


def is_pushed(
    job: dict,
    state: dict,
) -> bool:

    key = job_key(job)

    semantic = semantic_key(job)

    pushed = state.get(
        "pushed_keys",
        {},
    )

    semantic_pushed = state.get(
        "semantic_keys",
        {},
    )

    if key and key in pushed:
        return True

    if (
        semantic
        and semantic in semantic_pushed
    ):
        return True

    return False


def mark_pushed(
    path: str,
    jobs: list[dict],
) -> int:

    state = load_state(path)

    pushed = state.setdefault(
        "pushed_keys",
        {},
    )

    semantic_pushed = state.setdefault(
        "semantic_keys",
        {},
    )

    now = dt.datetime.now(
        dt.timezone.utc
    ).isoformat()

    added = 0

    for job in jobs:

        key = job_key(job)

        semantic = semantic_key(job)

        info = {
            "pushed_at": now,
            "first_seen": (
                job.get("first_seen")
                or ""
            ),
            "company": (
                job.get("company_name")
                or ""
            ),
            "title": clean_title(job),
            "source_id": (
                job.get("source_id")
                or ""
            ),
            "region": region_name(job),
            "kind": recruitment_kind(job),
        }

        if key and key not in pushed:
            pushed[key] = info
            added += 1

        if semantic:
            semantic_pushed[
                semantic
            ] = now

    state[
        "last_marked_at"
    ] = now

    state[
        "last_marked_count"
    ] = added

    os.makedirs(
        os.path.dirname(path),
        exist_ok=True,
    )

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2,
        )

        f.write("\n")

    return added


# ============================================================
# 来源优先级
# ============================================================

def source_score(
    job: dict,
) -> int:

    sid = clean(
        job.get("source_id")
    )

    if sid == "gov-sasac":
        return 100

    if sid == "gov-qyzp":
        return 98

    if clean(
        job.get("org_type")
    ).lower() == "soe":
        return 96

    if sid.startswith("gov-"):
        return 94

    if sid == "cn-iguopin":
        return 90

    if sid == "gov-ncss":
        return 88

    if sid == "gov-mohrss":
        return 86

    if sid.startswith("edu-"):
        return 75

    return 70


# ============================================================
# 排序
# ============================================================

def priority_sort_key(
    job: dict,
):

    region_score = {
        "浙江": 100,
        "江苏": 100,
        "上海": 100,
        "安徽": 100,
        "其他地区": 20,
    }

    kind_score = {
        "⭐27届校园招聘": 100,
        "🟦校园招聘/应届生": 90,
        "🟨国企公开招聘": 80,
        "🟧国企社会招聘": 70,
        "🟩事业单位招聘": 60,
        "🟪事业单位/编外": 50,
    }

    deadline = parse_date(
        job.get(
            "deadline",
            "",
        )
    )

    urgent = 0

    if deadline:
        left = (
            deadline
            - today()
        ).days

        if 0 <= left <= 3:
            urgent = 30
        elif 4 <= left <= 7:
            urgent = 20
        elif 8 <= left <= 14:
            urgent = 10

    return (
        region_score.get(
            region_name(job),
            0,
        ),
        kind_score.get(
            recruitment_kind(job),
            0,
        ),
        urgent,
        publish_day(job),
        first_seen_day(job),
        source_score(job),
    )


# ============================================================
# 同一次运行中的跨来源去重
# ============================================================

def deduplicate(
    jobs: list[dict],
) -> list[dict]:

    unique: dict[
        str,
        dict,
    ] = {}

    for job in jobs:

        signature = semantic_key(job)

        old = unique.get(
            signature
        )

        if old is None:
            unique[
                signature
            ] = job

            continue

        # 同一条招聘多个来源时，
        # 优先保留官方级别更高的来源
        if (
            source_score(job)
            >
            source_score(old)
        ):
            unique[
                signature
            ] = job

    return list(
        unique.values()
    )


# ============================================================
# 核心BUILD
#
# 保留原参数，确保原workflow和send_notify兼容
# ============================================================

def build(
    limit: int = 0,
    min_focus: int = 0,
    min_match: int = 0,
    mode: str = "new",
    since: str = "",
    include_existing_due: bool = False,
    state_path: str = STATE,
    ignore_state: bool = False,
    workbench_url: str = DEFAULT_WORKBENCH_URL,
) -> tuple[str, list[dict]]:

    # 这些旧参数仅为兼容原项目
    _ = (
        limit,
        min_focus,
        min_match,
        include_existing_due,
    )

    if not os.path.exists(JOBS):

        jobs = []

    else:

        with open(
            JOBS,
            encoding="utf-8",
        ) as f:
            jobs = json.load(f)

    # --------------------------------------------------------
    # 1. 过滤有效目标招聘
    # --------------------------------------------------------

    candidates: list[dict] = []

    for job in jobs:

        if job.get("gone"):
            continue

        if is_expired(job):
            continue

        if not is_target_job(job):
            continue

        candidates.append(job)

    # --------------------------------------------------------
    # 2. 同一次抓取内部去重
    # --------------------------------------------------------

    candidates = deduplicate(
        candidates
    )

    # --------------------------------------------------------
    # 3. 读取历史推送状态
    # --------------------------------------------------------

    if (
        state_path
        and not ignore_state
    ):

        state = load_state(
            state_path
        )

    else:

        state = {
            "pushed_keys": {},
            "semantic_keys": {},
        }

    # --------------------------------------------------------
    # 4. 新增过滤
    #
    # 最关键修改：
    # 不再只选“最新first_seen那一天”。
    # 只要没推送过，就永远留在待推送队列。
    # --------------------------------------------------------

    if mode == "all":

        pool = candidates

    else:

        pool = [
            job
            for job in candidates
            if not is_pushed(
                job,
                state,
            )
        ]

        # 只有手动指定 --since 才限制日期
        if since:

            pool = [
                job
                for job in pool
                if (
                    first_seen_day(job)
                    >= since
                )
            ]

    # --------------------------------------------------------
    # 5. 排序
    # --------------------------------------------------------

    pool.sort(
        key=priority_sort_key,
        reverse=True,
    )

    # --------------------------------------------------------
    # 6. 不再只推8条
    #
    # 所有未推送招聘全部进入发送队列。
    # --------------------------------------------------------

    selected = pool

    # --------------------------------------------------------
    # 7. 推送预览分组
    # --------------------------------------------------------

    region_groups = {
        "浙江": [],
        "江苏": [],
        "上海": [],
        "安徽": [],
        "其他地区": [],
    }

    for job in selected:

        region = region_name(job)

        region_groups.setdefault(
            region,
            [],
        ).append(job)

    # --------------------------------------------------------
    # 8. Markdown预览
    # --------------------------------------------------------

    lines = [
        (
            "# 🎯 江浙沪皖国资招聘雷达｜"
            f"{today().isoformat()}"
        ),
        "",
        (
            f"> 待推送招聘："
            f"**{len(selected)} 条**"
        ),
        "",
        (
            "> ⭐ 江浙沪皖优先，"
            "同时保留全国央企招聘"
        ),
        "",
    ]

    if workbench_url:

        lines.extend([
            (
                "[📋 查看完整招聘信息台]"
                f"({workbench_url})"
            ),
            "",
        ])

    for region in (
        "浙江",
        "江苏",
        "上海",
        "安徽",
        "其他地区",
    ):

        rows = region_groups.get(
            region,
            [],
        )

        if not rows:
            continue

        lines.append(
            f"## 📍 {region}｜"
            f"{len(rows)}条"
        )

        lines.append("")

        for job in rows:
            lines.append(
                line(job)
            )
            lines.append("")

    if not selected:

        lines.extend([
            "## 今日结果",
            "",
            "当前没有新的未推送招聘信息。",
            "",
        ])

    lines.extend([
        "---",
        (
            "已成功推送的岗位自动去重；"
            "未成功发送的岗位下次继续推送。"
        ),
    ])

    return (
        "\n".join(lines),
        selected,
    )


# ============================================================
# CLI
# ============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "江浙沪皖国资招聘雷达"
            "推送预览"
        )
    )

    parser.add_argument(
        "--out",
        default=OUT,
    )

    # 保留旧参数
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--min-focus",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--min-match",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--mode",
        choices=(
            "new",
            "all",
        ),
        default="new",
    )

    parser.add_argument(
        "--since",
        default="",
    )

    parser.add_argument(
        "--include-existing-due",
        action="store_true",
    )

    parser.add_argument(
        "--state",
        default=STATE,
    )

    parser.add_argument(
        "--ignore-state",
        action="store_true",
    )

    parser.add_argument(
        "--mark-pushed",
        action="store_true",
    )

    parser.add_argument(
        "--workbench-url",
        default=DEFAULT_WORKBENCH_URL,
    )

    args = parser.parse_args()

    os.makedirs(
        os.path.dirname(args.out),
        exist_ok=True,
    )

    md, selected = build(
        limit=args.limit,
        min_focus=args.min_focus,
        min_match=args.min_match,
        mode=args.mode,
        since=args.since,
        include_existing_due=(
            args.include_existing_due
        ),
        state_path=args.state,
        ignore_state=args.ignore_state,
        workbench_url=(
            args.workbench_url
        ),
    )

    with open(
        args.out,
        "w",
        encoding="utf-8",
    ) as f:
        f.write(md)

    print(
        "✅ 江浙沪皖国资招聘"
        f"推送预览已生成：{args.out}"
    )

    print(
        f"✅ 当前待推送 "
        f"{len(selected)} 条招聘信息"
    )

    region_count = {}

    for job in selected:

        region = region_name(job)

        region_count[
            region
        ] = (
            region_count.get(
                region,
                0,
            )
            + 1
        )

    for region in (
        "浙江",
        "江苏",
        "上海",
        "安徽",
        "其他地区",
    ):

        count = region_count.get(
            region,
            0,
        )

        print(
            f"  - {region}: "
            f"{count} 条"
        )

    if args.mark_pushed:

        added = mark_pushed(
            args.state,
            selected,
        )

        print(
            f"✅ 已标记 "
            f"{added} 条为已推送"
        )


if __name__ == "__main__":
    main()
