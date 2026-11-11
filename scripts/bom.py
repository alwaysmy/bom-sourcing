#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BOM 配单：解析 BOM → 立创匹配 → 指标核对 → 报价单 + 渠道建议。

流程（对应 SKILL.md 的 A 阶段）：
  1. BOM 体检：识别列（型号/数量/封装/位号），缺列给出提示
  2. 分类：MPN 行（有完整型号） vs 参数行（10k 0603 / 100nF 0603 50V）
  3. 检索：立创 search（MPN 用相关度；参数行用价格升序多取候选）
  4. 指标核对：spec.verify() 比阻值/容值/耐压/精度/频率/封装，fail 直接淘汰
  5. 定料：同型号多 C 号时优先有货 + 满足数量 + 价格
  6. 数量：按损耗模型加备料（阻容 0.3%，IC 不加）
  7. 渠道：按数量与品类给「淘宝 / 立创 / 1688」建议

用法：
  python bom.py bom.csv
  python bom.py bom.csv --qty 50 --pref price --md report.md --json result.json
  python bom.py bom.csv --columns          # 只看解析出的列与行（不联网）
  python bom.py bom.csv --strict           # 指标核对未通过的行不推荐
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lcsc import Lcsc, money, price_at, price_from_ladder  # noqa: E402
from spec import detect_family, norm_pkg, parse_need, summarize, verify  # noqa: E402

# --------------------------------------------------------------------------- 列识别
COL_PATTERNS = {
    "mpn": [r"^mpn$", r"manufacturer.?part", r"^part.?number$", r"^partno$", r"^型号$", r"^器件型号$",
            r"^料号$", r"^comment$", r"^value$", r"^值$", r"^规格$", r"^规格型号$", r"^device$", r"^name$"],
    "qty": [r"^qty$", r"^quantity$", r"^数量$", r"^用量$", r"^per.?board$", r"^count$", r"^单板用量$"],
    "package": [r"^package$", r"^footprint$", r"^封装$", r"^封装形式$"],
    "designator": [r"designator", r"^ref", r"^reference", r"^位号$", r"^标号$"],
    "description": [r"description", r"^描述$", r"^说明$", r"^备注说明$"],
    "note": [r"^note", r"备注"],
}
ESSENTIAL = ["mpn", "qty"]


def detect_columns(header):
    mapping = {}
    for i, h in enumerate(header):
        hn = str(h or "").strip().lower()
        if not hn:
            continue
        for role, pats in COL_PATTERNS.items():
            if role in mapping:
                continue
            if any(re.search(p, hn, re.I) for p in pats):
                mapping[role] = i
                break
    return mapping


def read_table(path: Path):
    ext = path.suffix.lower()
    if ext in (".csv", ".tsv", ".txt"):
        raw = path.read_bytes()
        text = None
        for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise SystemExit("无法解码该文件，请另存为 UTF-8 CSV")
        delim = "\t" if (ext == ".tsv" or text.count("\t") > text.count(",")) else ","
        rows = [r for r in csv.reader(text.splitlines(), delimiter=delim) if any(str(c).strip() for c in r)]
        return (rows[0], rows[1:]) if rows else ([], [])
    if ext in (".xlsx", ".xlsm"):
        try:
            import openpyxl  # noqa: PLC0415
        except ImportError as e:
            raise SystemExit("需要 openpyxl 才能读 xlsx：pip install openpyxl，或另存为 CSV") from e
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb.active
        data = [[c.value for c in row] for row in ws.iter_rows()]
        rows = [r for r in data if any(v not in (None, "") for v in r)]
        if not rows:
            return [], []
        return [("" if c is None else str(c)) for c in rows[0]], rows[1:]
    raise SystemExit(f"不支持的扩展名: {ext}（支持 .csv/.tsv/.txt/.xlsx）")


def parse_bom(path: Path, default_qty=1):
    header, rows = read_table(path)
    cols = detect_columns(header) if header else {}
    lines = []
    if header and "mpn" in cols:
        for idx, r in enumerate(rows):
            def cell(role):
                i = cols.get(role)
                if i is None or i >= len(r) or r[i] is None:
                    return ""
                return str(r[i]).strip()
            mpn = cell("mpn")
            if not mpn or mpn.lower() in ("total", "合计", "小计"):
                continue
            q = cell("qty")
            try:
                qty = int(float(re.sub(r"[^\d.]", "", q))) if q else 0
            except ValueError:
                qty = 0
            designator = cell("designator")
            if qty <= 0:  # 没写数量：按位号个数推
                n = len(re.split(r"[,\s]+", designator)) if designator else 0
                qty = n or default_qty
            lines.append({"line": idx + 1, "mpn": mpn, "qty": qty, "package": cell("package"),
                          "designator": designator, "description": cell("description"), "note": cell("note")})
    else:
        for idx, r in enumerate(rows):
            text = " ".join(str(c).strip() for c in r if str(c).strip())
            if not text:
                continue
            m = re.search(r"(?:[x*×]\s*|[x*×]\s*(\d+)\s*$)", text)
            qty = default_qty
            mm = re.search(r"[x*×]\s*(\d+)\s*$", text)
            if mm:
                qty = int(mm.group(1))
                text = text[: mm.start()].strip()
            lines.append({"line": idx + 1, "mpn": text, "qty": qty, "package": "",
                          "designator": "", "description": "", "note": ""})
    return cols, header, lines


# --------------------------------------------------------------------------- 分类
MPN_LIKE = re.compile(r"[A-Za-z]")


def classify(line):
    text = line["mpn"]
    need = parse_need(text, family=detect_family(text))
    has_value = any(need.get(k) is not None for k in ("ohm", "farad", "henry", "freq"))
    looks_mpn = bool(MPN_LIKE.search(text)) and bool(re.search(r"\d", text))
    # LED 颜色/灯珠类按参数检索更准（"LED 0805 red" 不是型号）
    if need.get("family") == "led" and not re.search(r"\d{3,}[A-Z]{2}", text):
        return "param", need
    # "AMS1117-3.3" 这类带数字的完整型号走 MPN；"10uF 0805 16V" 走参数
    if has_value and not re.search(r"[A-Za-z]{2,}\d", text):
        return "param", need
    if has_value and re.search(r"\b(0402|0603|0805|1206|1210|2512)\b", text, re.I):
        return "param", need
    return ("mpn" if looks_mpn else "param"), need


# --------------------------------------------------------------------------- 匹配：MPN
def _pick_best(cands, qty, pref):
    def key(rec):
        stock_ok = 1 if (rec.get("stock") or 0) >= qty else 0
        instock = 1 if rec.get("in_stock") else 0
        price = price_at(rec, max(qty, rec.get("min_buy") or 1)) or 9e9
        sales = rec.get("sales") or 0
        if pref == "price":
            return (stock_ok, instock, -price, sales)
        return (stock_ok, instock, sales, -price)
    return sorted(cands, key=key, reverse=True)


def _blacklist_filter(cands):
    """按 data/knowledge/blacklist.yaml 剔除候选；返回 (保留, 命中描述列表)。

    黑名单是人为判断（品牌/店铺/料号），必须在排序前剔除：
    否则黑名单里的低价品牌会排到最前面被推荐。
    """
    try:
        import blacklist as _bl
    except Exception:  # noqa: BLE001 - 黑名单坏掉不能拖垮配单
        return list(cands), []
    kept, dropped = _bl.filter_records(cands)
    hits = []
    for r, hs in dropped:
        hits.append({"code": r.get("code"), "model": r.get("model"), "brand": r.get("brand"),
                     "hits": [{"kind": h["kind"], "name": h["name"], "reason": h["reason"]} for h in hs]})
    return kept, hits


def match_mpn(cli: Lcsc, line, need, pref="stock"):
    mpn = line["mpn"].strip()
    qty = line["qty"]
    target = re.sub(r"[\s\-_/]+", "", mpn).upper()
    queries = [mpn]
    if line.get("package") and norm_pkg(line["package"]) not in norm_pkg(mpn):
        queries.insert(0, f"{mpn} {line['package']}")
    seen = {}
    for q in queries:
        try:
            res = cli.raw_search(q, sort="relevance")  # spotFilter 只接受 1；传 0 会静默返 0 条
        except Exception as e:  # noqa: BLE001
            return {"chosen": None, "candidates": [], "confidence": "error", "reason": str(e), "checks": []}
        for rec in res["records"]:
            seen[rec["code"]] = rec
        if any(re.sub(r"[\s\-_/]+", "", (r.get("model") or "")).upper() == target for r in seen.values()):
            break

    _kept, bl_hits = _blacklist_filter(list(seen.values()))
    seen = {r["code"]: r for r in _kept}

    exact = [r for r in seen.values() if re.sub(r"[\s\-_/]+", "", (r.get("model") or "")).upper() == target]
    if exact:
        ranked = _pick_best(exact, qty, pref)
        chosen = ranked[0]
        checks = []
        if need.get("pkg") or line.get("package"):
            n = dict(need)
            n.setdefault("pkg", norm_pkg(line.get("package")))
            checks, _ = verify(n, chosen)
        reason = ""
        brands = sorted({r.get("brand") for r in exact if r.get("brand")})
        if len(exact) > 1:
            reason = (f"同型号 {len(exact)} 个 C 号"
                      f"（品牌 {'/'.join(brands[:4])}），按{'价格' if pref == 'price' else '供货'}选了 {chosen.get('brand')}")
        return {"chosen": chosen, "candidates": ranked[:5], "confidence": "exact",
                "reason": reason, "checks": checks, "blacklisted": bl_hits}

    # 退一步：前缀/包含匹配
    near = [r for r in seen.values()
            if re.sub(r"[\s\-_/]+", "", (r.get("model") or "")).upper().startswith(target) or target in re.sub(r"[\s\-_/]+", "", (r.get("model") or "")).upper()]
    if near:
        ranked = _pick_best(near, qty, pref)
        return {"chosen": ranked[0], "candidates": ranked[:5], "confidence": "close",
                "reason": f"未找到完全同型号，最接近 {ranked[0]['model']}", "checks": [],
                "blacklisted": bl_hits}
    return {"chosen": None, "candidates": [], "confidence": "none",
            "reason": "立创无检索结果（可能停产/型号写法不同/需人工确认）", "checks": [],
            "blacklisted": bl_hits}


# --------------------------------------------------------------------------- 匹配：参数行
def match_param(cli: Lcsc, line, need, pref="price"):
    text = line["mpn"].strip()
    qty = line["qty"]
    keyword = re.sub(r"\s+", " ", text).strip()
    if line.get("package") and norm_pkg(line["package"]) not in keyword:
        keyword += " " + line["package"]
    try:
        res = cli.search(keyword, limit=40, sort="price_asc")
    except Exception as e:  # noqa: BLE001
        return {"chosen": None, "candidates": [], "confidence": "error", "reason": str(e),
                "checks": [], "blacklisted": []}
    recs, bl_hits = _blacklist_filter(res["records"])
    if not recs:
        return {"chosen": None, "candidates": [], "confidence": "none",
                "reason": "立创无检索结果（或全部命中黑名单）", "checks": [],
                "blacklisted": bl_hits}

    scored = []
    for rec in recs:
        checks, worst = verify(need, rec)
        if worst == "fail":
            continue
        ok_cnt = sum(1 for c in checks if c[3] == "ok")
        unk_cnt = sum(1 for c in checks if c[3] == "unknown")
        price = price_at(rec, max(qty, rec.get("min_buy") or 1)) or 9e9
        in_stock = 1 if rec.get("in_stock") else 0
        stock_ok = 1 if (rec.get("stock") or 0) >= qty else 0
        if pref == "price":
            rank = (in_stock, stock_ok, ok_cnt, -unk_cnt, -price)
        elif pref == "brand":
            rank = (in_stock, stock_ok, ok_cnt, rec.get("sales") or 0, -price)
        else:  # stock/sales
            rank = (in_stock, stock_ok, rec.get("sales") or 0, ok_cnt, -price)
        scored.append((rank, rec, checks, worst))
    if not scored:
        return {"chosen": None, "candidates": [], "confidence": "none",
                "reason": "有检索结果但均不满足指标（值/耐压/精度不符）", "checks": [],
                "blacklisted": bl_hits}
    scored.sort(key=lambda x: x[0], reverse=True)
    _, chosen, checks, worst = scored[0]
    cands = [s[1] for s in scored[:5]]
    conf = {"ok": "param", "warn": "param_warn", "unknown": "param_guess"}[worst]
    return {"chosen": chosen, "candidates": cands, "confidence": conf,
            "reason": "", "checks": checks, "blacklisted": bl_hits}


# --------------------------------------------------------------------------- 数量与渠道
def _family(line, rec):
    fam = line.get("family")
    if fam and fam != "unknown":
        return fam
    if rec:
        fam = detect_family(rec.get("type"), rec.get("name"))
        if fam != "unknown":
            return fam
    return detect_family(line.get("description"), line.get("mpn"))


def order_qty(line, rec=None):
    """损耗模型：阻容感二极管加 0.3%（至少 +5 颗），IC/连接器不加。"""
    fam = _family(line, rec)
    qty = line["qty"]
    if fam in ("resistor", "mlcc", "inductor", "bead", "led", "diode"):
        return qty + max(5, math.ceil(qty * 0.003))
    return qty


def moq_cost(rec, qty):
    if not rec:
        return None, None, None
    moq = rec.get("min_buy") or 1
    buy = max(qty, moq)
    unit = price_at(rec, buy)
    if unit is None:
        return buy, None, None
    return buy, round(unit * buy, 2), unit


def channel_advice(line, rec, qty, production=False):
    fam = _family(line, rec)
    if fam in ("connector", "switch") or re.search(r"模块|开发板|成品", line.get("mpn", "")):
        if production:
            return "立创优先（量产口径）", "成品/模块淘宝型号多，但量产要可追溯与批次一致性，立创自营更稳"
        return "淘宝优先", "成品/模块类淘宝型号多、单价低；立创多卖芯片（淘宝可买拆机/散新，注意标注成色）"
    if fam in ("mcu", "ldo", "dcdc", "flash", "crystal", "opamp"):
        if qty <= 5:
            if production:
                return "立创优先", "核心器件 + 量产/高可靠：淘宝只认全新原装；拆机/散新/翻新不可用"
            return "立创优先", "核心器件事关可靠性，立创自营可追溯（淘宝同型号存在翻新/散新）"
        return "立创批量", "核心器件批量走立创阶梯价，交期与批次可预期"
    if qty <= 10:
        if production:
            return "立创 / 淘宝比价（仅全新）", "量产口径：淘宝只比全新原装，拆机/散新/翻新一律不参与"
        return "淘宝优先", "少量阻容淘宝散卖包邮更省（立创有最低运费与起订约束；拆机/散新可用但要标注）"
    if qty <= 100:
        return "立创 / 淘宝比价", "小批量两边都比：立创正品有票，淘宝可能更便宜（成色要标注）"
    return "立创批量 / 1688", "批量走阶梯价，1688 批发更优；淘宝仅作替代料来源（电子元件默认不查 1688）"


# --------------------------------------------------------------------------- 替代
def _needs_alt(res, rec, oq):
    """只有把握不足、或库存扛不住采购量时才值得去取替代料。"""
    if res.get("confidence") not in ("exact", "param"):
        return True
    stock = rec.get("stock") or 0
    return bool(oq) and stock < oq


def collect_alternates(cli: Lcsc, lines, results, limit=3, sleep=0.6):
    """给需要注意的行取立创替代料。返回 {行号: [候选dict]}。"""
    out = {}
    for l, r in zip(lines, results):
        rec = r.get("chosen")
        if not rec:
            continue
        oq = order_qty(l, rec)
        if not _needs_alt(r, rec, oq):
            continue
        try:
            sub = cli.alternates(rec["code"], qty=oq, limit=limit * 2, enrich=False)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 行{l['line']} 替代料获取失败: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        src = sub.get("source_params") or {}
        rows = []
        for a in sub.get("alternates") or []:
            params = a.get("params") or {}
            diff = [f"{k}:{src[k]}→{v}" for k, v in params.items() if k in src and src[k] != v]
            rows.append({
                "code": a.get("code"), "model": a.get("model"), "brand": a.get("brand"),
                "sim": a.get("sim"), "qty": oq, "stock": a.get("stock"),
                "price": price_from_ladder(a.get("ladder") or [], oq),
                "diff": "; ".join(diff)[:60],
            })
            if len(rows) >= limit:
                break
        out[l["line"]] = rows
        print(f"[alt] 行{l['line']} {l['mpn']} -> {len(rows)} 条候选", file=sys.stderr)
        time.sleep(sleep)
    return out


# --------------------------------------------------------------------------- 渲染
def render(lines, results, args, alts=None):
    alts = alts or {}
    production = bool(getattr(args, "production", False))
    out = [f"# BOM 配单报价单\n",
           f"- BOM: `{args.bom}`",
           f"- 选型倾向: {args.pref}　备料: {'按损耗模型' if args.spares else '不加备料'}",
           f"- 采购口径: **{'量产 / 高可靠' if production else '打样 / 小批量'}**"
           f"（{('淘宝只认全新原装，拆机/散新/翻新不参与比价' if production else '拆机/散新可用，采购时标注成色即可')}）",
           f"- 数据源: 立创商城（含税单价，按数量取阶梯价）",
           f"- 生成: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
           "| 行 | 需求 | 数量 | 采购量 | 推荐C号 | 实际型号 | 品牌 | 封装 | 单价 | 小计 | 指标核对 | 把握 | 渠道 | 备注 |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    total = 0.0
    unresolved, need_confirm = 0, 0
    for line, res in zip(lines, results):
        rec = res.get("chosen")
        oq = order_qty(line, rec) if args.spares else line["qty"]
        buy, cost, unit = moq_cost(rec, oq) if rec else (None, None, None)
        if cost:
            total += cost
        if not rec:
            unresolved += 1
        conf = res.get("confidence")
        if conf not in ("exact", "param"):
            need_confirm += 1
        mark = {"exact": "✔", "param": "✔", "close": "≈", "param_warn": "!", "param_guess": "?",
                "none": "✘", "error": "!"}.get(conf, "?")
        ch, _ = channel_advice(line, rec, oq, production)
        cells = [str(line["line"]), line["mpn"], str(line["qty"]), str(buy or oq),
                 rec["code"] if rec else "—", rec["model"] if rec else "未匹配",
                 (rec.get("brand") or "") if rec else "", (rec.get("package") or "") if rec else "",
                 money(unit) if unit is not None else "",
                 f"{cost:.2f}" if cost is not None else "",
                 summarize(res.get("checks") or []), mark, ch,
                 (res.get("reason") or "")[:40]]
        out.append("| " + " | ".join(str(c).replace("|", "/") for c in cells) + " |")
    out.append("")
    out.append("## 汇总\n")
    out.append(f"- 行数 {len(lines)}｜未匹配 {unresolved}｜需人工确认 {need_confirm}")
    out.append(f"- 立创合计（含起订量与备料）: **¥{total:.2f}**")
    qty_all = sum(order_qty(l, r.get("chosen")) if args.spares else l["qty"] for l, r in zip(lines, results))
    ch, why = channel_advice({"mpn": "", "description": ""}, None, qty_all, production)
    out.append(f"- 整体渠道建议（{qty_all} 件）: **{ch}** —— {why}")
    out.append("")
    out.append("")
    bl_all = [h for r in results for h in (r.get("blacklisted") or [])]
    if bl_all:
        out.append("## 黑名单剔除\n")
        out.append("名单：`data/knowledge/blacklist.yaml`（`python scripts/blacklist.py list|add|remove` 维护）")
        for h in bl_all[:20]:
            why = "、".join(f"{x['name']}" for x in h.get("hits") or [])
            out.append(f"- `{h.get('code')}` {h.get('model')}（{h.get('brand')}）—— {why}"
                       f"{('：' + h['hits'][0]['reason']) if h.get('hits') and h['hits'][0].get('reason') else ''}")
        out.append("")
    # 品牌白名单：按「品牌 × 品类」核对（新品牌 / 已有品牌进入非同类物料都必须先背调）
    try:
        import whitelist as _wl

        wl_sum = {}
        for ln, r in zip(lines, results):
            rec = r.get("chosen")
            if not rec:
                continue
            fam = _family(ln, rec) or ln.get("family")
            st = _wl.status(rec.get("brand"), family=fam)
            key = rec.get("brand") or "(未知品牌)"
            s = wl_sum.setdefault(key, {"status": st["status"], "label": st["label"],
                                        "tier": st.get("tier"), "note": st["note"],
                                        "count": 0, "codes": []})
            s["count"] += 1
            if rec.get("code") and len(s["codes"]) < 5:
                s["codes"].append(rec["code"])
        txt = _wl.render_summary(wl_sum)
        if txt.strip():
            out.append(txt)
    except Exception as e:  # 白名单坏掉不拖垮报价单
        print(f"[警告] 品牌白名单核对失败：{e}", file=sys.stderr)
    bad = [(l, r) for l, r in zip(lines, results) if r.get("confidence") in ("close", "param_warn", "param_guess", "none", "error")]
    if bad:
        out.append("## 需人工确认\n")
        for l, r in bad:
            out.append(f"- **{l['mpn']}**（行{l['line']}，{l['qty']} 件）：{r.get('reason') or '指标未完全核对通过'}")
            alt_txt = "、".join(f"{c['code']}({c['model']},{money(price_at(c, max(l['qty'], c.get('min_buy') or 1)))}元)"
                                for c in (r.get("candidates") or [])[:3])
            if alt_txt:
                out.append(f"  - 候选: {alt_txt}")
            for c in (r.get("checks") or []):
                if c[3] in ("fail", "unknown", "warn"):
                    out.append(f"  - {c[0]} {c[1]} {c[2]}")
        out.append("")
    if alts:
        out.append("## 替代候选（立创 substitute 接口）\n")
        for l, r in zip(lines, results):
            block = alts.get(l["line"])
            if not block:
                continue
            rec = r.get("chosen") or {}
            out.append(f"**{l['mpn']}**（行{l['line']}，源料 {rec.get('code', '—')} "
                       f"{rec.get('brand') or ''}）：")
            for a in block:
                diff = a.get("diff") or ""
                out.append(f"- `{a['code']}` {a['model']}｜{a.get('brand') or ''}｜"
                           f"相似 {a.get('sim') or '—'}｜{money(a.get('price'))}@{a.get('qty')}"
                           f"｜库存 {a.get('stock')}" + (f"｜{diff}" if diff else ""))
            out.append("")
        out.append("风险档确认：MCU/电源/晶振/连接器/光耦/隔离器属高风险，替换前必须查手册核对；"
                   "阻容感/LED 可替，但电容须同介质同耐压。\n")

    out.append("## 下一步建议\n")
    out.append("1. 逐行核对「指标核对」列的 `?`/`✘` 项（手册确认后再定料）")
    out.append("2. 核心器件（MCU/电源/晶振/连接器）不建议替换，先确认原厂料是否可采")
    out.append("3. 少量先买淘宝样品验证，批量再走立创阶梯价/1688；立创与嘉立创的库存价格互相独立")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="BOM 配单（立创匹配 + 指标核对 + 报价）")
    ap.add_argument("bom")
    ap.add_argument("--qty", type=int, default=0, help="覆盖所有行的单板用量")
    ap.add_argument("--pref", default="price", choices=["price", "stock", "brand"], help="选型倾向")
    ap.add_argument("--md", default="", help="报告写到文件")
    ap.add_argument("--json", default="", help="结构化结果写到文件")
    ap.add_argument("--columns", action="store_true", help="只打印解析结果（不联网）")
    ap.add_argument("--strict", action="store_true", help="指标未核对通过的行不出推荐")
    ap.add_argument("--alternate", action="store_true",
                    help="对把握不足/库存不够的行取立创替代料候选（多打 1 次接口/行）")
    ap.add_argument("--alt-limit", type=int, default=3, help="每行替代候选数")
    ap.add_argument("--spares", dest="spares", action="store_true", default=True, help="按损耗模型加备料")
    ap.add_argument("--no-spares", dest="spares", action="store_false")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--production", action="store_true",
                    help="按量产/高可靠口径给渠道建议：淘宝只认全新原装，拆机/散新/翻新不参与比价")
    a = ap.parse_args(argv)

    path = Path(a.bom)
    if not path.exists():
        raise SystemExit(f"找不到 BOM 文件: {path}")
    cols, header, lines = parse_bom(path)
    if a.qty:
        for l in lines:
            l["qty"] = a.qty
    if a.columns:
        print("识别列:", cols)
        print("表头:", header)
        print(f"有效行: {len(lines)}")
        for l in lines:
            kind, need = classify(l)
            print(f"  行{l['line']:>2} [{kind:5s}] {l['mpn']}  x{l['qty']}  指标={ {k: v for k, v in need.items() if k not in ('raw',)} }")
        return 0
    if not lines:
        raise SystemExit("BOM 解析后没有有效行（检查表头是否含型号/数量列）")

    missing = [c for c in ESSENTIAL if c not in cols] if cols else ESSENTIAL
    if missing:
        print(f"[warn] 未识别到列: {missing}（按纯文本模式解析）", file=sys.stderr)

    cli = Lcsc(use_cache=not a.no_cache)
    results = []
    for l in lines:
        kind, need = classify(l)
        l["family"] = need.get("family") or "unknown"
        if kind == "mpn":
            res = match_mpn(cli, l, need, pref=a.pref)
        else:
            res = match_param(cli, l, need, pref=a.pref)
        if a.strict and res.get("confidence") in ("param_guess", "close"):
            res["reason"] = (res.get("reason") or "") + "；--strict 下不出推荐"
            res["chosen"] = None
        results.append(res)
        ch = res.get("chosen")
        print(f"[{l['line']}/{len(lines)}] [{kind}] {l['mpn']} x{l['qty']} -> "
              f"{(ch['code'] + ' ' + ch['model']) if ch else '未匹配'} ({res['confidence']})",
              file=sys.stderr)
    alts = collect_alternates(cli, lines, results, limit=a.alt_limit) if a.alternate else {}
    report = render(lines, results, a, alts=alts)
    print(report)
    if a.md:
        Path(a.md).write_text(report, "utf-8")
        print(f"[saved] {a.md}", file=sys.stderr)
    if a.json:
        Path(a.json).write_text(json.dumps({"lines": lines, "results": results, "alternates": alts},
                                           ensure_ascii=False, indent=1), "utf-8")
        print(f"[saved] {a.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
