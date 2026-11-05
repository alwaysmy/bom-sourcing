#!/usr/bin/env python3
"""海外分销商检索（Mouser 贸泽 / DigiKey 得捷）—— 走真浏览器（Kimi WebBridge）。

为什么走浏览器：两站都有反爬（DigiKey 403 Akamai、Mouser 403 DataDome），
纯 HTTP 拿不到；用用户已登录的真实浏览器可以正常读，且不违反站点条款的登录要求。

用法：
    python distributor.py check
    python distributor.py search "TPS25947" --site mouser --limit 5
    python distributor.py search "TPS25947" --site digikey --limit 5
    python distributor.py search "TPS25947" --site both --json out.json

输出：控制台表格 + 可选 JSON。价格是**含税人民币**（Mouser 中国站口径），
DigiKey 中国站同为人民币含税，两者与立创（人民币含税）可直接比。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from taobao import Bridge, BridgeError  # noqa: E402

MOUSER_URL = "https://www.mouser.cn/zh/c/?q={kw}"
DIGIKEY_URL = "https://www.digikey.cn/zh/products/result?keywords={kw}"

MOUSER_JS = r"""
(() => {
  const t = document.querySelector('table.persist-area.SearchResultsTable')
        || document.querySelector('table.SearchResultsTable');
  if (!t) return JSON.stringify({error: 'no result table', title: document.title,
                                 text: (document.body.innerText || '').slice(0, 300)});
  const rows = Array.from(t.querySelectorAll('tbody tr')).map(tr => {
    const tds = Array.from(tr.querySelectorAll('td'));
    const txt = (i) => tds[i] ? (tds[i].innerText || '').replace(/\s+/g, ' ').trim() : '';
    const link = tr.querySelector('a[href*="/ProductDetail/"]');
    return {
      raw_part: txt(2),
      mfr: txt(3),
      desc: txt(4),
      stock: txt(6),
      price: txt(7),
      moq: txt(8),
      url: link ? link.href : ''
    };
  });
  return JSON.stringify({count: rows.length, rows: rows});
})()
"""

DIGIKEY_JS = r"""
(() => {
  const cards = Array.from(document.querySelectorAll('[data-testid="card"]'));
  const cats = cards.map(c => (c.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean);
  const tables = Array.from(document.querySelectorAll('table'));
  const rows = [];
  for (const t of tables) {
    for (const tr of Array.from(t.querySelectorAll('tbody tr'))) {
      const tds = Array.from(tr.querySelectorAll('td')).map(td => (td.innerText || '').replace(/\s+/g, ' ').trim());
      if (tds.length >= 4) rows.push(tds);
    }
  }
  return JSON.stringify({
    title: document.title,
    url: location.href,
    categories: cats.slice(0, 8),
    row_count: rows.length,
    rows: rows.slice(0, 10),
    links: Array.from(document.querySelectorAll('a[href*="/product-detail/"]')).slice(0, 5).map(a => a.href)
  });
})()
"""


DIGIKEY_CAT_JS = r"""
(() => {
  const a = document.querySelector('[data-testid^="category-link-"]')
        || Array.from(document.querySelectorAll('a[href*="/products/"]'))
             .find(x => /product-detail|category|results/.test(x.href) === false && x.innerText.trim());
  return JSON.stringify({href: a ? a.href : '', text: a ? (a.innerText || '').trim().slice(0, 80) : ''});
})()
"""


def _clean_mouser(rows, limit):
    out = []
    for r in rows[:limit]:
        raw = r.get("raw_part", "")
        mpn = ""
        m = re.search(r"制造商零件编号\s*([^\s]+)", raw)
        if m:
            mpn = m.group(1)
        else:
            parts = raw.split()
            mpn = parts[0] if parts else ""
        stock_m = re.search(r"([\d,]+)\s*库存", r.get("stock", ""))
        stock = int(stock_m.group(1).replace(",", "")) if stock_m else None
        prices = []
        for q, p in re.findall(r"(\d[\d,]*)\s*¥\s*([\d.,]+)", r.get("price", "")):
            try:
                prices.append((float(q.replace(",", "")), float(p.replace(",", ""))))
            except ValueError:
                continue
        unit1 = prices[0][1] if prices else None
        out.append({
            "site": "mouser", "mpn": mpn, "mfr": r.get("mfr", ""), "desc": r.get("desc", ""),
            "stock": stock, "unit_price": unit1,
            "ladder": "; ".join(f"{int(q)}只 ¥{p:g}" for q, p in prices[:5]),
            "url": r.get("url", ""), "raw_price": r.get("price", ""),
        })
    return out


def search_mouser(br, kw, limit=8, wait=4.0):
    br.navigate(MOUSER_URL.format(kw=kw), new_tab=False, group_title="配单比价")
    time.sleep(wait)
    data = json.loads(br.evaluate(MOUSER_JS))
    if data.get("error"):
        raise BridgeError(f"Mouser 未拿到结果表：{data.get('error')}（title={data.get('title')}）")
    return _clean_mouser(data.get("rows") or [], limit)


def search_digikey(br, kw, limit=8, wait=4.0):
    """DigiKey 搜索页常先落「品类卡片页」，需要点进品类才出料表。"""
    br.navigate(DIGIKEY_URL.format(kw=kw), new_tab=False, group_title="配单比价")
    time.sleep(wait)
    data = json.loads(br.evaluate(DIGIKEY_JS))
    if not data.get("row_count"):
        cat = br.evaluate(DIGIKEY_CAT_JS)
        cat = json.loads(cat) if isinstance(cat, str) else (cat or {})
        href = (cat.get("href") or "").strip()
        if not href:
            raise BridgeError(
                "DigiKey 既没有料表也没有品类链接：" f"{data.get('categories')}；URL={data.get('url')}")
        br.navigate(href, new_tab=False, group_title="配单比价")
        time.sleep(wait)
        data = json.loads(br.evaluate(DIGIKEY_JS))
        if not data.get("row_count"):
            raise BridgeError(f"DigiKey 点进品类后仍无料表（URL={data.get('url')}）")
    out = []
    for tds in (data.get("rows") or [])[:limit]:
        blob = " ".join(c for c in tds if c).strip()
        # DigiKey 把「型号 + 描述 + 品牌」放在同一个 td 里，只能按模式拆
        mpn_m = re.search(r"\b([A-Z][A-Z0-9]{1,}[A-Z0-9\-/]{2,})\b", blob)
        stock_m = re.search(r"([\d,]+)\s*(?:现货|库存|In\s*Stock)", blob)
        price_m = re.search(r"¥\s*([\d.,]+)", blob)
        mpn = mpn_m.group(1) if mpn_m else ""
        rest = blob.replace(mpn, "", 1)
        for pat in (r"[\d,]+\s*(?:现货|库存|In\s*Stock)", r"¥\s*[\d.,]+", r"剪切带[^ ]*", r"卷轴[^ ]*", r"管件[^ ]*", r"托盘[^ ]*"):
            rest = re.sub(pat, " ", rest)
        out.append({
            "site": "digikey", "mpn": mpn, "mfr": "", "desc": re.sub(r"\s+", " ", rest).strip()[:80],
            "stock": int(stock_m.group(1).replace(",", "")) if stock_m else None,
            "unit_price": float(price_m.group(1).replace(",", "")) if price_m else None,
            "ladder": "", "url": data.get("url", ""), "raw_price": blob[:120],
        })
    return out


def print_table(rows):
    if not rows:
        print("（无结果）")
        return
    print(f"{'#':2} {'站点':8} {'型号':26} {'品牌':16} {'库存':>8} {'单只价':>10}  描述")
    print("-" * 120)
    for i, r in enumerate(rows, 1):
        print(f"{i:2} {r['site']:8} {(r.get('mpn') or '')[:26]:26} {(r.get('mfr') or '')[:16]:16} "
              f"{(r.get('stock') or 0):>8} {(r.get('unit_price') or 0):>10.4f}  {(r.get('desc') or '')[:40]}")


def cmd_check(a):
    br = Bridge(session=a.session, timeout=a.timeout, trace=a.trace)
    st = br.status() if hasattr(br, "status") else None
    print(f"daemon = {br.daemon_url('/status') if hasattr(br, 'daemon_url') else 'n/a'}")
    print(f"status = {json.dumps(st, ensure_ascii=False)[:400] if st else 'n/a'}")
    for name, fn in (("mouser", search_mouser), ("digikey", search_digikey)):
        try:
            rows = fn(br, "TPS25947", limit=2)
            print(f"[{name}] OK  {len(rows)} 条  首条={json.dumps(rows[0], ensure_ascii=False)[:160] if rows else '—'}")
        except Exception as exc:  # noqa: BLE001
            print(f"[{name}] 失败: {type(exc).__name__}: {exc}")
        time.sleep(3)


def cmd_search(a):
    br = Bridge(session=a.session, timeout=a.timeout, trace=a.trace)
    sites = ["mouser", "digikey"] if a.site == "both" else [a.site]
    all_rows = []
    for s in sites:
        fn = search_mouser if s == "mouser" else search_digikey
        try:
            rows = fn(br, a.keyword, limit=a.limit)
        except Exception as exc:  # noqa: BLE001
            print(f"[{s}] 失败: {type(exc).__name__}: {exc}")
            continue
        all_rows.extend(rows)
        time.sleep(a.interval)
    print_table(all_rows)
    if a.json:
        Path(a.json).write_text(json.dumps(all_rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n-> {a.json}")


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="海外分销商检索（Mouser / DigiKey，走真浏览器）")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("check", help="检查 bridge 与两站可达性")
    p.add_argument("--session", default="bom-sourcing")
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--trace", action="store_true")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("search", help="按型号/关键词检索")
    p.add_argument("keyword")
    p.add_argument("--site", default="both", choices=["mouser", "digikey", "both"])
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--interval", type=float, default=3.0, help="站间间隔秒（默认 3）")
    p.add_argument("--json", default="")
    p.add_argument("--session", default="bom-sourcing")
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--trace", action="store_true")
    p.set_defaults(func=cmd_search)

    a = ap.parse_args(argv)
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a) or 0


if __name__ == "__main__":
    raise SystemExit(main())
