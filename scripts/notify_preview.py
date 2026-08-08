#!/usr/bin/env python3

"""
27届国央企招聘雷达 - 企业微信推送预览

目标：
1. 只保留央企 / 国企 / 省属国企 / 地方国企
2. 重点识别 2027届、27届、校园招聘、秋招、提前批、应届毕业生
3. 不再过滤机械、材料、电气、设备、工艺等岗位
4. 自动过滤已经推送过的招聘
5. 自动过滤已截止岗位
6. 企业微信按央企 / 省属国企 / 地方国企分类推送
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from collections import Counter
from zoneinfo import ZoneInfo


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")

JOBS = os.path.join(DATA_DIR, "jobs.json")
OUT = os.path.join(DATA_DIR, "notify_preview.md")
STATE = os.path.join(DATA_DIR, "notify_state.json")

DEFAULT_WORKBENCH_URL = os.getenv("WORKBENCH_URL", "").strip()

TZ = ZoneInfo("Asia/Shanghai")


# ============================================================
# 1. 央国企信源
# ============================================================

# 这两个来源本身就是央企官方/国家央企招聘专栏，可直接认为是央企来源
CENTRAL_OFFICIAL_SOURCES = {
    "gov-sasac",
    "gov-qyzp",
}


# ============================================================
# 2. 央企关键词
# ============================================================

CENTRAL_SOE_KEYWORDS = (
    "国家电网",
    "南方电网",

    "中国核工业",
    "中核集团",
    "中核",

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

    "中国石油",
    "中石油",
    "中国石化",
    "中石化",
    "中国海油",
    "中海油",
    "国家管网",

    "国家能源集团",
    "国家能源",
    "中国华能",
    "华能集团",
    "中国大唐",
    "大唐集团",
    "中国华电",
    "华电集团",
    "国家电投",
    "三峡集团",

    "中国移动",
    "中国电信",
    "中国联通",

    "中国一汽",
    "东风汽车集团",
    "中国中车",

    "中国宝武",
    "鞍钢集团",
    "中国铝业",

    "中国远洋海运",
    "招商局集团",
    "华润集团",
    "中信集团",

    "中国商飞",
    "中国邮政",
    "中国中煤",

    "中国建材",
    "中国建筑",
    "中建集团",
    "中国中铁",
    "中国铁建",
    "中国交建",

    "中国能建",
    "中国电建",

    "中粮集团",
    "中国五矿",
    "中国化学",
    "国投集团",
    "国家开发投资集团",
    "中广核",
)


# ============================================================
# 3. 招聘类型关键词
# ============================================================

COHORT_2027 = re.compile(
    r"2027\s*届|27\s*届|2027校招|2027校园招聘|2027秋招",
    re.I,
)

CAMPUS_RE = re.compile(
    r"校园招聘|校招|秋招|春招|提前批|应届生|应届毕业生|"
    r"高校毕业生|毕业生招聘|管培生|管理培训生",
    re.I,
)

SOCIAL_RE = re.compile(
    r"社会招聘|社招|社会人员招聘",
    re.I,
)

STATE_OWNED_RE = re.compile(
    r"央企|中央企业|国有企业|国企|国有控股|"
    r"省属企业|省属国企|市属企业|市属国企|地方国企",
    re.I,
)

PROVINCIAL_RE = re.compile(
    r"省属国企|省属企业|省国资委|省属重点企业",
    re.I,
)

LOCAL_RE = re.compile(
    r"市属国企|市属企业|市国资委|区属国企|"
    r"城投集团|交投集团|产投集团",
    re.I,
)


# ============================================================
# 基础工具
# ============================================================

def today() -> dt.date:
    return dt.datetime.now(TZ).date()


def tags(job: dict) -> set[str]:
    return set(job.get("tags") or [])


def extra(job: dict) -> dict:
    value = job.get("extra")
    return value if isinstance(value, dict) else {}


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def job_text(job: dict) -> str:
    ext = extra(job)

    values = [
        job.get("company_name"),
        job.get("title"),
        job.get("jd_text"),
        job.get("org_type"),
        job.get("job_type"),
        " ".join(job.get("tags") or []),
        ext.get("nature"),
        ext.get("recruitment_type"),
        ext.get("category"),
    ]

    return " ".join(clean(v) for v in values if v).lower()


def clean_title(job: dict) -> str:
    title = clean(job.get("title"))
    company = clean(job.get("company_name"))

    if company and title.startswith(company):
        title = title[len(company):].strip(" -—·:：、，,")

    return title or company or "招聘公告"


def job_key(job: dict) -> str:
    """
    优先使用项目本身的 dedup_key。
    """
    return clean(
        job.get("dedup_key")
        or job.get("job_id")
        or job.get("official_url")
        or (
            f"{job.get('source_id', '')}|"
            f"{job.get('company_name', '')}|"
            f"{job.get('title', '')}"
        )
    )


def first_seen_day(job: dict) -> str:
    return clean(job.get("first_seen"))[:10]


def publish_day(job: dict) -> str:
    return clean(job.get("publish_time"))[:10]


def parse_date(value: str) -> dt.date | None:
    value = clean(value)

    if len(value) < 10:
        return None

    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def is_expired(job: dict) -> bool:
    d = parse_date(job.get("deadline", ""))

    if d is None:
        return False

    return d < today()


# ============================================================
# 判断是不是央国企
# ============================================================

def is_state_owned(job: dict) -> bool:

    sid = clean(job.get("source_id"))
    org_type = clean(job.get("org_type")).lower()
    company = clean(job.get("company_name"))
    hay = job_text(job)

    # 国资委、中央企业应届毕业生招聘专栏
    if sid in CENTRAL_OFFICIAL_SOURCES:
        return True

    # 企业官网信源明确标记为 soe
    if org_type == "soe":
        return True

    # 数据中直接标明企业性质
    if STATE_OWNED_RE.search(hay):
        return True

    # 已知央企集团
    if any(k in company for k in CENTRAL_SOE_KEYWORDS):
        return True

    return False


# ============================================================
# 判断是不是 27 届 / 校招
# ============================================================

def is_2027_recruitment(job: dict) -> bool:

    hay = job_text(job)
    sid = clean(job.get("source_id"))
    job_type = clean(job.get("job_type")).lower()

    # 明确写 2027 届
    if COHORT_2027.search(hay):
        return True

    # 明确社招，并且没有任何校园招聘信息
    if SOCIAL_RE.search(hay) and not CAMPUS_RE.search(hay):
        return False

    # 人社部央企应届毕业生专栏
    if sid == "gov-qyzp":
        return True

    # 项目已经识别为 campus
    campus_signal = (
        job_type == "campus"
        or bool(CAMPUS_RE.search(hay))
    )

    if not campus_signal:
        return False

    # 2026年7月以后出现的秋招/校园招聘，
    # 在当前周期主要对应 2027 届
    pub = parse_date(job.get("publish_time", ""))

    if pub and pub >= dt.date(2026, 7, 1):
        return True

    # 有些高校就业网不给发布日期。
    # 如果是本次新抓到的校园招聘，也予以保留。
    fs = parse_date(job.get("first_seen", ""))

    if fs and fs >= dt.date(2026, 7, 1):
        return True

    return False


# ============================================================
# 企业级别分类
# ============================================================

def enterprise_level(job: dict) -> str:

    sid = clean(job.get("source_id"))
    company = clean(job.get("company_name"))
    hay = job_text(job)

    if sid in CENTRAL_OFFICIAL_SOURCES:
        return "央企"

    if any(k in company for k in CENTRAL_SOE_KEYWORDS):
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
    loc = clean(job.get("location"))
    return loc or "地区见公告"


def deadline_text(job: dict) -> str:

    raw = clean(job.get("deadline"))

    if not raw:
        return "截止时间见公告"

    d = parse_date(raw)

    if d is None:
        return raw

    left = (d - today()).days

    if left == 0:
        return f"{d.isoformat()}（今天截止）"

    if 0 < left <= 7:
        return f"{d.isoformat()}（剩{left}天）"

    return d.isoformat()


def publish_text(job: dict) -> str:
    return publish_day(job) or first_seen_day(job) or "日期见公告"


def source_name(job: dict) -> str:

    sid = clean(job.get("source_id"))

    mapping = {
        "cn-iguopin": "国聘",
        "gov-sasac": "国务院国资委",
        "gov-qyzp": "央企应届招聘专栏",
        "gov-ncss": "国家24365",
        "gov-mohrss": "人社部",
    }

    if sid in mapping:
        return mapping[sid]

    if sid.startswith("edu-"):
        return "高校就业网"

    return "企业官网"


def line(job: dict) -> str:

    company = clean(job.get("company_name")) or "未知企业"
    title = clean_title(job)
    loc = location_text(job)
    deadline = deadline_text(job)
    pub = publish_text(job)
    source = source_name(job)
    url = clean(job.get("official_url"))

    if url:
        head = f"- [{company}｜{title}]({url})"
    else:
        head = f"- {company}｜{title}"

    return (
        f"{head}\n"
        f"  地区：{loc}｜发布：{pub}｜截止：{deadline}｜来源：{source}"
    )


# ============================================================
# 推送状态
# ============================================================

def load_state(path: str) -> dict:

    if not path or not os.path.exists(path):
        return {
            "version": 1,
            "pushed_keys": {},
        }

    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return {
            "version": 1,
            "pushed_keys": {},
        }

    if not isinstance(state.get("pushed_keys"), dict):
        state["pushed_keys"] = {}

    state.setdefault("version", 1)

    return state


def is_pushed(job: dict, state: dict) -> bool:

    key = job_key(job)

    return bool(
        key
        and key in state.get("pushed_keys", {})
    )


def mark_pushed(path: str, jobs: list[dict]) -> int:

    state = load_state(path)
    pushed = state.setdefault("pushed_keys", {})

    now = dt.datetime.now(dt.timezone.utc).isoformat()

    added = 0

    for job in jobs:

        key = job_key(job)

        if not key or key in pushed:
            continue

        pushed[key] = {
            "pushed_at": now,
            "first_seen": job.get("first_seen") or "",
            "company": job.get("company_name") or "",
            "title": clean_title(job),
            "source_id": job.get("source_id") or "",
        }

        added += 1

    state["last_marked_at"] = now
    state["last_marked_count"] = added

    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2,
        )
        f.write("\n")

    return added


# ============================================================
# 排序
# ============================================================

def source_score(job: dict) -> int:

    sid = clean(job.get("source_id"))

    if sid == "gov-sasac":
        return 100

    if sid == "gov-qyzp":
        return 98

    if clean(job.get("org_type")).lower() == "soe":
        return 95

    if sid == "cn-iguopin":
        return 90

    if sid == "gov-ncss":
        return 85

    if sid == "gov-mohrss":
        return 82

    if sid.startswith("edu-"):
        return 75

    return 70


def sort_key(job: dict):

    deadline = parse_date(job.get("deadline", ""))

    urgent = 0

    if deadline:
        left = (deadline - today()).days

        if 0 <= left <= 7:
            urgent = 1

    return (
        first_seen_day(job),
        publish_day(job),
        urgent,
        source_score(job),
    )


def pick_rows(rows: list[dict], limit: int) -> list[dict]:
    """
    同一家企业最多推送 2 条，避免某一家企业刷屏。
    """

    counts = Counter()
    picked = []

    for job in rows:

        company = clean(job.get("company_name"))

        if counts[company] >= 2:
            continue

        picked.append(job)
        counts[company] += 1

        if len(picked) >= limit:
            break

    return picked


# ============================================================
# 核心 Build
#
# 参数保持与原项目一致，确保 send_notify.py 无需修改
# ============================================================

def build(
    limit: int = 8,
    min_focus: int = 120,
    min_match: int = 50,
    mode: str = "new",
    since: str = "",
    include_existing_due: bool = False,
    state_path: str = STATE,
    ignore_state: bool = False,
    workbench_url: str = DEFAULT_WORKBENCH_URL,
) -> tuple[str, list[dict]]:

    # min_focus / min_match 为兼容旧版参数保留
    _ = min_focus, min_match, include_existing_due

    with open(JOBS, encoding="utf-8") as f:
        jobs = json.load(f)

    # --------------------------------------------------------
    # 第一步：只保留有效岗位
    # --------------------------------------------------------

    candidates = []

    for job in jobs:

        if job.get("gone"):
            continue

        if is_expired(job):
            continue

        if not is_state_owned(job):
            continue

        if not is_2027_recruitment(job):
            continue

        candidates.append(job)

    candidates.sort(
        key=sort_key,
        reverse=True,
    )

    # --------------------------------------------------------
    # 第二步：新增过滤
    # --------------------------------------------------------

    state = (
        load_state(state_path)
        if state_path and not ignore_state
        else {"pushed_keys": {}}
    )

    if mode == "all":

        pool = candidates

    else:

        if since:
            since_day = since
        else:
            latest = max(
                (
                    first_seen_day(j)
                    for j in candidates
                    if first_seen_day(j)
                ),
                default=today().isoformat(),
            )

            since_day = latest

        pool = [
            j
            for j in candidates
            if first_seen_day(j) >= since_day
        ]

        pool = [
            j
            for j in pool
            if not is_pushed(j, state)
        ]

    # --------------------------------------------------------
    # 第三步：再次按招聘信息去重
    # --------------------------------------------------------

    unique = {}

    for job in pool:

        signature = (
            clean(job.get("company_name")).lower(),
            clean_title(job).lower(),
        )

        old = unique.get(signature)

        if old is None:
            unique[signature] = job
            continue

        if source_score(job) > source_score(old):
            unique[signature] = job

    pool = list(unique.values())

    pool.sort(
        key=sort_key,
        reverse=True,
    )

    # 企业微信单次推送保持精简
    selected = pick_rows(
        pool,
        max(1, limit),
    )

    # --------------------------------------------------------
    # 第四步：按企业类型分组
    # --------------------------------------------------------

    central = [
        j for j in selected
        if enterprise_level(j) == "央企"
    ]

    provincial = [
        j for j in selected
        if enterprise_level(j) == "省属国企"
    ]

    local = [
        j for j in selected
        if enterprise_level(j) == "地方国企"
    ]

    other = [
        j for j in selected
        if enterprise_level(j) == "国企"
    ]

    # --------------------------------------------------------
    # 第五步：企业微信 Markdown
    # --------------------------------------------------------

    lines = [
        f"# 🎯 27届国央企招聘雷达｜{today().isoformat()}",
        "",
        f"> 新增符合条件：**{len(pool)} 条**",
        f"> 本次推送：**{len(selected)} 条**",
        "",
    ]

    if workbench_url:
        lines.extend([
            f"[📋 查看完整招聘信息台]({workbench_url})",
            "",
        ])

    groups = [
        ("🏢 央企", central),
        ("🏛️ 省属国企", provincial),
        ("🏙️ 地方国企", local),
        ("📌 其他国企", other),
    ]

    for title, rows in groups:

        if not rows:
            continue

        lines.append(f"## {title}")

        for job in rows:
            lines.append(line(job))

        lines.append("")

    if not selected:

        lines.extend([
            "## 今日结果",
            "",
            "今天暂未发现新的27届国央企校招信息。",
            "",
        ])

    lines.extend([
        "---",
        "仅推送新增信息，历史岗位自动去重。",
    ])

    return "\n".join(lines), selected


# ============================================================
# CLI
# ============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description="27届国央企招聘雷达推送预览"
    )

    parser.add_argument(
        "--out",
        default=OUT,
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=8,
    )

    # 保留旧参数兼容 send_notify.py
    parser.add_argument(
        "--min-focus",
        type=int,
        default=120,
    )

    parser.add_argument(
        "--min-match",
        type=int,
        default=50,
    )

    parser.add_argument(
        "--mode",
        choices=("new", "all"),
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
        include_existing_due=args.include_existing_due,
        state_path=args.state,
        ignore_state=args.ignore_state,
        workbench_url=args.workbench_url,
    )

    with open(
        args.out,
        "w",
        encoding="utf-8",
    ) as f:
        f.write(md)

    print(
        f"✅ 27届国央企招聘推送预览已生成：{args.out}"
    )

    print(
        f"✅ 本次选中 {len(selected)} 条招聘信息"
    )

    if args.mark_pushed:

        added = mark_pushed(
            args.state,
            selected,
        )

        print(
            f"✅ 已标记 {added} 条为已推送"
        )


if __name__ == "__main__":
    main()
