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
    parse_volt, parse_watt, parse_package, pkg_key, function_check,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CAT_YAML = DATA_DIR / "categories.yaml"
CAT_JSON = DATA_DIR / "categories.json"

# 反向电流阻断：**用户说了才筛选，没说只标注**（立创没有这个参数键，只能查知识库）
# 见 data/knowledge/load-switch.yaml 与 scripts/loadswitch.py
_RB_RE = re.compile(
    r"防倒灌|防反灌|防反接|反向电流阻断|反向阻断|反向电流保护|阻断反向|不许倒流|不允许倒流"
    r"|不能倒流|防倒流|ORing|OR-ing|理想二极管|理想二極管",
    re.I)
# 哪些品类默认带「反向阻断」列（其它品类靠知识库命中动态开启，避免整列 ❔未核 的噪音）
_RB_FAMILIES = ("powerswitch", "load_switch")

# --------------------------------------------------------------------- 物理量别名
# quant -> (中文/英文键名片段, 单位类别, 极性)
#   极性 eq  : 要求相等（输出电压、容值）
#        ge  : 越大越好（输出电流、耐压、主频）
#        le  : 越小越好（静态电流、导通电阻）
#        text: 文本枚举（接口类型、极性）
ALIASES = {
    "vout":     (["输出电压", "Vout"], "volt", "eq"),
    "vin":      (["工作电压", "输入电压", "Vin", "供电电压"], "volt", "in"),
    "iout":     (["输出电流", "最大输出电流", "连续漏极电流", "最大连续电流", "Iout", "Id"], "amp", "ge"),
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
    # 负载开关/eFuse：指标是"工作电压区间"（要包含目标电压）+ 最大连续电流
    "load_switch": "vin", "powerswitch": "vin",
    "tvs": "vrwm", "esd": "vrwm", "mosfet": "vdss", "diode": "vmax",
    "schottky": "vmax", "mlcc": "vmax", "electrolytic": "vmax", "tantalum": "vmax",
    "led": "vf", "crystal": "freq", "opamp": None, "comparator": None,
}
FAMILY_AMP_ROLE = {
    "ldo": "iout", "dcdc": "iout", "mosfet": "iout", "diode": "ifwd", "schottky": "ifwd",
    "load_switch": "iout", "powerswitch": "iout",
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
    """把 `ldo` / `LDO` / `线性稳压器` / `稳压芯片` 归一到一个 family。

    注意：**短词只能全等**。早期版本对任意长度都做子串匹配，导致
    `--param 沟道=N` 里的 token `N` 命中 `i**n**ductor`（功率电感）、
    `P` 命中 `m**p**u`（单片机），于是 P 沟道 MOS 被解析成单片机。
    """
    t = (token or "").strip()
    if not t:
        return None
    low = t.lower()
    if low in cats:
        return low
    if low in BUILTIN_KEYWORDS:
        return low
    # 1~2 个字符的 token（N / P / L / C / R）只认全等，绝不参与子串匹配
    if len(low) >= 3:
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
    # 区间写成「3.3V~21V」或「3.3~21V」都要吃得住：先扫区间，再扫单值（跳过已被区间覆盖的位置），
    # 否则「3.3V~21V」会被拆成 3.3V 与 21V 两条独立约束（21V 当"不低于"是错的语义）。
    volt_spans = []
    for m in re.finditer(
            r"([-−]?)\s*(\d+(?:\.\d+)?)\s*V?\s*[~～\-–—]\s*([-−]?)\s*(\d+(?:\.\d+)?)\s*V\b",
            t, re.I):
        volt_spans.append(m.span())
        lo, hi = float(m.group(2)), float(m.group(4))
        pol = ALIASES.get(volt_role or "", ("", "", "eq"))[2]
        if volt_role and pol == "in":
            # 工作电压是区间参数：要求候选区间**覆盖** [lo, hi]
            out.append(Constraint(volt_role, "cover", (lo, hi), m.group(0).strip(), "V"))
            continue
        if volt_role:
            out.append(Constraint(volt_role, ">=", hi, m.group(0).strip(), "V"))
    for m in re.finditer(r"([-−]?)\s*(\d+(?:\.\d+)?)\s*V\b", t, re.I):
        if any(a <= m.start() < b for a, b in volt_spans):
            continue
        # 负号：MOSFET 的 `-30V` 是**P 沟道**的习惯写法，参数仍是 30V（绝对值）
        neg = bool(m.group(1))
        lo = float(m.group(2))
        if neg and (family or "") in ("mosfet",):
            out.append(Constraint("count_type", "=", "P沟道", f"P沟道（{m.group(0).strip()} 推得）", ""))
        if volt_role:
            # 极性决定语义：输出电压要"是 3.3V"，耐压/漏源电压只要"不低于"
            pol = ALIASES.get(volt_role, ("", "", "eq"))[2]
            op = "=" if pol == "eq" else ">="
            out.append(Constraint(volt_role, op, lo, m.group(0).strip(), "V"))
    # 沟道类型：`N沟道` / `N 沟道` / `NMOS` / `P 沟道` / `PMOS`
    if (family or "") in ("mosfet",) and not any(c.quant == "count_type" for c in out):
        mc = re.search(r"\b([NP])\s*(?:沟道|MOS|MOSFET)\b", t, re.I)
        if mc:
            out.append(Constraint("count_type", "=", f"{mc.group(1).upper()}沟道", mc.group(0), ""))
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


_UNIT_HINT = {"volt": "V", "amp": "A", "ohm": "Ω", "farad": "F", "henry": "H",
              "watt": "W", "freq": "Hz", "tol": "%"}
_NUM_RE = {
    "volt": re.compile(r"([\d.]+)\s*V\b", re.I),
    "amp": re.compile(r"([\d.]+)\s*(m|u|µ)?A\b"),
    "ohm": re.compile(r"([\d.]+)\s*(m|k)?Ω", re.I),
}


def _value_from_name(rec, quant):
    """从商品名里兜底抽数值。

    立创很多料把关键指标只写在名字里（TPS22919「5.5V、1.5A、90mΩ自保护负载开关」
    的 `最大连续电流` 只有 8/90 条记录才有），paramLinkedMap 反而缺。
    只按物理量做严格单位匹配，抽不到就返回 None（不能瞎猜）。
    """
    kind = ALIASES.get(quant, ("", "", ""))[1]
    text = " ".join(x for x in (rec.get("name") or "", rec.get("type") or "") if x)
    if not text:
        return None
    rx = _NUM_RE.get(kind)
    if not rx:
        return None
    m = rx.findall(text)
    if not m:
        return None
    if kind == "volt":
        # 名字里出现多个电压时取最大（"2.7 - 18V" 取 18；"1V至5.5V" 取 5.5）
        return max(float(x) for x in m)
    if kind == "amp":
        vals = [float(v) * {"m": 1e-3, "u": 1e-6, "µ": 1e-6, "": 1.0}.get(p or "", 1.0)
                for v, p in m]
        return max(vals)
    if kind == "ohm":
        vals = [float(v) * {"m": 1e-3, "k": 1e3, "": 1.0}.get(p or "", 1.0) for v, p in m]
        return max(vals)
    return None


def check_one(rec, c):
    """返回 (状态, 说明)；状态 ∈ ok/warn/fail/unknown。"""
    if c.quant == "_pkg":
        pk = rec.get("package") or ""
        return ("ok", pk) if pkg_key(pk) == pkg_key(c.value) else ("fail", pk)
    hits = find_keys(rec, c.quant)
    if not hits:
        # paramLinkedMap 里没有 → 再试商品名（很多料的电流/电压只写在名字里）
        nv = _value_from_name(rec, c.quant)
        if nv is None:
            return ("unknown", "")
        kind_hint = ALIASES[c.quant][1]
        hits = [("商品名", f"{nv:.6g}{_UNIT_HINT.get(kind_hint, '')}")]
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
            if isinstance(c.value, tuple):
                # 「3.3V~21V」= 候选区间必须**覆盖**该区间（两头都要满足）
                lo_need, hi_need = c.value
                if key == "商品名":
                    # 名字里只能抽到一个电压（通常就是上限），只能校验上界
                    ok = hi >= hi_need * 0.98
                else:
                    ok = lo <= lo_need * 1.02 and hi >= hi_need * 0.98
                if ok:
                    return ("ok", f"{key}={raw}")
                best = best or ("fail", f"{key}={raw}")
                continue
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


# --------------------------------------------------------------------- 封装（展示与回退）
# 片式封装的标称尺寸（mm）：立创只给 "0805" 这种代号，看不出体积，配单时面积差一倍很常见。
_CHIP_SIZE = {
    "01005": (0.4, 0.2), "0201": (0.6, 0.3), "0402": (1.0, 0.5), "0603": (1.6, 0.8),
    "0805": (2.0, 1.25), "1206": (3.2, 1.6), "1210": (3.2, 2.5), "1812": (4.5, 3.2),
    "2010": (5.0, 2.5), "2512": (6.4, 3.2),
}
_PKG_DIM_RE = re.compile(r"[(（]\s*(\d+(?:\.\d+)?)\s*[xX×*]\s*(\d+(?:\.\d+)?)\s*[)）]")
# 只有"引脚数型"封装名后面的数字才是引脚数。SOT-23 / SOD-123 / DO-214AC / TO-252 里的数字
# 是封装代号，不是引脚数（SOT-23 是 3 脚，写成 23 会误导）。
_PIN_PKG_RE = re.compile(
    r"(?:LQFP|TQFP|QFP|QFN|DFN|SOP|SOIC|TSSOP|MSOP|SSOP|WLCSP|DIP|BGA|LGA)[- ]?(\d{1,3})", re.I)


def pkg_meta(text):
    """把封装字符串拆成可展示、可比较的元数据。

    `LQFP-48(7x7)` → pins=48, 7.0×7.0mm, area=49.0
    `0805`         → 片式封装按标称尺寸 2.0×1.25mm, area=2.5
    `SOP-8-208mil` → pins=8, 尺寸未知（只有引脚数与宽度代号）
    """
    raw = (text or "").strip()
    if not raw:
        return {"name": "", "pins": None, "w": None, "h": None, "area": None, "label": ""}
    key = pkg_key(raw)
    w = h = None
    m = _PKG_DIM_RE.search(raw)
    if m:
        w, h = float(m.group(1)), float(m.group(2))
    elif key in _CHIP_SIZE:
        w, h = _CHIP_SIZE[key]
    pins = None
    pm = _PIN_PKG_RE.search(raw)
    if pm:
        try:
            pins = int(pm.group(1))
        except ValueError:
            pins = None
    area = round(w * h, 2) if (w and h) else None
    label = raw
    if area:
        label = f"{raw} {area:g}mm²"
    return {"name": raw, "pins": pins, "w": w, "h": h, "area": area, "label": label}


def pkg_relation(need_text, got_text):
    """候选封装 vs 需求封装 → (level, note)。

    level: same（同封装）/ smaller（更小）/ larger（更大）/ close（面积接近）/ different（无法比较）
    note : 给人看的差异说明，例如 "面积 0.48×（更小，焊接/散热需复核）"
    """
    nk, gk = pkg_key(need_text), pkg_key(got_text)
    if nk and nk == gk:
        return "same", ""
    a, b = pkg_meta(need_text), pkg_meta(got_text)
    if a["area"] and b["area"]:
        ratio = b["area"] / a["area"]
        if 0.9 <= ratio <= 1.1:
            return "close", f"面积 {ratio:.2f}×（接近）"
        if ratio < 0.9:
            return "smaller", f"面积 {ratio:.2f}×（更小，散热/爬电距离需复核）"
        return "larger", f"面积 {ratio:.2f}×（更大，看板上空间）"
    if a["pins"] and b["pins"] and a["pins"] != b["pins"]:
        return "different", f"引脚 {a['pins']}→{b['pins']}"
    return "different", f"需求 {need_text}，实为 {got_text or '未知'}"


# --------------------------------------------------------------------- 输出
def function_gate(rec, info, family=None):
    """功能符合性闸门：参数满足 ≠ 功能对。

    立创的 catalog 归类很粗（`969 功率电子开关` 里同时挂着降压转换器、过压保护开关、
    电子保险丝、负载开关、理想二极管 ORing），`productType` 更是 catalog 级标签、零区分力。
    所以最后必须用商品名里的功能词再判一次。

    三态判定（关键：**正向未命中 ≠ 功能不符**，很多料 name 只有型号或纯参数）：
      ok        正向命中且无反向 → 功能确认
      mismatch  只命中反向        → 直接剔除
      conflict  正反都命中        → 名称歧义，保留但必须人工确认
      unknown   都没命中          → 功能未确认（保留，标注需查手册）
    """
    name = " ".join(x for x in (rec.get("name") or "", rec.get("type") or "") if x)
    pos = (info or {}).get("function_keywords") or []
    neg = (info or {}).get("exclude_keywords") or []
    return function_check(name, pos, neg, family=family)


def _rb_reason(rb):
    """把 reverse_block 判定翻译成一句人话（用于落选原因与提示）。"""
    if not rb:
        return "未核"
    v, g = rb.get("value"), rb.get("grade")
    if v == "no":
        return "该料反向经体二极管导通（手册明确）" if g == "fact" else "疑似不阻断（仅见分销页）"
    if v == "yes":
        return f"有阻断但证据只到 {g}（筛选要求 fact）" if g != "fact" else "有阻断"
    return "未查手册登记" if not rb.get("known") else "登记为未核实"


def _rb_cell(rb):
    """表格单元格：只有 fact 级才用 ✅/❌，其余加问号提示不可当结论。"""
    if not rb:
        return ""
    v, g = rb.get("value"), rb.get("grade")
    if v == "yes":
        return "✅有" if g == "fact" else f"?有({g or '未证'})"
    if v == "no":
        return "❌无" if g == "fact" else f"?无({g or '未证'})"
    return "❔未核"


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


def verify_candidates(cli, picked, n, qty, info=None, family=None):
    """主动核对：把选出来的前 N 条**回到立创实时复核**一遍（不吃缓存）。

    核对项与判据：
      库存复核   重新取一次库存，与扫描时比对；为 0 直接判「不可下单」
      价格复核   按数量重算阶梯价，变了就报出来（价格是快照，交付必须带时间）
      生命周期   商品名/在售状态（"停售"字样、in_stock）
      手册可得   datasheet_pdf 能不能取到签名直链（取不到 = 无法核对规格）
      功能符合   function_check 结论 + 商品名原文（参数满足 ≠ 功能对）
      结论       可下单 / 需人工确认 / 不可用（附原因）
    """
    n = min(n, len(picked or []))
    if n <= 0:
        return []
    print(f"\n## 主动核对（前 {n} 条，回立创实时复核；价格/库存为 {datetime.now():%Y-%m-%d %H:%M} 快照）")
    header = ["C号", "型号", "库存复核", "价格复核", "生命周期", "手册", "功能", "结论"]
    rows, records = [], []
    for r in picked[:n]:
        code = (r.get("code") or "").strip()
        try:
            fresh = cli.raw_search(code, cache=False)
            rec = next((x for x in (fresh.get("records") or [])
                        if (x.get("code") or "").upper() == code.upper()), None)
        except Exception as e:  # noqa: BLE001
            rows.append([code, (r.get("model") or "")[:20], "复核失败", "-", "-", "-", "-", f"不可用（{e}）"])
            continue
        if rec is None:
            rows.append([code, (r.get("model") or "")[:20], "已下架", "-", "-", "-", "-", "不可用（检索不到）"])
            continue
        # 1) 库存
        s0, s1 = r.get("stock") or 0, rec.get("stock") or 0
        stock_txt = f"{s1:,}" + ("" if s0 == s1 else f"（{s1 - s0:+,}）")
        # 2) 价格
        p0, p1 = price_at(r, qty), price_at(rec, qty)
        price_txt = "?" if p1 is None else money(p1) + ("" if p0 == p1 else "（变动）")
        # 3) 生命周期
        nm = f"{rec.get('name') or ''}{rec.get('type') or ''}"
        if "停售" in nm or "停产" in nm:
            life = "停售/停产"
        elif s1 <= 0:
            life = "无货"
        else:
            life = "在售"
        # 4) 手册
        try:
            pdf = cli.datasheet_pdf(code)
        except Exception:  # noqa: BLE001
            pdf = None
        sheet = "有" if pdf else "无（需原厂核对）"
        # 5) 功能
        verdict, _p, _ngs, why = function_gate(rec, info or {}, family)
        func = {"ok": "ok", "mismatch": "不符", "conflict": "歧义", "unknown": "未确认"}.get(verdict, verdict)
        # 6) 结论
        if life != "在售":
            concl = "不可用（" + life + "）"
        elif s1 < qty:
            concl = f"需人工（库存 {s1:,} < 需求 {qty}）"
        elif verdict == "mismatch":
            concl = f"不可用（功能不符：{why}）"
        elif verdict in ("conflict", "unknown") or not pdf:
            concl = "需人工确认" + ("（功能歧义）" if verdict == "conflict" else
                                    "（功能未确认）" if verdict == "unknown" else "（无手册）")
        else:
            concl = "可下单"
        rows.append([code, (rec.get("model") or "")[:20], stock_txt, price_txt, life, sheet, func, concl])
        records.append({"code": code, "model": rec.get("model"), "stock": s1, "price": p1,
                        "lifecycle": life, "datasheet": pdf, "function": verdict, "conclusion": concl})
    w = [max(cwidth(h), *(cwidth(row[i]) for row in rows)) for i, h in enumerate(header)]
    print("  " + "  ".join(pad(h, w[i]) for i, h in enumerate(header)))
    for row in rows:
        print("  " + "  ".join(pad(v, w[i]) for i, v in enumerate(row)))
    print("  核对口径：库存/价格回立创实时接口重取；手册走商品页签名直链；功能按商品名正/反向词判定。"
          "\n  仍需人工的一步：手册里的绝对最大额定值、封装焊盘图、EOL/PCN 公告 —— 这些接口没有。")
    return records


def render(cat, qty, picked, total_scanned, fails_stat, unknowns, args,
           pkg_fallback=None, pkg_need=None, pkg_dist=None,
           rb_active=False, rb_require=False, rb_dropped=None):
    label = cat.get("label_cn") or cat.get("keyword")
    print(f"\n品类: {label}（catalogIdFilter={cat.get('catalog_id') or '未解析'}，关键词={cat.get('keyword')}）")
    print(f"扫描 {total_scanned} 条候选，按 {args.sort} 排序；数量 {qty}；命中 {len(picked)} 条")
    shown = [c.raw for c in (getattr(args, "_constraints", None) or [])]
    if pkg_need:
        shown.append(f"封装={pkg_need}")
    if rb_require:
        shown.append("反向电流阻断=有（fact 级证据）")
    if shown:
        print("约束: " + "，".join(shown))
    if pkg_dist:
        # 没提封装要求时，封装就是选型的第一变量，直接摊开
        print("封装分布: " + "  ".join(pkg_dist) + "（未指定封装，全部列出，按面积/体积自行取舍）")
    if not picked:
        print("\n没有满足全部约束的料。建议放宽：" + ("，".join(fails_stat[:3]) if fails_stat else "换品类或去掉约束"))
        if not pkg_fallback:
            return
        print("下面这些料**其余约束都满足、只是封装不对**，供取舍：")
    if picked:
        header = ["#", "C号", "型号", "品牌", "封装（含面积）", "关键参数"]
        if rb_active:
            header.append("反向阻断")
        header += [f"单价@{qty}", "库存", "销量"]
        rows = []
        for i, r in enumerate(picked, 1):
            price = price_at(r, qty)
            brief = param_brief(r, cat.get("info"), limit=5)
            row = [str(i), r.get("code") or "", (r.get("model") or "")[:28], (r.get("brand") or "")[:16],
                   pkg_meta(r.get("package"))["label"],
                   brief[:80] + ("…" if len(brief) > 80 else "")]
            if rb_active:
                row.append(_rb_cell(r.get("reverse_block")))
            row += [money(price) if price is not None else "?", f"{r.get('stock') or 0:,}",
                    str(r.get("sales") or 0)]
            rows.append(row)
        widths = [max(cwidth(h), *(cwidth(row[i]) for row in rows)) for i, h in enumerate(header)]
        print("  " + "  ".join(pad(h, widths[i]) for i, h in enumerate(header)))
        for row in rows:
            print("  " + "  ".join(pad(v, widths[i]) for i, v in enumerate(row)))
        if rb_active:
            if rb_require:
                print("  反向阻断 = 手册确认（fact 级）才算「有」；未提要求的搜索不加这列筛选，只标注。")
            else:
                print("  反向阻断：只标注、未筛选（用户没提这条要求）。要筛就加一句「防倒灌」"
                      "或 --require-reverse-block。")
    if pkg_fallback:
        print(f"\n## 封装回退候选（需求 {pkg_need}；其余约束全部满足，仅封装不同）")
        fb_header = ["C号", "型号", "品牌", "实际封装", "差异", f"单价@{qty}", "库存"]
        fb_rows = []
        for r in pkg_fallback:
            level, note = pkg_relation(pkg_need, r.get("package"))
            price = price_at(r, qty)
            fb_rows.append([r.get("code") or "", (r.get("model") or "")[:24], (r.get("brand") or "")[:14],
                            pkg_meta(r.get("package"))["label"], note or "同封装",
                            money(price) if price is not None else "?", f"{r.get('stock') or 0:,}"])
        fw = [max(cwidth(h), *(cwidth(row[i]) for row in fb_rows)) for i, h in enumerate(fb_header)]
        print("  " + "  ".join(pad(h, fw[i]) for i, h in enumerate(fb_header)))
        for row in fb_rows:
            print("  " + "  ".join(pad(v, fw[i]) for i, v in enumerate(row)))
        print("  取舍要点：封装更小 → 焊盘/散热/爬电距离要复核；封装更大 → 看板上空间与钢网；"
              "引脚数不同 → 必须改 PCB。封装不符的料不能直接替代，需人工确认。")
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


_ASSORT_RE = re.compile(
    r"芯片包|元件包|阻容包|元器件包|套装|套餐|组合装|混装|样品盒|样品包|整盒|一盒|散装包|分类盒|\d{1,3}\s*种")
# 开发板/套件不是元件，比价时必须剔除（STM32 这类料淘宝前几名常是开发板）
_DEVBOARD_RE = re.compile(r"开发板|最小系统|核心板|面包板|仿真器|下载器|烧录器|套件|同款科协")
# 系列链接：一条链接覆盖多个阻值/容值，标价是"一包/一份"的起价，不能当单只价。
# 只认电阻/电容单位，且左边界不能紧贴字母数字 —— 否则 "AO3400A/30V/5.8A" 这类型号里的
# 数字会被当成数值，把单只料误判成"系列"。
_RC_VAL_RE = re.compile(
    r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?\s*(?:[RrKkMm]\d*|Ω|欧|[uUnNpP]F)(?![A-Za-z0-9])")
# 阻值连写（"1k2k4.7k10k47k100k"）：没有空格分隔，靠单位字母切
_GLUED_VAL_RE = re.compile(r"\d+(?:\.\d+)?[kKmMrR](?![A-Za-z])")
# 容值连写（"1U1.5U2.2U…10UF15UF"）：U/N/P 后面紧跟数字
_GLUED_CAP_RE = re.compile(r"\d+(?:\.\d+)?\s*[UuNnPp](?=[\d.])")

SAMPLE_OK_LIMIT = 10   # 包装 <= 10 只算"小包装/可打样"
BATCH_QTY = 100        # 超过视为批量，默认不查淘宝


def _looks_series(title):
    """标题像"一条链接挂多个阻值/容值"（系列链接）时返回 True。

    这类链接的标价是"一包/一份"的起价，按单只价比较会把淘宝算成贵几十倍。
    实测 5 组样本（60 条标题）上：阈值为 2 时阻容系列全部命中，芯片/型号标题 0 个命中。
    """
    if "系列" in title:
        return True
    n = (len(_RC_VAL_RE.findall(title))
         + len(_GLUED_VAL_RE.findall(title))
         + len(_GLUED_CAP_RE.findall(title)))
    return n >= 2


def _market_usable(x):
    """淘宝/1688 里"混装包/套装/开发板"的单只价没有可比性，先剔掉；conf=low 的也不要用。"""
    title = x.get("title") or ""
    if _ASSORT_RE.search(title):
        return False
    if _DEVBOARD_RE.search(title):
        return False
    if (x.get("unit_note") or "").startswith("数量区间"):
        return False
    if str(x.get("unit_confidence") or "").lower() == "low":
        return False
    return True


def _shop_type(shop, badges=None):
    """店铺类型：旗舰店 / 专营店 / 企业店 / 散货配单 / 普通店。"""
    t = f"{shop or ''} {' '.join(badges or [])}"
    if "旗舰店" in t:
        return "旗舰店"
    if "专营店" in t or "专卖店" in t:
        return "专营店"
    if "企业店" in t or "企业购" in t:
        return "企业店"
    if re.search(r"配单|一站式|元器件|电子|芯片|半导体", t):
        return "散货/配单"
    return "普通店"


def _shipping_note(x):
    """运费提示：只能从标题/店铺标里读到"包邮"，其余按淘宝零售运费给保守区间。"""
    t = (x.get("title") or "") + "".join(x.get("shop_badges") or [])
    if "包邮" in t:
        return "包邮"
    p = x.get("price_value") or 0
    if p and p < 1:
        return "运费另计（≈¥8-12，单价低于运费建议凑单）"
    return "运费另计（≈¥8-12）"


def sample_info(x):
    """一条淘宝/1688 结果 → 样品可得性。

    返回 {sample_ok, pack, unit_price, pack_text, sample_text, shipping_note,
          shop_type, assumed, note}
    `assumed=True` 表示标题没标数量、按"1 只/1 份"计价（可能是整包，需人工核对）。
    """
    out = {
        "sample_ok": False, "pack": None, "unit_price": None, "pack_text": "—",
        "sample_text": "—", "shipping_note": _shipping_note(x),
        "shop_type": _shop_type(x.get("shop"), x.get("shop_badges")),
        "assumed": False, "note": x.get("unit_note") or "",
    }
    title = x.get("title") or ""
    if _DEVBOARD_RE.search(title):
        out["sample_text"] = "✗ 开发板/套件"
        out["note"] = out["note"] or "不是元件"
        return out
    if x.get("assortment") or _ASSORT_RE.search(title):
        out["sample_text"] = "✗ 混装包"
        out["note"] = "混装/套装（含多个型号），不做单只价"
        return out
    if out["note"].startswith("数量区间"):
        out["sample_text"] = "✗ 区间价"
        return out

    pack = x.get("pack_qty")
    if pack:
        pack = int(pack)
        out["pack"] = pack
        out["unit_price"] = x.get("unit_price")
        out["pack_text"] = f"{pack} 只/份"
        out["sample_ok"] = pack <= SAMPLE_OK_LIMIT
        out["sample_text"] = "✓ 可打样" if out["sample_ok"] else f"✗ 最小 {pack} 只"
        return out

    price = x.get("price_value")
    if price is None:
        return out
    if _looks_series(title):
        # 一条链接挂多个阻值/容值，标价是"一份"的起价 —— 不给单只价，但可以打样
        out["sample_ok"] = True
        out["sample_text"] = "✓ 可打样（系列链接）"
        out["note"] = "系列链接：多阻值/容值同价，标价为一包起价，单只价看 SKU"
        return out
    out["unit_price"] = float(price)
    out["pack"] = 1
    out["pack_text"] = "1 只（标题未标数量）"
    out["sample_ok"] = True
    out["assumed"] = True
    out["sample_text"] = "✓ 可买 1 只"
    return out


def _dump_market_raw(args, model, site, items, meta):
    """把淘宝/1688 原始结果按型号 + 时间戳落盘（--taobao-json DIR）。"""
    base = getattr(args, "taobao_json", None)
    if not base:
        return None
    try:
        d = Path(base)
        d.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^0-9A-Za-z._-]+", "_", model).strip("_")[:40] or "item"
        p = d / f"pick_{safe}_{site}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        p.write_text(json.dumps({
            "model": model, "site": site,
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "meta": meta, "items": items,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        return p
    except OSError as e:  # noqa: BLE001
        print(f"[warn] 原始结果落盘失败（{e}）", file=sys.stderr)
        return None


def taobao_plan(args):
    """要不要去淘宝比价，返回取样型号数（0 = 不查）。"""
    if getattr(args, "no_taobao", False):
        return 0
    if getattr(args, "taobao", 0) and args.taobao > 0:
        return args.taobao
    if args.qty > BATCH_QTY:
        return 0
    if args.qty <= SAMPLE_OK_LIMIT:
        return max(1, getattr(args, "taobao_sample", 0) or 3)
    return 0


def _ratio_text(tb_price, lc_price, site_name="淘宝"):
    """淘宝/1688 vs 立创的相对价差文案（省 90% 以上改说"便宜 N×"，避免出现"省 100%"）。"""
    if not tb_price or not lc_price:
        return ""
    d = tb_price / lc_price
    if d >= 1:
        return f"{site_name} {d:.1f}×"
    save = 1 - d
    if d < 0.1:
        return f"{site_name}便宜 {1 / d:.0f}×"
    return f"{site_name}省 {save * 100:.0f}%"


def market_compare(picked, args, n=None):
    """拿 pick 出来的型号去淘宝/1688 摸零售单只价 + 样品可得性，判断渠道。"""
    try:
        import taobao as tb  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        print(f"\n[warn] 淘宝脚本不可用（{e}），跳过渠道比价", file=sys.stderr)
        return
    site = args.market
    site_name = "1688" if site == "1688" else "淘宝"
    n = min(n if n is not None else (args.taobao or 0), len(picked))
    if n <= 0:
        return
    print(f"\n## 渠道比价（{site}，按销量取样 {n} 个型号；{site_name}需浏览器已登录）")
    header = ["型号", "立创单只", f"{site}单只", "对比", "包装/起订", "样品", "运费", "店铺类型"]
    rows, concl = [], []
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
            rows.append([model[:24], money(lc) if lc else "?", "—", f"取数失败: {str(e)[:24]}",
                         "—", "—", "—", "—"])
            continue
        _dump_market_raw(args, model, site, items, {
            "url": res.get("url"), "sort_applied": res.get("sort_applied"),
            "total": res.get("total"), "used_fallback": res.get("used_fallback"),
        })
        infos = [(x, sample_info(x)) for x in items if _market_usable(x)]
        bl_shops = [x for x, _ in infos if x.get("shop_blacklisted")]
        if bl_shops:
            # 店铺黑名单：命中即不参与最低价比较，并明确说出来（否则"最便宜"可能来自被拉黑的店）
            for x in bl_shops[:3]:
                why = "、".join(h["name"] + (f"（{h['reason']}）" if h["reason"] else "")
                                for h in x["shop_blacklisted"])
                print(f"  ⛔ 黑名单店铺已排除：{model} @ {x['shop']}（{money(x.get('unit_price'))}/只）—— {why}")
            infos = [(x, i) for x, i in infos if not x.get("shop_blacklisted")]
        with_price = [(x, i) for x, i in infos if i.get("unit_price")]
        if with_price:
            x, i = min(with_price, key=lambda xi: xi[1]["unit_price"])
            lc_s = money(lc) if lc else "?"
            rows.append([model[:24], lc_s, money(i["unit_price"]),
                         _ratio_text(i["unit_price"], lc, site_name),
                         i["pack_text"], i["sample_text"], i["shipping_note"], i["shop_type"]])
            start = f"{i['pack']} 只起" if i.get("pack") else "标题未标数量"
            if i.get("sample_ok"):
                small = (f"{site_name}打样" if (lc and i["unit_price"] < lc)
                         else f"立创（{site_name}没更便宜）")
                small_note = f"少量（≤{SAMPLE_OK_LIMIT}）建议{small}"
            else:
                small_note = (f"少量（≤{SAMPLE_OK_LIMIT}）这个链接 {i['pack']} 只起、不能打样，"
                              "打样要另找小包装/散卖链接")
            concl.append(f"{model}: {site_name} {money(i['unit_price'])}/只（{start}） vs 立创 {lc_s}/只 —— "
                         f"{small_note}；批量（>{BATCH_QTY}）走 1688 询盘/原厂代理")
        elif infos:
            x, i = infos[0]
            rows.append([model[:24], money(lc) if lc else "?", "—", "无单只价",
                         i["pack_text"], i["sample_text"], i["shipping_note"], i["shop_type"]])
            concl.append(f"{model}: {site_name} {len(infos)} 条可用结果都没有单只价（{i['note'][:28]}）——"
                         f"立创 {money(lc) if lc else '?'}/只 更靠谱，{site_name}只作打样渠道")
        else:
            rows.append([model[:24], money(lc) if lc else "?", "—", "无可用结果", "—", "—", "—", "—"])
            concl.append(f"{model}: {site_name}无可用结果（{len(items)} 条原始命中，均被混装/开发板规则剔除）")
    widths = [max(cwidth(h), *(cwidth(row[i]) for row in rows)) for i, h in enumerate(header)]
    print("  " + "  ".join(pad(h, widths[i]) for i, h in enumerate(header)))
    for row in rows:
        print("  " + "  ".join(pad(v, widths[i]) for i, v in enumerate(row)))
    if concl:
        print("\n### 样品可得性 / 渠道建议")
        for line in concl:
            print(f"  - {line}")
    print(f"\n  说明：{site} 价是「单只价」估算（标题带 100个/包 已归一；标题没标数量时按 1 只计，"
          "assumed 见 JSON）。混装包/套装/开发板/数量区间已剔除。"
          f"{site_name}需登录态，卡片 0 条按登录态过期处理。")


def cmd_pick(args):
    cats = load_categories()
    cli = Lcsc(rate_limit=getattr(args, "rate", 0.8))
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
    # 封装要求单独一组：它的失败**不直接淘汰**，而是进「回退候选」（见下）。
    # 封装可能来自 --package，也可能来自句子里（"10uF 25V 0805 电容"），两处合并。
    pkg_from_text = [c.value for c in constraints if c.quant == "_pkg"]
    pkg_need = (args.package or "").strip() or (pkg_from_text[0] if pkg_from_text else None)
    pkg_cs = [Constraint("_pkg", "=", pkg_need, pkg_need, "")] if pkg_need else []
    cs = [c for c in constraints if c.quant != "_pkg"]  # 名称/参数约束（不含封装）
    args._constraints = cs

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

    # 黑名单：品牌 / 料号维度的人为判断，必须在排序之前剔除（否则低价黑名单品牌会排到前面）
    bl_hits = []
    if not getattr(args, "no_blacklist", False):
        try:
            import blacklist as _bl
            recs, _dropped = _bl.filter_records(recs)
            for r, hits in _dropped:
                bl_hits.append({"code": r.get("code"), "model": r.get("model"),
                                "brand": r.get("brand"),
                                "hits": [{"kind": h["kind"], "name": h["name"],
                                          "reason": h["reason"]} for h in hits]})
        except Exception as e:  # 黑名单坏掉不能拖垮选型
            print(f"[警告] 黑名单加载失败，已按空处理：{e}", file=sys.stderr)

    # 品牌白名单：按「品牌 × 品类」放行（用户 m03469）
    #   新品牌 / 已有品牌进入非同类物料 → 必须先背调或做知识库核对，不能静默推荐
    wl_summary, wl_dropped = {}, []
    if not getattr(args, "no_whitelist", False):
        try:
            import whitelist as _wl
            _bl_mod = None
            try:
                import blacklist as _bl_mod  # noqa: F811  黑名单优先
            except Exception:
                _bl_mod = None
            recs, wl_summary = _wl.gate_records(
                recs, family=cat.get("family"), catalog_id=cat.get("catalog_id"),
                blacklist_mod=_bl_mod)
            if getattr(args, "strict_brand", False):
                allow = [r for r in recs
                         if r.get("whitelist_status") in ("approved", "kb_known")]
                wl_dropped = [r for r in recs
                              if r.get("whitelist_status") not in ("approved", "kb_known")]
                recs = allow
        except Exception as e:  # 白名单坏掉不能拖垮选型
            print(f"[警告] 白名单加载失败，已按空处理：{e}", file=sys.stderr)
            wl_summary = {}

    ok, fails_all, unknown_dropped = [], [], []
    func_mismatch, func_unconfirmed, func_conflict = [], [], []
    pkg_fallback = []  # 封装不符、但其余约束全满足的候选（用户要求"依然列出来并说明"）
    rb_require = bool(getattr(args, "require_reverse_block", False)) or (
        not getattr(args, "no_reverse_block", False) and bool(_RB_RE.search(text)))
    rb_mod, rb_data = None, None
    rb_active = rb_require or (cat.get("family") in _RB_FAMILIES)
    if rb_active:
        try:
            import loadswitch as _ls
            rb_mod, rb_data = _ls, _ls.load()
        except Exception as e:  # 判据库坏掉不能拖垮选型
            print(f"[警告] 反向阻断判据库加载失败，已按未知处理：{e}", file=sys.stderr)
            rb_mod = None
    rb_dropped = []
    info = cat.get("info") or {}
    # 非功率开关品类：只有当候选里真的有登记过的料时才开这列（否则整列 ❔未核 是噪音）
    if rb_mod is not None and not rb_active:
        _parts = (rb_data or {}).get("parts") or {}
        if any((r.get("code") or "") in _parts for r in recs):
            rb_active = True
    for r in recs:
        good, fails, unknowns = evaluate(r, cs)
        if not good:
            fails_all.extend(fails)
            continue
        # 功能符合性：参数满足 ≠ 功能对（立创 catalog 混装严重）
        if not getattr(args, "no_func", False):
            verdict, _pos, _neg, why = function_gate(r, info, cat.get("family"))
            if verdict == "mismatch":
                func_mismatch.append(f"{r.get('model')}（{why}）")
                fails_all.append(f"功能:{why}")
                continue
            if verdict == "conflict":
                func_conflict.append(f"{r.get('model')}（{why}）")
            elif verdict == "unknown":
                func_unconfirmed.append(r.get("model"))
        # 反向电流阻断：知识库里 fact 级才算「有」；用户提了要求才据此淘汰
        if rb_mod is not None:
            rb = rb_mod.reverse_block(code=r.get("code"), model=r.get("model"),
                                      name=r.get("name") or "", data=rb_data)
            r["reverse_block"] = rb
            if rb_require and not (rb["value"] == "yes" and rb.get("grade") == "fact"):
                why = _rb_reason(rb)
                rb_dropped.append((r, why))
                fails_all.append(f"反向阻断:{why}")
                continue
        if unknowns and not args.allow_unknown:
            # 关键约束在该料上根本没这个参数 → 不能当作"满足"（例如只标了 300mA 的料没写耐压）
            unknown_dropped.append(r)
            continue
        pkg_ok = True
        if pkg_cs:
            pkg_ok, pkg_fails, _ = evaluate(r, pkg_cs)
        if pkg_ok:
            ok.append(r)
        else:
            fails_all.extend(pkg_fails)
            pkg_fallback.append(r)
    from collections import Counter
    fails_stat = [f"{k} ×{v}" for k, v in Counter(fails_all).most_common(3)]
    picked = rank(ok, args.qty, args.sort)[: args.limit]
    # 回退候选：只有「封装要求一条都没满足」时才兜底（满足了就不列，避免噪音）
    # 按「离需求封装多近」排，再按价格
    n_pkg_fb = 0 if getattr(args, "no_pkg_fallback", False) else max(0, getattr(args, "pkg_fallback", 3))
    if pkg_need and n_pkg_fb and not picked:
        rel_rank = {"close": 0, "smaller": 1, "larger": 2, "different": 3}
        pkg_fallback = sorted(
            pkg_fallback,
            key=lambda r: (rel_rank.get(pkg_relation(pkg_need, r.get("package"))[0], 9),
                           price_at(r, args.qty) or 9e9))[:n_pkg_fb]
    else:
        pkg_fallback = []
    # 封装分布：没提封装要求时，把"都有哪些封装"直接摊开给用户挑
    pkg_dist = []
    if not pkg_need and ok:
        cnt = Counter((pkg_meta(r.get("package"))["label"] or r.get("package") or "未知") for r in ok)
        pkg_dist = [f"{k}×{v}" for k, v in cnt.most_common(6)]
    all_unknowns = [u for r in recs for u in evaluate(r, cs)[2]]
    render(cat, args.qty, picked, scanned, fails_stat, all_unknowns, args,
           pkg_fallback=pkg_fallback, pkg_need=pkg_need, pkg_dist=pkg_dist,
           rb_active=rb_active, rb_require=rb_require, rb_dropped=rb_dropped)
    if rb_require and rb_dropped:
        print("\n## 反向电流阻断筛选（要求：有反向阻断，且证据为 fact）")
        print(f"  已剔除 {len(rb_dropped)} 条（其余约束满足，仅这一项不达标/未核实）：")
        for r, why in rb_dropped[:5]:
            print(f"    {r.get('code')} {r.get('model')}（{r.get('brand')}）—— {why}")
        if len(rb_dropped) > 5:
            print(f"    …… 另 {len(rb_dropped) - 5} 条")
        print("  说明：立创参数表没有「反向电流阻断」字段，判定只能来自手册登记"
              "（data/knowledge/load-switch.yaml）；未登记的料一律按未核实剔除，不猜。")
        print("  补登记：`python loadswitch.py add <C号> --model <型号> --class <类别> "
              "--reverse-block yes|no --grade fact --basis \"手册哪一节怎么说\" "
              "--authorized \"谁/何时/为什么\"`")
    if bl_hits:
        names = []
        for h in bl_hits[:3]:
            why = "、".join(f"{x['name']}" for x in h["hits"])
            names.append(f"{h['model'] or h['code']}（{h['brand']}｜{why}）")
        print(f"黑名单已剔除 {len(bl_hits)} 条：" + "；".join(names)
              + ("…" if len(bl_hits) > 3 else "")
              + "（改名单：`python blacklist.py list|add|remove`；本次放行加 --no-blacklist）")
    if wl_summary:
        print(_wl.render_summary(wl_summary, cat.get("family")), end="")
    if wl_dropped:
        print(f"--strict-brand 已剔除 {len(wl_dropped)} 条未背调品牌的候选"
              "（不加该开关时只标注、不剔除）")
    if func_mismatch:
        print(f"功能不符已剔除 {len(func_mismatch)} 条："
              + "；".join(func_mismatch[:3]) + ("…" if len(func_mismatch) > 3 else ""))
    if func_conflict:
        print(f"⚠ 功能有歧义 {len(func_conflict)} 条（名称正反词都命中，必须人工确认）："
              + "；".join(func_conflict[:3]))
    if func_unconfirmed and picked:
        print(f"功能未确认 {len(func_unconfirmed)} 条：商品名里没有功能描述（只有型号/纯参数），"
              "选型前需查手册或原厂页面 —— `python lcsc.py detail <C号> --pdf` 下载后交 read-pdf。")
    if unknown_dropped:
        print(f"另有 {len(unknown_dropped)} 条因缺少约束对应参数被排除（加 --allow-unknown 可放行）")
    verified = []
    if picked and getattr(args, "verify", 0):
        verified = verify_candidates(cli, picked, args.verify, args.qty, info, cat.get("family"))
    n_cmp = taobao_plan(args)
    if picked and n_cmp:
        market_compare(picked, args, n_cmp)
    elif picked and args.qty > BATCH_QTY and not getattr(args, "no_taobao", False):
        print(f"渠道: 批量（{args.qty} 只 > {BATCH_QTY}）默认不查淘宝 —— 走 1688 询盘/原厂代理；"
              "要零售比价可加 --taobao N。")
    if args.json:
        out = {
            "generated": datetime.now().isoformat(timespec="seconds"),
            "category": cat, "qty": args.qty, "scanned": scanned,
            "constraints": [c.raw for c in constraints],
            "package_need": pkg_need,
            "package_distribution": pkg_dist,
            "reverse_block_required": bool(rb_require),
            "reverse_block_dropped": [
                {"code": r.get("code"), "model": r.get("model"),
                 "brand": r.get("brand"), "reason": why,
                 "reverse_block": r.get("reverse_block")}
                for r, why in rb_dropped],
            "picked": [dict(r, unit_price=price_at(r, args.qty),
                            package_meta=pkg_meta(r.get("package"))) for r in picked],
            "package_fallback": [dict(r, unit_price=price_at(r, args.qty),
                                      package_meta=pkg_meta(r.get("package")),
                                      package_relation=pkg_relation(pkg_need, r.get("package"))[0],
                                      package_note=pkg_relation(pkg_need, r.get("package"))[1])
                                 for r in pkg_fallback],
            "verified": verified,
            "blacklisted": bl_hits,
            "brand_whitelist": wl_summary,
        }
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nJSON 已写入 {args.json}")
    return 0


def cmd_resolve(args):
    cli = Lcsc(rate_limit=getattr(args, "rate", 0.5))
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
    p.add_argument("--package", help="封装，如 SOT-23 / 0805（不满足的会进「封装回退」段，不直接丢弃）")
    p.add_argument("--pkg-fallback", dest="pkg_fallback", type=int, default=3, metavar="N",
                   help="封装回退候选条数（默认 3；0 关闭）：封装不符但其余约束全满足的料仍列出并说明差异")
    p.add_argument("--no-pkg-fallback", dest="no_pkg_fallback", action="store_true",
                   help="完全按封装硬筛，不给回退候选")
    p.add_argument("--verify", type=int, nargs="?", const=3, default=0, metavar="N",
                   help="主动核对前 N 条（默认 3）：回立创实时复核库存/价格/生命周期/手册，并给下单结论")
    p.add_argument("--brand-id", help="立创品牌 id（见 search --brand）")
    p.add_argument("--price-min", default="")
    p.add_argument("--price-max", default="")
    p.add_argument("--qty", type=int, default=1, help="采购数量（决定阶梯价）")
    p.add_argument("--sort", default="sales", choices=list(SORT_CHOICES))
    p.add_argument("--pages", type=int, default=2, help="翻页数，每页 30")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--json", help="把结果写到 JSON 文件")
    p.add_argument("--allow-unknown", action="store_true", help="允许缺少约束参数的料入选")
    p.add_argument("--no-func", dest="no_func", action="store_true",
                   help="关闭功能符合性校验（默认开启：滤掉名称含反向功能词的料，如把降压转换器当负载开关）")
    p.add_argument("--require-reverse-block", dest="require_reverse_block", action="store_true",
                   help="要求「有反向电流阻断」并据此筛选（只认知识库里 fact 级证据；"
                        "句子里写「防倒灌」等词等同于加这个开关）")
    p.add_argument("--no-reverse-block", dest="no_reverse_block", action="store_true",
                   help="即使句子里提到防倒灌，也只标注不筛选（把要求降级为提示）")
    p.add_argument("--no-blacklist", dest="no_blacklist", action="store_true",
                   help="本次忽略黑名单（默认按 data/knowledge/blacklist.yaml 剔除品牌/料号）")
    p.add_argument("--no-whitelist", dest="no_whitelist", action="store_true",
                   help="本次不做品牌白名单核对（默认按「品牌 × 品类」标注是否已背调）")
    p.add_argument("--strict-brand", dest="strict_brand", action="store_true",
                   help="只保留白名单已通过的品牌（未背调/跨品类的一律剔除）")
    p.add_argument("--taobao", type=int, default=0, metavar="N",
                   help="对前 N 个结果去淘宝/1688 查零售单只价，做渠道比价")
    p.add_argument("--no-taobao", dest="no_taobao", action="store_true",
                   help="关闭少量场景（--qty<=10）的自动淘宝比价")
    p.add_argument("--taobao-sample", dest="taobao_sample", type=int, default=3, metavar="N",
                   help="少量场景自动比价的型号数（默认 3）")
    p.add_argument("--taobao-json", dest="taobao_json", metavar="DIR",
                   help="把淘宝/1688 原始结果按型号+时间戳落盘到 DIR")
    p.add_argument("--market", default="taobao", choices=["taobao", "1688"])
    p.add_argument("--debug", action="store_true")
    p.set_defaults(func=cmd_pick)

    p2 = sub.add_parser("resolve", help="关键词 → 品类树")
    p2.add_argument("keyword", nargs="+")
    p2.set_defaults(func=cmd_resolve)

    p3 = sub.add_parser("cats", help="列出已知品类索引")
    p3.set_defaults(func=cmd_cats)

    for _p in sub.choices.values():  # 所有子命令共享限速参数
        _p.add_argument("--rate", type=float, default=0.8,
                        help="请求间隔秒数（默认 0.8；被反爬时调大）")

    a = ap.parse_args(argv)
    if not getattr(a, "func", None):
        ap.print_help()
        return 2
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
