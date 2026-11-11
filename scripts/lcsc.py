#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""立创商城（szlcsc.com）检索 / 比价 / 指标查询 CLI。

只使用 Python 3 标准库（urllib），不需要登录态，不需要浏览器。
接口事实见 references/lcsc-api.md（同目录上级）。

常用：
  python lcsc.py search "STM32F103C8T6"
  python lcsc.py search "10k 0603 1%" --sort sales_desc --limit 15
  python lcsc.py search "AMS1117-3.3" --brand AMS --json
  python lcsc.py price C8734 --qty 100
  python lcsc.py detail C8734
  python lcsc.py compare C8734 C6186 --qty 100

约定：
  - 价格为「含税单价（元/个）」的阶梯价；--qty 指定数量，按阶梯匹配单价。
  - 库存 stockNumber 是立创自营库存；totalStockNumber 是含渠道总库存。
  - 每次真实请求写缓存（默认 %LOCALAPPDATA%/bom-sourcing/cache/lcsc），TTL 6 小时。
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SEARCH_URL = "https://so.szlcsc.com/query/product"
ITEM_URL = "https://item.szlcsc.com/{product_id}.html"
# 数据手册：旧的 https://datasheet.lcsc.com/{pdfDESProductId}.pdf 已失效（只回 100 余字节跳转页），
# 真实 PDF 是商品页 pdfFileDetailVO 里的 atta.szlcsc.com 签名直链，见 Lcsc.datasheet_pdf()。
_PDF_URL_RE = re.compile(
    r"https://atta\.szlcsc\.com/[^\"'<>\\ ]+?\.pdf(?:\?[^\"'<>\\ ]*)?", re.I
)
# 替代料接口：比海外站全（C8734 → 36 条 vs 5 条），带 simScore 与参数差异。body 必须是 {}
SUBSTITUTE_URL = "https://list.szlcsc.com/substitute/simple/list?productCode={code}"
# 海外站商品页内嵌 __NEXT_DATA__，是**唯一**带替代料明细的入口（中文站没有）
DETAIL_URL = "https://www.lcsc.com/product-detail/{code}.html"
_NEXTDATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S
)


class AntiBotError(RuntimeError):
    """立创反爬（HTTP 203 + tws2_ JS 挑战）：请求太密时出现，通常是瞬时的。"""

    exit_code = 3

    def __init__(self, message, hint=""):
        super().__init__(message)
        self.hint = hint


_ANTIBOT_MSG = "立创触发了反爬（HTTP 203 / tws2_ 挑战）"
_ANTIBOT_HINT = (
    "请求太密被打回。处置（按代价从低到高）：\n"
    "  1) 等 3~10 分钟再试，并把 --rate 调大（如 2.0，即 QPS≤0.5）；\n"
    "  2) 少翻页：--pages 1、单页 ≤30 条（pageSize>30 会静默返 0 条）；\n"
    "  3) 用真实浏览器取一次 cookie 存下来（之后自动带上）：python lcsc.py cookie；\n"
    "  4) 若 ③ 也不行，说明该出口 IP 被封，换网络或用浏览器的 fetch 通道。"
)
# 商品页（item.szlcsc.com）是另一套 WAF，跟搜索接口无关；不要用上面那套处置建议
_WAF_HINT = (
    "商品页被阿里云 WAF（acw_sc__v2）拦了 —— 这是页面级挑战，不是搜索接口限流。\n"
    "  1) 确认 Kimi WebBridge daemon 与浏览器扩展已连接：python taobao.py check；\n"
    "  2) 连上后重跑即可（脚本会自动改用真实浏览器读商品页）；\n"
    "  3) 只想绕过浏览器：用 `python lcsc.py cookie` 存一份 cookie（浏览器里取，含 acw_sc__v2），再重跑。"
)

# sortNumber 实测语义（详见 references/lcsc-api.md）
SORT_MAP = {
    "relevance": 0,   # 综合（销量权重高）
    "price_asc": 1,   # 单价升序
    "price_desc": 2,  # 单价降序
    "stock_asc": 3,
    "stock_desc": 4,
    "sales_desc": 6,  # 近期销量降序 —— 「不知道选什么就按卖得多的」
}

DEFAULT_BODY = {
    "currentPage": 1,
    "pageSize": 30,
    "catalogIdFilter": "",
    "brandIdFilter": "",
    "standardFilter": "",
    "arrangeFilter": "",
    "labelFilter": "",
    "authenticationFilter": "",
    "keyword": "",
    "sortNumber": 0,
    "satisfyStockType": "",
    "startPrice": "",
    "endPrice": "",
    "demandNumber": "",
    "spotFilter": 1,
    "discountFilter": 1,
    "hasDataFile": False,
    "brandPlaceFilter": "",
    "secondKeyword": "",
    "queryParameterValue": "",
    "lastParamName": "",
}

HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "origin": "https://so.szlcsc.com",
    "referer": "https://so.szlcsc.com/global.html",
    "accept-language": "zh-CN,zh;q=0.9",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36 Edg/156.0.0.0"
    ),
}

CACHE_DIR = Path(
    os.environ.get("BOM_CACHE") or (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "bom-sourcing" / "cache")
) / "lcsc"
CACHE_TTL = int(os.environ.get("BOM_CACHE_TTL", 6 * 3600))

# 反爬（HTTP 203 + tws2_ JS 挑战）是**瞬时限流**：请求太密会命中，停几分钟自动解除。
# 命中后不要死循环重试，给明确提示；需要立即恢复时可用真实浏览器取一次 cookie 再带着走。
COOKIE_FILE = Path(
    os.environ.get("BOM_COOKIE_FILE")
    or (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "bom-sourcing" / "lcsc-cookie.txt")
)

_TAG_RE = re.compile(r"<[^>]+>")


def load_cookie():
    """cookie 来源：环境变量 LCSC_COOKIE > 文件 ~/AppData/Local/bom-sourcing/lcsc-cookie.txt。"""
    val = os.environ.get("LCSC_COOKIE", "").strip()
    if val:
        return val
    try:
        if COOKIE_FILE.exists():
            return COOKIE_FILE.read_text("utf-8").strip()
    except OSError:
        pass
    return ""


def _looks_like_challenge(text, status):
    """立创反爬页：HTTP 203 + 混淆 JS（含 tws2_ / _xvasu），不是 JSON。"""
    head = (text or "")[:600].lstrip()
    if status == 203:
        return True
    if head.startswith("<") and ("tws2_" in head or "_xvasu" in head):
        return True
    return False


# 商品页（item.szlcsc.com）另有一套阿里云 WAF：返回 200 + 一个 20 余 KB 的
# `acw_sc__v2` 计算页（`aliyun_waf_aa` / `arg1=`）。**它长得不像错误页**（HTTP 200、
# 有完整 HTML），旧代码因此把它当成"这料没有上传 PDF"，把反爬误报成业务结论。
_WAF_MARKERS = ("aliyun_waf_aa", "acw_sc__v2", "acw_tc", "renderData")


def _looks_like_waf(text):
    """阿里云 WAF 的 JS 挑战页（商品页用）。真商品页里不会出现这些标记。"""
    head = (text or "")[:2000]
    return any(k in head for k in _WAF_MARKERS)



# ----------------------------------------------------------------------------- utils
def strip_html(s):
    if not isinstance(s, str):
        return s
    return html.unescape(_TAG_RE.sub("", s)).strip()


def cwidth(s):
    """显示宽度（中文/全角算 2）。"""
    w = 0
    for ch in str(s):
        w += 2 if "\u1100" <= ch <= "\u115f" or "\u2e80" <= ch <= "\ua4cf" or "\uac00" <= ch <= "\ud7a3" or "\uf900" <= ch <= "\ufaff" or "\ufe30" <= ch <= "\ufe4f" or "\uff00" <= ch <= "\uff60" or "\uffe0" <= ch <= "\uffe6" else 1
    return w


def pad(s, width, align="left"):
    s = "" if s is None else str(s)
    fill = max(0, width - cwidth(s))
    return (" " * fill + s) if align == "right" else (s + " " * fill)


def money(v, nd=4):
    if v is None:
        return "-"
    if v >= 1:
        return f"{v:.2f}"
    if v >= 0.01:
        return f"{v:.4f}".rstrip("0")
    return f"{v:.5f}".rstrip("0")


def cache_get(key, ttl=CACHE_TTL):
    p = CACHE_DIR / (hashlib.sha1(key.encode()).hexdigest() + ".json")
    if not p.exists():
        return None
    if time.time() - p.stat().st_mtime > ttl:
        return None
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return None


def cache_put(key, obj):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p = CACHE_DIR / (hashlib.sha1(key.encode()).hexdigest() + ".json")
        p.write_text(json.dumps(obj, ensure_ascii=False), "utf-8")
    except Exception:
        pass


# ----------------------------------------------------------------------------- client
class Lcsc:
    def __init__(self, rate_limit=1.0, retries=3, use_cache=True, cookie=""):
        self.rate_limit = rate_limit
        self.retries = retries
        self.use_cache = use_cache
        self.cookie = cookie or ""
        self._last = 0.0

    def _throttle(self):
        dt = time.time() - self._last
        if dt < self.rate_limit:
            time.sleep(self.rate_limit - dt)
        self._last = time.time()

    def _post(self, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = dict(HEADERS)
        cookie = self.cookie or load_cookie()
        if cookie:
            headers["cookie"] = cookie
        last = None
        for attempt in range(self.retries):
            self._throttle()
            req = urllib.request.Request(SEARCH_URL, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=25) as r:
                    text = r.read().decode("utf-8", "replace")
                if _looks_like_challenge(text, 200):
                    raise AntiBotError(_ANTIBOT_MSG)
                return json.loads(text)
            except AntiBotError:
                # 命中反爬：不要快速重试（重试只会延长封禁），直接给出可执行的处置建议
                raise
            except urllib.error.HTTPError as e:
                body_text = e.read().decode("utf-8", "replace")
                if _looks_like_challenge(body_text, e.code):
                    raise AntiBotError(_ANTIBOT_MSG) from None
                last = f"HTTP {e.code}: {body_text[:200]!r}"
            except Exception as e:  # noqa: BLE001
                last = f"{type(e).__name__}: {e}"
            time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"立创请求失败: {last}")

    # -- 查询 -----------------------------------------------------------------
    def raw_search(self, keyword, sort=0, page=1, page_size=30, brand_id="", package="",
                   price_min="", price_max="", demand_number="", spot=1, discount=1,
                   catalog_id="", cache=True):
        # spotFilter 只认 1（含现货）：传 0 会**静默返回 0 条**（实测，不是"不过滤"）
        if spot not in (1, True):
            raise ValueError(f"spotFilter 只接受 1（含现货）；传 {spot!r} 会静默返回 0 条结果")
        body = dict(DEFAULT_BODY)
        body.update(
            keyword=keyword,
            sortNumber=SORT_MAP.get(sort, sort) if isinstance(sort, str) else sort,
            currentPage=page,
            pageSize=page_size,
            brandIdFilter=brand_id,
            catalogIdFilter=catalog_id,
            standardFilter=package,
            startPrice=price_min,
            endPrice=price_max,
            demandNumber=demand_number,
            spotFilter=spot,
            discountFilter=discount,
        )
        key = "search:" + json.dumps(body, sort_keys=True, ensure_ascii=False)
        if cache and self.use_cache:
            got = cache_get(key)
            if got is not None:
                return got
        obj = self._post(body)
        if obj.get("code") != 200:
            raise RuntimeError(f"立创返回错误 code={obj.get('code')} msg={obj.get('msg')}")
        res = obj.get("result") or {}
        sr = res.get("searchResult") or {}
        out = {
            "keyword": keyword,
            "total": sr.get("totalCount"),
            "count_page": sr.get("countPage"),
            "sort_sign": sr.get("querySortBySign"),
            "brands": sr.get("gradePlateGroup") or [],
            "packages": sr.get("encapsulationGroup") or [],
            "catalogs": sr.get("catalogGroup") or [],
            "parents": sr.get("parentCatalogGroup") or [],
            "records": [normalize(it) for it in (sr.get("productRecordList") or [])],
            "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if cache and self.use_cache:
            cache_put(key, out)
        return out

    def search(self, keyword, limit=10, **kw):
        """按需翻页，最多取 limit 条。"""
        out = []
        page = 1
        meta = None
        while len(out) < limit:
            r = self.raw_search(keyword, page=page, **kw)
            meta = meta or r
            recs = r["records"]
            if not recs:
                break
            out.extend(recs)
            if page >= (r.get("count_page") or 1):
                break
            page += 1
        res = dict(meta or {})
        res["records"] = out[:limit]
        return res

    def lookup(self, product_code, demand_number=""):
        """按 C 编号/型号精确取一条（优先 productCode 完全相等）。"""
        code = product_code.strip().upper()
        r = self.raw_search(code, demand_number=demand_number)
        for rec in r["records"]:
            if (rec.get("code") or "").upper() == code:
                return rec
        # 退化：型号完全匹配
        for rec in r["records"]:
            if (rec.get("model") or "").strip().lower() == product_code.strip().lower():
                return rec
        return r["records"][0] if r["records"] else None

    # -- 方便的品牌/封装解析 ---------------------------------------------------
    def resolve_brand_id(self, keyword, brand):
        r = self.raw_search(keyword)
        b = brand.strip().lower()
        best = None
        for item in r.get("brands") or []:
            label = (item.get("label") or "").lower()
            if b in label:
                if best is None or (len(label) < len(best[1])):
                    best = (str(item.get("value")), label)
        return best[0] if best else None

    def resolve_package(self, keyword, package):
        r = self.raw_search(keyword)
        p = package.strip().lower().replace(" ", "")
        for item in r.get("packages") or []:
            label = (item.get("label") or "").lower().replace(" ", "")
            if label == p or label.startswith(p):
                return item.get("label")
        return package

    # -- 海外站详情（替代料 + 中文参数名） -------------------------------------
    def _get_direct(self, url):
        """直连取页：www.lcsc.com 走系统代理会 SSLEOFError，必须绕开代理。"""
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        headers = {
            "user-agent": HEADERS["user-agent"],
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        cookie = self.cookie or load_cookie()
        if cookie:
            headers["cookie"] = cookie
        req = urllib.request.Request(url, headers=headers)
        with opener.open(req, timeout=40) as r:
            text = r.read().decode("utf-8", "replace")
        if _looks_like_challenge(text, 200):
            raise AntiBotError(_ANTIBOT_MSG, _ANTIBOT_HINT)
        return text

    # -- 数据手册（PDF 签名直链 / 下载） ---------------------------------------
    def _pdf_via_browser(self, product_id):
        """商品页被阿里云 WAF 拦时，用真实浏览器（Kimi WebBridge）读页面取签名直链。

        浏览器里 JS 跑完就有 `acw_sc__v2`，页面是完整商品页；`datasheet_pdf()` 自动降级到这里。
        桥不可用 → 抛 AntiBotError（明确"被拦了"，不冒充"没手册"）。
        """
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            import taobao  # 同目录，复用它的 WebBridge 客户端
        except ImportError as e:  # pragma: no cover
            raise AntiBotError(
                "商品页被阿里云 WAF 拦（acw_sc__v2），且同目录没有 taobao.py 无法走浏览器兜底",
                _WAF_HINT) from e
        br = taobao.Bridge(session="bom-sourcing", timeout=120)
        st = br.status()
        if not (st.get("running") and st.get("extension_connected")):
            raise AntiBotError(
                "商品页被阿里云 WAF 拦（acw_sc__v2），浏览器桥未就绪（daemon 或扩展未连接）",
                _WAF_HINT)
        br.navigate(ITEM_URL.format(product_id=product_id), new_tab=True,
                    group_title="配单比价")
        page = br.evaluate("document.documentElement.outerHTML") or ""
        cands = [html.unescape(m.group(0)) for m in _PDF_URL_RE.finditer(page)]
        return max(cands, key=len) if cands else None

    def datasheet_pdf(self, product_code, download=None, browser="auto"):
        """取数据手册 PDF 的签名直链，可选下载到本地。

        实测（2026-11）：
          - https://datasheet.lcsc.com/{pdfDESProductId}.pdf 只返回 101~117 字节的跳转 HTML（已失效）
          - 真实 PDF 在商品页 pdfFileDetailVO 里：atta.szlcsc.com + OSS 签名参数
          - 商品页对脚本流量会返回 **阿里云 WAF 的 acw_sc__v2 挑战页**（HTTP 200、20 余 KB），
            此时 `browser="auto"` 自动改用真实浏览器；被拦而浏览器也不可用则抛 AntiBotError
            （以前这里返回 None，被调用方写成"该料没有上传 PDF"，是错的）
        返回 (url, path)；确认没有手册的料返回 (None, None)。
        """
        code = product_code.strip().upper()
        key = "pdf:" + code
        url = cache_get(key, ttl=6 * 3600) if self.use_cache else None
        if not url:
            rec = self.lookup(code)
            pid = (rec or {}).get("product_id")
            if not pid:
                return None, None
            page = self._get_direct(ITEM_URL.format(product_id=pid))
            if _looks_like_waf(page):
                if browser in (False, "never"):
                    raise AntiBotError(
                        f"{code} 商品页被阿里云 WAF 拦（acw_sc__v2），未启用浏览器兜底",
                        _WAF_HINT)
                url = self._pdf_via_browser(pid)
                if not url:
                    return None, None
            else:
                # 页面里同一份 PDF 出现多次：先是不带签名的裸地址（会被跳转拦截），
                # 后面才是带 Expires/Signature 的可用直链 → 取最长的那条。
                cands = [html.unescape(m.group(0)) for m in _PDF_URL_RE.finditer(page)]
                if not cands:
                    return None, None
                url = max(cands, key=len)
            if self.use_cache:
                cache_put(key, url)
        if not download:
            return url, None
        path = Path(download)
        # 目录（含"还没建的目录"）→ 存成 <C号>.pdf；给了 .pdf 后缀才当文件路径
        if path.is_dir() or not path.suffix:
            path = path / f"{code}.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._throttle()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(url, headers={"user-agent": HEADERS["user-agent"]})
        with opener.open(req, timeout=60) as r:
            path.write_bytes(r.read())
        return url, path

    def intl_detail(self, product_code):
        """海外站商品页 webData：中文参数表、美元阶梯价、替代料清单。"""
        code = product_code.strip().upper()
        key = "intl:" + code
        if self.use_cache:
            got = cache_get(key)
            if got is not None:
                return got
        page = self._get_direct(DETAIL_URL.format(code=code))
        m = _NEXTDATA_RE.search(page)
        if not m:
            raise RuntimeError("未取到 __NEXT_DATA__（海外站页面结构可能已变）")
        data = json.loads(m.group(1))
        wd = (((data.get("props") or {}).get("pageProps") or {}).get("webData")) or {}

        def params_of(node):
            out = {}
            for p in node.get("paramVOList") or []:
                name = strip_html(p.get("paramName") or "")
                if name:
                    out[name] = strip_html(p.get("paramValue") or "")
            return out

        ladder = []
        for p in wd.get("productPriceList") or []:
            try:
                ladder.append({"qty_from": int(p.get("ladder") or 0),
                               "usd": float(p.get("productPrice") or 0)})
            except (TypeError, ValueError):
                continue
        alts = []
        for it in wd.get("alternatePartList") or []:
            alts.append({
                "code": it.get("productCode"),
                "model": it.get("productModel"),
                "brand": it.get("brandNameEn"),
                "package": it.get("encapStandard"),
                "stock": it.get("stockNumber"),
                "smt": it.get("smtLabel"),
                "params": params_of(it),
            })
        out = {
            "code": code,
            "model": wd.get("productModel"),
            "brand": wd.get("brandNameEn"),
            "package": wd.get("encapStandard"),
            "stock": wd.get("stockNumber"),
            "usd_ladder": ladder,
            "params": params_of(wd),
            "alternates": alts,
            "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if self.use_cache:
            cache_put(key, out)
        return out

    # -- 替代料 ---------------------------------------------------------------
    def substitutes(self, product_code):
        """立创替代料接口：比海外站全得多（C8734：36 条 vs 5 条），带相似度与参数差异。

        POST https://list.szlcsc.com/substitute/simple/list?productCode=C8734  body {}
        免登录；返回 mainProduct + all/domestic/internation/sameBrand 四组。
        """
        code = product_code.strip().upper()
        key = "sub:" + code
        if self.use_cache:
            got = cache_get(key)
            if got is not None:
                return got
        url = SUBSTITUTE_URL.format(code=code)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            url, data=b"{}",
            headers={
                "content-type": "application/json",
                "origin": "https://item.szlcsc.com",
                "referer": ITEM_URL.format(product_id=""),
                "user-agent": HEADERS["user-agent"],
                "accept": "application/json, text/plain, */*",
            }, method="POST")
        with opener.open(req, timeout=30) as r:
            obj = json.loads(r.read().decode("utf-8", "replace"))
        if obj.get("code") != 200:
            raise RuntimeError(f"替代料接口 code={obj.get('code')} msg={obj.get('msg')}")
        res = obj.get("result") or {}
        main = res.get("mainProduct") or {}

        def ladder_of(node):
            out = []
            for p in node.get("productPriceList") or []:
                try:
                    out.append({"qty_from": int(p.get("startPurchasedNumber") or 0),
                                "qty_to": int(p.get("endPurchasedNumber") or 0),
                                "price": float(p.get("productPrice") or 0)})
                except (TypeError, ValueError):
                    continue
            return out

        groups = {}
        rows = []
        for grp in ("all", "domestic", "internation", "sameBrand"):
            g = res.get(grp) or {}
            groups[grp] = len(g.get("substitutes") or [])
            if grp != "all":
                continue
            for it in g.get("substitutes") or []:
                rows.append({
                    "code": it.get("productCode"),
                    "model": it.get("productModel"),
                    "brand": it.get("productGradePlateName"),
                    "package": it.get("encapsulationModel"),
                    "stock": it.get("stockNumber"),
                    "smt_stock": it.get("smtStockNumber"),
                    "sim": it.get("simScore"),
                    "label": it.get("subLabel"),
                    "domestic": it.get("isDomestic"),
                    "delivery": it.get("deliveryTimeWayDays"),
                    "params": {k: strip_html(v) for k, v in (it.get("paramLinkedMap") or {}).items()},
                    "ladder": ladder_of(it),
                })
        out = {
            "code": code,
            "model": main.get("productModel"),
            "package": main.get("mainEncapsulationModel") or main.get("encapsulationModel"),
            "brand": main.get("productGradePlateName"),
            "source_params": {k: strip_html(v) for k, v in (main.get("mainParamLinkedMap") or {}).items()},
            "groups": groups,
            "alternates": rows,
            "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if self.use_cache:
            cache_put(key, out)
        return out

    def alternates(self, product_code, qty=1, limit=10, enrich=True):
        """替代料：优先立创 substitute 接口 → 海外站 alternatePartList → 同型号兜底。"""
        try:
            sub = self.substitutes(product_code)
            rows = []
            for r in sub["alternates"][:limit]:
                row = dict(r)
                row["cny_price"] = price_from_ladder(r.get("ladder") or [], qty)
                row["cny_stock"] = r.get("stock")
                rows.append(row)
            return {"code": sub["code"], "model": sub["model"], "package": sub["package"],
                    "source": f"立创替代料接口（全部 {sub['groups'].get('all')} 条，"
                              f"国产 {sub['groups'].get('domestic')} 条，同品牌 {sub['groups'].get('sameBrand')} 条）",
                    "source_params": sub["source_params"], "qty": qty,
                    "alternates": rows, "fetched": sub["fetched"]}
        except Exception:  # noqa: BLE001
            pass
        src = None
        alts = []
        try:
            detail = self.intl_detail(product_code)
            src = {"code": detail["code"], "model": detail["model"],
                   "package": detail["package"], "params": detail["params"]}
            alts = detail["alternates"]
            source = "海外站 alternatePartList"
        except Exception as e:  # noqa: BLE001
            source = f"同型号兜底（海外站不可用：{type(e).__name__}）"
            rec0 = self.lookup(product_code)
            if not rec0:
                return {"code": product_code, "source": source, "source_params": {},
                        "alternates": []}
            src = {"code": rec0["code"], "model": rec0["model"],
                   "package": rec0["package"], "params": rec0["params"]}
            same = self.search(rec0["model"], limit=30, sort="price_asc")
            base = (rec0["model"] or "").strip().lower()

            def same_part(m):
                m = (m or "").strip().lower()
                # 同型号：完全相同，或只多一个包装后缀（TR/T&R/REEL…），避免把开发板/别家型号当替代
                return m == base or (m.startswith(base) and len(m) - len(base) <= 4)

            alts = [{"code": r["code"], "model": r["model"], "brand": r["brand"],
                     "package": r["package"], "stock": r["stock"], "smt": None,
                     "params": r["params"]}
                    for r in same["records"]
                    if r["code"] != src["code"] and same_part(r["model"])]

        rows = []
        for a in alts[:limit]:
            row = dict(a)
            row["cny_price"] = None
            row["cny_stock"] = None
            if enrich:
                try:
                    rec = self.lookup(a["code"], demand_number=str(qty))
                    if rec:
                        row["cny_price"] = price_at(rec, qty)
                        row["cny_stock"] = rec["stock"]
                        row["sales"] = rec["sales"]
                except Exception:  # noqa: BLE001
                    pass
            rows.append(row)
        return {"code": src["code"], "model": src["model"], "package": src["package"],
                "source": source, "source_params": src["params"], "qty": qty,
                "alternates": rows,
                "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds")}


# ----------------------------------------------------------------------------- normalize
def normalize(record):
    vo = record.get("productVO") or {}
    params = {k: strip_html(v) for k, v in (record.get("paramLinkedMap") or {}).items()}
    ladder = []
    for p in vo.get("productPriceList") or []:
        try:
            a = int(p.get("startPurchasedNumber") or 0)
        except (TypeError, ValueError):
            a = 0
        try:
            b = int(p.get("endPurchasedNumber") or 0)
        except (TypeError, ValueError):
            b = 0
        price = p.get("productPrice")
        ladder.append({"qty_from": a, "qty_to": b, "price": price})
    ladder.sort(key=lambda x: x["qty_from"])
    pid = vo.get("productId")
    return {
        "code": vo.get("productCode"),
        "model": vo.get("productModel"),
        "name": vo.get("productName"),
        "brand": vo.get("productGradePlateName"),
        "package": vo.get("encapsulationModel") or record.get("lightStandard"),
        "type": vo.get("productType"),
        "type_code": vo.get("productTypeCode"),
        "spec": (record.get("lightProductIntro") or "").strip(),
        "params": params,
        "stock": vo.get("validStockNumber") if vo.get("validStockNumber") is not None else vo.get("stockNumber"),
        "total_stock": record.get("totalStockNumber"),
        "sales": vo.get("recentlySalesCount"),
        "in_stock": vo.get("hasStockNow") == "yes",
        "min_buy": vo.get("minBuyNumber"),
        "reel": vo.get("productMinEncapsulationNumber"),
        "reel_unit": vo.get("productMinEncapsulationUnit"),
        "ladder": ladder,
        # 手册直链不在这里给：旧 URL 已失效，真链接每次都要从商品页换签名 → Lcsc.datasheet_pdf()
        "datasheet": None,
        "url": ITEM_URL.format(product_id=pid) if pid else None,
        "product_id": pid,
        "smt": vo.get("smtLabel"),
        "delivery_days": vo.get("deliveryTimeWayDays"),
    }


def price_at(rec, qty=1):
    """按阶梯取单价。qty 超过最高档时用最高档价格。"""
    if not rec:
        return None
    ladder = rec.get("ladder") or []
    if not ladder:
        return None
    for tier in ladder:
        to_ = tier["qty_to"] or 10 ** 12
        if tier["qty_from"] <= qty <= to_:
            return tier["price"]
    return ladder[-1]["price"]


def price_from_ladder(ladder, qty=1):
    """给裸阶梯价列表（substitute 接口返回的格式）按数量取单价。"""
    return price_at({"ladder": ladder or []}, qty)


# ----------------------------------------------------------------------------- render
def print_search(res, qty=1, show_params=False, params_keys=None):
    recs = res["records"]
    print(f"关键词: {res['keyword']}  共 {res.get('total')} 条 / {res.get('count_page')} 页  "
          f"排序sign={res.get('sort_sign')}")
    if res.get("brands"):
        bs = "、".join(f"{b.get('label')}({b.get('count')})" for b in res["brands"][:8])
        print(f"品牌分布: {bs}")
    if res.get("packages"):
        ps = "、".join(f"{p.get('label')}({p.get('count')})" for p in res["packages"][:10])
        print(f"封装分布: {ps}")
    print()
    head = ["#", "编号", "型号", "品牌", "封装", f"单价@{qty}", "库存", "销量", "起订", "网址"]
    widths = [3, 12, 26, 14, 14, 10, 9, 8, 6, 30]
    print(" ".join(pad(h, w) for h, w in zip(head, widths)))
    print(" ".join("-" * w for w in widths))
    for i, r in enumerate(recs, 1):
        row = [
            str(i),
            r.get("code") or "-",
            (r.get("model") or "-")[:24],
            (r.get("brand") or "-")[:12],
            (r.get("package") or "-")[:12],
            money(price_at(r, qty)),
            str(r.get("stock") if r.get("stock") is not None else "-"),
            str(r.get("sales") if r.get("sales") is not None else "-"),
            str(r.get("min_buy") if r.get("min_buy") is not None else "-"),
            r.get("url") or "-",
        ]
        print(" ".join(pad(c, w) for c, w in zip(row, widths)))
        if show_params:
            keys = params_keys or list(r.get("params") or {})[:6]
            ps = "；".join(f"{k}={r['params'].get(k)}" for k in keys if k in (r.get("params") or {}))
            if ps:
                print("    " + ps)
    print()


def _client(a):
    """按命令行参数构造客户端（--rate 控制请求间隔，默认 1.0s，即 QPS≤1）。"""
    return Lcsc(rate_limit=float(getattr(a, "rate", 1.0) or 1.0), use_cache=not a.no_cache)


def cmd_search(a):
    cli = _client(a)
    kw = dict(sort=a.sort, page_size=30, price_min=a.price_min, price_max=a.price_max,
              spot=1)  # spotFilter 只认 1；--include-out-of-stock 不影响服务端（缺货靠 stock 字段判断）
    if a.brand:
        bid = cli.resolve_brand_id(a.keyword, a.brand)
        if not bid:
            print(f"[warn] 未找到品牌 {a.brand}，忽略品牌过滤", file=sys.stderr)
        else:
            kw["brand_id"] = bid
    if a.package:
        kw["package"] = cli.resolve_package(a.keyword, a.package)
    res = cli.search(a.keyword, limit=a.limit, **kw)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print_search(res, qty=a.qty, show_params=a.show_params, params_keys=a.param)


def cmd_price(a):
    cli = _client(a)
    rec = cli.lookup(a.code)
    if not rec:
        print(f"未找到 {a.code}")
        return 2
    unit = price_at(rec, a.qty)
    print(json.dumps({
        "code": rec["code"], "model": rec["model"], "brand": rec["brand"],
        "package": rec["package"], "qty": a.qty, "unit_price": unit,
        "total": round(unit * a.qty, 4) if unit is not None else None,
        "stock": rec["stock"], "sales": rec["sales"], "min_buy": rec["min_buy"],
        "ladder": rec["ladder"], "url": rec["url"],
        "datasheet_hint": f"python lcsc.py detail {rec['code']} --pdf",
        "params": rec["params"],
    }, ensure_ascii=False, indent=1))


def cmd_detail(a):
    cli = _client(a)
    rec = cli.lookup(a.code)
    if not rec:
        print(f"未找到 {a.code}")
        return 2
    print(f"{rec['code']}  {rec['model']}")
    print(f"  {rec['name']}")
    print(f"  品牌: {rec['brand']}   封装: {rec['package']}   类目: {rec['type']}")
    print(f"  库存: {rec['stock']}（含渠道 {rec['total_stock']}） 近期销量: {rec['sales']}  "
          f"起订: {rec['min_buy']}  整盘: {rec['reel']}{rec['reel_unit'] or ''}")
    print(f"  阶梯价: " + "  ".join(f"{t['qty_from']}-{t['qty_to']}:{money(t['price'])}" for t in rec["ladder"]))
    print(f"  {rec['url']}")
    if a.pdf or a.download:
        url, path = cli.datasheet_pdf(a.code, download=a.download)
        if url:
            print(f"  数据手册: {url}")
            if path:
                print(f"  已下载: {path}（{path.stat().st_size} 字节）→ 用 read-pdf skill 读")
        else:
            print("  数据手册: 商品页里没有 PDF 链接（该料确实没上传手册；"
                  "若是 WAF 拦截会直接报错而不是这句话）")
    else:
        print("  数据手册: 加 --pdf 取直链（旧的 datasheet.lcsc.com 直链已失效）")
    if rec["params"]:
        print("  参数:")
        for k, v in rec["params"].items():
            print(f"    {k}: {v}")
    if a.json:
        print(json.dumps(rec, ensure_ascii=False, indent=1))


def cmd_compare(a):
    rows = []
    cli = _client(a)
    for code in a.codes:
        rec = cli.lookup(code)
        if rec:
            rows.append(rec)
    if not rows:
        print("都没找到")
        return 2
    keys = []
    for r in rows:
        for k in r.get("params") or {}:
            if k not in keys:
                keys.append(k)
    w = [18] + [20] * len(rows) + [10]
    print(" ".join(pad(h, x) for h, x in zip(["参数"] + [r["code"] + " " + (r["model"] or "")[:12] for r in rows] + [f"单价@{a.qty}"], w)))
    print(" ".join("-" * x for x in w))
    for k in keys:
        vals = [str((r.get("params") or {}).get(k, "-")) for r in rows]
        print(" ".join(pad(h, x) for h, x in zip([k] + vals + [""], w)))
    extra = [
        ("品牌", [r.get("brand") or "-" for r in rows]),
        ("封装", [r.get("package") or "-" for r in rows]),
        ("库存", [str(r.get("stock")) for r in rows]),
        ("销量", [str(r.get("sales")) for r in rows]),
        ("阶梯价", [f"{money(r['ladder'][0]['price'])}→{money(r['ladder'][-1]['price'])} ({len(r['ladder'])}档)" for r in rows]),
    ]
    for name, vals in extra:
        print(" ".join(pad(h, x) for h, x in zip([name] + vals + [""], w)))
    prices = [price_at(r, a.qty) for r in rows]
    print(" ".join(pad(h, x) for h, x in zip(["单价"] + [money(p) for p in prices] + [""], w)))
    ok = [p for p in prices if p]
    if ok:
        best = min(range(len(rows)), key=lambda i: prices[i] if prices[i] else 9e9)
        print(" ".join(pad(h, x) for h, x in zip(["最低"] + ["" for _ in rows] + [money(prices[best])], w)) + f"  <-- {rows[best]['code']}")
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))


def cmd_alternate(a):
    cli = _client(a)
    res = cli.alternates(a.code, qty=a.qty, limit=a.limit, enrich=not a.no_enrich)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    print(f"源料：{res['code']}  {res.get('model') or ''}  封装 {res.get('package') or '-'}")
    print(f"来源：{res['source']}\n")
    if not res["alternates"]:
        print("没有查到替代料。")
        return 0
    hdr = ["C号", "相似", "型号", "品牌", "封装", "库存", f"单价@{a.qty}", "参数差异"]
    rows = []
    src_params = res.get("source_params") or {}
    for r in res["alternates"]:
        diff = []
        for k, v in (r.get("params") or {}).items():
            sv = src_params.get(k)
            if sv is not None and sv != v:
                diff.append(f"{k}:{sv}→{v}")
        rows.append([
            r.get("code") or "-",
            (f"{r['sim']:.0f}" if isinstance(r.get("sim"), (int, float)) else "-"),
            (r.get("model") or "")[:22],
            (r.get("brand") or "")[:14],
            (r.get("package") or "")[:16],
            str(r.get("cny_stock") if r.get("cny_stock") is not None else (r.get("stock") or "-")),
            money(r.get("cny_price")),
            "; ".join(diff)[:56] or "-",
        ])
    widths = [10, 5, 23, 15, 17, 8, 9, 56]
    print(" ".join(pad(h, w) for h, w in zip(hdr, widths)))
    print(" ".join("-" * w for w in widths))
    for row in rows:
        print(" ".join(pad(str(c), w) for c, w in zip(row, widths)))
    print("\n提示：替代料必须按品类风险档人工确认（见 references/spec-check.md §1.3）；"
          "「参数差异」列只列接口返回的参数，未列出的参数不代表相同。")


def cmd_cookie(a):
    """用真实浏览器（Kimi WebBridge）取一次 so.szlcsc.com 的 cookie 并落盘。

    立创的反爬（HTTP 203 + tws2_ 挑战）本质是「让 JS 算一个 cookie 再放行」，
    浏览器里 JS 跑完就有了。取到的 cookie 存到 COOKIE_FILE，之后所有请求自动带上。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import taobao  # 同目录，复用它的 WebBridge 客户端
    except ImportError as e:
        print(f"取 cookie 需要同目录的 taobao.py（Kimi WebBridge 客户端）：{e}", file=sys.stderr)
        return 2
    br = taobao.Bridge(session="bom-sourcing", timeout=120)
    st = br.status()
    if not st.get("running") or not st.get("extension_connected"):
        print("WebBridge 未就绪（daemon 或浏览器扩展未连接）。先启动 Kimi WebBridge。", file=sys.stderr)
        return 2
    print("[1/3] 打开 so.szlcsc.com（让 JS 跑完反爬挑战）…")
    br.navigate("https://so.szlcsc.com/global.html?k=STM32F103C8T6", new_tab=True,
                group_title="配单比价")
    for i in range(1, 7):
        time.sleep(2)
        ck = br.evaluate("document.cookie") or ""
        if "tws2_" in ck:
            print(f"[2/3] 拿到 cookie（第 {i} 次轮询，{len(ck)} 字符）")
            break
    else:
        print("没等到 tws2_ cookie：挑战可能没触发（那就说明已解封，直接跑 search 即可）",
              file=sys.stderr)
        return 1
    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    COOKIE_FILE.write_text(ck, "utf-8")
    print(f"[3/3] 已保存到 {COOKIE_FILE}")
    if a.show:
        print("cookie:", ck)
    else:
        print("关键项:", ", ".join(k for k in ck.split("; ") if k.startswith(("tws2_", "isLogin", "ssxmod"))))
    print("验证：python lcsc.py search STM32F103C8T6 --limit 3")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="立创商城检索/比价/指标 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="关键词检索")
    s.add_argument("keyword")
    s.add_argument("--sort", default="relevance",
                   help="relevance|price_asc|price_desc|stock_asc|stock_desc|sales_desc")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--qty", type=int, default=1, help="按此数量显示单价")
    s.add_argument("--brand", default="", help="品牌关键字，如 ST / 厚声 / TI")
    s.add_argument("--package", default="", help="封装，如 0603 / LQFP-48")
    s.add_argument("--price-min", default="")
    s.add_argument("--price-max", default="")
    s.add_argument("--include-out-of-stock", action="store_true",
                    help="服务端 spotFilter 只认 1（这里保留参数兼容旧脚本）；"
                         "缺货与否看输出的「库存」列")
    s.add_argument("--show-params", action="store_true")
    s.add_argument("--param", nargs="*", default=None, help="只显示这些参数键")
    s.add_argument("--json", action="store_true")
    s.add_argument("--no-cache", action="store_true")
    s.set_defaults(func=cmd_search)

    p = sub.add_parser("price", help="按数量取价")
    p.add_argument("code")
    p.add_argument("--qty", type=int, default=1)
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    p.set_defaults(func=cmd_price)

    d = sub.add_parser("detail", help="查看参数详情（--pdf 取数据手册直链）")
    d.add_argument("code")
    d.add_argument("--pdf", action="store_true", help="解析数据手册 PDF 的签名直链")
    d.add_argument("--download", nargs="?", const=".", default=None,
                   help="下载 PDF（可给目录或文件路径；省略参数则存当前目录）")
    d.add_argument("--json", action="store_true")
    d.add_argument("--no-cache", action="store_true")
    d.set_defaults(func=cmd_detail)

    c = sub.add_parser("compare", help="多型号指标对比")
    c.add_argument("codes", nargs="+")
    c.add_argument("--qty", type=int, default=1)
    c.add_argument("--json", action="store_true")
    c.add_argument("--no-cache", action="store_true")
    c.set_defaults(func=cmd_compare)

    al = sub.add_parser("alternate", help="替代料（立创 substitute 接口，含国产替代）")
    al.add_argument("code")
    al.add_argument("--qty", type=int, default=1)
    al.add_argument("--limit", type=int, default=10)
    al.add_argument("--no-enrich", action="store_true", help="不回填中文站人民币价格")
    al.add_argument("--json", action="store_true")
    al.add_argument("--no-cache", action="store_true")
    al.set_defaults(func=cmd_alternate)

    ck = sub.add_parser("cookie", help="用真实浏览器取一次立创 cookie（反爬时用）")
    ck.add_argument("--show", action="store_true", help="打印 cookie（默认只报长度与关键项）")
    ck.set_defaults(func=cmd_cookie)

    for _p in sub.choices.values():  # 所有子命令共享限速参数
        _p.add_argument("--rate", type=float, default=1.0,
                        help="请求间隔秒数（默认 1.0，即 QPS≤1；被反爬时调大）")

    a = ap.parse_args(argv)
    try:
        return a.func(a) or 0
    except AntiBotError as e:
        print(f"[反爬] {e}", file=sys.stderr)
        print(e.hint or _ANTIBOT_HINT, file=sys.stderr)
        return AntiBotError.exit_code


if __name__ == "__main__":
    sys.exit(main())
