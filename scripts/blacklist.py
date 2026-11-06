# -*- coding: utf-8 -*-
"""黑名单 / 白名单 —— 把「这个牌子/这家店/这颗料不要」变成可维护、可复现的规则。

为什么单独一层：
  1. 它是**人的判断**，不是从数据里推出来的（数据里只能看到价格和库存）；
  2. 它必须能累积、能追溯（谁加的、什么时候、为什么），不能只活在对话里；
  3. 它要同时管三个维度：品牌（立创 productGradePlateName）、店铺（淘宝/1688 店名）、
     精确料号（C 号 / 型号）。

匹配口径（避免误伤）：
  - 统一小写、去空白、去中英文括号 → `Tokmas(托克马斯)` 与 `tokmas` 视为同一条；
  - 用「别名子串」匹配，不做模糊纠错（`Tokma` 不会命中 `Tokmas`，避免误杀）；
  - 品牌黑名单只挡「品牌」，不挡「型号」：某型号若只有黑名单品牌在卖，会明确提示，
    由人决定是接受还是改料，绝不静默替换。

用法：
  python scripts/blacklist.py list
  python scripts/blacklist.py add "Tokmas(托克马斯)" --kind brand --reason "批次一致性差，用户指定" --alias tokmas
  python scripts/blacklist.py check "Tokmas(托克马斯)"
  python scripts/blacklist.py remove "Tokmas(托克马斯)" --kind brand

文件：data/knowledge/blacklist.yaml（可用环境变量 BOM_BLACKLIST 指向别的文件）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - 环境里一定有 pyyaml（其它脚本也依赖）
    yaml = None

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge" / "blacklist.yaml"

KINDS = ("brand", "shop", "code")
KIND_CN = {"brand": "品牌", "shop": "店铺", "code": "料号"}

_EMPTY = {
    "schema": "bom-sourcing/knowledge/blacklist",
    "version": 1,
    "updated": "",
    "brands": [],
    "shops": [],
    "codes": [],
}
_KIND_KEY = {"brand": "brands", "shop": "shops", "code": "codes"}


# --------------------------------------------------------------------------- 归一
def norm(s) -> str:
    """小写 + 去空白 + 去括号：`Tokmas(托克马斯)` → `tokmas托克马斯`。"""
    if s is None:
        return ""
    t = str(s).lower()
    for ch in (" ", "\t", "\u3000", "(", ")", "（", "）", "【", "】", "[", "]"):
        t = t.replace(ch, "")
    return t


def _aliases(entry) -> list[str]:
    names = [entry.get("name") or ""]
    names.extend(entry.get("aliases") or [])
    return [a for a in (norm(x) for x in names) if a]


# --------------------------------------------------------------------------- 读写
def path_of(path=None) -> Path:
    p = path or os.environ.get("BOM_BLACKLIST") or DEFAULT_PATH
    return Path(p)


def load(path=None) -> dict:
    p = path_of(path)
    if not p.exists():
        return json.loads(json.dumps(_EMPTY))
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out = json.loads(json.dumps(_EMPTY))
    out.update(data)
    for k in ("brands", "shops", "codes"):
        out[k] = out.get(k) or []
    return out


def save(data: dict, path=None) -> Path:
    p = path_of(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data["updated"] = date.today().isoformat()
    header = (
        "# 黑名单 / 白名单（人工维护，可追溯）\n"
        "# 维护：python scripts/blacklist.py add|remove|list|check\n"
        "# 口径：小写、去空白、去括号后按「别名子串」匹配；只挡对应维度，不静默替换型号\n"
    )
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=110)
    p.write_text(header + body, encoding="utf-8")
    return p


# --------------------------------------------------------------------------- 查询
def find(text, kind=None, data=None) -> list[dict]:
    """在 text 里查黑名单命中项；kind=None 表示三个维度都查。"""
    data = data or load()
    t = norm(text)
    if not t:
        return []
    hits = []
    for k in (KINDS if kind is None else (kind,)):
        for e in data.get(_KIND_KEY[k]) or []:
            for a in _aliases(e):
                if a and a in t:
                    hits.append({"kind": k, "name": e.get("name"), "alias": a,
                                 "reason": e.get("reason") or "", "added": e.get("added") or "",
                                 "source": e.get("source") or ""})
                    break
    return hits


def is_blocked(text, kind=None, data=None) -> bool:
    return bool(find(text, kind=kind, data=data))


def check_record(rec, data=None) -> list[dict]:
    """检查一条立创记录（品牌 / 型号 / C 号）。"""
    data = data or load()
    hits = []
    hits.extend(find(rec.get("brand"), "brand", data))
    hits.extend(find(rec.get("model"), "code", data))
    hits.extend(find(rec.get("code"), "code", data))
    return hits


def check_shop(name, data=None) -> list[dict]:
    return find(name, "shop", data)


def filter_records(records, data=None, kind="brand"):
    """按品牌/料号过滤候选；返回 (保留, 剔除[(rec, hits)])。"""
    data = data or load()
    kept, dropped = [], []
    for r in records:
        hits = check_record(r, data)
        if hits:
            dropped.append((r, hits))
        else:
            kept.append(r)
    return kept, dropped


# --------------------------------------------------------------------------- 维护
def add(name, kind="brand", reason="", source="", aliases=None, path=None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind 必须是 {KINDS}")
    if not (name or "").strip():
        raise ValueError("name 不能为空")
    data = load(path)
    key = _KIND_KEY[kind]
    for e in data[key]:
        if norm(e.get("name")) == norm(name):
            e.setdefault("aliases", [])
            for a in (aliases or []):
                if norm(a) not in [norm(x) for x in e["aliases"]]:
                    e["aliases"].append(a)
            if reason:
                e["reason"] = reason
            save(data, path)
            return e
    entry = {"name": name.strip(), "aliases": list(aliases or []),
             "reason": reason, "added": date.today().isoformat(), "source": source}
    data[key].append(entry)
    save(data, path)
    return entry


def remove(name, kind="brand", path=None) -> bool:
    data = load(path)
    key = _KIND_KEY[kind]
    before = len(data[key])
    data[key] = [e for e in data[key] if norm(e.get("name")) != norm(name)]
    ok = len(data[key]) != before
    if ok:
        save(data, path)
    return ok


# --------------------------------------------------------------------------- 渲染
def render(data: dict) -> None:
    print(f"黑名单文件：{path_of()}")
    print(f"更新日期：{data.get('updated') or '—'}")
    total = 0
    for k in KINDS:
        rows = data.get(_KIND_KEY[k]) or []
        total += len(rows)
        print(f"\n## {KIND_CN[k]}（{len(rows)} 条）")
        if not rows:
            print("  （空）")
            continue
        for e in rows:
            alias = "、".join(e.get("aliases") or []) or "—"
            print(f"  - {e.get('name')}")
            print(f"      别名: {alias}")
            print(f"      原因: {e.get('reason') or '—'}")
            print(f"      加入: {e.get('added') or '—'}  来源: {e.get('source') or '—'}")
    print(f"\n合计 {total} 条。文件是唯一事实来源，可直接编辑（YAML）。")


# --------------------------------------------------------------------------- CLI
def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(prog="blacklist.py", description="品牌 / 店铺 / 料号 黑名单")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="列出全部黑名单")
    p.add_argument("--json", help="输出 JSON 到文件")

    p = sub.add_parser("add", help="加入黑名单")
    p.add_argument("name")
    p.add_argument("--kind", choices=KINDS, default="brand")
    p.add_argument("--reason", default="")
    p.add_argument("--source", default="")
    p.add_argument("--alias", action="append", default=[], help="可多个")

    p = sub.add_parser("remove", help="从黑名单移除")
    p.add_argument("name")
    p.add_argument("--kind", choices=KINDS, default="brand")

    p = sub.add_parser("check", help="查一段文字是否命中黑名单")
    p.add_argument("text")
    p.add_argument("--kind", choices=KINDS, default=None)
    p.add_argument("--json", action="store_true")

    a = ap.parse_args(argv)

    if a.cmd == "list":
        data = load()
        if a.json:
            Path(a.json).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"JSON 已写入：{a.json}")
            return 0
        render(data)
        return 0

    if a.cmd == "add":
        e = add(a.name, a.kind, a.reason, a.source, a.alias)
        print(f"已加入{KIND_CN[a.kind]}黑名单：{e.get('name')}（别名 {e.get('aliases') or '—'}）")
        return 0

    if a.cmd == "remove":
        if remove(a.name, a.kind):
            print(f"已移除：{a.name}")
            return 0
        print(f"没找到：{a.name}", file=sys.stderr)
        return 1

    if a.cmd == "check":
        hits = find(a.text, a.kind)
        if a.json:
            print(json.dumps(hits, ensure_ascii=False, indent=1))
        elif hits:
            for h in hits:
                print(f"命中 {KIND_CN[h['kind']]}：{h['name']}（别名 {h['alias']}）{h['reason']}")
        else:
            print("未命中")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
