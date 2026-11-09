# -*- coding: utf-8 -*-
"""品牌背调队列 —— 按「料号数量 × 采购频次」排优先级，决定先查哪个品牌。

为什么需要队列：`brands.index.yaml` 有 1,296 个品牌，`vendors.yaml` 只覆盖 138 个，
逐个背调是人力活，必须有明确的先后。优先级不能只看料号数（Knowles 22 万条全是 MLCC
一个品类，实际采购面很窄），要乘上"品类广度"（跨品类 = 通用品牌 = 更容易被用到）。

优先级分数（越大越先查）：
    score = 2.0 * log10(part_count + 1)      # 料号规模（对数压缩，避免被巨头垄断）
          + 0.4 * 品类数量                   # 品类广度（跨品类的品牌更通用）
          + 1.5 * 常用品类命中数             # 采购频次代理：阻容感/二极管/MOS/电源/MCU/连接器
          + 6.0 * 已登记待背调               # pending 队列直接插队
          + 3.0 * 出现过待确认料号           # 在我们自己的结果里出现过
          - 3.0 * 知识库已有分层             # 已核过的降权

用法：
  python brand_queue.py                      # 前 20 名
  python brand_queue.py --limit 50 --family ldo
  python brand_queue.py --pending            # 只看待背调/未背调的
  python brand_queue.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
INDEX = BASE / "data" / "knowledge" / "brands.index.yaml"
VENDORS = BASE / "data" / "knowledge" / "vendors.yaml"
WHITELIST = BASE / "data" / "knowledge" / "whitelist.yaml"

# 采购频次代理：这几个品类几乎每个项目都会用到
COMMON_FAMILIES = {
    "resistor", "mlcc", "inductor", "bead", "led", "diode", "schottky", "tvs", "esd",
    "mosfet", "bjt", "ldo", "dcdc", "mcu", "crystal", "connector", "eeprom", "norflash",
}

FAMILY_CN = {
    "resistor": "贴片电阻", "mlcc": "贴片电容", "inductor": "电感", "bead": "磁珠",
    "led": "LED", "diode": "二极管", "schottky": "肖特基", "tvs": "TVS", "esd": "ESD",
    "bjt": "三极管", "mosfet": "MOSFET", "mcu": "MCU", "ldo": "LDO", "dcdc": "DC-DC",
    "opamp": "运放", "comparator": "比较器", "vref": "电压基准", "eeprom": "EEPROM",
    "norflash": "NOR FLASH", "crystal": "无源晶振", "oscillator": "有源晶振",
    "isolator": "数字隔离器", "optocoupler": "光耦", "connector": "连接器", "relay": "继电器",
    "powerswitch": "功率电子开关", "electrolytic": "铝电解",
}


def _load_yaml(p: Path) -> dict:
    if not p.exists():
        return {}
    import yaml  # noqa: PLC0415

    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def load_queue() -> list:
    """返回按优先级降序的队列行。"""
    idx = (_load_yaml(INDEX).get("index") or {})
    vendors = (_load_yaml(VENDORS).get("vendors") or {})
    wl = (_load_yaml(WHITELIST).get("brands") or {})

    # 品牌名归一 → 白名单条目
    def norm(s: str) -> str:
        return "".join(ch for ch in str(s or "").lower() if not ch.isspace() and ch not in "()（）【】[]")

    wl_map = {}
    for slug, e in wl.items():
        for n in [slug, e.get("name") or ""] + list(e.get("aka") or []):
            k = norm(n)
            if k:
                wl_map.setdefault(k, e)

    vendor_names = set()
    for key, e in vendors.items():
        if not isinstance(e, dict):
            continue
        for n in [key, e.get("name") or ""] + list(e.get("aka") or []):
            k = norm(n)
            if k:
                vendor_names.add(k)

    rows = []
    for brand_id, info in idx.items():
        name = info.get("name") or str(brand_id)
        fams = list(info.get("families") or [])
        part_count = int(info.get("part_count") or 0)
        wl_entry = wl_map.get(norm(name))
        approved = list((wl_entry or {}).get("approved") or [])
        pending = list((wl_entry or {}).get("pending") or [])
        appr_fams = {str(a.get("family") or "") for a in approved}
        pend_fams = {str(p.get("family") or "") for p in pending}
        # family="*" = 全线放行（IDM 原厂），覆盖该品牌在立创的全部品类
        wildcard = "*" in appr_fams
        covered = set(fams) if wildcard else (appr_fams & set(fams))
        uncovered = [] if wildcard else [f for f in fams if f not in appr_fams]
        if not uncovered and fams:
            status = "done"            # 本品类的全部品类都已背调
        elif pend_fams & set(fams):
            status = "pending"         # 有登记待背调
        elif approved:
            status = "partial"         # 部分品类通过
        elif norm(name) in vendor_names:
            status = "kb_only"         # 知识库有分层但无白名单
        else:
            status = "unknown"         # 完全没记录

        common = len(set(fams) & COMMON_FAMILIES)
        score = (2.0 * math.log10(part_count + 1)
                 + 0.4 * len(fams)
                 + 1.5 * common
                 + (6.0 if status == "pending" else 0.0)
                 - (3.0 if status in ("done", "partial") else 0.0)
                 - (1.0 if norm(name) in vendor_names else 0.0))
        rows.append({
            "brand_id": brand_id, "name": name, "part_count": part_count,
            "families": fams, "family_count": len(fams), "common_families": common,
            "tier": (wl_entry or {}).get("tier") or ("original_idm" if norm(name) in vendor_names else "unknown"),
            "status": status, "approved_families": sorted(appr_fams - {""}),
            "pending_families": sorted(pend_fams - {""}),
            "uncovered_families": uncovered,
            "score": round(score, 2),
        })
    rows.sort(key=lambda r: -r["score"])
    return rows


STATUS_CN = {
    "done": "✅ 已全部背调", "partial": "◐ 部分品类通过", "pending": "⏳ 待背调",
    "kb_only": "📚 仅知识库分层", "unknown": "❔ 未背调",
}


def render(rows, limit=20, family=None) -> str:
    sel = rows
    if family:
        fam = family.strip().lower()
        sel = [r for r in sel if fam in [f.lower() for f in r["families"]]]
    sel = sel[:limit]
    out = [f"| # | 品牌 | 料号数 | 品类 | 常用品类 | 状态 | 分数 | 未覆盖品类 |",
           "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(sel, 1):
        fam_txt = "、".join(FAMILY_CN.get(f, f) for f in r["families"][:4])
        if len(r["families"]) > 4:
            fam_txt += f" 等 {len(r['families'])} 类"
        unc = "、".join(FAMILY_CN.get(f, f) for f in r["uncovered_families"][:4]) or "-"
        out.append(f"| {i} | {r['name']} | {r['part_count']:,} | {fam_txt} | "
                   f"{r['common_families']} | {STATUS_CN.get(r['status'], r['status'])} | "
                   f"{r['score']} | {unc} |")
    return "\n".join(out)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="brand_queue.py", description="品牌背调优先级队列")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--family", help="只看某个品类（如 ldo / mosfet）")
    ap.add_argument("--pending", action="store_true", help="只看未背调/待背调")
    ap.add_argument("--json", help="写 JSON 到文件")
    ap.add_argument("--all", action="store_true", help="不看 limit，全部输出")
    a = ap.parse_args(argv)

    rows = load_queue()
    if a.pending:
        rows = [r for r in rows if r["status"] in ("pending", "unknown", "kb_only")]
    n = len(rows) if a.all else a.limit
    print(f"品牌总数 {len(load_queue())}｜本次列出 {min(n, len(rows))}｜"
          f"待背调 {sum(1 for r in load_queue() if r['status'] in ('pending', 'unknown'))}｜"
          f"已覆盖 {sum(1 for r in load_queue() if r['status'] in ('done', 'partial'))}")
    print()
    print(render(rows, n, a.family))
    if a.json:
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nJSON 已写入 {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
