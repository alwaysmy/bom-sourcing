# -*- coding: utf-8 -*-
"""功率电子开关的功能判据（反向电流阻断等）—— 立创参数表里查不到，只能查手册后登记。

为什么单独一个模块：立创 `paramLinkedMap` 对 `功率电子开关` 只给 类型 / 工作电压 /
通道数 / 输入控制逻辑 / 最大连续电流 / 导通电阻，"反向电流阻断"根本没有这个键。
而这一项**直接决定板子会不会倒灌**（V(OUT) > V(IN) 时电流反向），所以必须：
  1. 有人把结论登记进 `data/knowledge/load-switch.yaml`（带 grade 与 basis）；
  2. `pick.py` 按「用户提了要求 → 筛选；没提 → 标注」两套语义使用它。

命令：
  python loadswitch.py list                      # 已登记料号
  python loadswitch.py classes                   # 器件类别默认能力表
  python loadswitch.py check C47345802           # 查一颗（C号或型号）
  python loadswitch.py infer "过压保护开关 LP5280" # 按名称/型号猜类别（只给提示，不当结论）
  python loadswitch.py add C47345802 --model LP5280SHVF --class ovp_switch \
      --reverse-block no --grade fact --basis "手册 Rev1.5 §OTG…" --authorized "谁/何时/为什么"
  python loadswitch.py validate

写操作需要 `--authorized`（与 blacklist / whitelist / brand_dossier 同一套门禁）。
"""
import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "data" / "knowledge" / "load-switch.yaml"

SCHEMA = "bom-sourcing/knowledge/load-switch"
VERSION = 1
GRADES = ("fact", "claim", "inference")
RB_VALUES = ("yes", "no", "unknown")
CLASS_KEYS = ("load_switch_single", "load_switch_b2b", "efuse", "ovp_switch",
              "ideal_diode", "oring_controller", "hotswap")

# 类别推断用的名称词表（只给提示，不是结论）
CLASS_HINTS = [
    ("efuse", ("efuse", "e-fuse", "电子保险丝", "电子熔断")),
    ("ideal_diode", ("ideal diode", "理想二极管", "oring", "or-ing")),
    ("ovp_switch", ("ovp", "过压保护", "over-voltage protection", "过压钳位")),
    ("hotswap", ("hot swap", "hotswap", "热插拔")),
    ("load_switch_b2b", ("reverse current blocking", "反向电流阻断", "背对背", "back-to-back")),
    ("load_switch_single", ("load switch", "负载开关", "电源分配开关")),
]

_AUTH_HINT = ("写操作必须带 --authorized \"<谁/什么时候/为什么>\"；"
              "知识库条目会被下游 pick.py 直接用于筛选，不能随手改")


def _auth(value):
    if not value or not str(value).strip():
        raise PermissionError(_AUTH_HINT)


def path_of(path=None):
    return Path(path or os.environ.get("BOM_LOADSWITCH") or DEFAULT_PATH)


def load(path=None):
    p = path_of(path)
    if not p.exists():
        return {"schema": SCHEMA, "version": VERSION, "parts": {}}
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"schema": SCHEMA, "version": VERSION, "parts": {}}


def save(data, path=None):
    p = path_of(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data.setdefault("schema", SCHEMA)
    data.setdefault("version", VERSION)
    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, width=200)
    return p


def norm_model(s):
    """型号归一：大写、去空格与常见分隔符，用于「同型号不同封装/后缀」的比对。"""
    return re.sub(r"[^0-9A-Z]", "", str(s or "").upper())


def classes(data=None):
    data = data if data is not None else load()
    return {c["key"]: c for c in (data.get("device_classes") or [])}


def infer_class(model="", name=""):
    """按型号/商品名猜器件类别（只给提示，不参与筛选）。"""
    text = f"{model} {name}".lower()
    for key, words in CLASS_HINTS:
        if any(w in text for w in words):
            return key
    return None


def _find_part(data, key):
    """按 C号精确 → 型号归一等值 → 型号前缀匹配。返回 (part_key, entry)。"""
    parts = data.get("parts") or {}
    k = str(key or "").strip().upper()
    if k in parts:
        return k, parts[k]
    nm = norm_model(key)
    if not nm:
        return None, None
    for k2, e in parts.items():
        if norm_model(e.get("model")) == nm:
            return k2, e
    # 前缀：查 TPS25947 时能命中 TPS259470ARPWR（只在唯一命中时给结论）
    hits = [(k2, e) for k2, e in parts.items() if norm_model(e.get("model")).startswith(nm)]
    if len(hits) == 1:
        return hits[0]
    return None, None


def lookup(code=None, model=None, data=None):
    """查已登记条目 → dict；查不到返回 None。"""
    data = data if data is not None else load()
    for key in (code, model):
        if not key:
            continue
        k, e = _find_part(data, key)
        if e:
            return dict(e, part_key=k)
    return None


def reverse_block(code=None, model=None, name="", data=None):
    """返回反向电流阻断的判定：

    {value: yes|no|unknown, grade: fact|claim|inference|None, basis, class, known: bool}
    `known` = 知识库里有这条记录（不论 grade）；筛选时要求 value=="yes" 且 grade=="fact"。
    """
    data = data if data is not None else load()
    e = lookup(code=code, model=model, data=data)
    if e:
        return {"value": str(e.get("reverse_block") or "unknown"),
                "grade": e.get("grade"), "basis": e.get("basis"),
                "class": e.get("class"), "known": True,
                "part_key": e.get("part_key"), "checked": e.get("checked")}
    cls = infer_class(model=model or "", name=name)
    cdef = (classes(data).get(cls) or {}) if cls else {}
    return {"value": "unknown", "grade": None, "basis": None, "class": cls,
            "known": False, "class_default": cdef.get("reverse_block_default"),
            "class_label": cdef.get("label_cn")}


def add(code, model=None, cls=None, reverse="unknown", grade="fact", basis=None,
        brand=None, source="datasheet", path=None, authorized=None):
    """登记一条（或更新）。grade 必须是 GRADES；reverse 必须是 RB_VALUES。"""
    _auth(authorized)
    if reverse not in RB_VALUES:
        raise ValueError(f"reverse_block 只能是 {RB_VALUES}")
    if grade not in GRADES:
        raise ValueError(f"grade 只能是 {GRADES}")
    if grade == "fact" and not basis:
        raise ValueError("grade=fact 必须写 --basis（手册哪一节怎么说）")
    key = str(code or "").strip().upper()
    if not re.match(r"^C\d+$", key):
        raise ValueError("C 号形如 C47345802")
    data = load(path)
    entry = data.setdefault("parts", {}).get(key) or {}
    entry.update({
        "model": model or entry.get("model"),
        "class": cls or entry.get("class") or infer_class(model or ""),
        "reverse_block": reverse,
        "grade": grade,
        "basis": basis or entry.get("basis"),
        "source": source or entry.get("source"),
        "checked": date.today().isoformat(),
        "authorized": authorized,
    })
    if brand:
        entry["brand"] = brand
    data["parts"][key] = entry
    save(data, path)
    return entry


def validate(data=None):
    data = data if data is not None else load()
    errs = []
    if data.get("schema") != SCHEMA:
        errs.append(f"schema 应为 {SCHEMA}，实际 {data.get('schema')!r}")
    ck = classes(data)
    for k, e in (data.get("parts") or {}).items():
        if not re.match(r"^C\d+$", k):
            errs.append(f"{k}: 键必须是 C 号")
        if not e.get("model"):
            errs.append(f"{k}: 缺 model")
        if e.get("reverse_block") not in RB_VALUES:
            errs.append(f"{k}: reverse_block 非法 {e.get('reverse_block')!r}")
        if e.get("grade") not in GRADES:
            errs.append(f"{k}: grade 非法 {e.get('grade')!r}")
        if e.get("grade") == "fact" and not e.get("basis"):
            errs.append(f"{k}: grade=fact 必须写 basis")
        if e.get("class") and e.get("class") not in ck:
            errs.append(f"{k}: class {e.get('class')!r} 不在 device_classes 里")
    return errs


def render(data):
    parts = data.get("parts") or {}
    out = [f"| C号 | 型号 | 类别 | 反向阻断 | 证据等级 | 依据 |", "|---|---|---|---|---|---|"]
    mark = {"yes": "✅ 有阻断", "no": "❌ 不阻断", "unknown": "❔ 未核"}
    for k, e in sorted(parts.items(), key=lambda kv: (kv[1].get("class") or "", kv[0])):
        out.append(f"| {k} | {e.get('model') or ''} | {e.get('class') or '-'} | "
                   f"{mark.get(e.get('reverse_block'), e.get('reverse_block'))} | "
                   f"{e.get('grade') or '-'} | {(e.get('basis') or '')[:90]} |")
    return "\n".join(out)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="功率电子开关功能判据（反向电流阻断等）")
    ap.add_argument("--file", default=None, help="知识库路径（默认 data/knowledge/load-switch.yaml）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="已登记料号")
    sub.add_parser("classes", help="器件类别默认能力表")
    sp = sub.add_parser("check", help="查一颗（C 号或型号）")
    sp.add_argument("key")
    sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("infer", help="按型号/名称猜类别（只给提示）")
    sp.add_argument("text")
    sp = sub.add_parser("add", help="登记 / 更新一条")
    sp.add_argument("code")
    sp.add_argument("--model")
    sp.add_argument("--class", dest="cls", choices=CLASS_KEYS)
    sp.add_argument("--reverse-block", dest="reverse", choices=RB_VALUES, default="unknown")
    sp.add_argument("--grade", choices=GRADES, default="fact")
    sp.add_argument("--basis")
    sp.add_argument("--brand")
    sp.add_argument("--source", default="datasheet")
    sp.add_argument("--authorized")
    sub.add_parser("validate", help="校验知识库")

    a = ap.parse_args(argv)
    try:
        if a.cmd == "list":
            data = load(a.file)
            print(render(data))
            print(f"\n共 {len(data.get('parts') or {})} 条")
            return 0
        if a.cmd == "classes":
            data = load(a.file)
            print("| 类别 | 中文 | 默认反向阻断 | 说明 |")
            print("|---|---|---|---|")
            for k, c in classes(data).items():
                print(f"| {k} | {c.get('label_cn')} | {c.get('reverse_block_default')} | "
                      f"{(c.get('why') or '').replace('|', '/')[:80]} |")
            return 0
        if a.cmd == "check":
            rb = reverse_block(code=a.key if a.key.upper().startswith("C") else None,
                              model=None if a.key.upper().startswith("C") else a.key)
            if a.json:
                print(json.dumps(rb, ensure_ascii=False, indent=1))
                return 0
            label = {"yes": "✅ 有反向阻断", "no": "❌ 不阻断（反向经体二极管导通）",
                     "unknown": "❔ 未核实"}[rb["value"]]
            print(f"{a.key}: {label}")
            if rb.get("known"):
                print(f"  类别: {rb.get('class') or '-'}   证据: {rb.get('grade') or '-'}")
                if rb.get("basis"):
                    print(f"  依据: {rb['basis']}")
                if rb.get("checked"):
                    print(f"  核对: {rb['checked']}")
            else:
                print(f"  知识库无此料；按名称推断类别: {rb.get('class') or '无法判断'}"
                      f"（该类默认反向阻断: {rb.get('class_default') or '不适用'}）")
                print("  → 需要查手册登记：python loadswitch.py add <C号> --reverse-block yes|no "
                      "--grade fact --basis \"手册某节…\" --authorized \"…\"")
            return 0
        if a.cmd == "infer":
            cls = infer_class(a.text)
            data = load(a.file)
            c = classes(data).get(cls) if cls else None
            print(f"推断类别: {cls or '无法判断'}"
                  + (f"（{c.get('label_cn')}，默认反向阻断 {c.get('reverse_block_default')}）" if c else ""))
            if c and c.get("caveats"):
                for x in c["caveats"]:
                    print("  caveat:", x)
            print("  ↑ 只是提示，不是结论 —— 必须查手册后登记")
            return 0
        if a.cmd == "add":
            e = add(a.code, model=a.model, cls=a.cls, reverse=a.reverse, grade=a.grade,
                    basis=a.basis, brand=a.brand, source=a.source, path=a.file,
                    authorized=a.authorized)
            print(f"已登记 {a.code}: {e.get('model')} class={e.get('class')} "
                  f"reverse_block={e.get('reverse_block')} grade={e.get('grade')}")
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
    except PermissionError as e:
        print(f"[拒绝] {e}", file=sys.stderr)
        return 2
    except (ValueError, KeyError) as e:
        print(f"[参数错误] {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
