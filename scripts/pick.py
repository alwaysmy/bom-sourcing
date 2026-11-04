#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pick.py —— 按意图/单个品类找料（不依赖已有 BOM）。

    python pick.py "找 3.3V 1A 的 LDO" --qty 100
    python pick.py ldo --param 输出电压=3.3V --param 输出电流>=1A
    python pick.py mosfet --param Vdss>=30V --param Id>=4A --package SOT-23
    python pick.py resolve 稳压
    python pick.py cats

设计要点：
1. 品类解析：`data/categories.yaml`（cat-probe 扫描结果）→ 命中即用；未命中走
   `resolve 关键词` 的 catalogGroup 动态解析。
2. 品类内检索：`catalogIdFilter` + 排序（sales/price_asc），翻页取候选。
3. 参数约束：**从候选自带的 paramLinkedMap 动态聚键**，再用别名表把 `输出电压`
   `Vdss` `Ciss` 这类写法映射到物理量；不硬编码品类字段表，参数键随类目变化。
4. 立创无服务端参数区间筛选，所以区间过滤只能在客户端做（见 references/lcsc-api.md §3）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lcsc import Lcsc, cwidth, money, pad, price_at  # noqa: E402
from spec import (  # noqa: E402
    parse_amp, parse_farad, parse_freq, parse_henry, parse_ohm, parse_tol,
    parse_volt, parse_watt, parse_package, pkg_key,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CAT_YAML = DATA_DIR / "categories.yaml"
CAT_JSON = DATA_DIR / "categories.json"

# --------------------------------------------------------------------- 物理量别名
# quant -> (中文/英文键名片段, 单位类别, 极性)
#   极性 eq  : 要求相等（输出电压、容值）
#        ge  : 越大越好（输出电流、耐压、主频）
#        le  : 越小越好（静态电流、导通电阻）
#        text: 文本枚举（接口类型、极性）
ALIASES = {
    "vout":     (["输出电压", "Vout"], "volt", "eq"),
    "vin":      (["工作电压", "输入电压", "Vin", "供电电压"], "volt", "in"),
    "iout":     (["输出电流", "最大输出电流", "连续漏极电流", "Iout", "Id"], "amp", "ge"),
    "iq":       (["静态电流", "静态工作电流", "待机电流", "Iq"], "amp", "le"),
    "vref":     (["基准电压", "Vref"], "volt", "eq"),
    "vdss":     (["漏源电压", "Vdss"], "volt", "ge"),
    "vrwm":     (["反向工作电压", "Vrwm", "反向截止电压"], "volt", "ge"),
    "vmax":     (["额定电压", "耐压", "反向电压", "最大电压", "集电极-发射极"], "volt", "ge"),
    "vclamp":   (["钳位电压"], "volt", "le"),
    "vf":       (["正向压降", "Vf", "正向电压"], "volt", "le"),
    "ifwd":     (["正向电流", "额定电流", "正向平均电流", "If"], "amp", "ge"),
    "rds":      (["导通电阻", "RDS"], "ohm", "le"),
    "res":      (["阻值"], "ohm", "eq"),
    "cap":      (["容值"], "farad", "eq"),
    "ind":      (["电感值"], "henry", "eq"),
    "power":    (["功率", "耗散功率", "额定功率", "Pd"], "watt", "ge"),
    "tol":      (["精度", "容差", "偏差"], "tol", "le"),
    "freq":     (["频率", "主频", "开关频率", "时钟频率", "增益带宽积"], "freq", "ge"),
    "flash":    (["程序存储容量", "存储容量"], "bits", "ge"),
    "bits":     (["CPU位数", "位数", "分辨率", "位数(bits)"], "bits", "ge"),
    "vos":      (["失调电压"], "volt", "le"),
    "channels": (["通道数", "放大器数", "路数"], "int", "ge"),
    "count_type": (["数量"], "text", "text"),
    "iface":    (["接口类型", "接口", "通信协议"], "text", "text"),
    "polarity": (["极性", "输出极性", "类型"], "text", "text"),
    "dielectric": (["温度系数", "介质"], "text", "text"),
    "temp":     (["工作温度"], "text", "text"),
}

# 用户写的写法 → quant（长写法优先匹配）
QUANT_SYNONYMS = {
    "vout": ["vout", "输出电压", "output voltage", "out"],
    "vin": ["vin", "输入电压", "工作电压", "input voltage", "供电"],
    "iout": ["iout", "输出电流", "电流", "id", "current"],
    "iq": ["iq", "静态电流", "待机电流", "quiescent"],
    "vdss": ["vdss", "漏源电压"],
    "vrwm": ["vrwm", "反向工作电压", "截止电压"],
    "vmax": ["vmax", "耐压", "额定电压", "反向电压", "vr", "vds"],
    "vclamp": ["vclamp", "钳位电压"],
    "vf": ["vf", "正向压降", "正向电压"],
    "ifwd": ["if", "正向电流", "额定电流"],
    "rds": ["rds", "rds(on)", "导通电阻", "内阻"],
    "res": ["r", "res", "阻值", "电阻"],
    "cap": ["c", "cap", "容值", "电容"],
    "ind": ["l", "ind", "电感值", "电感"],
    "power": ["p", "power", "功率"],
    "tol": ["tol", "精度", "容差"],
    "freq": ["freq", "f", "频率", "主频"],
    "flash": ["flash", "容量", "存储", "程序存储"],
    "bits": ["bits", "位数", "分辨率"],
    "vos": ["vos", "失调电压"],
    "channels": ["ch", "通道", "路数", "放大器数"],
    "count_type": ["数量", "沟道", "n沟道", "p沟道"],
    "iface": ["iface", "接口"],
    "polarity": ["polarity", "极性"],
    "dielectric": ["dielectric", "介质", "温度系数"],
}

# 无单位数字按家族落到哪个物理量（"找 3.3V 1A 的 LDO" 这类自然语言意图）
FAMILY_VOLT_ROLE = {
    "ldo": "vout", "dcdc": "vout", "vref": "vout", "adc": "vout",
    "tvs": "vrwm", "esd": "vrwm", "mosfet": "vdss", "diode": "vmax",
    "schottky": "vmax", "mlcc": "vmax", "electrolytic": "vmax", "tantalum": "vmax",
    "led": "vf", "crystal": "freq", "opamp": None, "comparator": None,
}
FAMILY_AMP_ROLE = {
    "ldo": "iout", "dcdc": "iout", "mosfet": "iout", "diode": "ifwd", "schottky": "ifwd",
}

# 没有 categories.yaml 时的兜底关键词（立创裸词检索够用）
BUILTIN_KEYWORDS = {
    "ldo": "LDO", "dcdc": "DC-DC", "mosfet": "MOS", "mcu": "单片机", "opamp": "运放",
    "comparator": "比较器", "vref": "电压基准", "eeprom": "EEPROM", "norflash": "FLASH",
    "crystal": "无源晶振", "oscillator": "有源晶振", "optocoupler": "光耦",
    "isolator": "数字隔离器", "tvs": "TVS", "esd": "ESD", "schottky": "肖特基",
    "diode": "二极管", "bjt": "三极管", "led": "LED", "resistor": "电阻", "mlcc": "电容",
    "inductor": "电感", "bead": "磁珠", "connector": "排针", "relay": "继电器",
}

SORT_CHOICES = {"sales": 6, "price": 1, "price_desc": 2, "stock": 4, "relevance": 0}


# --------------------------------------------------------------------- 数值解析
def _num_bounds(text):
    """把 `3.3V` / `5.5V~36V` / `±10ppm` / `47mΩ@10V` 拆成 (lo, hi)，去掉测试条件。"""
    if text is None:
        return None
    s = str(text).replace("±", "")
    s = s.split("@")[0].split("；")[0]
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    if not nums:
        return None
    lo = float(nums[0])
    hi = float(nums[1]) if len(nums) > 1 and ("~" in s or "-" in s[1:]) else lo
    return lo, hi


def _scaled(quant, text, raw_unit_hint=None):
    """按物理量把文本解析成 SI 数值（区间取 hi，需要下限时另取）。"""
    if text is None:
        return None
    s = str(text)
    kind = ALIASES.get(quant, (None, "text", "text"))[1]
    if kind == "volt":
        typ, mx = parse_volt(s)
        return mx if mx is not None else typ
    if kind == "amp":
        return parse_amp(s)
    if kind == "ohm":
        return parse_ohm(s)
    if kind == "farad":
        return parse_farad(s)
    if kind == "henry":
        return parse_henry(s)
    if kind == "watt":
        return parse_watt(s)
    if kind == "freq":
        return parse_freq(s)
    if kind == "tol":
        return parse_tol(s)
    if kind == "bits":
        m = re.search(r"(\d+(?:\.\d+)?)\s*([kKmMgG]?)\s*(bit|B|b)\b", s, re.I)
        if not m:
            return None
        mult = {"": 1, "k": 1e3, "m": 1e6, "g": 1e9}[m.group(2).lower()]
        return float(m.group(1)) * mult / 8 if m.group(3) in "Bb" and m.group(2) else float(m.group(1)) * mult
    if kind == "int":
        v = _num_bounds(s)
        return v[0] if v else None
    return None


def parse_quantity_value(text):
    """把用户写的 `3.3V` / `1A` / `10uF` / `10k` / `1%` / `8MHz` / `SPI` 解析成 (数值, 单位类别)。"""
    t = str(text or "").strip()
    for kind, parser in (("volt", parse_volt), ("amp", parse_amp), ("ohm", parse_ohm),
                         ("farad", parse_farad), ("henry", parse_henry),
                         ("watt", parse_watt), ("freq", parse_freq)):
        try:
            v = parser(t)
        except Exception:  # noqa: BLE001
            v = None
        if isinstance(v, tuple):
            v = v[1]
        if v is not None:
            return v, kind
    v = parse_tol(t)
    if v is not None:
        return v, "tol"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([kKmMgG])?\s*(?:bit|bits|B)?", t, re.I)
    if m:
        mult = {"": 1, "k": 1e3, "m": 1e6, "g": 1e9}[(m.group(2) or "").lower()]
        return float(m.group(1)) * mult, "num"
    return t, "text"


# --------------------------------------------------------------------- 品类解析
def load_categories():
    """返回 {family: {label_cn, keywords, catalog_id, param_keys, key_constraints}}。

    真源是 `data/categories.yaml`；读成功后顺手写 `data/categories.json` 作为缓存，
    环境里没有 PyYAML 时退回读这份缓存（缓存永远由 YAML 生成，不会比 YAML 新）。
    """
    if CAT_YAML.exists():
        try:
            import yaml  # noqa: PLC0415
            obj = yaml.safe_load(CAT_YAML.read_text(encoding="utf-8")) or {}
            try:
                CAT_JSON.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
            except OSError:
                pass
            return obj.get("families") or {}
        except Exception as e:  # noqa: BLE001
            print(f"[warn] categories.yaml 读取失败（{e}），尝试缓存；再不行退化为内置关键词表", file=sys.stderr)
    if CAT_JSON.exists():
        try:
            return (json.loads(CAT_JSON.read_text(encoding="utf-8")) or {}).get("families") or {}
        except Exception as e:  # noqa: BLE001
            print(f"[warn] categories.json 读取失败（{e}），退化为内置关键词表", file=sys.stderr)
    return {}


def match_family(token, cats):
    """把 `ldo` / `LDO` / `线性稳压器` / `稳压芯片` 归一到一个 family。"""
    t = (token or "").strip()
    if not t:
        return None
    low = t.lower()
    if low in cats:
        return low
    if low in BUILTIN_KEYWORDS:
        return low
    for fam, info in cats.items():
        names = [fam, info.get("label_cn") or ""] + list(info.get("keywords") or [])
        for n in names:
            if n and (n.lower() == low or n.lower() in low or low in n.lower()):
                return fam
    for fam, kw in BUILTIN_KEYWORDS.items():
        if kw.lower() in low or low in kw.lower():
            return fam
    return None


def resolve_catalog(cli, keyword, want=None, page_size=30):
    """裸关键词 → catalogGroup → 选最匹配的品类。返回 {label, value, count, parents}。"""
    r = cli.raw_search(keyword, page=1, page_size=page_size)
    groups = r.get("catalogs") or []
    if not groups:
        return None
    groups = sorted(groups, key=lambda g: g.get("count") or 0, reverse=True)
    if want:
        wl = want.lower()
        for g in groups:
            if wl in (g.get("label") or "").lower() or (g.get("label") or "").lower() in wl:
                return g
    return groups[0]


def category_for(cli, family, cats, verbose=False):
    """family → (keyword, catalog_id, label)。优先静态表，缺失时动态解析。"""
    info = cats.get(family) or {}
    cid = str(info.get("catalog_id") or "")
    label = info.get("label_cn") or ""
    kws = list(info.get("keywords") or [])
    kw = kws[0] if kws else BUILTIN_KEYWORDS.get(family) or family
    if not cid:
        g = resolve_catalog(cli, kw, want=label or None)
        if g:
            cid = str(g.get("value") or "")
            label = label or g.get("label") or ""
            if verbose:
                print(f"[catalog] {family}: {label} = {cid} (count={g.get('count')})", file=sys.stderr)
    return {"family": family, "keyword": label or kw, "catalog_id": cid, "label_cn": label, "info": info}


# --------------------------------------------------------------------- 约束
class Constraint:
    __slots__ = ("quant", "op", "value", "raw", "unit")

    def __init__(self, quant, op, value, raw, unit):
        self.quant, self.op, self.value, self.raw, self.unit = quant, op, value, raw, unit

    def __repr__(self):
        return f"<{self.quant} {self.op} {self.value}{self.unit}>"


def quant_of(name):
    n = (name or "").strip().lower().replace(" ", "")
    for quant, syns in QUANT_SYNONYMS.items():
        if n == quant or n in [s.lower() for s in syns]:
            return quant
    for quant, syns in QUANT_SYNONYMS.items():
        for s in syns:
            if s and s.lower() in n:
                return quant
    return None


def make_constraint(name, op, value_text):
    quant = quant_of(name)
    if not quant:
        return None
    val, unit = parse_quantity_value(value_text)
    if val is None:
        return None
    return Constraint(quant, op or ">=", val, f"{name}{op or '>='}{value_text}",
                      unit if unit != "num" else "")


def parse_param_arg(text):
    """`输出电压=3.3V` / `输出电流>=1A` / `Vdss>=30V`。"""
    m = re.match(r"\s*([^<>=!]+?)\s*(>=|<=|=>|=<|==|=|>|<|~)\s*(.+?)\s*$", text)
    if not m:
        return None
    name, op, val = m.group(1), m.group(2), m.group(3)
    op = {"=>": ">=", "=<": "<=", "==": "=", "~": ">="}.get(op, op)
    if op == "=":
        op = "="
    return make_constraint(name, op, val)


def parse_intent(text, family):
    """自然语言 → 约束列表。`找 3.3V 1A 的 LDO` / `30V 5A 的 MOS 管`。"""
    out = []
    t = str(text or "")
    volt_role = FAMILY_VOLT_ROLE.get(family)
    amp_role = FAMILY_AMP_ROLE.get(family)
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:~\s*(\d+(?:\.\d+)?))?\s*V\b", t, re.I):
        if volt_role:
            # 极性决定语义：输出电压要"是 3.3V"，耐压/漏源电压只要"不低于"
            pol = ALIASES.get(volt_role, ("", "", "eq"))[2]
            op = "=" if (pol == "eq" and not m.group(2)) else ">="
            out.append(Constraint(volt_role, op, float(m.group(1)), m.group(0), "V"))
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(m?A)\b", t):
        v = float(m.group(1)) * (1e-3 if m.group(2) == "mA" else 1)
        if amp_role:
            out.append(Constraint(amp_role, ">=", v, m.group(0), "A"))
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*([pnuµm]?)F\b", t):
        out.append(Constraint("cap", "=", float(m.group(1) and m.group(1)) * {"": 1, "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3}[m.group(2)], m.group(0), "F"))
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*([pnuµm]?)H\b", t):
        out.append(Constraint("ind", "=", float(m.group(1)) * {"": 1, "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3}[m.group(2)], m.group(0), "H"))
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*([kKmMrR])?(?:Ω|ohm|欧)\b", t, re.I):
        out.append(Constraint("res", "=", parse_ohm(m.group(0)), m.group(0), "Ω"))
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*[kMG]?Hz\b", t, re.I):
        op = "=" if (family or "") in ("crystal", "oscillator") else ">="
        out.append(Constraint("freq", op, parse_freq(m.group(0)), m.group(0), "Hz"))
    for m in re.finditer(r"±?\s*(\d+(?:\.\d+)?)\s*%", t):
        out.append(Constraint("tol", "<=", float(m.group(1)), m.group(0), "%"))
    pkg = parse_package(t)
    if pkg:
        out.append(Constraint("_pkg", "=", pkg, pkg, ""))
    return [c for c in out if c is not None]


# --------------------------------------------------------------------- 匹配与排序
def find_keys(rec, quant):
    """在一条记录里找属于该物理量的参数键（可能多个，如 工作电压 / 输出电压）。"""
    hits = []
    kind_alias = ALIASES.get(quant)
    if not kind_alias:
        return hits
    names = kind_alias[0]
    for k, v in (rec.get("params") or {}).items():
        for n in names:
            if n.lower() in k.lower():
                hits.append((k, v))
                break
    return hits


def check_one(rec, c):
    """返回 (状态, 说明)；状态 ∈ ok/warn/fail/unknown。"""
    if c.quant == "_pkg":
        pk = rec.get("package") or ""
        return ("ok", pk) if pkg_key(pk) == pkg_key(c.value) else ("fail", pk)
    hits = find_keys(rec, c.quant)
    if not hits:
        return ("unknown", "")
    kind = ALIASES[c.quant][1]
    polarity = ALIASES[c.quant][2]
    if kind == "text" or polarity == "text":
        got = "、".join(v for _, v in hits)
        ok = str(c.value).lower() in got.lower()
        return ("ok" if ok else "fail", got[:40])
    best = None
    for key, raw in hits:
        lo, hi = _num_bounds(raw) or (None, None)
        if lo is None:
            continue
        # 区间参数（5.5V~36V）对 vin 要"包含"；其它取上限
        if c.quant in ("vin", "vmax", "vrwm", "vdss") and polarity == "in":
            ok = lo <= c.value <= hi if hi != lo else c.value <= hi
            if ok:
                return ("ok", f"{key}={raw}")
            best = best or ("fail", f"{key}={raw}")
            continue
        hi_v = _scaled(c.quant, raw)
        if hi_v is None:
            continue
        need = c.value
        op = c.op
        tol = 0.02
        if op == "=":  # 显式等值优先：晶振频率、阻值这类"要 8MHz 就得是 8MHz"
            ok = abs(hi_v - need) <= max(abs(need) * tol, 1e-12) if need else hi_v == 0
        elif polarity == "ge" or op == ">=":
            ok = hi_v >= need * (1 - tol)
        elif polarity == "le" or op == "<=":
            ok = hi_v <= need * (1 + tol)
        else:
            ok = abs(hi_v - need) <= max(abs(need) * tol, 1e-12) if need else hi_v == 0
        if ok:
            return ("ok", f"{key}={raw}")
        best = best or ("fail", f"{key}={raw}")
        best_ok = ("fail", f"{key}={raw}")
        if not ok and best is None:
            best = best_ok
    return best or ("unknown", "")


def evaluate(rec, constraints):
    if not constraints:
        return True, [], []
    fails, unknowns = [], []
    for c in constraints:
        state, note = check_one(rec, c)
        if state == "fail":
            fails.append(f"{c.raw}→{note or '无此参数'}")
        elif state == "unknown":
            unknowns.append(c.raw)
    return (not fails), fails, unknowns


def rank(recs, qty, sort="sales"):
    if sort == "price":
        return sorted(recs, key=lambda r: (price_at(r, qty) is None, (r.get("stock") or 0) <= 0,
                                           price_at(r, qty) or 9e9))
    if sort == "stock":
        return sorted(recs, key=lambda r: (-(r.get("stock") or 0), price_at(r, qty) or 9e9))
    return sorted(recs, key=lambda r: (-(r.get("sales") or 0), price_at(r, qty) or 9e9))


def dedupe_by_model(recs):
    """同型号多 C 号保留库存最多的一条（立创同一个 MPN 常有多个 C 号，库存差异极大）。"""
    best = {}
    for r in recs:
        key = (r.get("model") or "").strip().upper()
        if not key:
            key = r.get("code")
        cur = best.get(key)
        if cur is None or (r.get("stock") or 0) > (cur.get("stock") or 0):
            best[key] = r
    return list(best.values())


# --------------------------------------------------------------------- 输出
def param_brief(rec, info, limit=4):
    keys = (info or {}).get("key_constraints") or []
    out = []
    params = rec.get("params") or {}
    for k in keys:
        if k in params:
            out.append(f"{k}={params[k]}")
        if len(out) >= limit:
            break
    if not out:
        for k, v in list(params.items())[:limit]:
            out.append(f"{k}={v}")
    return "；".join(out)


def render(cat, qty, picked, total_scanned, fails_stat, unknowns, args):
    label = cat.get("label_cn") or cat.get("keyword")
    print(f"\n品类: {label}（catalogIdFilter={cat.get('catalog_id') or '未解析'}，关键词={cat.get('keyword')}）")
    print(f"扫描 {total_scanned} 条候选，按 {args.sort} 排序；数量 {qty}；命中 {len(picked)} 条")
    shown = [c.raw for c in (getattr(args, "_constraints", None) or [])]
    if shown:
        print("约束: " + "，".join(shown))
    if not picked:
        print("\n没有满足全部约束的料。建议放宽：" + ("，".join(fails_stat[:3]) if fails_stat else "换品类或去掉约束"))
        return
    header = ["#", "C号", "型号", "品牌", "封装", "关键参数", f"单价@{qty}", "库存", "销量"]
    rows = []
    for i, r in enumerate(picked, 1):
        price = price_at(r, qty)
        brief = param_brief(r, cat.get("info"), limit=5)
        rows.append([str(i), r.get("code") or "", (r.get("model") or "")[:28], (r.get("brand") or "")[:16],
                     r.get("package") or "", brief[:80] + ("…" if len(brief) > 80 else ""),
                     money(price) if price is not None else "?", f"{r.get('stock') or 0:,}", str(r.get("sales") or 0)])
    widths = [max(cwidth(h), *(cwidth(row[i]) for row in rows)) for i, h in enumerate(header)]
    print("  " + "  ".join(pad(h, widths[i]) for i, h in enumerate(header)))
    for row in rows:
        print("  " + "  ".join(pad(v, widths[i]) for i, v in enumerate(row)))
    if unknowns:
        tail = "" if args.allow_unknown else "（这些候选按「缺参数视为不满足」排除）"
        print(f"\n注意: {len(unknowns)} 个约束在部分候选上找不到对应参数字段：{'、'.join(sorted(set(unknowns))[:5])}{tail}")
    if fails_stat:
        print("落选主因（前 3）: " + "；".join(fails_stat[:3]))
    print("\n提示: 价格是数量 " + str(qty) + " 的立创阶梯价（人民币含税）；库存为立创有效库存。"
          " 下单前请复核 datasheet 与封装。")
    if picked:
        best = min((price_at(r, qty) for r in picked if price_at(r, qty) is not None), default=None)
        print("渠道: " + channel_hint(qty, best))


def channel_hint(qty, unit_price=None):
    """按数量给渠道倾向（口径与 bom.py 一致，实测校正见 references/channels.md）。"""
    p = f" 当前最低 ¥{unit_price:g}/只。" if unit_price else ""
    if qty <= 10:
        return f"少量：淘宝样品/小包装常更便宜（运费与凑单要算），立创可与其它料合并下单省运费。{p}"
    if qty < 100:
        return f"中小批量：立创阶梯价通常最优，淘宝只作比价参考（零售价不一定随量降）。{p}"
    return f"批量：走立创阶梯价，同时把型号丢给 1688 询盘比价（1688 阶梯价不公开，需人工问）。{p}"


_ASSORT_RE = re.compile(r"芯片包|元件包|套装|套餐|组合装|混装|样品盒|样品包|整盒|一盒|散装包")


def _market_usable(x):
    """淘宝/1688 里"混装包/套装"的单只价没有可比性，先剔掉；conf=low 的也不要用。"""
    if _ASSORT_RE.search(x.get("title") or ""):
        return False
    if str(x.get("unit_confidence") or "").lower() == "low":
        return False
    return True


def market_compare(picked, args):
    """拿 pick 出来的型号去淘宝/1688 摸一下零售单只价，判断渠道。"""
    import time as _t
    try:
        import taobao as tb  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        print(f"\n[warn] 淘宝脚本不可用（{e}），跳过渠道比价", file=sys.stderr)
        return
    site = args.market
    n = min(args.taobao, len(picked))
    print(f"\n## 渠道比价（{site}，按销量取样 {n} 个型号；淘宝需浏览器已登录）")
    header = ["型号", "立创单只", f"{site}最低单只", "对比", f"{site}样本（标题/销量）"]
    rows = []
    try:
        br = tb.Bridge()
    except Exception as e:  # noqa: BLE001
        print(f"[warn] WebBridge 连接失败（{e}）", file=sys.stderr)
        return
    for r in picked[:n]:
        model = r.get("model") or ""
        lc = price_at(r, args.qty)
        try:
            tb.throttle(site)
            if site == "1688":
                res = tb.search_1688(br, model, "sales", 5)
            else:
                res = tb.search_taobao(br, model, "sales", 5, 0)
            items = [x for x in tb.normalize(res["items"], site) if not x.get("sponsored")]
        except Exception as e:  # noqa: BLE001
            rows.append([model, money(lc) if lc else "?", "—", f"取数失败: {str(e)[:24]}", ""])
            continue
        priced = [x for x in items if x.get("unit_price")]
        usable = [x for x in priced if _market_usable(x)]
        best = min(usable, key=lambda x: x["unit_price"]) if usable else None
        if not best and priced:  # 只有混装/低置信的价，仍给出来但明确标注
            best = dict(min(priced, key=lambda x: x["unit_price"]),
                        title=(min(priced, key=lambda x: x["unit_price"]).get("title") or "")
                        + "（含混装/低置信，需人工核对）")
        if not best:
            if items:
                kinds = sorted({str(x.get("unit_note") or "无单只价") for x in items})
                rows.append([model[:24], money(lc) if lc else "?", "区间/混装", "需人工询价",
                             f"{len(items)} 条无单只价（{kinds[0][:20]}）"])
            else:
                rows.append([model[:24], money(lc) if lc else "?", "—", "无结果", ""])
            continue
        tb_price = best.get("unit_price")
        ratio = ""
        if tb_price and lc:
            d = tb_price / lc
            ratio = f"淘宝 {d:.1f}×" if d >= 1 else f"淘宝省 {(1 - d) * 100:.0f}%"
        sample = f"{best.get('title') or ''}"
        cnt = best.get("sales_text") or ""
        rows.append([model[:24], money(lc) if lc else "?", money(tb_price) if tb_price else "?",
                     ratio, (sample[:34] + (f"｜{cnt}" if cnt else ""))])
    widths = [max(cwidth(h), *(cwidth(row[i]) for row in rows)) for i, h in enumerate(header)]
    print("  " + "  ".join(pad(h, widths[i]) for i, h in enumerate(header)))
    for row in rows:
        print("  " + "  ".join(pad(v, widths[i]) for i, v in enumerate(row)))
    print("  说明：淘宝价是「单只价」估算（标题里带 100个/包 之类已归一，conf 低时人工核对）；"
          "立创价是含税阶梯价。小批量(<10)淘宝通常更省，批量看立创阶梯 + 免运费门槛。")


def cmd_pick(args):
    cats = load_categories()
    cli = Lcsc(rate_limit=0.8)
    text = " ".join(args.intent or [])
    family = match_family(args.family or "", cats) if args.family else None
    if family is None and text:
        for tok in re.split(r"[\s,，、]+", text):
            family = match_family(tok, cats)
            if family:
                break
    if family is None and not args.cat:
        print("无法识别品类。用 `pick.py resolve <关键词>` 看品类树，或 --family ldo / --cat \"线性稳压器(LDO)\"。", file=sys.stderr)
        return 2
    if family:
        cat = category_for(cli, family, cats, verbose=args.debug)
    else:
        cat = {"family": None, "keyword": args.cat, "catalog_id": "", "label_cn": args.cat, "info": {}}
        if args.cat:
            g = resolve_catalog(cli, args.cat, want=args.cat)
            if g:
                cat["catalog_id"] = str(g.get("value") or "")
                cat["label_cn"] = g.get("label") or args.cat
                cat["info"] = {}
    constraints = []
    for p in args.params or []:
        c = parse_param_arg(p)
        if not c:
            print(f"[warn] 看不懂的约束: {p}", file=sys.stderr)
        else:
            constraints.append(c)
    constraints.extend(parse_intent(text, cat.get("family")))
    if args.package:
        constraints.append(Constraint("_pkg", "=", args.package, args.package, ""))
    args._constraints = [c for c in constraints if c.quant != "_pkg"]

    pages = max(1, args.pages)
    recs, total, page = [], None, 1
    while page <= pages:
        r = cli.raw_search(cat["keyword"], catalog_id=cat["catalog_id"], sort=SORT_CHOICES.get(args.sort, 6),
                           page=page, page_size=30,
                           brand_id=args.brand_id or "", price_min=args.price_min, price_max=args.price_max)
        total = total if total is not None else (r.get("total") or 0)
        batch = r.get("records") or []
        # 品类内的"同族复核"：关键词检索会带进别的品类，按 productType 收口
        if cat.get("label_cn"):
            allow = cat["label_cn"].replace(" ", "")
            same = [x for x in batch if allow and (x.get("type") or "").replace(" ", "") and
                    (allow in (x.get("type") or "") or (x.get("type") or "") in allow)]
            batch = same or batch
        recs.extend(batch)
        if page >= (r.get("count_page") or 1):
            break
        page += 1
    recs = dedupe_by_model(recs)
    scanned = len(recs)

    ok, fails_all, unknown_dropped = [], [], []
    for r in recs:
        good, fails, unknowns = evaluate(r, constraints)
        if not good:
            fails_all.extend(fails)
        elif unknowns and not args.allow_unknown:
            # 关键约束在该料上根本没这个参数 → 不能当作"满足"（例如只标了 300mA 的料没写耐压）
            unknown_dropped.append(r)
        else:
            ok.append(r)
    from collections import Counter
    fails_stat = [f"{k} ×{v}" for k, v in Counter(fails_all).most_common(3)]
    picked = rank(ok, args.qty, args.sort)[: args.limit]
    all_unknowns = [u for r in recs for u in evaluate(r, constraints)[2]]
    render(cat, args.qty, picked, scanned, fails_stat, all_unknowns, args)
    if unknown_dropped:
        print(f"另有 {len(unknown_dropped)} 条因缺少约束对应参数被排除（加 --allow-unknown 可放行）")
    if args.taobao and picked:
        market_compare(picked, args)
    if args.json:
        out = {
            "generated": datetime.now().isoformat(timespec="seconds"),
            "category": cat, "qty": args.qty, "scanned": scanned,
            "constraints": [c.raw for c in constraints],
            "picked": [dict(r, unit_price=price_at(r, args.qty)) for r in picked],
        }
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nJSON 已写入 {args.json}")
    return 0


def cmd_resolve(args):
    cli = Lcsc(rate_limit=0.5)
    kw = " ".join(args.keyword)
    r = cli.raw_search(kw)
    groups = sorted(r.get("catalogs") or [], key=lambda g: g.get("count") or 0, reverse=True)
    print(f"关键词: {kw}  总数 {r.get('total')}")
    parents = "、".join(f"{g.get('label')}={g.get('value')}" for g in (r.get("parents") or [])[:5])
    if parents:
        print(f"父类: {parents}")
    if not groups:
        print("没有品类 facet（可能关键词太偏，换个说法试试）")
        return 0
    print("\n品类候选（按商品数降序）:")
    for g in groups[:15]:
        print(f"  {pad(str(g.get('value')), 8)} {pad(g.get('label') or '', 26)} {str(g.get('count') or '').rjust(8)}")
    print("\n用法: pick.py pick --cat \"<品类名>\" --param \"输出电压=3.3V\"")
    return 0


def cmd_cats(args):
    cats = load_categories()
    if not cats:
        print("还没有 data/categories.yaml（cat-probe 尚未产出）。当前可用内置兜底关键词：")
        for k, v in BUILTIN_KEYWORDS.items():
            print(f"  {pad(k, 12)} {v}")
        return 0
    print(f"共 {len(cats)} 个 family（来源 data/categories.yaml）\n")
    for fam, info in sorted(cats.items()):
        keys = "、".join(f"{k.get('key')}" for k in (info.get("param_keys") or [])[:5])
        print(f"  {pad(fam, 12)} {pad(info.get('label_cn') or '', 24)} id={pad(str(info.get('catalog_id') or ''), 7)} 键: {keys}")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # 允许 `pick.py "找 3.3V 的 LDO"` 不带子命令
    if argv and not argv[0].startswith("-") and argv[0] not in ("pick", "resolve", "cats"):
        argv = ["pick"] + argv
    ap = argparse.ArgumentParser(description="按意图/品类找料（立创商城）")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("pick", help="按意图找料")
    p.add_argument("intent", nargs="*", help="自然语言意图，如 \"找 3.3V 1A 的 LDO\"")
    p.add_argument("--family", help="family 名或中文名（ldo / 线性稳压器 / mosfet）")
    p.add_argument("--cat", help="直接指定立成品类名（走 catalogGroup 解析）")
    p.add_argument("--param", dest="params", action="append", help="约束，如 输出电压=3.3V / 输出电流>=1A")
    p.add_argument("--package", help="封装，如 SOT-23 / 0805")
    p.add_argument("--brand-id", help="立创品牌 id（见 search --brand）")
    p.add_argument("--price-min", default="")
    p.add_argument("--price-max", default="")
    p.add_argument("--qty", type=int, default=1, help="采购数量（决定阶梯价）")
    p.add_argument("--sort", default="sales", choices=list(SORT_CHOICES))
    p.add_argument("--pages", type=int, default=2, help="翻页数，每页 30")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--json", help="把结果写到 JSON 文件")
    p.add_argument("--allow-unknown", action="store_true", help="允许缺少约束参数的料入选")
    p.add_argument("--taobao", type=int, default=0, metavar="N",
                   help="对前 N 个结果去淘宝/1688 查零售单只价，做渠道比价")
    p.add_argument("--market", default="taobao", choices=["taobao", "1688"])
    p.add_argument("--debug", action="store_true")
    p.set_defaults(func=cmd_pick)

    p2 = sub.add_parser("resolve", help="关键词 → 品类树")
    p2.add_argument("keyword", nargs="+")
    p2.set_defaults(func=cmd_resolve)

    p3 = sub.add_parser("cats", help="列出已知品类索引")
    p3.set_defaults(func=cmd_cats)

    a = ap.parse_args(argv)
    if not getattr(a, "func", None):
        ap.print_help()
        return 2
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
