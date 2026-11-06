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
  python scripts/blacklist.py check "Tokmas(托克马斯)"
  python scripts/blacklist.py import entries.yaml --kind shop --authorized "傅师傅 2026-11-06"
  python scripts/blacklist.py add "Tokmas(托克马斯)" --kind brand --reason "批次一致性差" --authorized "傅师傅 2026-11-06"
  python scripts/blacklist.py remove "Tokmas(托克马斯)" --kind brand --authorized "傅师傅 2026-11-06"

写入门禁：
  黑名单是**采购策略事实**，不是演示数据。所有写操作（add / remove / import）都必须带
  `--authorized "<谁 / 什么时候 / 为什么>"`，缺了直接拒绝；授权说明写进条目的 `authorized` 字段。
  **不要手工编辑 YAML** —— 走 `import`（校验 schema、去重、补审计字段）。单测/演示只用虚构名字。

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
        "# 维护：python scripts/blacklist.py import|add|remove|list|check（写操作需 --authorized）\n"
        "# 不要手工编辑本文件：走 import 接口，它会补 added/source/authorized 审计字段\n"
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
_AUTH_HINT = (
    "写操作需要用户授权：加 --authorized \"<谁 / 什么时候 / 为什么>\"，"
    "例如 --authorized \"傅师傅 2026-11-06 指定 Tokmas 拉黑\"。\n"
    "黑名单是采购策略事实，未经授权的条目不允许写入（也不要手工编辑 YAML）。"
)


def _require_auth(authorized) -> str:
    """写入门禁：没有授权说明就拒绝。"""
    text = (authorized or "").strip()
    if not text:
        raise PermissionError(_AUTH_HINT)
    return text


def add(name, kind="brand", reason="", source="", aliases=None, path=None, authorized="") -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind 必须是 {KINDS}")
    if not (name or "").strip():
        raise ValueError("name 不能为空")
    auth = _require_auth(authorized)
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
            e["authorized"] = auth
            save(data, path)
            return e
    entry = {"name": name.strip(), "aliases": list(aliases or []),
             "reason": reason, "added": date.today().isoformat(),
             "source": source, "authorized": auth}
    data[key].append(entry)
    save(data, path)
    return entry


def remove(name, kind="brand", path=None, authorized="") -> bool:
    _require_auth(authorized)
    data = load(path)
    key = _KIND_KEY[kind]
    before = len(data[key])
    data[key] = [e for e in data[key] if norm(e.get("name")) != norm(name)]
    ok = len(data[key]) != before
    if ok:
        save(data, path)
    return ok


def _rows_from_file(file, kind="brand"):
    """把导入文件读成 [(kind, {name, aliases, reason}), ...]。

    支持三种形态：
      1. 完整名单文档（brands / shops / codes 三组）—— 忽略 kind 参数；
      2. 条目列表 `[{name: ..., aliases: [...], reason: ...}, ...]` 或纯字符串列表；
      3. 每行一个名字的文本（.txt / .csv）。
    """
    p = Path(file)
    if not p.exists():
        raise FileNotFoundError(f"导入文件不存在：{p}")
    suffix = p.suffix.lower()
    text = p.read_text(encoding="utf-8")
    if suffix in (".yaml", ".yml", ".json"):
        raw = (yaml.safe_load(text) if suffix != ".json" else json.loads(text)) or {}
        if isinstance(raw, dict) and any(k in raw for k in ("brands", "shops", "codes")):
            rows = []
            for k, key in _KIND_KEY.items():
                for e in raw.get(key) or []:
                    rows.append((k, e if isinstance(e, dict) else {"name": str(e)}))
            return rows
        items = raw if isinstance(raw, list) else [raw]
        return [(kind, e if isinstance(e, dict) else {"name": str(e)}) for e in items if e]
    # 纯文本：每行一个名字，允许行内 `#` 注释
    rows = []
    for line in text.splitlines():
        name = line.split("#", 1)[0].strip().lstrip("-").strip()
        if name:
            rows.append((kind, {"name": name}))
    return rows


def import_entries(rows, source="", authorized="", path=None, dry_run=False) -> dict:
    """批量导入（唯一推荐入口）：校验 + 去重 + 补审计字段。

    返回 {"added": [...], "updated": [...], "skipped": [...], "dry_run": bool}。
    """
    auth = _require_auth(authorized)
    data = load(path)
    added, updated, skipped = [], [], []
    for kind, raw in rows:
        if kind not in KINDS:
            skipped.append({"name": str(raw), "why": f"kind 非法：{kind}"})
            continue
        name = (raw.get("name") or "").strip() if isinstance(raw, dict) else str(raw).strip()
        if not name:
            skipped.append({"name": "", "why": "name 为空"})
            continue
        aliases = [a for a in (raw.get("aliases") or []) if str(a).strip()] if isinstance(raw, dict) else []
        reason = (raw.get("reason") or "") if isinstance(raw, dict) else ""
        key = _KIND_KEY[kind]
        hit = next((e for e in data[key] if norm(e.get("name")) == norm(name)), None)
        if hit is None:
            data[key].append({"name": name, "aliases": aliases, "reason": reason,
                              "added": date.today().isoformat(),
                              "source": source, "authorized": auth})
            added.append(f"{KIND_CN[kind]}:{name}")
            continue
        changed = False
        hit.setdefault("aliases", [])
        for a in aliases:
            if norm(a) not in [norm(x) for x in hit["aliases"]]:
                hit["aliases"].append(a)
                changed = True
        if reason and hit.get("reason") != reason:
            hit["reason"] = reason
            changed = True
        if hit.get("authorized") != auth:
            hit["authorized"] = auth
            changed = True
        (updated if changed else skipped).append(f"{KIND_CN[kind]}:{name}")
    if not dry_run and (added or updated):
        save(data, path)
    return {"added": added, "updated": updated, "skipped": skipped, "dry_run": dry_run}


def import_file(file, kind="brand", source="", authorized="", path=None, dry_run=False) -> dict:
    return import_entries(_rows_from_file(file, kind), source=source,
                          authorized=authorized, path=path, dry_run=dry_run)


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
            print(f"      授权: {e.get('authorized') or '（未记录，历史条目）'}")
    print(f"\n合计 {total} 条。维护走 `blacklist.py import|add|remove --authorized \"<授权说明>\"`，不要手工编辑 YAML。")


# --------------------------------------------------------------------------- CLI
def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(prog="blacklist.py", description="品牌 / 店铺 / 料号 黑名单")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="列出全部黑名单")
    p.add_argument("--json", help="输出 JSON 到文件")

    p = sub.add_parser("add", help="加入黑名单（需 --authorized）")
    p.add_argument("name")
    p.add_argument("--kind", choices=KINDS, default="brand")
    p.add_argument("--reason", default="")
    p.add_argument("--source", default="")
    p.add_argument("--alias", action="append", default=[], help="可多个")
    p.add_argument("--authorized", default="", help="谁/什么时候/为什么授权（必填）")

    p = sub.add_parser("import", help="批量导入黑名单（推荐入口，需 --authorized）")
    p.add_argument("file", help="YAML/JSON/TXT；YAML 可含 brands/shops/codes 三组")
    p.add_argument("--kind", choices=KINDS, default="brand", help="文件里没有分组时按这个维度导入")
    p.add_argument("--source", default="", help="来源，如 用户指令 2026-11-06")
    p.add_argument("--authorized", default="", help="谁/什么时候/为什么授权（必填）")
    p.add_argument("--dry-run", action="store_true", help="只报告，不落盘")
    p.add_argument("--json", action="store_true", help="输出 JSON 汇总")

    p = sub.add_parser("remove", help="从黑名单移除（需 --authorized）")
    p.add_argument("name")
    p.add_argument("--kind", choices=KINDS, default="brand")
    p.add_argument("--authorized", default="", help="谁/什么时候/为什么授权（必填）")

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
        try:
            e = add(a.name, a.kind, a.reason, a.source, a.alias, authorized=a.authorized)
        except PermissionError as e:
            print(str(e), file=sys.stderr)
            return 2
        print(f"已加入{KIND_CN[a.kind]}黑名单：{e.get('name')}（别名 {e.get('aliases') or '—'}）")
        return 0

    if a.cmd == "import":
        try:
            res = import_file(a.file, a.kind, a.source, a.authorized, dry_run=a.dry_run)
        except PermissionError as e:
            print(str(e), file=sys.stderr)
            return 2
        except (FileNotFoundError, ValueError) as e:
            print(f"[失败] {e}", file=sys.stderr)
            return 1
        if a.json:
            print(json.dumps(res, ensure_ascii=False, indent=1))
            return 0
        tag = "（dry-run，未落盘）" if res["dry_run"] else ""
        print(f"导入完成{tag}：新增 {len(res['added'])}、更新 {len(res['updated'])}、跳过 {len(res['skipped'])}")
        for k, rows in (("新增", res["added"]), ("更新", res["updated"]), ("跳过", res["skipped"])):
            for r in rows:
                print(f"  {k}: {r}")
        return 0

    if a.cmd == "remove":
        try:
            ok = remove(a.name, a.kind, authorized=a.authorized)
        except PermissionError as e:
            print(str(e), file=sys.stderr)
            return 2
        if ok:
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
