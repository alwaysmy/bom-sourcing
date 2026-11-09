# -*- coding: utf-8 -*-
"""品牌背调档案（brand dossier）—— 把「这个牌子能不能用」做成可复核的证据链。

为什么需要它
------------
`data/knowledge/vendors.yaml` 的品牌分层是靠**立创料号反推**得来的（看它卖什么、卖多贵、
横跨多少不相关品类）。这条路子有硬缺陷：只在立创上卖冷门料的品牌（例如只卖 ULN2803
达林顿阵列的 Tokmas）永远进不了采样集合，于是被当成"不存在"。

真正能回答"这牌子行不行"的材料在站外：**工商主体、是否自有产线、商标归属、授权代理、
官网产品线、社区口碑、翻新/假货投诉**。本模块把这些材料按固定结构收进档案，并且：

1. 每条材料必须带 `channel` + `url` + `grade`（fact / claim / inference）+ `confidence`；
2. `grade` 的语义是硬的：`fact` = 可复核的客观事实（工商、商标、官网产品线、授权公告），
   `claim` = 对方自己的宣传（"年销售额 6 亿美元"），`inference` = 我们根据事实推的结论；
3. 结论必须能溯源到 `evidence[]` 里的条目，`gaps[]` 显式列出没查到的东西；
4. `tier_from_evidence()` 只按证据给**建议** tier，人工可覆盖，但覆盖要写理由。

用法
----
    python brand_dossier.py new 12489 --name "Tokmas(托克马斯)" --alias 托克马斯 --alias TOKMAS
    python brand_dossier.py add 12489 --channel qcc_ic --url "https://..." \
        --claim "广州托克马斯电子有限公司，官网 tokmas.com" --grade fact --confidence high
    python brand_dossier.py add 12489 --channel agent_site --url "http://www.olasshop.com/..." \
        --claim "宣称 1995 年成立、年销售额 6 亿美元" --grade claim --confidence low
    python brand_dossier.py tier 12489          # 打印建议 tier 与依据
    python brand_dossier.py show 12489          # 人读摘要
    python brand_dossier.py render 12489        # 输出 Markdown
    python brand_dossier.py list
    python brand_dossier.py validate 12489

档案落在 `data/knowledge/brands.dossier/<lcsc_brand_id>-<slug>.yaml`。
写操作遵守与 blacklist.py 相同的门禁：**新增/修改品牌结论必须带 --authorized**。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

SCHEMA = "bom-sourcing/knowledge/brand-dossier"
VERSION = 1

# 取证渠道：顺序即「可信度优先级」，同一条结论有多个渠道时取排前的
CHANNELS = {
    "official_site": "品牌官网（自有域名、产品线、公司介绍）",
    "official_doc": "官方文档 / 数据手册 / 认证证书（RoHS/REACH/AEC-Q/UL）",
    "trademark": "商标注册公告（国家知识产权局 / CIPO / USPTO 等）",
    "business_registry": "工商登记（企查查 / 天眼查 / 爱企查 / 国家企业信用信息公示系统）",
    "authorized_dist": "授权代理公告（原厂或代理商的正式签约稿）",
    "qcc_ic": "IC 资料站（114ic / icpdf / 立创品牌页等有编辑维护的目录站）",
    "lcsc_brand_page": "立创商城品牌页（料号规模、品类分布）",
    "distributor_page": "分销商商品页（bomman / 锐单 / 圣禾堂等）",
    "community": "社区口碑（知乎 / 贴吧 / B站 / CSDN / 立创社区 / EEVblog）",
    "complaint": "质量投诉 / 翻新料 / 假货报告",
    "agent_site": "代理商或店铺自述（营销文案，只能作 claim）",
    "inference": "本仓推论（由上面的事实推出，不是检索到的）",
}

# 这些渠道天然只能给 claim（自述），不能当 fact
CLAIM_ONLY = {"agent_site", "community"}

GRADES = ("fact", "claim", "inference")
CONFIDENCES = ("high", "medium", "low")

TIER_ORDER = ["original_idm", "original_fabless", "domestic_second", "trader", "unknown"]

TIER_RULES = {
    "original_idm": "检索到自有晶圆/封测产线证据（官网产线介绍、工厂地址、认证证书）",
    "original_fabless": "检索到自有品牌 + 明确代工模式（fabless），或原厂官网/商标在自有实体名下",
    "domestic_second": "国产二线：有品牌与型号体系，但公开资料少、无产线证据，价格显著低于一线",
    "trader": "只有分销/贸易页面，无自有品牌资料；同型号挂多个不同品牌",
    "unknown": "除立创料号外没有任何独立资料",
}


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _dir(path: str | None = None) -> Path:
    d = Path(path) if path else (_root() / "data" / "knowledge" / "brands.dossier")
    d.mkdir(parents=True, exist_ok=True)
    return d


def slug(text: str) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "-", text or "").strip("-").lower()
    return s or "brand"


def _need_yaml() -> None:
    if yaml is None:
        raise SystemExit("需要 pyyaml：pip install pyyaml")


def _auth(value: str | None) -> str:
    if not value or not value.strip():
        raise PermissionError(
            "品牌结论属于知识库写操作，必须带 --authorized \"<谁/什么时候/为什么>\"："
            "只有用户明确指定的品牌核查才能落库。"
        )
    return value.strip()


# ---------------------------------------------------------------------------
# 读写
# ---------------------------------------------------------------------------
def path_for(brand_id, name: str = "", directory: str | None = None) -> Path:
    d = _dir(directory)
    if brand_id in (None, "", 0, "0"):
        return d / f"{slug(name)}.yaml"
    hits = sorted(d.glob(f"{brand_id}-*.yaml"))
    if hits:
        return hits[0]
    return d / f"{brand_id}-{slug(name or str(brand_id))}.yaml"


def load(brand_id, directory: str | None = None):
    _need_yaml()
    p = path_for(brand_id, directory=directory)
    if not p.exists():
        raise SystemExit(f"档案不存在：{p}（先用 new 建）")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def save(doc, directory: str | None = None) -> Path:
    _need_yaml()
    doc["generated"] = str(date.today())
    p = path_for(doc["brand"].get("lcsc_brand_id"), doc["brand"].get("name_lcsc", ""), directory)
    p.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def new(brand_id, name: str, aliases=None, directory: str | None = None, authorized: str | None = None):
    auth = _auth(authorized)
    doc = {
        "schema": SCHEMA,
        "version": VERSION,
        "generated": str(date.today()),
        "brand": {
            "lcsc_brand_id": int(brand_id) if str(brand_id).isdigit() else brand_id,
            "name_lcsc": name,
            "aliases": list(aliases or []),
            "legal_entity": None,
            "website": None,
            "country": None,
            "tier_suggested": "unknown",
            "tier_final": None,
            "tier_override_reason": None,
            "confidence": "low",
            "authorized": auth,
        },
        "evidence": [],
        "gaps": [],
        "conclusion": "",
    }
    save(doc, directory)
    return doc


def add_evidence(brand_id, channel: str, url: str, claim: str,
                 grade: str = "fact", confidence: str = "medium",
                 note: str = "", directory: str | None = None,
                 authorized: str | None = None):
    _auth(authorized)
    if channel not in CHANNELS:
        raise SystemExit(f"未知渠道 {channel!r}，可用：{', '.join(CHANNELS)}")
    if grade not in GRADES:
        raise SystemExit(f"grade 只能是 {GRADES}")
    if confidence not in CONFIDENCES:
        raise SystemExit(f"confidence 只能是 {CONFIDENCES}")
    if channel in CLAIM_ONLY and grade == "fact":
        raise SystemExit(f"渠道 {channel} 是自述材料，只能记 claim，不能记 fact")
    doc = load(brand_id, directory)
    doc.setdefault("evidence", []).append({
        "channel": channel,
        "url": url,
        "claim": claim.strip(),
        "grade": grade,
        "confidence": confidence,
        "note": note.strip() or None,
        "fetched": str(date.today()),
    })
    save(doc, directory)
    return doc


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------
def tier_from_evidence(doc) -> tuple[str, list[str]]:
    """按证据给建议 tier。只认 fact 级证据；claim 只降低 confidence，不升 tier。"""
    ev = [e for e in doc.get("evidence", []) if e.get("grade") == "fact"]
    channels = {e["channel"] for e in ev}
    why: list[str] = []

    has_fab = any("产线" in (e.get("claim") or "") or "工厂" in (e.get("claim") or "")
                  or "封装厂" in (e.get("claim") or "") for e in ev)
    if "official_site" in channels and has_fab and "official_doc" in channels:
        why.append("官网+认证证书显示自有产线")
        return "original_idm", why

    fabless = any("代工" in (e.get("claim") or "") or "fabless" in (e.get("claim") or "").lower()
                  or "流片" in (e.get("claim") or "") for e in ev)
    brand_owned = {"official_site", "trademark", "business_registry"} & channels
    if fabless or (brand_owned and "authorized_dist" in channels):
        why.append("自有品牌 + 代工/授权代理证据")
        return "original_fabless", why

    if brand_owned:
        why.append("有自有品牌资料（官网/商标/工商），但无产线或代工模式证据")
        return "domestic_second", why

    if {"lcsc_brand_page", "distributor_page"} & channels:
        why.append("只有目录站/分销页，没有独立品牌资料")
        return "trader", why

    why.append("除立创料号外无独立资料")
    return "unknown", why


def confidence_from_evidence(doc) -> str:
    ev = doc.get("evidence", [])
    facts = [e for e in ev if e.get("grade") == "fact"]
    if len(facts) >= 3 and len({e["channel"] for e in facts}) >= 3:
        return "high"
    if len(facts) >= 2:
        return "medium"
    return "low"


def refresh(brand_id, directory: str | None = None, authorized: str | None = None):
    _auth(authorized)
    doc = load(brand_id, directory)
    tier, why = tier_from_evidence(doc)
    doc["brand"]["tier_suggested"] = tier
    doc["brand"]["confidence"] = confidence_from_evidence(doc)
    doc["brand"]["tier_basis"] = why
    if not doc["brand"].get("tier_final"):
        doc["brand"]["tier_final"] = tier
    save(doc, directory)
    return doc


def validate(doc) -> list[str]:
    errs: list[str] = []
    if doc.get("schema") != SCHEMA:
        errs.append(f"schema 应为 {SCHEMA}")
    b = doc.get("brand") or {}
    for k in ("lcsc_brand_id", "name_lcsc", "tier_suggested", "confidence"):
        if k not in b:
            errs.append(f"brand.{k} 缺失")
    if b.get("tier_suggested") not in TIER_ORDER:
        errs.append(f"tier_suggested 非法：{b.get('tier_suggested')}")
    if b.get("confidence") not in CONFIDENCES:
        errs.append(f"confidence 非法：{b.get('confidence')}")
    ev = doc.get("evidence") or []
    if not ev:
        errs.append("evidence 为空：没有证据就没有结论")
    seen = set()
    for i, e in enumerate(ev):
        tag = f"evidence[{i}]"
        if e.get("channel") not in CHANNELS:
            errs.append(f"{tag}.channel 非法：{e.get('channel')}")
        if e.get("grade") not in GRADES:
            errs.append(f"{tag}.grade 非法：{e.get('grade')}")
        if e.get("confidence") not in CONFIDENCES:
            errs.append(f"{tag}.confidence 非法：{e.get('confidence')}")
        if not (e.get("url") or "").startswith("http"):
            errs.append(f"{tag}.url 必须是 http(s) 链接（结论要可复核）")
        if not e.get("claim"):
            errs.append(f"{tag}.claim 不能为空")
        key = (e.get("url"), e.get("claim"))
        if key in seen:
            errs.append(f"{tag} 重复")
        seen.add(key)
        if e.get("channel") in CLAIM_ONLY and e.get("grade") == "fact":
            errs.append(f"{tag} 渠道 {e['channel']} 只能记 claim")
    if not (doc.get("conclusion") or "").strip():
        errs.append("conclusion 为空：档案要有一句结论")
    return errs


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------
GRADE_MARK = {"fact": "检索事实", "claim": "自述材料", "inference": "推论"}


def render_md(doc) -> str:
    b = doc["brand"]
    ev = doc.get("evidence", [])
    out = [f"# {b['name_lcsc']} —— 品牌背调档案", ""]
    out.append(f"- 立创品牌 id：`{b.get('lcsc_brand_id')}`")
    out.append(f"- 工商主体：{b.get('legal_entity') or '**未查到**'}")
    out.append(f"- 官网：{b.get('website') or '**未查到**'}")
    out.append(f"- 机械判定（仅按证据关键词，可能偏保守）：`{b.get('tier_suggested')}`（把握 {b.get('confidence')}）")
    if b.get("tier_final") and b["tier_final"] != b.get("tier_suggested"):
        out.append(f"- 人工覆盖：`{b['tier_final']}` —— {b.get('tier_override_reason') or '未写理由'}")
    out.append(f"- 取证时间：{doc.get('generated')}")
    out.append("")
    if b.get("tier_basis"):
        out.append("判定依据：")
        out += [f"- {x}" for x in b["tier_basis"]]
        out.append("")

    out.append("## 证据链")
    out.append("")
    out.append("| # | 渠道 | 结论 | 等级 | 把握 | 来源 |")
    out.append("|---|------|------|------|------|------|")
    for i, e in enumerate(ev, 1):
        claim = (e["claim"] or "").replace("|", "\\|")
        out.append(f"| {i} | {CHANNELS.get(e['channel'], e['channel'])} | {claim} | "
                   f"{GRADE_MARK.get(e['grade'], e['grade'])} | {e['confidence']} | {e['url']} |")
    out.append("")

    facts = [e for e in ev if e.get("grade") == "fact"]
    claims = [e for e in ev if e.get("grade") == "claim"]
    infers = [e for e in ev if e.get("grade") == "inference"]
    out.append("## 分级说明")
    out.append("")
    out.append(f"- **检索事实** {len(facts)} 条：可点开链接复核，直接支撑结论。")
    out.append(f"- **自述材料** {len(claims)} 条：品牌方/代理商自己的说法，只能当背景。")
    out.append(f"- **推论** {len(infers)} 条：由上面事实推出，不是检索到的；结论若只靠推论，必须写进 gaps。")
    out.append("")

    if doc.get("gaps"):
        out.append("## 没查到的（gaps）")
        out.append("")
        out += [f"- {g}" for g in doc["gaps"]]
        out.append("")

    if doc.get("conclusion"):
        out.append("## 结论")
        out.append("")
        out.append(doc["conclusion"].strip())
        out.append("")

    out.append("---")
    out.append("")
    out.append("> 本档案只回答「品牌可信度 / 主体是否可追溯」，不回答「这颗料参数够不够」——"
               "参数核对见 `data/spec-rules.yaml` 与 `pick.py`。")
    return "\n".join(out) + "\n"


def show(doc) -> str:
    b = doc["brand"]
    lines = [f"{b['name_lcsc']}  (id {b.get('lcsc_brand_id')})",
             f"  主体: {b.get('legal_entity') or '未查到'}",
             f"  官网: {b.get('website') or '未查到'}",
             f"  分层: {b.get('tier_suggested')}  (把握 {b.get('confidence')})"]
    if b.get("tier_final") and b["tier_final"] != b.get("tier_suggested"):
        lines.append(f"  覆盖: {b['tier_final']} —— {b.get('tier_override_reason')}")
    lines.append(f"  证据: {len(doc.get('evidence') or [])} 条"
                 f"（事实 {sum(1 for e in doc.get('evidence') or [] if e['grade']=='fact')} / "
                 f"自述 {sum(1 for e in doc.get('evidence') or [] if e['grade']=='claim')} / "
                 f"推论 {sum(1 for e in doc.get('evidence') or [] if e['grade']=='inference')}）")
    if doc.get("gaps"):
        lines.append(f"  gaps: {len(doc['gaps'])} 条")
    return "\n".join(lines)


def cmd_list(directory: str | None = None) -> str:
    d = _dir(directory)
    files = sorted(d.glob("*.yaml"))
    if not files:
        return "（还没有品牌档案）"
    rows = ["| id | 品牌 | 主体 | 分层 | 把握 | 证据 |", "|----|------|------|------|------|------|"]
    for f in files:
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        b = doc.get("brand", {})
        # 显示最终分层：人工覆盖优先，* 标记与建议分层不同
        tier = b.get("tier_final") or b.get("tier_suggested")
        if b.get("tier_final") and b["tier_final"] != b.get("tier_suggested"):
            tier = f"{tier} *"
        rows.append(f"| {b.get('lcsc_brand_id')} | {b.get('name_lcsc')} | "
                    f"{b.get('legal_entity') or '—'} | {tier} | "
                    f"{b.get('confidence')} | {len(doc.get('evidence') or [])} |")
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="品牌背调档案（证据链 + 建议分层）")
    ap.add_argument("--dir", default=None, help="档案目录（默认 data/knowledge/brands.dossier）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new", help="新建档案")
    p.add_argument("brand_id")
    p.add_argument("--name", required=True)
    p.add_argument("--alias", action="append", default=[])
    p.add_argument("--authorized", default=None)

    p = sub.add_parser("add", help="追加一条证据")
    p.add_argument("brand_id")
    p.add_argument("--channel", required=True, choices=list(CHANNELS))
    p.add_argument("--url", required=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--grade", default="fact", choices=list(GRADES))
    p.add_argument("--confidence", default="medium", choices=list(CONFIDENCES))
    p.add_argument("--note", default="")
    p.add_argument("--authorized", default=None)

    p = sub.add_parser("tier", help="按证据重算建议分层")
    p.add_argument("brand_id")
    p.add_argument("--authorized", default=None)

    p = sub.add_parser("meta", help="设置主体/官网/人工覆盖分层")
    p.add_argument("brand_id")
    p.add_argument("--legal-entity", default=None)
    p.add_argument("--website", default=None)
    p.add_argument("--country", default=None)
    p.add_argument("--tier", default=None, choices=TIER_ORDER, help="人工覆盖分层")
    p.add_argument("--reason", default=None, help="覆盖理由（覆盖必填）")
    p.add_argument("--authorized", default=None)

    p = sub.add_parser("gaps", help="设置 gaps（未查到的东西），每行一条")
    p.add_argument("brand_id")
    p.add_argument("--file", required=True, help="UTF-8 文本文件，每行一个 gap")
    p.add_argument("--authorized", default=None)

    p = sub.add_parser("conclusion", help="设置结论正文")
    p.add_argument("brand_id")
    p.add_argument("--file", required=True, help="UTF-8 文本文件")
    p.add_argument("--authorized", default=None)

    p = sub.add_parser("show", help="人读摘要")
    p.add_argument("brand_id")

    p = sub.add_parser("render", help="输出 Markdown")
    p.add_argument("brand_id")
    p.add_argument("--out", default=None)

    p = sub.add_parser("validate", help="校验档案")
    p.add_argument("brand_id")

    sub.add_parser("list", help="列出全部档案")

    a = ap.parse_args(argv)
    try:
        if a.cmd == "new":
            doc = new(a.brand_id, a.name, a.alias, a.dir, a.authorized)
            print(f"已建：{path_for(a.brand_id, a.name, a.dir)}")
            print(show(doc))
        elif a.cmd == "add":
            doc = add_evidence(a.brand_id, a.channel, a.url, a.claim, a.grade,
                               a.confidence, a.note, a.dir, a.authorized)
            print(f"已追加，共 {len(doc['evidence'])} 条")
        elif a.cmd == "tier":
            doc = refresh(a.brand_id, a.dir, a.authorized)
            b = doc["brand"]
            print(f"建议分层：{b['tier_suggested']}（把握 {b['confidence']}）")
            for w in b.get("tier_basis") or []:
                print(f"  - {w}")
            print(f"  规则：{TIER_RULES[b['tier_suggested']]}")
        elif a.cmd == "meta":
            _auth(a.authorized)
            doc = load(a.brand_id, a.dir)
            b = doc["brand"]
            if a.legal_entity:
                b["legal_entity"] = a.legal_entity
            if a.website:
                b["website"] = a.website
            if a.country:
                b["country"] = a.country
            if a.tier:
                if not a.reason:
                    raise SystemExit("人工覆盖分层必须写 --reason（为什么不信自动判定）")
                b["tier_final"] = a.tier
                b["tier_override_reason"] = a.reason
            save(doc, a.dir)
            print(show(doc))
        elif a.cmd == "gaps":
            _auth(a.authorized)
            doc = load(a.brand_id, a.dir)
            rows = [ln.strip() for ln in Path(a.file).read_text(encoding="utf-8").splitlines() if ln.strip()]
            doc["gaps"] = rows
            save(doc, a.dir)
            print(f"已写入 {len(rows)} 条 gap")
        elif a.cmd == "conclusion":
            _auth(a.authorized)
            doc = load(a.brand_id, a.dir)
            doc["conclusion"] = Path(a.file).read_text(encoding="utf-8").strip()
            save(doc, a.dir)
            print(f"已写入结论（{len(doc['conclusion'])} 字符）")
        elif a.cmd == "show":
            print(show(load(a.brand_id, a.dir)))
        elif a.cmd == "render":
            text = render_md(load(a.brand_id, a.dir))
            if a.out:
                Path(a.out).write_text(text, encoding="utf-8")
                print(f"已写入 {a.out}（{len(text)} 字符）")
            else:
                print(text)
        elif a.cmd == "validate":
            errs = validate(load(a.brand_id, a.dir))
            if errs:
                print("❌ 校验失败：")
                for e in errs:
                    print(f"  - {e}")
                return 1
            print("✅ 校验通过")
        elif a.cmd == "list":
            print(cmd_list(a.dir))
    except PermissionError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
