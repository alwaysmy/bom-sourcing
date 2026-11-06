#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""品牌索引：按品类枚举立创品牌 facet，修复「采样式知识库」的覆盖率缺陷。

为什么要有它
------------
`data/knowledge/vendors.yaml` 是**关键词驱动采样**建起来的（用 "稳压""电阻""SS34"
这类词检索，再从结果里收品牌）。盲区：只卖冷门料的品牌（例如 Tokmas 的 ULN2803
达林顿阵列）永远不出现在热门关键词结果里，于是永远进不了知识库。

实测（2026-11-06）：26 个品类的品牌 facet 合计 1,296 个品牌，vendors.yaml 只覆盖 22.3%。

本模块改为**按品类枚举品牌 facet**（`gradePlateGroup` 天然返回该品类全部品牌 + 条数），
产出 `data/knowledge/brands.index.yaml`：

    brand_id → {name, short, cn, aliases, families, part_count}

与 vendors.yaml 的关系
----------------------
- `brands.index.yaml` = **全集**（谁是立创在售品牌、卖在哪些品类、多少条料）；
- `vendors.yaml`     = **有证据的子集**（tier / 价差 / 风险备注，人工与实测得来）。
两者用 brand_id 关联，查不到 tier 时回落到 `unknown`。

用法
----
    python brands.py build                 # 扫 26 个品类，重建索引（约 40 秒）
    python brands.py lookup tokmas        # 按名字/别名/品牌号查
    python brands.py coverage             # 覆盖率体检（index vs vendors.yaml）
    python brands.py list --family mosfet # 列某品类的品牌
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lcsc  # noqa: E402

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CATEGORIES = os.path.join(ROOT, "data", "categories.yaml")
VENDORS = os.path.join(ROOT, "data", "knowledge", "vendors.yaml")
INDEX = os.path.join(ROOT, "data", "knowledge", "brands.index.yaml")

SCHEMA = "bom-sourcing/knowledge/brands-index"
VERSION = 1

_NAME_RE = re.compile(r"^\s*(?P<short>[^()（）]*?)\s*[（(]\s*(?P<cn>[^()（）]*?)\s*[)）]\s*$")


def _now():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def norm(s):
    """品牌名归一：小写 + 去空白 + 去括号（与 blacklist.py 同一口径）。"""
    t = str(s or "").lower()
    for ch in (" ", "\t", "(", ")", "（", "）", "【", "】", "[", "]"):
        t = t.replace(ch, "")
    return t


def split_name(label):
    """`VBsemi(微碧半导体)` → ("VBsemi", "微碧半导体")；没括号时 cn 为空。"""
    m = _NAME_RE.match(str(label or ""))
    if m:
        return (m.group("short") or "").strip(), (m.group("cn") or "").strip()
    return str(label or "").strip(), ""


def aliases_of(label):
    short, cn = split_name(label)
    out = []
    for x in (short, cn):
        if x and x not in out:
            out.append(x)
    return short, cn, out


def load_yaml(path, default=None):
    if yaml is None or not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or default


def load_categories(path=CATEGORIES):
    data = load_yaml(path, {}) or {}
    return data.get("families") or {}


def load_vendors(path=VENDORS):
    data = load_yaml(path, {}) or {}
    return data.get("vendors") or {}


def vendor_name_set(vendors=None):
    """vendors.yaml 里所有名字与别名的归一集合。"""
    vendors = vendors if vendors is not None else load_vendors()
    out = set()
    for _k, v in (vendors or {}).items():
        if not isinstance(v, dict):
            continue
        for n in [v.get("name")] + list(v.get("aka") or []):
            if n:
                out.add(norm(n))
    return out


# --------------------------------------------------------------------------- 构建


def scan(categories=None, rate=1.0, sleep=0.0, verbose=True):
    """按品类扫品牌 facet，返回 {brand_id: {...}}。"""
    cats = categories if categories is not None else load_categories()
    cli = lcsc.Lcsc(rate_limit=rate)
    brands = {}
    for key, c in cats.items():
        label = c.get("label_cn") or key
        cid = str(c.get("catalog_id") or "")
        try:
            res = cli.raw_search(label, catalog_id=cid, page_size=30)
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"[跳过] {label}: {type(e).__name__}: {str(e)[:80]}")
            continue
        facets = res.get("brands") or []
        for f in facets:
            bid = str(f.get("value") or "").strip()
            name = str(f.get("label") or "").strip()
            if not bid or not name:
                continue
            item = brands.setdefault(bid, {"name": name, "families": [], "part_count": 0})
            if key not in item["families"]:
                item["families"].append(key)
            item["part_count"] += int(f.get("count") or 0)
        if verbose:
            print(f"  {label:28} 品牌 {len(facets):4}")
        if sleep:
            time.sleep(sleep)
    return brands


def build(path=INDEX, rate=1.0, sleep=0.0, verbose=True):
    """扫描并写出 brands.index.yaml（覆盖写，带时间戳与统计）。"""
    if yaml is None:
        raise RuntimeError("需要 PyYAML")
    cats = load_categories()
    brands = scan(cats, rate=rate, sleep=sleep, verbose=verbose)
    known = vendor_name_set()
    entries = {}
    for bid, info in sorted(brands.items(), key=lambda kv: -kv[1]["part_count"]):
        short, cn, al = aliases_of(info["name"])
        v = sorted({x for x in [info["name"]] + al})
        matched = [x for x in v if norm(x) in known]
        entries[bid] = {
            "name": info["name"],
            "short": short,
            "cn": cn,
            "aliases": al,
            "families": sorted(info["families"]),
            "part_count": info["part_count"],
            "in_vendors": bool(matched),
        }
    doc = {
        "schema": SCHEMA,
        "version": VERSION,
        "generated": _now(),
        "purpose": "立创在售品牌全集（按品类枚举品牌 facet），用于品牌解析/覆盖率体检；"
                   "厂商分层与风险见 vendors.yaml，两者以 brand_id 关联。",
        "source": "POST https://so.szlcsc.com/query/product → searchResult.gradePlateGroup",
        "catalogs_scanned": len(cats),
        "brands": len(entries),
        "in_vendors": sum(1 for e in entries.values() if e["in_vendors"]),
        "index": dict(sorted(entries.items(), key=lambda kv: -kv[1]["part_count"])),
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False, width=200)
    return doc


def load_index(path=INDEX):
    data = load_yaml(path, {}) or {}
    return data.get("index") or {}


# --------------------------------------------------------------------------- 查询


def lookup(text, path=INDEX, limit=10):
    """按名字/中文名/别名/品牌号查（子串，忽略大小写与括号）。"""
    idx = load_index(path)
    q = norm(text)
    if not q:
        return []
    hits = []
    if q.lstrip("c").isdigit() and q.startswith("c"):  # C123 形式
        q = q[1:]
    for bid, e in idx.items():
        pool = [bid, e.get("name"), e.get("short"), e.get("cn")] + list(e.get("aliases") or [])
        if any(x and q in norm(x) for x in pool):
            hits.append(dict(e, brand_id=bid))
    hits.sort(key=lambda e: -int(e.get("part_count") or 0))
    return hits[:limit]


def coverage(path=INDEX, vendors_path=VENDORS):
    """覆盖率体检：index 里的品牌有多少进了 vendors.yaml。"""
    idx = load_index(path)
    known = vendor_name_set(load_vendors(vendors_path))
    total = len(idx)
    hit = [e for e in idx.values() if e.get("in_vendors")]
    missing = [e for e in idx.values() if not e.get("in_vendors")]
    missing.sort(key=lambda e: -int(e.get("part_count") or 0))
    return {
        "index_brands": total,
        "in_vendors": len(hit),
        "missing": len(missing),
        "coverage_pct": round(100.0 * len(hit) / total, 1) if total else 0.0,
        "top_missing": [{"name": e["name"], "part_count": e["part_count"],
                         "families": e["families"][:4]} for e in missing[:20]],
        "vendors_names": len(known),
    }


def by_family(family, path=INDEX):
    idx = load_index(path)
    rows = [(bid, e) for bid, e in idx.items() if family in (e.get("families") or [])]
    rows.sort(key=lambda kv: -int(kv[1].get("part_count") or 0))
    return rows


# --------------------------------------------------------------------------- CLI


def cmd_build(a):
    doc = build(path=a.out or INDEX, rate=a.rate, sleep=a.sleep)
    print(f"已写出 {a.out or INDEX}")
    print(f"  品类 {doc['catalogs_scanned']}  品牌 {doc['brands']}  "
          f"其中 vendors.yaml 已收录 {doc['in_vendors']}")
    return 0


def cmd_lookup(a):
    hits = lookup(a.text, limit=a.limit)
    if not hits:
        print(f"没有匹配「{a.text}」的品牌。")
        return 1
    if a.json:
        print(json.dumps(hits, ensure_ascii=False, indent=1))
        return 0
    print(f"命中 {len(hits)} 个品牌：\n")
    print(f"{'brand_id':>8}  {'品牌':30} {'料号数':>8}  品类")
    for e in hits:
        fam = ",".join(e.get("families") or [])[:44]
        print(f"{e['brand_id']:>8}  {str(e.get('name'))[:30]:30} {e.get('part_count'):>8}  {fam}")
    return 0


def cmd_coverage(a):
    rep = coverage()
    print(f"索引品牌 {rep['index_brands']}；vendors.yaml 已覆盖 {rep['in_vendors']}"
          f"（{rep['coverage_pct']}%）；未收录 {rep['missing']}")
    print("\n未收录里料号最多的 20 个：")
    print(f"{'品牌':32} {'料号数':>8}  品类")
    for e in rep["top_missing"]:
        print(f"{str(e['name'])[:32]:32} {e['part_count']:>8}  {','.join(e['families'])[:40]}")
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


def cmd_list(a):
    rows = by_family(a.family)
    print(f"{a.family} 品类共 {len(rows)} 个品牌（按料号数降序，前 {a.limit}）：\n")
    print(f"{'brand_id':>8}  {'品牌':30} {'料号数':>8}  vendors")
    for bid, e in rows[: a.limit]:
        print(f"{bid:>8}  {str(e.get('name'))[:30]:30} {e.get('part_count'):>8}  "
              f"{'✔' if e.get('in_vendors') else '—'}")
    return 0


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    p = argparse.ArgumentParser(description="立创品牌索引（按品类枚举品牌 facet）")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="扫描品类品牌 facet 并重建索引")
    b.add_argument("--out", default="", help="输出路径（默认 data/knowledge/brands.index.yaml）")
    b.add_argument("--rate", type=float, default=1.0, help="同站最小间隔秒（默认 1.0）")
    b.add_argument("--sleep", type=float, default=0.0, help="额外等待秒")
    b.set_defaults(func=cmd_build)

    lk = sub.add_parser("lookup", help="按名字/别名/品牌号查")
    lk.add_argument("text")
    lk.add_argument("--limit", type=int, default=10)
    lk.add_argument("--json", action="store_true")
    lk.set_defaults(func=cmd_lookup)

    cv = sub.add_parser("coverage", help="覆盖率体检（index vs vendors.yaml）")
    cv.add_argument("--json", action="store_true")
    cv.set_defaults(func=cmd_coverage)

    ls = sub.add_parser("list", help="列某品类的品牌")
    ls.add_argument("--family", required=True)
    ls.add_argument("--limit", type=int, default=30)
    ls.set_defaults(func=cmd_list)

    a = p.parse_args(argv)
    try:
        return a.func(a)
    except lcsc.AntiBotError as e:  # 反爬时给人话
        print(f"[反爬] {e}", file=sys.stderr)
        print(lcsc._ANTIBOT_HINT, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
