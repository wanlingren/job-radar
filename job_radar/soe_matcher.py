"""江浙沪皖国企主体库匹配器。

设计原则：
1. 官方/人工核验主体库优先；
2. 名称与别名匹配优先于关键词猜测；
3. 自动生成库和人工种子库分离，便于 GitHub Actions 持续扩充；
4. 仅在没有主体库命中时才由 target_rules 使用旧关键词兜底。
"""
from __future__ import annotations

import csv
import os
import re
from functools import lru_cache
from typing import Dict, Iterable, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config")
SEED = os.path.join(CONFIG, "soe_registry.csv")
GENERATED = os.path.join(CONFIG, "soe_registry_generated.csv")
ALIASES = os.path.join(CONFIG, "soe_aliases.csv")

_SUFFIX_RE = re.compile(
    r"(?:有限责任公司|股份有限公司|集团有限公司|控股有限公司|有限公司|集团|公司)$"
)
_PUNCT_RE = re.compile(r"[\s·•（）()【】\[\]《》<>“”\"'，,。.:：;；/\\|｜\-_]+")


def _read_csv(path: str) -> List[Dict[str, str]]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return []
    return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(lines)]


def normalize_name(value: str) -> str:
    s = _PUNCT_RE.sub("", str(value or "")).lower()
    # 去掉少量常见公司后缀用于宽松别名匹配，但保留集团/研究所等主体特征
    s = re.sub(r"有限责任公司$|股份有限公司$|集团有限公司$|有限公司$", "", s)
    return s


def _iter_aliases(row: Dict[str, str]) -> Iterable[str]:
    vals = [row.get("canonical_name", ""), row.get("short_name", "")]
    vals.extend((row.get("aliases", "") or "").split("|"))
    for v in vals:
        v = (v or "").strip()
        if len(v) >= 2:
            yield v


@lru_cache(maxsize=1)
def registry() -> List[Dict[str, str]]:
    rows: Dict[str, Dict[str, str]] = {}
    for path in (SEED, GENERATED):
        for r in _read_csv(path):
            key = r.get("entity_id") or normalize_name(r.get("canonical_name", ""))
            if not key:
                continue
            old = rows.get(key)
            # generated 里通常有更新的 website/source/last_verified，覆盖空字段但不抹掉人工字段
            if old:
                merged = dict(old)
                for k, v in r.items():
                    if v:
                        merged[k] = v
                rows[key] = merged
            else:
                rows[key] = r

    alias_extra: Dict[str, List[str]] = {}
    for a in _read_csv(ALIASES):
        entity = a.get("entity_id", "")
        alias = a.get("alias", "")
        if entity and alias:
            alias_extra.setdefault(entity, []).append(alias)

    out = []
    for r in rows.values():
        extras = alias_extra.get(r.get("entity_id", ""), [])
        if extras:
            existing = [x for x in (r.get("aliases", "") or "").split("|") if x]
            r = dict(r)
            r["aliases"] = "|".join(dict.fromkeys(existing + extras))
        out.append(r)
    return out


@lru_cache(maxsize=1)
def _alias_index():
    idx = []
    for row in registry():
        for alias in _iter_aliases(row):
            n = normalize_name(alias)
            if len(n) >= 2:
                idx.append((n, alias, row))
    # 长名称先匹配，避免“国投”先吞掉“国家开发投资集团”
    idx.sort(key=lambda x: len(x[0]), reverse=True)
    return idx


def reload_registry() -> None:
    registry.cache_clear()
    _alias_index.cache_clear()


def match_company(name: str) -> Optional[Dict[str, str]]:
    n = normalize_name(name)
    if not n:
        return None

    # 1) 完全匹配
    for alias_n, _alias, row in _alias_index():
        if n == alias_n:
            return dict(row)

    # 2) 长别名包含匹配。要求别名足够长，减少“国投/城投”等泛词误判
    for alias_n, _alias, row in _alias_index():
        if len(alias_n) >= 4 and (alias_n in n or n in alias_n and len(n) >= 5):
            return dict(row)
    return None


def match_text(text: str) -> Optional[Dict[str, str]]:
    n = normalize_name(text)
    if not n:
        return None
    for alias_n, _alias, row in _alias_index():
        # 文本场景限制更严格
        if len(alias_n) >= 4 and alias_n in n:
            return dict(row)
    return None


def is_registered_soe(name: str, text: str = "") -> bool:
    return bool(match_company(name) or (text and match_text(text)))


def parent_central_group(name: str, text: str = "") -> str:
    row = match_company(name) or (match_text(text) if text else None)
    if not row:
        return ""
    if row.get("level", "").startswith("央企"):
        return row.get("parent_group") or row.get("canonical_name", "")
    return row.get("parent_group", "")


def enrich(job: dict) -> dict:
    """返回主体库补充字段，不直接修改 Job 模型。"""
    name = str(job.get("company_name") or "")
    text = " ".join(str(job.get(k) or "") for k in ("title", "jd_text", "location"))
    row = match_company(name) or match_text(text)
    if not row:
        return {}
    return {
        "soe_entity_id": row.get("entity_id", ""),
        "soe_canonical_name": row.get("canonical_name", ""),
        "soe_level": row.get("level", ""),
        "soe_parent_group": row.get("parent_group", ""),
        "soe_regulator": row.get("regulator", ""),
        "soe_province": row.get("province", ""),
        "soe_city": row.get("city", ""),
        "soe_district": row.get("district", ""),
        "soe_registry_source": row.get("source_url", ""),
    }
