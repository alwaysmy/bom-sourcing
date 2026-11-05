#!/usr/bin/env python3
"""原厂官方商城 / 官方渠道检索（origin store sourcing）。

用途：当 BOM 里出现**已知型号**（MPN），需要确认「原厂还产不产、原厂卖什么价、
原厂有没有现货、封装/起订量/包装是什么」时，直接问原厂，而不是在分销商那里猜。

设计原则（实测得来，不要"优化"掉）：
  1. **绝不编造价格与库存**。拿不到就返回 `status="need_login"` / `"browser"` / `"no_price"`，
     并原样把原厂页面上的提示（如「登录以查看库存」）带回来。
  2. 价格必须标注**币种与口径**：`price_cny_incl_tax`（含税人民币）/ `price_usd_1ku`
     （USD、1ku 参考价）不是同一个东西，不要混。
  3. 每个原厂的 `access` 说明**实测**能不能纯 HTTP 拿：
       http     —— 纯 HTTP 就能拿（最快，不需要浏览器）
       browser  —— 需要真浏览器（Kimi WebBridge），要跑 daemon
       none     —— 实测拿不到（站点超时 / 全站 403 / 只有询价表单）
  4. 注册表里的 URL 模板都是**人工实测**过的，不是猜的；改之前先跑 `check`。

CLI:
  python origin.py list
  python origin.py search TPS259470ARPWR
  python origin.py search TPA7836B --vendor 3peak --json out.json
  python origin.py search TPA7836B --refresh        # 强制刷新 3peak 本地目录
  python origin.py check
  python origin.py check --vendor 3peak

依赖：标准库。需要浏览器的原厂（TI 库存）依赖本机 Kimi WebBridge daemon。
"""

from __future__ import annotations

import argparse
import inspect
import json
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
CACHE = Path(tempfile.gettempdir()) / "bom_origin_cache"
CACHE.mkdir(parents=True, exist_ok=True)

# 3peak 商城目录缓存有效期（秒）。原厂价格变动不频繁，12 小时足够。
PEAK_TTL = 12 * 3600


# --------------------------------------------------------------------------- #
# 注册表
# --------------------------------------------------------------------------- #
VENDORS: list[dict] = [
    {
        "key": "3peak",
        "name": "思瑞浦 3PEAK",
        "site": "https://www.3peakic.cn",
        "store": "思瑞浦商城（原厂直营）",
        "access": "http",
        "search_url": "https://www.3peakic.cn/appList",
        "price": "含税13%人民币阶梯价",
        "stock": True,
        "fields": ["mpn", "title", "category", "stock", "package", "moq",
                   "price_cny_incl_tax", "state"],
        "note": "原厂直营商城，价格/库存/封装/起订量全公开，无需登录。"
                "BOM 里 3PEAK 的料优先查这里。",
    },
    {
        "key": "ti",
        "name": "德州仪器 TI 中国",
        "site": "https://www.ti.com.cn",
        "store": "TI.com.cn（原厂直营）",
        "access": "http",
        "search_url": "https://www.ti.com.cn/product/zh-cn/{base}",
        "price": "USD 1ku 参考价（JSON-LD）",
        "stock": "browser",
        "fields": ["mpn", "variants", "price_usd_1ku", "package", "qty_pack", "state"],
        "note": "产品文件夹页服务端渲染，JSON-LD 里有全部 OPN 变体与 1ku 美元价；"
                "**人民币价与库存要登录**（页面写「登录以查看库存」）。"
                "库存可走浏览器 API /storeservices/cart/opninventory?opn=<OPN>。",
    },
    {
        "key": "mps",
        "name": "MPS 芯源",
        "site": "https://www.monolithicpower.cn",
        "store": None,
        "access": "http",
        "search_url": "https://www.monolithicpower.cn/cn/catalogsearch/result/?q={q}",
        "price": None,
        "stock": False,
        "fields": ["mpn", "product_url"],
        "note": "Magento 站内搜索可用（纯 HTTP），能拿到型号与产品页链接；"
                "原厂不公开人民币价与库存，需走分销商。",
    },
    {
        "key": "silan",
        "name": "士兰微 Silan",
        "site": "https://www.silan.com.cn",
        "store": None,
        "access": "http",
        "search_url": "https://www.silan.com.cn/index.php/search.html?search={q}",
        "price": None,
        "stock": False,
        "fields": ["mpn", "product_url"],
        "note": "站内搜索可用（注意 https 回 502，**必须用 http**）。无公开价格库存。",
    },
    {
        "key": "prisemi",
        "name": "芯导科技 Prisemi",
        "site": "https://www.prisemi.com",
        "store": None,
        "access": "none",
        "search_url": "https://www.prisemi.com/?s={q}&type=",
        "price": None,
        "stock": False,
        "fields": [],
        "note": "站内搜索已损坏：?s= 页面在真浏览器里也只显示 "
                "「THE SERVER CANNOT FIND DATA FOR THE RESOURCE」，无结果可用。",
    },
    {
        "key": "wch",
        "name": "沁恒 WCH",
        "site": "https://www.wch.cn",
        "store": None,
        "access": "browser",
        "search_url": "https://www.wch.cn/search.html?q={q}&t=all",
        "price": None,
        "stock": False,
        "fields": ["mpn", "product_url"],
        "note": "纯 JS SPA（首屏 1815B），必须浏览器渲染。官方不直销，走淘宝/立创。",
    },
    {
        "key": "geehy",
        "name": "极海 Geehy",
        "site": "https://www.geehy.com",
        "store": None,
        "access": "browser",
        "search_url": "https://www.geehy.com/search?keyword={q}",
        "price": None,
        "stock": False,
        "fields": ["mpn", "product_url"],
        "note": "纯 HTTP 一律 405 Not Allowed（WAF），必须浏览器。",
    },
    {
        "key": "hdsc",
        "name": "小华半导体 HDSC",
        "site": "https://www.hdscmcu.com",
        "store": None,
        "access": "browser",
        "search_url": "https://www.hdscmcu.com",
        "price": None,
        "stock": False,
        "fields": ["mpn", "product_url"],
        "note": "直连 DNS 解析失败 / 代理 SSL 提前 EOF，只能浏览器。",
    },
    {
        "key": "novosense",
        "name": "纳芯微 NOVOSENSE",
        "site": "https://www.novosense.com",
        "store": None,
        "access": "browser",
        "search_url": "https://www.novosense.com",
        "price": None,
        "stock": False,
        "fields": ["mpn", "product_url"],
        "note": "同 HDSC：直连 DNS 失败、代理 SSL EOF，只能浏览器。",
    },
    {
        "key": "cmsemicon",
        "name": "中微半导体 CMSemicon",
        "site": "https://www.cmsemicon.com",
        "store": None,
        "access": "browser",
        "search_url": "https://www.cmsemicon.com",
        "price": None,
        "stock": False,
        "fields": ["mpn", "product_url"],
        "note": "同 HDSC：直连 DNS 失败、代理 SSL EOF，只能浏览器。",
    },
    {
        "key": "sgmicro",
        "name": "圣邦微 SGMICRO",
        "site": "https://www.sg-micro.com",
        "store": None,
        "access": "browser",
        "search_url": "https://www.sg-micro.com/global-search?keyword={q}",
        "price": None,
        "stock": False,
        "fields": ["mpn", "title", "product_url", "lifecycle"],
        "note": "Nuxt 站：纯 HTTP 的 global-search 恒返回「0 results」（参数被 hydration "
                "覆盖），**必须走真浏览器**。实测 SGM2019 → 11 条结果，能拿到型号、"
                "品类、生命周期（Active / Not Recommended for New Designs）与描述；"
                "无公开价格库存。",
    },
    {
        "key": "gigadevice",
        "name": "兆易创新 GigaDevice",
        "site": "https://www.gigadevice.com",
        "store": None,
        "access": "http",
        "search_url": "https://www.gigadevice.com/product-search?wd={q}",
        "price": None,
        "stock": False,
        "fields": ["mpn", "product_url"],
        "note": "站内搜索 /product-search?wd= 纯 HTTP 可用（实测 GD25Q64 → "
                "GD25Q64C/E/H 等型号 + 产品页）。另有 /product-inventory-search "
                "库存查询，但那是 oemsecrets.com 的第三方分销库存挂件，**不是原厂库存**，"
                "别当原厂数据用。",
    },
    {
        "key": "nationstech",
        "name": "国民技术 Nationstech",
        "site": "https://www.nationstech.com",
        "store": None,
        "access": "browser",
        "search_url": "https://www.nationstech.com",
        "price": None,
        "stock": False,
        "fields": ["mpn", "product_url"],
        "note": "有「购买样品」入口，站内搜索 /product/search/ 需 JS。",
    },
    {
        "key": "willsemi",
        "name": "韦尔半导体 WILLSEMI",
        "site": "https://www.willsemi.com",
        "store": None,
        "access": "none",
        "search_url": None,
        "price": None,
        "stock": False,
        "fields": [],
        "note": "willsemi.com / willsemi.cn 直连与代理全部超时（WinError 10060），"
                "实测不可达，不要浪费时间重试。",
    },
    {
        "key": "etek",
        "name": "力芯微 ETek",
        "site": "https://www.etek.com.cn",
        "store": None,
        "access": "browser",
        "search_url": "https://www.etek.com.cn/search.html?query={q}",
        "price": None,
        "stock": False,
        "fields": ["mpn", "product_url"],
        "note": "搜索表单 action=/search.html、name=query；纯 HTTP 一律 403（WAF），"
                "必须浏览器。",
    },
    {
        "key": "eta",
        "name": "钰泰 ETA",
        "site": "https://www.eta-semi.com",
        "store": None,
        "access": "browser",
        "search_url": "https://www.eta-semi.com",
        "price": None,
        "stock": False,
        "fields": ["mpn", "product_url"],
        "note": "无站内搜索表单（/search?keyword= 404），只能浏览器翻产品目录。"
                "注意 etasolution.com 证书 hostname 不匹配。",
    },
    {
        "key": "hsxp",
        "name": "航顺芯片 HSXP",
        "site": "https://www.hsxp-hk.com",
        "store": None,
        "access": "browser",
        "search_url": "http://www.hsxp-hk.com",
        "price": None,
        "stock": False,
        "fields": ["mpn", "product_url"],
        "note": "首页只有 2151B 纯 JS 壳，/search 会 302；必须浏览器。",
    },
    {
        "key": "southchip",
        "name": "南芯 Southchip",
        "site": "https://www.southchip.com",
        "store": None,
        "access": "browser",
        "search_url": "https://www.southchip.com",
        "price": None,
        "stock": False,
        "fields": ["mpn", "product_url"],
        "note": "有登录/注册 + 样片申请；/search?keyword= 会落到首页（无此路由），"
                "站内检索需浏览器。",
    },
    {
        "key": "gd32",
        "name": "兆易 GD32（MCU 子站）",
        "site": "https://www.gd32mcu.com",
        "store": None,
        "access": "http",
        "search_url": "https://www.gd32mcu.com/cn/download?kw={q}",
        "price": None,
        "stock": False,
        "fields": ["mpn", "doc_url"],
        "note": "站内搜索是**下载检索**（找 datasheet/固件），不是料号检索；"
                "查 GD32 料请用 gigadevice 主站的 /product-search?wd=。",
    },
]


# --------------------------------------------------------------------------- #
# 通用 HTTP
# --------------------------------------------------------------------------- #
def http_get(url, noproxy=True, timeout=35):
    """noproxy=True：国内原厂站直连；False：走 127.0.0.1:7890。"""
    handlers = [urllib.request.ProxyHandler({})] if noproxy else [
        urllib.request.ProxyHandler({
            "http": "http://127.0.0.1:7890",
            "https": "http://127.0.0.1:7890"})]
    op = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"})
    with op.open(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace"), r.geturl()


def http_post_json(url, payload, noproxy=True, timeout=45, referer=""):
    handlers = [urllib.request.ProxyHandler({})] if noproxy else [
        urllib.request.ProxyHandler({
            "http": "http://127.0.0.1:7890",
            "https": "http://127.0.0.1:7890"})]
    op = urllib.request.build_opener(*handlers)
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/plain, */*",
               "User-Agent": UA,
               "Origin": urllib.parse.urlsplit(url).scheme + "://" +
                         urllib.parse.urlsplit(url).netloc}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers)
    with op.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def snippet(text, n=160):
    return re.sub(r"\s+", " ", text or "").strip()[:n]


# --------------------------------------------------------------------------- #
# 3PEAK 思瑞浦商城（原厂直营，唯一能拿到含税人民币价 + 库存的）
# --------------------------------------------------------------------------- #
PEAK_API = "https://www.3peakic.cn"
PEAK_LIST = PEAK_API + "/api/bbb/goodsInfo"
PEAK_REF = PEAK_API + "/quickBuy"


def _peak_page(page, size):
    d = http_post_json(PEAK_LIST, {"pageNum": page, "pageSize": size},
                       referer=PEAK_REF)
    data = d.get("data") or {}
    return data.get("total"), (data.get("content") or [])


def _peak_catalog(refresh=False):
    """拉全量目录（1591 条 / 16 页），落盘缓存。返回 list[dict]。

    坑：该 API 的 offset 分页在 offset≈500 处有一页「毒记录」——整页返回空
    （pageNum 6 / pageSize 100 恒空，但 total 仍报 1591）。绕法：先用大 pageSize
    扫全量，再对空页对应的 offset 窗口用更小的 pageSize 细扫补回，按 goodsId 去重。
    实测可恢复到 1590/1591（剩余 1 条任何 offset 都取不到）。
    """
    cache = CACHE / "3peak_catalog.json"
    if not refresh and cache.exists() and (time.time() - cache.stat().st_mtime) < PEAK_TTL:
        try:
            return json.loads(cache.read_text("utf-8"))
        except Exception:  # noqa: BLE001
            pass

    def _sweep(size, lo=0, hi=None):
        """扫 [lo, hi) 这段 offset（按 size 切页）。"""
        find = {}
        gaps = []
        first = lo // size + 1
        last = ((hi if hi is not None else size * 10**6) + size - 1) // size
        page = first
        while page <= last:
            total, content = _peak_page(page, size)
            if total is not None:
                last = min(last, (total + size - 1) // size)
            if not content:
                if page <= last:
                    gaps.append(page)
                page += 1
                continue
            for g in content:
                find[g.get("goodsId")] = g
            page += 1
            if total is not None and page > (total + size - 1) // size:
                break
        return find, gaps

    items = {}
    for size, lo, hi in ((100, 0, None), (10, 500, 600), (1, 500, 600)):
        got, gaps = _sweep(size, lo, hi)
        items.update(got)
    rows = list(items.values())
    if rows:
        try:
            cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    return rows


def _peak_row(g):
    gp = g.get("goodsPriceObj") or {}
    ladder = ((gp.get("stepPrice") or {}).get("stepPriceRangeList") or [])
    moq = None
    try:
        raw = json.loads(g.get("increasesParam") or "[]")
        if raw and isinstance(raw[0], dict):
            moq = raw[0].get("value")
    except Exception:  # noqa: BLE001
        pass
    return {
        "vendor": "3peak",
        "vendor_name": "思瑞浦 3PEAK",
        "source": "原厂直营商城 www.3peakic.cn",
        "mpn": g.get("goodsName"),
        "title": snippet(g.get("goodsTitle"), 120),
        "category": g.get("categoryName"),
        "stock": g.get("singleGoodsStock"),
        "package": g.get("packaging"),
        "state": g.get("productState"),
        "moq": moq,
        "currency": "CNY",
        "price_note": "含税13%人民币价",
        "price_cny_incl_tax": [
            {"from": r.get("startNum"), "to": r.get("endNum"), "price": r.get("price")}
            for r in ladder],
        "url": PEAK_API + "/appdetail?id=" + urllib.parse.quote(str(g.get("goodsId") or "")),
    }


def search_3peak(mpn, limit=5, refresh=False):
    kw = (mpn or "").upper().strip()
    if not kw:
        return []
    try:
        catalog = _peak_catalog(refresh=refresh)
    except Exception as e:  # noqa: BLE001
        return [{"vendor": "3peak", "vendor_name": "思瑞浦 3PEAK",
                 "status": "error", "reason": f"{type(e).__name__}: {e}"}]
    if not catalog:
        return [{"vendor": "3peak", "vendor_name": "思瑞浦 3PEAK",
                 "status": "error", "reason": "目录为空（API 结构可能变了）"}]
    # 先精确后包含
    exact = [g for g in catalog if (g.get("goodsName") or "").upper() == kw]
    part = [g for g in catalog if kw in (g.get("goodsName") or "").upper()
            and (g.get("goodsName") or "").upper() != kw]
    rows = [_peak_row(g) for g in (exact + part)[:limit]]
    if not rows:
        return [{"vendor": "3peak", "vendor_name": "思瑞浦 3PEAK",
                 "status": "not_found",
                 "reason": f"商城目录（{len(catalog)} 个型号）里没有 {kw}"}]
    return rows


# --------------------------------------------------------------------------- #
# TI 中国（JSON-LD 拿 USD 1ku 价；库存需浏览器）
# --------------------------------------------------------------------------- #
TI_HOST = "https://www.ti.com.cn"
TI_LD_RE = re.compile(
    r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)
TI_OPN_RE = re.compile(r"^[A-Z0-9]{4,}[-A-Z0-9/]*$")


def _ti_base_candidates(mpn):
    """TI 的产品文件夹页只认「基号」（TPS259470ARPWR -> TPS25947）。
    从长到短逐个裁尾字符试，直到命中 200。"""
    mpn = (mpn or "").upper().strip()
    out = []
    for cut in range(0, min(10, len(mpn) - 3)):
        out.append(mpn[:len(mpn) - cut] if cut else mpn)
    return out


def _ti_folder(mpn):
    """返回 (base, variants[list], raw_jsonld)。失败抛异常。"""
    last = None
    for base in _ti_base_candidates(mpn):
        url = f"{TI_HOST}/product/zh-cn/{base}"
        try:
            st, html, _ = http_get(url, noproxy=False, timeout=30)
        except Exception as e:  # noqa: BLE001
            last = e
            continue
        if st != 200:
            continue
        for blob in TI_LD_RE.findall(html):
            try:
                j = json.loads(blob)
            except Exception:  # noqa: BLE001
                continue
            grp = j.get("mainEntity") or j
            if isinstance(grp, list):
                grp = grp[0] if grp else {}
            variants = grp.get("hasVariant") or []
            if variants:
                return base, variants, html
        last = RuntimeError(f"{base} 200 但没找到 hasVariant")
    raise RuntimeError(f"TI 产品文件夹页未命中（最后一个错误：{last}）")


def search_ti(mpn, limit=8, with_stock=False):
    kw = (mpn or "").upper().strip()
    try:
        base, variants, html = _ti_folder(kw)
    except Exception as e:  # noqa: BLE001
        return [{"vendor": "ti", "vendor_name": "德州仪器 TI 中国",
                 "status": "error", "reason": f"{type(e).__name__}: {e}"}]
    rows = []
    for v in variants[:max(limit, 8)]:
        off = v.get("offers") or {}
        rows.append({
            "vendor": "ti",
            "vendor_name": "德州仪器 TI 中国",
            "source": f"TI.com.cn 产品文件夹页 /product/zh-cn/{base}",
            "mpn": v.get("name"),
            "title": snippet(v.get("description"), 120),
            "currency": off.get("priceCurrency") or "USD",
            "price_usd_1ku": off.get("price"),
            "price_note": "USD 1ku 参考价（原厂页面公开值）；人民币价需登录",
            "availability": v.get("availability"),
            "url": off.get("url") or f"{TI_HOST}/product/zh-cn/{base}",
            "stock": None,
            "stock_note": "TI 中国站库存需登录（页面提示「登录以查看库存」）",
        })
    if not rows:
        return [{"vendor": "ti", "vendor_name": "德州仪器 TI 中国",
                 "status": "not_found", "reason": f"{base} 页面没有 OPN 变体"}]
    # 只保留与查询相关的 OPN（前缀匹配）
    rel = [r for r in rows if (r["mpn"] or "").upper().startswith(kw[:6])]
    rel = rel or rows
    if with_stock:
        # 只有「完整可订购 OPN」才有库存；基号返回 204
        for r in rel:
            if (r.get("mpn") or "").upper() != kw:
                continue
            try:
                info = ti_stock_via_browser(kw)
            except Exception as e:  # noqa: BLE001
                r["stock_note"] = f"浏览器取值失败：{type(e).__name__}: {e}"
                continue
            if info.get("status") == "ok":
                r["stock"] = info.get("inventory")
                r["stock_note"] = "TI 原厂库存（浏览器内 API 实取）"
            else:
                r["stock_note"] = f"库存接口 {info.get('status')}：{info.get('reason', '')}"
    return rel


# --------------------------------------------------------------------------- #
# 只有站内搜索、没有公开价格的原厂
# --------------------------------------------------------------------------- #
A_RE = re.compile(r"""<a\b[^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>""", re.S | re.I)


def _plain(html):
    html = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    html = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _search_links(vendor, template, mpn, limit=8, noproxy=True):
    url = template.format(q=urllib.parse.quote(mpn))
    try:
        st, html, final = http_get(url, noproxy=noproxy, timeout=30)
    except Exception as e:  # noqa: BLE001
        return [{"vendor": vendor["key"], "vendor_name": vendor["name"],
                 "status": "error", "reason": f"{type(e).__name__}: {e}"}]
    plain = _plain(html)
    n_hits = len(re.findall(r"共\s*<?\D{0,6}?(\d[\d,]*)\s*<?\D{0,6}?条", plain))
    rows, seen = [], set()
    kw = mpn.upper()
    for m in A_RE.finditer(html):
        href, raw = m.group(1), m.group(2)
        # 有的站把整张结果卡片都塞进 <a> 里，正文会混入「产品 -->」「描述」等噪音，
        # 所以从链接文本里把型号本身抠出来（必须含查询词，否则是导航链接）
        hit = re.search(re.escape(kw) + r"[A-Z0-9\-/_]*", _plain(raw).upper())
        if not hit:
            continue
        name = hit.group(0)
        # 排除搜索表单自身 / 语言切换 / 参数带关键词的导航链接
        low = href.lower()
        if any(t in low for t in ("catalogsearch", "search", "?q=", "?s=", "keyword",
                                  "javascript:")):
            continue
        if href in seen:
            continue
        seen.add(href)
        rows.append({"vendor": vendor["key"], "vendor_name": vendor["name"],
                     "source": vendor["site"], "mpn": name,
                     "url": urllib.parse.urljoin(final, href),
                     "price": None, "stock": None,
                     "price_note": "原厂不公开价格与库存"})
        if len(rows) >= limit:
            break
    if not rows:
        return [{"vendor": vendor["key"], "vendor_name": vendor["name"],
                 "status": "not_found",
                 "reason": f"站内搜索无命中（HTTP {st}，{len(html)}B）",
                 "search_url": url}]
    return rows


def _mk_links_handler(key, template, noproxy=True):
    def _h(mpn, limit=8, **kw):
        v = next(x for x in VENDORS if x["key"] == key)
        return _search_links(v, template, mpn, limit=limit, noproxy=noproxy)
    return _h


# --------------------------------------------------------------------------- #
# 通用「真浏览器」检索（给纯 JS 渲染站用）
# --------------------------------------------------------------------------- #
BROWSER_LINKS_JS = (
    "(() => {"
    "const kw = %s;"
    "const out = [];"
    "document.querySelectorAll('a[href]').forEach(a => {"
    "  const t = (a.textContent || '').replace(/\\s+/g, ' ').trim();"
    "  if (t && t.length < 120 && t.toUpperCase().includes(kw)) {"
    "    out.push({t: t.slice(0, 100), h: a.href});"
    "  }"
    "});"
    "return JSON.stringify({title: document.title, url: location.href,"
    "  links: out.slice(0, 100)});"
    "})()"
)


def _browser_search(vendor, url, mpn, limit=8, wait=7.0):
    """用真浏览器（Kimi WebBridge）打开检索页再抽链接。

    用于纯 JS 渲染的原厂站（如圣邦微 Nuxt）。纯 HTTP 拿到的是空壳，
    必须让浏览器跑完 hydration 才有结果。
    """
    try:
        from taobao import Bridge  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        return [{"vendor": vendor["key"], "vendor_name": vendor["name"],
                 "status": "error", "reason": f"无法导入 Bridge：{e}"}]
    kw = (mpn or "").upper().strip()
    try:
        br = Bridge(session="bom-sourcing")
        br.navigate(url, new_tab=False, group_title="原厂检索")
        time.sleep(wait)
        data = json.loads(br.evaluate(BROWSER_LINKS_JS % json.dumps(kw)))
    except Exception as e:  # noqa: BLE001
        return [{"vendor": vendor["key"], "vendor_name": vendor["name"],
                 "status": "error", "reason": f"{type(e).__name__}: {e}"}]
    rows, seen = [], set()
    for item in (data.get("links") or []):
        name = re.search(re.escape(kw) + r"[A-Z0-9\-/_]*", item["t"].upper())
        if not name or item["h"] in seen:
            continue
        seen.add(item["h"])
        rows.append({"vendor": vendor["key"], "vendor_name": vendor["name"],
                     "source": vendor["site"], "mpn": name.group(0),
                     "url": item["h"],
                     "price": None, "stock": None,
                     "price_note": "原厂不公开价格与库存"})
        if len(rows) >= limit:
            break
    if not rows:
        return [{"vendor": vendor["key"], "vendor_name": vendor["name"],
                 "status": "not_found",
                 "reason": f"浏览器检索无命中（{len(data.get('links') or [])} 条链接）",
                 "search_url": url}]
    return rows


def _mk_browser_handler(key, template, wait=7.0):
    def _h(mpn, limit=8, **kw):
        v = next(x for x in VENDORS if x["key"] == key)
        return _browser_search(v, template.format(q=urllib.parse.quote(mpn)),
                               mpn, limit=limit, wait=wait)
    return _h


HANDLERS = {
    "3peak": search_3peak,
    "ti": search_ti,
    "mps": _mk_links_handler(
        "mps", "https://www.monolithicpower.cn/cn/catalogsearch/result/?q={q}"),
    "silan": _mk_links_handler(
        "silan", "https://www.silan.com.cn/index.php/search.html?search={q}"),
    "gigadevice": _mk_links_handler(
        "gigadevice", "https://www.gigadevice.com/product-search?wd={q}"),
    "sgmicro": _mk_browser_handler(
        "sgmicro", "https://www.sg-micro.com/global-search?keyword={q}"),
}


# --------------------------------------------------------------------------- #
# 浏览器（Kimi WebBridge）—— 只在需要时导入，避免没装 daemon 时整个脚本不可用
# --------------------------------------------------------------------------- #
def _bridge():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from taobao import Bridge  # noqa: PLC0415
    return Bridge(session="bom-sourcing", timeout=120)


def ti_stock_via_browser(opn):
    """TI 库存 API 有 PerimeterX 保护，纯 HTTP 拿到的是挑战页；必须在浏览器里 fetch。"""
    br = _bridge()
    br.navigate(f"{TI_HOST}/product/zh-cn/", new_tab=False)
    time.sleep(2.0)
    code = (
        "(async () => {try{"
        f"const r=await fetch('/storeservices/cart/opninventory?opn={opn}',"
        "{headers:{'accept':'application/json'}});"
        "const t=await r.text();"
        "return JSON.stringify({status:r.status,body:t.slice(0,400)});"
        "}catch(e){return JSON.stringify({error:String(e)});}})()")
    raw = br.evaluate(code)
    try:
        j = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {"status": "error", "reason": f"返回不是 JSON：{str(raw)[:200]}"}
    body = j.get("body") or ""
    try:
        data = json.loads(body)
    except Exception:  # noqa: BLE001
        return {"status": "blocked" if "Privacy" in body or "PerimeterX" in body
                else "error", "reason": snippet(body, 200)}
    return {"status": "ok", "opn": data.get("orderable_number"),
            "inventory": data.get("inventory")}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
STATUS_LABEL = {
    "ok": "OK",
    "not_found": "未命中",
    "need_login": "需登录",
    "browser": "需浏览器",
    "no_price": "无公开价",
    "blocked": "被反爬拦截",
    "error": "错误",
    "skip": "跳过",
}


def _print_rows(rows):
    for r in rows:
        st = r.get("status", "ok")
        if st != "ok":
            print(f"  [{STATUS_LABEL.get(st, st)}] {r.get('vendor_name', r.get('vendor'))}"
                  f" — {r.get('reason', '')}")
            continue
        price = ""
        if r.get("price_cny_incl_tax"):
            price = " / ".join(f"{x['from']}-{x['to']}:¥{x['price']}"
                               for x in r["price_cny_incl_tax"])
        elif r.get("price_usd_1ku") is not None:
            price = f"{r['price_usd_1ku']} {r.get('currency', 'USD')} (1ku)"
        bits = [f"MPN={r.get('mpn')}"]
        if r.get("stock") is not None:
            bits.append(f"库存={r['stock']}")
        if r.get("package"):
            bits.append(f"封装={r['package']}")
        if r.get("moq"):
            bits.append(f"MOQ={r['moq']}")
        if r.get("state"):
            bits.append(f"状态={r['state']}")
        print(f"  {r.get('vendor_name')} | " + " | ".join(bits))
        if price:
            print(f"      价格: {price}   ({r.get('price_note', '')})")
        if r.get("stock_note"):
            print(f"      库存: {r['stock_note']}")
        if r.get("title"):
            print(f"      {r['title']}")
        if r.get("url"):
            print(f"      {r['url']}")


def _w(text):
    """按终端显示宽度补空格（CJK 算 2 列）。"""
    import unicodedata  # noqa: PLC0415
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(text))


def _pad(text, width):
    text = str(text)
    return text + " " * max(0, width - _w(text))


def cmd_list(args):
    print(f"原厂官方渠道注册表：共 {len(VENDORS)} 家\n")
    widths = (14, 22, 9, 26, 8)
    print(_pad("key", widths[0]) + _pad("原厂", widths[1]) + _pad("access", widths[2])
          + _pad("价格", widths[3]) + _pad("库存", widths[4]) + "官方渠道")
    print("-" * 118)
    for v in VENDORS:
        price = v.get("price") or "无公开价"
        stock = "有" if v.get("stock") is True else (
            "浏览器" if v.get("stock") == "browser" else "无")
        print(_pad(v["key"], widths[0]) + _pad(v["name"], widths[1])
              + _pad(v["access"], widths[2]) + _pad(price, widths[3])
              + _pad(stock, widths[4]) + (v.get("store") or "—"))
    print("\naccess 含义: http=纯 HTTP 可取 / browser=需真浏览器 / none=实测不可达")
    print("可执行检索的原厂:", ", ".join(sorted(HANDLERS)))
    return 0


def cmd_search(args):
    mpn = args.mpn.strip()
    if args.vendor and args.vendor not in HANDLERS:
        known = ", ".join(sorted(HANDLERS))
        print(f"错误：{args.vendor} 没有可执行检索（可用：{known}）", file=sys.stderr)
        return 2
    targets = [args.vendor] if args.vendor else list(HANDLERS)
    all_rows = []
    print(f"检索型号: {mpn}   原厂范围: {', '.join(targets)}\n")
    for key in targets:
        fn = HANDLERS[key]
        t0 = time.time()
        kwargs = {}
        sig = inspect.signature(fn)
        if "limit" in sig.parameters:
            kwargs["limit"] = args.limit
        if "refresh" in sig.parameters:
            kwargs["refresh"] = args.refresh
        if "with_stock" in sig.parameters:
            kwargs["with_stock"] = args.browser
        try:
            rows = fn(mpn, **kwargs)
        except Exception as e:  # noqa: BLE001
            rows = [{"vendor": key, "status": "error",
                     "reason": f"{type(e).__name__}: {e}"}]
        dt = time.time() - t0
        print(f"### {key}  ({dt:.1f}s)")
        _print_rows(rows)
        print()
        all_rows.extend(rows)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"mpn": mpn, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                   "rows": all_rows}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        print(f"JSON 已写入 {out}")
    ok = [r for r in all_rows if r.get("status", "ok") == "ok"]
    return 0 if ok else 5


def cmd_check(args):
    print("WebBridge daemon:")
    try:
        with urllib.request.urlopen("http://127.0.0.1:10086/status", timeout=8) as r:
            st = json.loads(r.read().decode("utf-8"))
        print(f"  OK  {st.get('version')}  extension_connected="
              f"{st.get('extension_connected')}")
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL  {type(e).__name__}: {e}")
    print("\n原厂站点可达性:")
    targets = ([v for v in VENDORS if v["key"] == args.vendor] if args.vendor
               else [v for v in VENDORS if v.get("site")])
    for v in targets:
        t0 = time.time()
        try:
            st, html, _ = http_get(v["site"], noproxy=True, timeout=20)
            print(f"  {v['key']:14}{v['name']:22} 直连 HTTP {st}  "
                  f"{len(html)}B  {time.time() - t0:.1f}s")
        except Exception as e:  # noqa: BLE001
            print(f"  {v['key']:14}{v['name']:22} 直连 FAIL  "
                  f"{type(e).__name__}: {snippet(str(e), 70)}")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(
        prog="origin.py",
        description="原厂官方商城 / 官方渠道检索（已知型号查原厂价格、库存、封装、起订量）",
        epilog="示例：\n"
               "  python origin.py list\n"
               "  python origin.py search TPA7836B --vendor 3peak\n"
               "  python origin.py search TPS259470ARPWR --json out.json\n"
               "  python origin.py check --vendor ti\n",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="列出原厂注册表")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("search", help="按型号检索原厂官方渠道")
    p.add_argument("mpn", help="器件型号（可带完整包装后缀，如 TPS259470ARPWR）")
    p.add_argument("--vendor", "-v", help="只查某一家（key，见 list）")
    p.add_argument("--limit", "-n", type=int, default=5, help="每家最多返回条数")
    p.add_argument("--json", "-j", help="把结果写成 JSON 文件")
    p.add_argument("--refresh", action="store_true", help="强制刷新本地目录缓存")
    p.add_argument("--browser", action="store_true",
                   help="允许用真浏览器补抓（TI 库存等）")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("check", help="自检 daemon 与原厂站点可达性")
    p.add_argument("--vendor", "-v", help="只查某一家")
    p.set_defaults(func=cmd_check)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
