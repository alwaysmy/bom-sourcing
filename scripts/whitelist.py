# -*- coding: utf-8 -*-
"""品牌白名单 —— 按「品牌 × 物料类别」放行，而不是按品牌整体放行。

设计依据（用户 m03469）：
  每次引入新品牌的时候，或者已有品牌但进入非同类物料的时候，
  都要进行背调或者知识库核对；引入的品牌存储在白名单。

所以白名单的粒度不是「品牌」，而是「品牌 + 物料类别（family / catalog_id）」：
一个品牌在连接器上背调通过，不代表它在 MOSFET 上也能用 —— 同一品牌下不同
品类的实际生产方、产线、质量体系都可能不同（贴牌/代理的情况尤其如此）。

三态判定（check() 的 status）：
  approved            该品牌在本品类已背调通过 → 可推荐
  pending             该品牌在本品类已登记待背调（见过料号但证据不足）→ 不能当结论
  approved_other_family 品牌在别的品类通过了，但本品类没核过 → 必须复核
  unknown             完全没见过 → 必须先跑品牌背调
  blacklisted         已拉黑（黑名单优先于白名单）

写操作门禁：add / approve / pending / remove 都必须带 --authorized "<谁/什么时候/为什么>"，
与 blacklist.py、brand_dossier.py 保持同一套规则（知识库只接受用户授权的写入）。

CLI：
  python whitelist.py list
  python whitelist.py show tokmas
  python whitelist.py check tokmas --family bjt
  python whitelist.py approve tokmas --family connector --basis "圣禾堂授权代理公告" \
      --grade fact --authorized "傅师傅 2026-11-06 允许放行"
  python whitelist.py pending tokmas --family bjt --reason "只见过 ULN2803，无产线证据" \
      --authorized "傅师傅 2026-11-06 登记待办"
  python whitelist.py validate
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

SCHEMA = "bom-sourcing/knowledge/whitelist"
VERSION = 2
GRADES = ("fact", "claim", "inference", "common_knowledge")
STATUSES = ("approved", "pending", "approved_other_family", "unknown", "blacklisted")

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge" / "whitelist.yaml"

STATUS_LABEL = {
    "approved": "✅ 已背调",
    "kb_known": "📚 知识库已知",
    "pending": "⏳ 待背调",
    "approved_other_family": "⚠ 跨品类未核",
    "unknown": "❔ 未背调",
    "blacklisted": "⛔ 已拉黑",
    "rejected": "🚫 不推荐（停业/高风险）",
}

VENDORS_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge" / "vendors.yaml"
_VENDORS_CACHE = None


def vendors_index(path=None) -> dict:
    """{归一化品牌名: {name, tier, confidence, dossier}} —— 来自 vendors.yaml（145 品牌）。"""
    global _VENDORS_CACHE
    if _VENDORS_CACHE is not None and path is None:
        return _VENDORS_CACHE
    p = Path(path) if path else VENDORS_PATH
    idx = {}
    if p.exists():
        try:
            import yaml  # noqa: PLC0415

            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            for key, e in (data.get("vendors") or {}).items():
                if not isinstance(e, dict):
                    continue
                names = [key, e.get("name") or ""] + list(e.get("aka") or [])
                info = {"name": e.get("name") or key, "tier": e.get("tier") or "unknown",
                        "confidence": e.get("confidence") or "low",
                        "dossier": e.get("dossier")}
                for n in names:
                    k = norm(n)
                    if k:
                        idx.setdefault(k, info)
        except Exception:  # 知识库坏掉不影响白名单本身
            idx = {}
    if path is None:
        _VENDORS_CACHE = idx
    return idx


def _kb_lookup(brand, vendors=None) -> dict | None:
    """在 vendors.yaml 里查品牌（精确 → 子串）。"""
    idx = vendors if vendors is not None else vendors_index()
    if not idx or not brand:
        return None
    k = norm(brand)
    if k in idx:
        return idx[k]
    for name, info in idx.items():
        if k and (k in name or name in k):
            return info
    return None


# --------------------------------------------------------------------------- 基础

def norm(s) -> str:
    """品牌名归一：小写 + 去空白/全角空格 + 去括号（Tokmas(托克马斯) → tokmas托克马斯）。"""
    if not s:
        return ""
    out = []
    for ch in str(s).lower():
        if ch.isspace() or ch in "()（）【】[]<>《》":
            continue
        out.append(ch)
    return "".join(out)


def path_of(path=None) -> Path:
    if path:
        return Path(path)
    return Path(os.environ.get("BOM_WHITELIST") or DEFAULT_PATH)


def load(path=None) -> dict:
    p = path_of(path)
    if not p.exists():
        return {"schema": SCHEMA, "version": VERSION, "generated": str(date.today()), "brands": {}}
    import yaml  # noqa: PLC0415  (延迟导入：只读场景不装 pyyaml 也能跑)

    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    data.setdefault("schema", SCHEMA)
    data.setdefault("version", VERSION)
    data.setdefault("brands", {})
    return data


def save(data: dict, path=None) -> Path:
    import yaml  # noqa: PLC0415

    p = path_of(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data["generated"] = str(date.today())
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=200),
                 encoding="utf-8")
    return p


def _auth(value: str) -> str:
    if not value or not str(value).strip():
        raise PermissionError(
            "白名单属于知识库写操作，必须带 --authorized \"<谁/什么时候/为什么>\"。"
            "例：--authorized \"傅师傅 2026-11-06 允许放行 Tokmas 连接器品类\"")
    return str(value).strip()


def _resolve_via_index(key: str):
    """用 brands.index.yaml 的 merge_into 把「被拆成两条的品牌」找回主档 brand_id。

    例：立创把 ADI 拆成 `178 ADI(亚德诺)` 与 `234 ADI(亚德诺)/MAXIM(美信)`，
    白名单只登记主档 178；拿 234 的名称来查时这里负责归到 178。
    """
    try:
        import brands as _b
        idx = _b.load_index()
    except Exception:  # noqa: BLE001 索引坏了不该拖垮白名单
        return None
    k = norm(key)
    if not k:
        return None
    for bid, e in idx.items():
        pool = [bid, e.get("name"), e.get("short"), e.get("cn")] + list(e.get("aliases") or [])
        if any(norm(x) == k for x in pool if x):
            return str(_b.resolve(bid, _idx=idx))
    return None


def _find(data: dict, key: str):
    """按 name / 别名 / brand_id / 文件名 slug 找条目，返回 (slug, entry) 或 (None, None)。"""
    if not key:
        return None, None
    k = norm(key)
    if k.isdigit():
        for slug, e in data.get("brands", {}).items():
            if str(e.get("brand_id") or "") == k:
                return slug, e
    for slug, e in data.get("brands", {}).items():
        names = [slug, e.get("name") or ""] + list(e.get("aka") or [])
        if any(norm(n) == k for n in names if n):
            return slug, e
    # 子串兜底（品牌全称包含简称）；短名（如 aka "TI"）太容易误命中，只在双方都 ≥3 字符时用
    for slug, e in data.get("brands", {}).items():
        names = [slug, e.get("name") or ""] + list(e.get("aka") or [])
        if any(k and (k in nn or nn in k) for nn in (norm(n) for n in names if n)
               if len(nn) >= 3 and len(k) >= 3):
            return slug, e
    # 归并兜底：立创拆成多条的品牌，按主档 brand_id 再找一次
    main = _resolve_via_index(key)
    if main:
        for slug, e in data.get("brands", {}).items():
            if str(e.get("brand_id") or "") == main:
                return slug, e
    return None, None


def _family_match(item: dict, family=None, catalog_id=None) -> bool:
    # family == "*" 表示「全线品类放行」：仅当品牌是自有产线的 IDM 原厂时可用
    # （产线、质量体系、追溯链覆盖全部产品线，不存在"这个品类是别人代工"的问题）
    if str(item.get("family") or "").strip() == "*":
        return True
    if family:
        fam = str(family).strip().lower()
        if str(item.get("family") or "").strip().lower() == fam:
            return True
    if catalog_id not in (None, ""):
        return str(item.get("catalog_id") or "") == str(catalog_id)
    return False


# --------------------------------------------------------------------------- 判定

def status(brand, family=None, catalog_id=None, data=None, vendors=None) -> dict:
    """返回 {status, label, tier, note, entry, matched}。

    白名单只认「品牌 + 品类」这一对；没给品类时按「品牌是否有任何已通过品类」回答。
    白名单里没有但 vendors.yaml 有分层 → `kb_known`（知识库核对过，本品类未单独背调）。
    """
    data = data if data is not None else load()
    entry = None
    slug, entry = _find(data, brand)
    if not entry:
        kb = _kb_lookup(brand, vendors)
        if kb:
            fam = f"「{family or catalog_id}」" if (family or catalog_id) else "本品类"
            return {"status": "kb_known", "label": STATUS_LABEL["kb_known"],
                    "tier": kb.get("tier"),
                    "note": (f"知识库有该品牌分层（tier={kb.get('tier')}，"
                             f"置信度 {kb.get('confidence')}），但{fam}未单独背调"),
                    "entry": None, "matched": None}
        return {"status": "unknown", "label": STATUS_LABEL["unknown"], "tier": "unknown",
                "note": "白名单与知识库都没有这个品牌，必须先做品牌背调（scripts/brand_dossier.py）",
                "entry": None, "matched": None}
    approved = entry.get("approved") or []
    pending = entry.get("pending") or []
    # 品牌整体判死（停业 / 假冒 / 明确不用）：优先于品类，直接给结论
    if entry.get("verdict") == "rejected":
        return {"status": "rejected", "label": STATUS_LABEL["rejected"],
                "tier": entry.get("tier"),
                "note": entry.get("verdict_reason") or "品牌已判不推荐，需找替代",
                "entry": entry, "matched": None}
    if family or catalog_id:
        for a in approved:
            if _family_match(a, family, catalog_id):
                return {"status": "approved", "label": STATUS_LABEL["approved"],
                        "tier": entry.get("tier"), "note": a.get("basis") or "",
                        "entry": entry, "matched": a}
        for p in pending:
            if _family_match(p, family, catalog_id):
                return {"status": "pending", "label": STATUS_LABEL["pending"],
                        "tier": entry.get("tier"),
                        "note": p.get("reason") or "已登记待背调，证据不足",
                        "entry": entry, "matched": p}
        if approved:
            names = "、".join(str(a.get("label") or a.get("family") or "?") for a in approved[:4])
            return {"status": "approved_other_family",
                    "label": STATUS_LABEL["approved_other_family"], "tier": entry.get("tier"),
                    "note": f"该品牌只在「{names}」背调过，本品类未核 → 需补该品类证据",
                    "entry": entry, "matched": None}
        return {"status": "pending", "label": STATUS_LABEL["pending"], "tier": entry.get("tier"),
                "note": "品牌已建档但没有任何品类通过背调", "entry": entry, "matched": None}
    # 没给品类：只要有一个通过品类就算"见过"
    if approved:
        names = "、".join(str(a.get("label") or a.get("family") or "?") for a in approved[:4])
        return {"status": "approved", "label": STATUS_LABEL["approved"], "tier": entry.get("tier"),
                "note": f"已通过品类：{names}", "entry": entry, "matched": approved[0]}
    return {"status": "pending", "label": STATUS_LABEL["pending"], "tier": entry.get("tier"),
            "note": "品牌已建档但无通过品类", "entry": entry, "matched": None}


def gate_records(records, family=None, catalog_id=None, data=None, blacklist_mod=None,
                 vendors=None):
    """给一批候选打白名单标记，返回 (records, summary)。

    records 里每条会被加上 `whitelist_status` / `whitelist_label` / `whitelist_note`。
    summary = {brand: {"status", "label", "count", "codes": [...], "note"}}
    """
    data = data if data is not None else load()
    vendors = vendors if vendors is not None else vendors_index()
    summary = {}
    for r in records:
        brand = r.get("brand") or ""
        st = status(brand, family, catalog_id, data, vendors)
        if blacklist_mod is not None:
            try:
                if blacklist_mod.check_record({"brand": brand}).get("blocked"):
                    st = {"status": "blacklisted", "label": STATUS_LABEL["blacklisted"],
                          "tier": st.get("tier"), "note": "黑名单优先", "entry": st.get("entry"),
                          "matched": None}
            except Exception:  # 黑名单坏掉不影响白名单判定
                pass
        r["whitelist_status"] = st["status"]
        r["whitelist_label"] = st["label"]
        r["whitelist_note"] = st["note"]
        s = summary.setdefault(brand or "(未知品牌)", {
            "status": st["status"], "label": st["label"], "tier": st.get("tier"),
            "note": st["note"], "count": 0, "codes": []})
        s["count"] += 1
        if r.get("code") and len(s["codes"]) < 5:
            s["codes"].append(r["code"])
    return records, summary


def needs_due_diligence(summary: dict) -> list:
    """哪些品牌必须先背调（按严重度排序：未背调 > 跨品类 > 待背调）。"""
    order = {"unknown": 0, "approved_other_family": 1, "pending": 2}
    rows = [(order.get(v["status"], 9), k, v) for k, v in (summary or {}).items()
            if v["status"] in order]
    return [(k, v) for _o, k, v in sorted(rows, key=lambda x: (x[0], -x[2]["count"]))]


def render_summary(summary: dict, family=None) -> str:
    """渲染「品牌白名单核对」段落。"""
    if not summary:
        return ""
    need = needs_due_diligence(summary)
    ok = [(k, v) for k, v in summary.items() if v["status"] == "approved"]
    kb = [(k, v) for k, v in summary.items() if v["status"] == "kb_known"]
    lines = ["", "## 品牌白名单核对", ""]
    if ok:
        lines.append(f"- ✅ 已背调（本品类通过）：" +
                     "；".join(f"{k}（{v['count']} 条）" for k, v in ok[:6]))
    if kb:
        lines.append(f"- 📚 知识库已知（本品类未单独背调）：" +
                     "；".join(f"{k}[{v.get('tier') or '?'}]" for k, v in kb[:8])
                     + (f" 等 {len(kb)} 个品牌" if len(kb) > 8 else ""))
    if need:
        lines.append(f"- ⚠ **需要先背调/核对 {len(need)} 个品牌**（未通过前不要当结论）：")
        for brand, v in need[:6]:
            codes = "、".join(v["codes"][:3])
            lines.append(f"  - {v['label']} **{brand}**（{v['count']} 条"
                         + (f"，如 {codes}" if codes else "") + f"）—— {v['note']}")
        lines.append("  - 处置：`python brand_dossier.py new/add ...` 取证 → "
                     "`python whitelist.py approve <品牌> --family <品类> "
                     "--basis \"<证据>\" --grade fact --authorized \"<谁/何时/为什么>\"`")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- 写操作

def add_brand(name, brand_id=None, aka=None, tier=None, dossier=None, note=None,
              path=None, authorized=None) -> dict:
    _auth(authorized)
    data = load(path)
    slug = norm(name) or f"brand{brand_id}"
    entry = data["brands"].get(slug)
    if not entry:
        entry = {"name": name, "aka": list(aka or []), "brand_id": brand_id,
                 "tier": tier or "unknown", "approved": [], "pending": [], "note": note or "",
                 "authorized": authorized}
        data["brands"][slug] = entry
    else:
        entry.setdefault("aka", [])
        entry.setdefault("approved", [])
        entry.setdefault("pending", [])
        for a in (aka or []):
            if a not in entry["aka"]:
                entry["aka"].append(a)
        if brand_id:
            entry["brand_id"] = brand_id
        if tier:
            entry["tier"] = tier
        if note:
            entry["note"] = note
        entry["authorized"] = authorized
    if dossier:
        entry["dossier"] = dossier
    save(data, path)
    return entry


def _upsert(kind: str, brand, family=None, label=None, catalog_id=None, basis=None,
            reason=None, grade="fact", expires=None, path=None, authorized=None) -> dict:
    _auth(authorized)
    if not (family or catalog_id):
        raise ValueError("必须给 --family 或 --catalog-id（白名单是「品牌 × 品类」粒度）")
    if kind == "approved" and grade not in GRADES:
        raise ValueError(f"--grade 只能是 {GRADES}")
    data = load(path)
    slug, entry = _find(data, brand)
    if not entry:
        entry = {"name": brand, "aka": [], "brand_id": None, "tier": "unknown",
                 "approved": [], "pending": [], "note": "", "authorized": authorized}
        slug = norm(brand) or "unknown"
        data["brands"][slug] = entry
    entry.setdefault("approved", [])
    entry.setdefault("pending", [])
    item = {"family": (family or "").strip().lower() or None,
            "label": label or family,
            "catalog_id": str(catalog_id) if catalog_id not in (None, "") else None}
    if kind == "approved":
        item.update({"basis": basis or "", "grade": grade, "date": str(date.today())})
        if expires:
            item["expires"] = expires
    else:
        item["reason"] = reason or ""
    # 同一品类只保留一条（approved 优先于 pending）
    tgt, other = (entry["approved"], entry["pending"]) if kind == "approved" else (entry["pending"], entry["approved"])
    tgt[:] = [x for x in tgt if not _family_match(x, item["family"], item["catalog_id"])]
    if kind == "approved":
        other[:] = [x for x in other if not _family_match(x, item["family"], item["catalog_id"])]
    tgt.append(item)
    entry["authorized"] = authorized
    save(data, path)
    return item


def approve(brand, family=None, label=None, catalog_id=None, basis=None, grade="fact",
            expires=None, path=None, authorized=None) -> dict:
    return _upsert("approved", brand, family, label, catalog_id, basis, None, grade, expires,
                   path, authorized)


def preclear(brands, basis=None, path=None, authorized=None) -> list:
    """免背调放行：业界公认的大厂（高置信度已知，不需要逐次检索取证）。

    与 `approve()` 的区别只在语义与 `grade`：这里写 `common_knowledge`，并在品牌条目上
    打 `precleared: true`，`brand_queue.py` 据此不再把它列进待办。

    **判据（必须同时满足）**：① 该品牌是业界公认的原厂/大厂（多年在售、主流分销渠道常备）；
    ② 知识库里已有其分层（vendors.yaml）或属于常识范畴；③ 不涉及需要核实的产线/代工关系。
    **不确定就老老实实背调** —— 免背调是省时间，不是省证据。
    """
    _auth(authorized)
    if not basis:
        raise ValueError("免背调必须写 --basis（为什么这个品牌可以不取证）")
    out = []
    data = load(path)
    for brand in brands:
        item = _upsert("approved", brand, "*", "全线品类（业界公认大厂，免逐次背调）", None,
                       basis, None, "common_knowledge", None, path, authorized)
        data = load(path)
        _slug, entry = _find(data, brand)
        if entry is not None:
            entry["precleared"] = True
            entry["precleared_basis"] = basis
            entry["authorized"] = authorized
            save(data, path)
        out.append(item)
    return out


def pending(brand, family=None, label=None, catalog_id=None, reason=None,
            path=None, authorized=None) -> dict:
    return _upsert("pending", brand, family, label, catalog_id, None, reason, "fact", None,
                   path, authorized)


def validate(data=None) -> list:
    data = data if data is not None else load()
    errs = []
    if data.get("schema") != SCHEMA:
        errs.append(f"schema 应为 {SCHEMA}，实际 {data.get('schema')!r}")
    for slug, e in (data.get("brands") or {}).items():
        if not e.get("name"):
            errs.append(f"{slug}: 缺 name")
        for kind in ("approved", "pending"):
            for i, it in enumerate(e.get(kind) or []):
                if not (it.get("family") or it.get("catalog_id")):
                    errs.append(f"{slug}.{kind}[{i}]: 缺 family/catalog_id")
                if kind == "approved":
                    if it.get("grade") not in GRADES:
                        errs.append(f"{slug}.approved[{i}]: grade 非法 {it.get('grade')!r}")
                    if not it.get("basis"):
                        errs.append(f"{slug}.approved[{i}]: 缺 basis（放行依据）")
                elif not it.get("reason"):
                    errs.append(f"{slug}.pending[{i}]: 缺 reason")
        if not e.get("authorized"):
            errs.append(f"{slug}: 缺 authorized（谁授权写入的）")
    return errs


# --------------------------------------------------------------------------- CLI

def _fmt_row(slug, e):
    appr = "、".join(str(a.get("label") or a.get("family")) for a in (e.get("approved") or [])) or "-"
    pend = "、".join(str(a.get("label") or a.get("family")) for a in (e.get("pending") or [])) or "-"
    return f"| {e.get('brand_id') or '-'} | {e.get('name')} | {e.get('tier')} | {appr} | {pend} |"


def reject(brand, reason=None, path=None, authorized=None) -> dict:
    """品牌整体判不推荐（停业 / 假冒 / 明确不用）：优先于品类判定。"""
    _auth(authorized)
    if not reason:
        raise ValueError("判不推荐必须写 --reason（依据是什么）")
    data = load(path)
    _slug, entry = _find(data, brand)
    if entry is None:
        raise KeyError(f"白名单里没有「{brand}」，先 add 再 reject")
    entry["verdict"] = "rejected"
    entry["verdict_reason"] = reason
    entry["authorized"] = authorized
    save(data, path)
    return entry


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="whitelist.py", description="品牌白名单（按品牌 × 品类放行）")
    ap.add_argument("--file", help="白名单路径（默认 data/knowledge/whitelist.yaml）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出全部品牌")
    sp = sub.add_parser("show", help="看单个品牌")
    sp.add_argument("brand")
    sp = sub.add_parser("check", help="查某品牌在某品类是否放行")
    sp.add_argument("brand")
    sp.add_argument("--family")
    sp.add_argument("--catalog-id")
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("add", help="登记一个品牌（还没通过任何品类）")
    sp.add_argument("brand")
    sp.add_argument("--brand-id")
    sp.add_argument("--aka", nargs="*")
    sp.add_argument("--tier", choices=["original_idm", "original_fabless",
                                       "domestic_second", "trader", "unknown"])
    sp.add_argument("--dossier")
    sp.add_argument("--note")
    sp.add_argument("--authorized", required=True)

    sp = sub.add_parser("approve", help="放行某品牌在某品类")
    sp.add_argument("brand")
    sp.add_argument("--family")
    sp.add_argument("--label")
    sp.add_argument("--catalog-id")
    sp.add_argument("--basis", help="放行依据（指向证据）")
    sp.add_argument("--grade", default="fact", choices=list(GRADES))
    sp.add_argument("--expires")
    sp.add_argument("--authorized", required=True)

    sp = sub.add_parser("pending", help="登记「该品类待背调」")
    sp.add_argument("brand")
    sp.add_argument("--family")
    sp.add_argument("--label")
    sp.add_argument("--catalog-id")
    sp.add_argument("--reason")
    sp.add_argument("--authorized", required=True)

    sp = sub.add_parser("reject", help="品牌整体判不推荐（停业/假冒/不用）")
    sp.add_argument("brand")
    sp.add_argument("--reason", required=True)
    sp.add_argument("--authorized", required=True)

    sub.add_parser("validate", help="校验文件")

    a = ap.parse_args(argv)
    try:
        if a.cmd == "list":
            data = load(a.file)
            print("| 品牌id | 品牌 | 分层 | 已通过品类 | 待背调品类 |")
            print("|---|---|---|---|---|")
            for slug, e in (data.get("brands") or {}).items():
                print(_fmt_row(slug, e))
            print(f"\n共 {len(data.get('brands') or {})} 个品牌")
            return 0
        if a.cmd == "show":
            data = load(a.file)
            slug, e = _find(data, a.brand)
            if not e:
                print(f"未找到品牌：{a.brand}")
                return 1
            print(json.dumps({slug: e}, ensure_ascii=False, indent=2))
            return 0
        if a.cmd == "check":
            st = status(a.brand, a.family, a.catalog_id)
            if a.json:
                print(json.dumps({k: v for k, v in st.items() if k != "entry"},
                                 ensure_ascii=False, indent=1))
            else:
                print(f"{st['label']}  {a.brand}"
                      + (f"  [{a.family or a.catalog_id}]" if (a.family or a.catalog_id) else "")
                      + f"\n  tier: {st.get('tier')}\n  说明: {st['note']}")
            return 0
        if a.cmd == "add":
            e = add_brand(a.brand, a.brand_id, a.aka, a.tier, a.dossier, a.note,
                          a.file, a.authorized)
            print(f"已登记品牌：{e['name']}")
            return 0
        if a.cmd == "approve":
            it = approve(a.brand, a.family, a.label, a.catalog_id, a.basis, a.grade,
                         a.expires, a.file, a.authorized)
            print(f"已放行：{a.brand} @ {it['label']}（{it['grade']}）")
            return 0
        if a.cmd == "pending":
            it = pending(a.brand, a.family, a.label, a.catalog_id, a.reason, a.file,
                         a.authorized)
            print(f"已登记待背调：{a.brand} @ {it['label']}")
            return 0
        if a.cmd == "reject":
            reject(a.brand, a.reason, a.file, a.authorized)
            print(f"已判不推荐：{a.brand} —— {a.reason}")
            return 0
        if a.cmd == "validate":
            errs = validate(load(a.file))
            if errs:
                print("❌ 校验失败：")
                for e in errs:
                    print("  -", e)
                return 1
            print("✅ 校验通过")
            return 0
    except (PermissionError, ValueError) as e:
        print(f"[拒绝] {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
