#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""元器件参数解析与指标核对（spec 核对核心）。

两件事：
1. 从 BOM 的一行文字（或立创记录的参数字段）里抽出可比的数值指标；
2. 把一个需求指标和候选料号的实际参数比对，产出 ok / warn / fail / unknown 结论。

设计原则（见 references/spec-check.md）：
- 只比「同一物理量 + 同一单位」的数值，不做跨类目猜测；抽不到就是 unknown，不假装通过。
- 电压类一律按「候选额定值 ≥ 需求」判断，另附降额提示（MLCC 2×、钽 2×）。
- 品牌、批次、交期不参与指标比对（属可放宽维度）。
"""
from __future__ import annotations

import re

NUM = r"(\d+(?:\.\d+)?)"
PREFIX = {
    "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6,
    "m": 1e-3, "": 1.0, "R": 1.0, "r": 1.0, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9,
}
UNIT_PREFIX = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3, "": 1.0,
               "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}

PACKAGE_RE = re.compile(
    r"(?<![0-9A-Za-z])(0201|0402|0603|0805|1206|1210|1812|2010|2512|3225|3216|5032|"
    r"SOT-?23(?:-3)?|SOT-?223|SOT-?89|SOD-?123|SOD-?323|SOD-?523|SMA|SMB|SMC|"
    r"DO-?214AC|DO-?214AA|DO-?41|"
    r"SOP-?8|SOP-?16|SOIC-?8|SOIC-?16|TSSOP-?16|MSOP-?8|"
    r"LQFP-?48|LQFP-?64|LQFP-?100|TQFP-?44|QFN-?\d+|DFN-?\d+|SSOP-?\d+|"
    r"USB-?C-?16P?|TYPE-?C|DIP-?\d+)(?![0-9A-Za-z])",
    re.I,
)

# 封装别名：不同写法的同一封装归一到同一组
PKG_ALIAS = {
    "SOP8": "SO8", "SO8": "SO8", "SOIC8": "SO8", "SOIC8208MIL": "SO8", "SO8208MIL": "SO8",
    "TSSOP8": "TSSOP8", "MSOP8": "MSOP8",
    "SMA": "DO214AC", "DO214AC": "DO214AC",
    "SMB": "DO214AA", "DO214AA": "DO214AA",
    "SMC": "DO214AB", "DO214AB": "DO214AB",
    "SOT23": "SOT23", "SOT233": "SOT23",
    "SOT223": "SOT223", "SOT2233": "SOT223",
    "TYPEC": "USBC", "USBC": "USBC", "USBC16P": "USBC", "USBC16": "USBC",
    "SOD123": "SOD123", "SOD323": "SOD323", "SOD523": "SOD523",
    "5032": "5032", "SMD5032": "5032",
    "3225": "3225", "3216": "3216",
}


def pkg_key(p):
    """封装归一为可比较的 key。'SOIC-8-208mil' 与 'SOP-8' 视为同一组。"""
    n = norm_pkg(p)
    if not n:
        return ""
    return PKG_ALIAS.get(n, n)

FAMILY_HINTS = [
    ("mcu", ["单片机", "MCU", "微控制器"]),
    ("ldo", ["线性稳压", "LDO", "低压差"]),
    ("dcdc", ["DC-DC", "开关电源", "电源模块", "开关稳压"]),
    ("resistor", ["贴片电阻", "直插电阻", "插件电阻", "电阻"]),
    ("mlcc", ["贴片电容", "MLCC", "陶瓷电容"]),
    ("electrolytic", ["铝电解", "直插电解", "电解电容"]),
    ("tantalum", ["钽"]),
    ("inductor", ["贴片电感", "功率电感", "电感"]),
    ("bead", ["磁珠"]),
    ("led", ["发光二极管", "LED", "发光"]),
    ("diode", ["二极管", "肖特基", "整流", "TVS", "ESD", "稳压二极管", "快恢复"]),
    ("mosfet", ["MOSFET", "场效应", "MOS"]),
    ("bjt", ["三极管", "晶体管"]),
    ("crystal", ["晶振", "无源晶振", "振荡器"]),
    ("connector", ["连接器", "排针", "端子", "USB", "TYPE-C", "插座"]),
    ("flash", ["FLASH", "EEPROM", "存储器"]),
    ("opamp", ["运放", "运算放大器", "比较器"]),
    ("optocoupler", ["光耦"]),
    ("fuse", ["保险丝", "自恢复"]),
    ("switch", ["轻触", "按键", "开关"]),
]

# 立创参数字段 → (物理量, 解析器名)
PARAM_FIELDS = [
    (("阻值",), "ohm"),
    (("容值",), "farad"),
    (("电感值", "感值"), "henry"),
    (("额定电压", "耐压", "击穿电压"), "volt"),
    (("正向压降",), "volt"),
    (("精度", "容差", "容值精度", "阻值精度", "误差"), "tol"),
    (("功率", "额定功率"), "watt"),
    (("额定电流", "电流"), "amp"),
    (("频率",), "freq"),
    (("直流电阻", "DCR", "内阻"), "ohm"),
    (("发光颜色", "颜色"), "color"),
    (("温度系数", "介质", "材质"), "dielectric"),
    (("极性",), "polarity"),
    (("触发电平",), "text"),
]


def to_num(s):
    """'10kΩ' → 10000.0；'100nF' → 1e-07；无法解析返回 None。"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    m = re.search(NUM + r"\s*([pnuµmkKMGRr]?)", str(s))
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    return v * PREFIX.get(m.group(2), 1.0)


def parse_ohm(text):
    if text is None:
        return None
    s = str(text)
    m = re.search(NUM + r"\s*([kKMGRr]?)\s*(?:Ω|ohms?|欧)?", s)
    if not m:
        return None
    try:
        return float(m.group(1)) * PREFIX.get(m.group(2), 1.0)
    except ValueError:
        return None


def parse_farad(text):
    m = re.search(NUM + r"\s*([pnuµm]?)\s*[Ff]\b", str(text or ""))
    if m:
        return float(m.group(1)) * UNIT_PREFIX.get(m.group(2), 1.0)
    m = re.search(NUM + r"\s*([pnuµm]?)\s*F", f"{text} ")
    return float(m.group(1)) * UNIT_PREFIX.get(m.group(2), 1.0) if m else None


def parse_henry(text):
    m = re.search(NUM + r"\s*([pnuµm]?)\s*[Hh]\b", str(text or ""))
    return float(m.group(1)) * UNIT_PREFIX.get(m.group(2), 1.0) if m else None


def parse_volt(text):
    """返回 (typ, max)；'1.6V~2.6V' → (1.6, 2.6)。"""
    s = str(text or "")
    vals = [float(v) * UNIT_PREFIX.get(p or "", 1.0)
            for v, p in re.findall(NUM + r"\s*([kM]?)\s*V\b", s)]
    if not vals:
        return None, None
    return vals[0], max(vals)


def parse_tol(text):
    m = re.search(NUM + r"\s*%", str(text or ""))
    return float(m.group(1)) if m else None


def parse_watt(text):
    m = re.search(NUM + r"\s*(m|k)?W\b", str(text or ""))
    return float(m.group(1)) * {"m": 1e-3, "k": 1e3, "": 1.0}.get(m.group(2) or "", 1.0) if m else None


def parse_amp(text):
    m = re.search(NUM + r"\s*(m|u|µ)?A\b", str(text or ""))
    return float(m.group(1)) * {"m": 1e-3, "u": 1e-6, "µ": 1e-6, "": 1.0}.get(m.group(2) or "", 1.0) if m else None


def parse_freq(text):
    m = re.search(NUM + r"\s*([kMG]?)\s*(?:Hz|HZ|hz)\b", str(text or ""))
    if not m:
        m = re.search(NUM + r"\s*([kMG]?)\s*HZ", str(text or ""), re.I)
    return float(m.group(1)) * UNIT_PREFIX.get(m.group(2) or "", 1.0) if m else None


def parse_package(text):
    m = PACKAGE_RE.search(str(text or ""))
    if not m:
        return None
    return norm_pkg(m.group(1))


def norm_pkg(p):
    if not p:
        return ""
    s = str(p).upper().replace(" ", "").replace("_", "")
    s = re.sub(r"\(.*?\)", "", s)          # LQFP-48(7x7) → LQFP-48
    s = s.replace("-", "")
    if s in ("SMD50322P", "SMD5032", "5032"):
        return "5032"
    if s.startswith("SOIC8"):
        return "SOIC8"
    if s in ("SOP8", "SO8"):
        return "SOP8"
    return s


PARSERS = {
    "ohm": parse_ohm, "farad": parse_farad, "henry": parse_henry, "volt": parse_volt,
    "tol": parse_tol, "watt": parse_watt, "amp": parse_amp, "freq": parse_freq,
    "text": lambda s: str(s or "").strip() or None,
    "color": lambda s: str(s or "").strip() or None,
    "dielectric": lambda s: str(s or "").strip() or None,
    "polarity": lambda s: str(s or "").strip() or None,
}


def detect_family(*texts):
    blob = " ".join(str(t or "") for t in texts)
    for fam, hints in FAMILY_HINTS:
        for h in hints:
            if h.lower() in blob.lower():
                return fam
    return "unknown"


# 功能符合性：立创的 catalog 归类很粗——DC-DC 降压转换器也会挂在「功率电子开关」下，
# 「电子保险丝」有的料 type 写「功率电子开关」、有的写「浪涌保护器」。
# 参数满足 ≠ 功能对：MP4316GRE-Z（45V/6A 同步降压转换器）能通过「工作电压/最大连续电流」筛选，
# 但它根本不是负载开关。所以最后必须用 productName 的正/反向关键词再判一次。
# 数据源：data/categories.yaml 每个 family 的 function_keywords / exclude_keywords；
# 这里只是「没有 YAML 时」的内置兜底，**以 YAML 为准**。
FUNCTION_FALLBACK = {
    "load_switch": (
        ["负载开关", "电子保险丝", "efuse", "过压保护", "热插拔", "hot swap", "hotswap",
         "限流开关", "理想二极管", "load switch", "浪涌保护", "hot-swap"],
        ["降压转换器", "降压", "升压", "dc-dc", "dcdc", "ldo", "稳压器", "充电管理",
         "电池管理", "转换器", "驱动芯片"],
    ),
    "ldo": (
        ["ldo", "线性稳压", "低压差"],
        ["降压转换器", "dc-dc", "升压", "开关稳压", "充电管理"],
    ),
    "dcdc": (
        ["dc-dc", "dcdc", "降压转换器", "升压转换器", "开关稳压", "buck", "boost"],
        ["ldo", "线性稳压", "负载开关", "电子保险丝"],
    ),
    "mosfet": (
        ["mosfet", "mos", "场效应", "n沟道", "p沟道", "n-channel", "p-channel"],
        ["三极管", "bjt", "二极管", "驱动芯片"],
    ),
    "bjt": (
        ["三极管", "bjt", "晶体管", "达林顿"],
        ["mosfet", "场效应", "二极管"],
    ),
    "tvs": (
        ["tvs", "瞬态", "浪涌抑制", "esd"],
        ["稳压二极管", "肖特基", "整流"],
    ),
    "diode": (
        ["二极管", "整流", "开关二极管", "快恢复"],
        ["tvs", "瞬态抑制", "稳压二极管", "mosfet", "三极管"],
    ),
    "schottky": (
        ["肖特基", "schottky"],
        ["tvs", "稳压二极管", "mosfet"],
    ),
    "crystal": (
        ["晶振", "晶体", "谐振器", "crystal", "resonator"],
        ["振荡器", "oscillator", "tcxo", "有源"],
    ),
    "oscillator": (
        ["振荡器", "oscillator", "有源晶振", "tcxo"],
        ["晶振", "晶体", "无源"],
    ),
}


def _norm_text(s):
    return re.sub(r"[\s\-_/]+", "", str(s or "")).lower()


def function_check(name, positive=(), negative=(), family=None):
    """功能符合性检查：用商品名判定「这到底是不是我要的那类器件」。

    返回 (verdict, pos_hits, neg_hits, reason)：
      ok        正向命中且无反向 → 功能对
      mismatch  只命中反向        → 功能不符（参数再好也不能用）
      conflict  正反都命中        → 名称歧义，必须人工/查手册
      unknown   都没命中          → 无法判定（名称只有型号的料很常见，如 HS2950P.M）
    """
    if not positive and not negative and family:
        positive, negative = FUNCTION_FALLBACK.get(family, ((), ()))
    blob = _norm_text(name)
    if not blob:
        return "unknown", [], [], "没有商品名，无法判定功能"
    pos = [k for k in positive if _norm_text(k) and _norm_text(k) in blob]
    neg = [k for k in negative if _norm_text(k) and _norm_text(k) in blob]
    if pos and neg:
        # 正反都命中：谁更"具体"听谁的。「集成TVS的28V/5A过压保护开关」——TVS 是它集成的功能，
        # 器件本身是过压保护开关；而「同步降压转换器」不会同时出现「负载开关」这种正向词。
        p_best, n_best = max(pos, key=len), max(neg, key=len)
        if len(_norm_text(p_best)) > len(_norm_text(n_best)):
            return "ok", pos, neg, f"命中「{p_best}」（同时提到「{n_best}」，属集成的保护功能）"
        if len(_norm_text(p_best)) < len(_norm_text(n_best)):
            return "mismatch", pos, neg, f"命中排除词「{n_best}」——不是目标功能"
        return "conflict", pos, neg, f"名称同时含「{p_best}」与「{n_best}」，功能有歧义"
    if pos:
        return "ok", pos, neg, f"命中「{pos[0]}」"
    if neg:
        return "mismatch", pos, neg, f"命中排除词「{neg[0]}」——不是目标功能"
    return "unknown", pos, neg, "商品名里没有功能描述（只有型号），需查手册或原厂页面"


def extract_params(params):
    """把立创 paramLinkedMap 转成 {物理量: 数值/文本}。"""
    out = {}
    for key, val in (params or {}).items():
        for names, kind in PARAM_FIELDS:
            if any(n in key for n in names):
                if kind == "volt":
                    typ, mx = parse_volt(val)
                    if mx is not None:
                        out.setdefault("volt", mx)
                        out.setdefault("volt_typ", typ)
                elif kind == "text":
                    out.setdefault("text", [])
                    out["text"].append(f"{key}={val}")
                else:
                    v = PARSERS[kind](val)
                    if v is not None:
                        out.setdefault(kind, v)
                out.setdefault("_raw", {})[key] = val
                break
    return out


def parse_need(text, family=None):
    """从 BOM 行文字抽指标。"""
    t = str(text or "")
    out = {"raw": t}
    fam = family or detect_family(t)
    out["family"] = fam
    # 有明确单位才认，避免把型号数字当阻值
    if re.search(NUM + r"\s*[pnuµm]?\s*[Ff]\b", t) or re.search(r"\b(?:p|n|u|µ)f\d*\b", t, re.I):
        out["farad"] = parse_farad(t)
    if re.search(NUM + r"\s*[pnuµm]?\s*[Hh]\b", t):
        out["henry"] = parse_henry(t)
    if re.search(NUM + r"\s*(?:k|K|M|R|r)?\s*(?:Ω|ohms?|欧)\b", t) or re.search(r"\b\d+(?:\.\d+)?\s*[kKmM]\s*(?:Ω|ohm|欧)?(?![A-Za-z])", t):
        v = parse_ohm(t)
        if v is not None:
            out["ohm"] = v
    if re.search(NUM + r"\s*[kM]?V\b", t):
        typ, mx = parse_volt(t)
        if mx is not None:
            out["volt"] = mx
    if re.search(NUM + r"\s*%", t):
        out["tol"] = parse_tol(t)
    if re.search(NUM + r"\s*(?:m|k)?W\b", t):
        out["watt"] = parse_watt(t)
    if re.search(NUM + r"\s*[kMG]?Hz\b", t, re.I):
        out["freq"] = parse_freq(t)
    pkg = parse_package(t)
    if pkg:
        out["pkg"] = pkg
    # 纯数值 BOM 写法：10k / 4.7nF / 1R，无空格无单位
    if "ohm" not in out and re.search(r"\b\d+(?:\.\d+)?[kKmMrR]?\d*\b", t) and re.search(r"\d[kKmMrR]\b", t):
        m = re.search(r"\b(\d+(?:\.\d+)?[kKmMrR])\b", t)
        if m:
            out["ohm"] = parse_ohm(m.group(1))
    for color in ("红", "绿", "蓝", "白", "黄", "橙", "红绿", "RGB"):
        if color in t:
            out["color"] = color
            break
    for die in ("X5R", "X7R", "X7S", "C0G", "NP0", "Y5V", "X6S"):
        if die.lower() in t.lower():
            out["dielectric"] = die.upper()
            break
    # 文字看不出类目时，用「单位 + 封装」反推，保证降额/损耗规则能命中
    if out.get("family") == "unknown":
        if out.get("ohm") is not None:
            out["family"] = "resistor"
        elif out.get("farad") is not None:
            out["family"] = "electrolytic" if (out["farad"] >= 1e-6 and re.search(r"电解|铝|铝壳", t)) else "mlcc"
        elif out.get("henry") is not None:
            out["family"] = "inductor"
        elif out.get("freq") is not None:
            out["family"] = "crystal"
        elif out.get("color"):
            out["family"] = "led"
    return out


REL_TOL = 0.02  # 数值比较的相对容差（2%），用于容差归一后的“同规格”判断


def _cmp_scalar(name, need, got, kind, better="equal"):
    if need is None:
        return None
    if got is None:
        return (name, "?", f"需求 {_fmt(need, kind)} / 候选未标", "unknown")
    a, b = need, got
    rel = abs(a - b) / max(abs(a), 1e-18)
    if better == "at_least":  # 候选 >= 需求 即通过
        if b >= a * (1 - REL_TOL):
            return (name, "✔", f"需求≥{_fmt(need, kind)} / 候选 {_fmt(got, kind)}", "ok")
        return (name, "✘", f"需求≥{_fmt(need, kind)} / 候选仅 {_fmt(got, kind)}", "fail")
    if rel <= REL_TOL:
        return (name, "✔", f"{_fmt(need, kind)} = {_fmt(got, kind)}", "ok")
    return (name, "✘", f"需求 {_fmt(need, kind)} ≠ 候选 {_fmt(got, kind)}", "fail")


def _fmt(v, kind):
    if v is None:
        return "-"
    if kind == "ohm":
        for div, suf in ((1e6, "MΩ"), (1e3, "kΩ")):
            if v >= div:
                return f"{v / div:g}{suf}"
        return f"{v:g}Ω"
    if kind == "farad":
        for div, suf in ((1e-3, "mF"), (1e-6, "uF"), (1e-9, "nF"), (1e-12, "pF")):
            if v >= div * 0.999:
                return f"{v / div:g}{suf}"
        return f"{v:g}F"
    if kind == "henry":
        for div, suf in ((1e-3, "mH"), (1e-6, "uH"), (1e-9, "nH")):
            if v >= div * 0.999:
                return f"{v / div:g}{suf}"
        return f"{v:g}H"
    if kind == "volt":
        return f"{v:g}V"
    if kind == "tol":
        return f"±{v:g}%"
    if kind == "watt":
        return f"{v * 1000:g}mW" if v < 1 else f"{v:g}W"
    if kind == "amp":
        return f"{v * 1000:g}mA" if v < 1 else f"{v:g}A"
    if kind == "freq":
        return f"{v / 1e6:g}MHz" if v >= 1e6 else f"{v / 1e3:g}kHz"
    return str(v)


def verify(need, rec, strict_pkg=True):
    """指标核对。返回 (checks, worst)。

    checks: [(名称, 标记, 说明, 'ok'|'warn'|'fail'|'unknown')]
    worst: 'ok' | 'warn' | 'fail' | 'unknown'
    """
    got = extract_params(rec.get("params") or {})
    fam = need.get("family") or detect_family(rec.get("type"), rec.get("name"))
    checks = []

    def add(res):
        if res is not None:
            name, mark, why, status = res
            checks.append((name, mark, why, status))

    add(_cmp_scalar("阻值", need.get("ohm"), got.get("ohm"), "ohm"))
    add(_cmp_scalar("容值", need.get("farad"), got.get("farad"), "farad"))
    add(_cmp_scalar("电感", need.get("henry"), got.get("henry"), "henry"))
    add(_cmp_scalar("频率", need.get("freq"), got.get("freq"), "freq"))
    if need.get("volt") is not None:
        add(_cmp_scalar("耐压", need["volt"], got.get("volt"), "volt", better="at_least"))
    if need.get("tol") is not None:
        gt = got.get("tol")
        if gt is None:
            checks.append(("精度", "?", f"需求 ±{need['tol']:g}% / 候选未标", "unknown"))
        elif gt <= need["tol"] * 1.0001:
            checks.append(("精度", "✔", f"需求 ±{need['tol']:g}% / 候选 ±{gt:g}%", "ok"))
        else:
            checks.append(("精度", "✘", f"需求 ±{need['tol']:g}% / 候选仅 ±{gt:g}%", "fail"))
    if need.get("watt") is not None:
        add(_cmp_scalar("功率", need["watt"], got.get("watt"), "watt", better="at_least"))
    if need.get("dielectric") and got.get("dielectric"):
        ok = str(need["dielectric"]).upper() in str(got["dielectric"]).upper()
        checks.append(("介质", "✔" if ok else "✘",
                       f"需求 {need['dielectric']} / 候选 {got['dielectric']}",
                       "ok" if ok else "fail"))
    if need.get("color") and got.get("_raw"):
        blob = " ".join(str(v) for v in got["_raw"].values())
        if need["color"] in blob:
            checks.append(("颜色", "✔", f"{need['color']}", "ok"))
    # 封装
    np_ = need.get("pkg")
    rp = rec.get("package")
    GENERIC_PKG = {"SMD", "SMT", "DIP", "直插", "贴片"}
    if np_ and rp:
        a, b = pkg_key(np_), pkg_key(rp)
        if a == b or (a and b and (a.startswith(b) or b.startswith(a))):
            checks.append(("封装", "✔", f"{np_} / {rp}", "ok"))
        elif a in GENERIC_PKG or b in GENERIC_PKG:
            checks.append(("封装", "i", f"需求 {np_} / 候选 {rp}（封装描述过粗，需人工确认尺寸）", "info"))
        else:
            checks.append(("封装", "✘", f"需求 {np_} / 候选 {rp}", "fail"))
    elif np_ and not rp:
        checks.append(("封装", "i", f"需求 {np_} / 候选未标封装", "info"))

    # 未标精度时给提示（不影响判定，避免默默按最低精度成交）
    if need.get("tol") is None and fam in ("resistor", "mlcc", "inductor") and got.get("tol") is not None:
        checks.append(("精度", "i", f"BOM 未标精度，候选 ±{got['tol']:g}%", "info"))

    # 降额提示（只提示，不淘汰候选、不降把握）
    if fam == "mlcc" and got.get("volt") and need.get("volt"):
        if got["volt"] < need["volt"] * 1.25:
            checks.append(("降额", "i", f"MLCC 候选耐压 {got['volt']:g}V 与需求 {need['volt']:g}V 无余量；"
                                         f"按额定 85% 上限使用时应升一档", "info"))
    if fam == "tantalum" and got.get("volt") and need.get("volt"):
        if got["volt"] < need["volt"] * 2:
            checks.append(("降额", "i", "钽电容建议耐压 ≥ 2× 且失效为短路", "info"))

    statuses = [c[3] for c in checks]
    if "fail" in statuses:
        worst = "fail"
    elif "warn" in statuses:
        worst = "warn"
    elif "ok" in statuses:
        worst = "ok"
    else:
        worst = "unknown"
    return checks, worst


def summarize(checks):
    marks = "".join(c[1] for c in checks)
    return marks or "-"


if __name__ == "__main__":  # 自测
    import json
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    samples = [
        ("10k 0603", {"params": {"阻值": "10kΩ", "精度": "±1%", "功率": "100mW"}, "package": "0603", "type": "贴片电阻"}),
        ("10uF 0805 16V X5R", {"params": {"容值": "10uF", "精度": "±10%", "额定电压": "16V", "温度系数": "X5R"}, "package": "0805", "type": "贴片电容(MLCC)"}),
        ("100nF 0603 50V", {"params": {"容值": "10nF", "精度": "±10%", "额定电压": "50V"}, "package": "0603", "type": "贴片电容(MLCC)"}),
        ("8MHz 5032", {"params": {"频率": "8MHz", "负载电容": "20pF"}, "package": "SMD5032-2P", "type": "无源晶振"}),
        ("470uF 10V", {"params": {"容值": "470uF", "额定电压": "6.3V"}, "package": "SMD", "type": "铝电解电容"}),
    ]
    for text, rec in samples:
        need = parse_need(text)
        checks, worst = verify(need, rec)
        print(f"{text:22s} → {worst:5s} {summarize(checks)}")
        for c in checks:
            print("    ", c)
        print("    need:", json.dumps({k: v for k, v in need.items() if k != 'raw'}, ensure_ascii=False))
