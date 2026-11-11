#!/usr/bin/env python3
"""淘宝 / 1688 检索（按销量 / 价格排序，价格单位归一）——走本机 Kimi WebBridge 驱动真实浏览器。

依赖：本机运行着 Kimi WebBridge daemon（默认 http://127.0.0.1:10086）且浏览器扩展已连接；
     淘宝需要浏览器里已登录淘宝账号（1688 免登录即可）。

用法：
    python scripts/taobao.py check
    python scripts/taobao.py search "10k 0603 电阻" --limit 20
    python scripts/taobao.py search "STM32F103C8T6" --site 1688 --sort sales --limit 20
    python scripts/taobao.py search "NE555" --sort price_asc --json out.json

纯标准库，Python 3.10+（实测 3.14）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

DAEMON = os.environ.get("KIMI_WEBBRIDGE_URL", "http://127.0.0.1:10086").rstrip("/")
DEFAULT_SESSION = "bom-sourcing"
GROUP_TITLE = "配单比价"
JS_DIR = Path(__file__).resolve().parent / "js"
STATE_FILE = Path(tempfile.gettempdir()) / "bom-sourcing-taobao-state.json"
MIN_INTERVAL = 3.0  # 同一站点两次检索最小间隔（秒）

EXIT_OK, EXIT_USAGE, EXIT_DAEMON, EXIT_BLOCKED, EXIT_EMPTY = 0, 2, 3, 4, 5

SITES = {
    "taobao": {
        "name": "淘宝",
        "search_url": "https://s.taobao.com/search?q={q}",
        "sort_label": {"sales": "销量", "price_asc": "价格", "price_desc": "价格"},
        "needs_login": True,
    },
    "1688": {
        "name": "1688",
        "search_url": "https://s.1688.com/selloffer/offer_search.htm?keywords={q}",
        # 实测：销量排序可直接用 URL 参数，免登录生效
        "sort_suffix": {"sales": "&sortType=va_sales360&descendOrder=true&beginPage=1"},
        "needs_login": False,
    },
}


# --------------------------------------------------------------------------- 输出
def _u8():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def money(v):
    if v is None:
        return "-"
    if v >= 1:
        return f"¥{v:.2f}"
    if v >= 0.01:
        return f"¥{v:.4f}"
    return f"¥{v:.5f}"


def cut(s, n):
    s = "" if s is None else str(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# --------------------------------------------------------------------------- 单位归一
_UNIT = r"(?:个|只|片|支|条|粒|颗|pcs)"
# 「1-100片」「10~100个」是数量区间（起订/阶梯），不是包装规格
_RANGE_RE = re.compile(r"(\d{1,6})\s*(?:-|~|—|－|–|至|到)\s*(\d{1,6})\s*" + _UNIT, re.I)
_PACK_RE = re.compile(r"(\d{1,6})\s*" + _UNIT, re.I)
_TOTAL_RE = re.compile(r"共\s*(\d{1,6})\s*" + _UNIT, re.I)
_BULK_ONLY_RE = re.compile(r"(盘|包|卷|盒|管)\s*(?:装)?$|整盘|1\s*(?:盘|包|卷|管)")
# 混装/套装：一单里是「多个不同型号」，价格不能折成任何单一型号的单只价
_ASSORT_RE = re.compile(r"芯片包|元件包|阻容包|元器件包|套装|套餐|组合装|混装|样品盒|样品包|整包|一盒|散装包|分类盒|\d{1,3}\s*种")


def detect_assortment(title, extra=""):
    """标题是否属于「混装/套装」（多个不同型号打包卖）。"""
    return bool(_ASSORT_RE.search(f"{title or ''} {extra or ''}"))


def detect_unit(title, extra="", price=None):
    """从标题/摘要里推断「一单含多少只」，返回 (pack_qty, note, confidence)。

    淘宝/1688 的阻容常按「包」「100PCS」卖，价格必须除以数量才是单只价。
    推断不出来时返回 (None, "", "none")，调用方不要拿它当单只价用。
    「1-100片」这类数量区间不是包装规格，一律不归一（否则会算出 1 分钱一颗的假信号）。
    """
    text = f"{title or ''} {extra or ''}"
    m = _RANGE_RE.search(text)
    if m:
        a, b = m.group(1), m.group(2)
        lo, hi = sorted((int(a), int(b)))
        if hi <= 100000 and lo < hi:
            return None, f"数量区间 {lo}-{hi}（起订/阶梯，非包装数量）", "none"
    m = _TOTAL_RE.search(text)
    if m:
        q = int(m.group(1))
        if 2 <= q <= 100000:
            return q, f"共{q}个/包", "high"
    m = _PACK_RE.search(text)
    if m:
        q = int(m.group(1))
        if 2 <= q <= 100000:
            return q, f"{q}个/份", "high" if q >= 10 else "low"
    if _BULK_ONLY_RE.search(text):
        return None, "按包/盘计价（数量未标注）", "none"
    return None, "", "none"


# --------------------------------------------------------------------- 品类与非料件
# 这些标题不是「一颗/一只可比的元器件」：开发板、成品模块、混装包、系列链接。
# 单只价对它们不成立，直接参与比价会把结论带偏（实测：STM32 搜索前 8 条里 5 条是开发板）。
_DEVBOARD_RE = re.compile(
    r"开发板|核心板|最小系统|学习板|实验板|评估板|demo\s*板|系统板|单片机板|转接板|底板|扩展板",
    re.I)
_MODULE_RE = re.compile(
    r"电源模块|降压模块|升压模块|稳压模块|转接座|转接头|适配器|模块板|传感器模块|继电器模块",
    re.I)
# 一条链接挂多个阻值/容值（"1k 2k 4.7k 10k …"）→ 价格是起价，不能当单只价
_RC_VAL_RE = re.compile(
    r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?\s*(?:[RrKkMm]\d*|Ω|欧|[uUnNpP]F)(?![A-Za-z0-9])")
_GLUED_VAL_RE = re.compile(r"\d+(?:\.\d+)?[kKmMrR](?![A-Za-z])")
_GLUED_CAP_RE = re.compile(r"\d+(?:\.\d+)?\s*[UuNnPp](?=[\d.])")


def detect_series(title):
    """标题像「一条链接挂多个型号/阻值/容值」→ True（价格是起价，不能折算单只）。"""
    if "系列" in (title or ""):
        return True
    n = (len(_RC_VAL_RE.findall(title or ""))
         + len(_GLUED_VAL_RE.findall(title or ""))
         + len(_GLUED_CAP_RE.findall(title or "")))
    return n >= 2


def classify_kind(title, extra=""):
    """判定条目类型：devboard / module / assortment / series / part（真正可比的元器件）。

    只有 `part` 才允许参与「单只价」比较；其余一律标注后剔除（`--all` 可显示）。
    """
    text = f"{title or ''} {extra or ''}"
    if detect_assortment(title, extra):
        return "assortment"
    if _DEVBOARD_RE.search(text):
        return "devboard"
    if _MODULE_RE.search(text):
        return "module"
    if detect_series(text):
        return "series"
    return "part"


KIND_CN = {"part": "元器件", "devboard": "开发板", "module": "成品模块",
           "assortment": "混装包", "series": "系列链接"}

# --------------------------------------------------------------------- 成色（真伪风险）
# 口径（用户 2026-11-11 定）：**没要求量产/高可靠时，拆机件可用，只标注**；
# 一旦用户提了量产/车规/高可靠，才据此剔除。
_COND_RULES = [
    ("翻新", re.compile(r"翻新|打磨|抛光|重打字|改标|洗标|重新打码", re.I)),
    ("拆机", re.compile(r"拆机|拆板|二手|回收|议价|旧件|拆件", re.I)),
    ("散新", re.compile(r"散新|散装新|库存散", re.I)),
    ("国产替代", re.compile(r"国产替代|国产|兼容|可代替|代用|替换型", re.I)),
    ("原装", re.compile(r"原装|正品原装|全新原装|进口原装|原厂", re.I)),
    ("全新", re.compile(r"全新|新品|新货", re.I)),
]
COND_RISK = {"翻新": "高", "拆机": "中", "散新": "中", "国产替代": "中", "原装": "低", "全新": "低",
             "未标明": "未知"}
# 量产/高可靠场景下拒绝的成色（拆机/散新/翻新都不行；国产替代要看具体件，先保留但提示）
COND_REJECT_IN_PRODUCTION = ("翻新", "拆机", "散新")


def detect_condition(title, extra=""):
    """从标题推断成色：翻新 > 拆机 > 散新 > 国产替代 > 原装 > 全新 > 未标明。

    卖家标题里的「原装正品」只是自述（claim），不能当证据；这里只做**标注**，
    除非用户明确要求量产/高可靠，否则不改动价格比较的结果。
    """
    text = f"{title or ''} {extra or ''}"
    for tag, rx in _COND_RULES:
        if rx.search(text):
            return tag, [tag]
    return "未标明", []


# 卡片上的服务标签（淘宝搜索页没有独立字段，只能从卡片文本里抓）
_SERVICE_RULES = [
    ("包邮", re.compile(r"包邮")),
    ("退货宝", re.compile(r"退货宝|退货运费险")),
    ("先鉴后发", re.compile(r"先鉴后发|先鉴定")),
    ("对公支付", re.compile(r"对公支付|对公转账")),
    ("企业购", re.compile(r"企业购")),
    ("技术文档", re.compile(r"技术文档")),
    ("当日发", re.compile(r"当日发|当天发")),
    ("24h发", re.compile(r"24\s*小时内发")),
    ("48h发", re.compile(r"48\s*小时内发")),
]


def detect_services(*texts):
    """从卡片文本里抓服务标签（包邮/退货宝/先鉴后发/对公支付/发货时效…）。

    淘宝搜索页**没有独立的包邮字段**，包邮只以文本标签出现，而且相当多链接根本不显示
    → 「包邮筛选」只能尽力而为：一条都没标时要明确说"本页没有标包邮的链接"，不能静默清空。
    """
    text = " ".join(t for t in texts if t)
    return [name for name, rx in _SERVICE_RULES if rx.search(text)]


def daemon_start_hint():
    """daemon 没起来时给出可直接复制的启动命令（二进制不在 PATH，必须绝对路径）。"""
    exe = Path(os.environ.get("USERPROFILE") or Path.home()) / ".kimi-webbridge" / "bin" / "kimi-webbridge.exe"
    if not exe.exists():
        exe = Path.home() / ".kimi-webbridge" / "bin" / "kimi-webbridge"
    return (f"daemon 没在跑。启动（幂等，已启动就 no-op）：\n"
            f"  & \"{exe}\" start\n"
            f"  然后确认：& \"{exe}\" status   # extension_connected 要为 true")


# --------------------------------------------------------------------------- WebBridge
class BridgeError(RuntimeError):
    def __init__(self, message, exit_code=EXIT_DAEMON, hint=""):
        super().__init__(message)
        self.exit_code = exit_code
        self.hint = hint


class Bridge:
    """Kimi WebBridge 客户端：POST /command，body {action, args, session}。"""

    def __init__(self, session=DEFAULT_SESSION, timeout=120, trace=False):
        self.session = session
        self.timeout = timeout
        self.trace = trace

    # -- 传输
    def _post(self, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        fd, path = tempfile.mkstemp(prefix="wb-req-", suffix=".json")
        os.close(fd)
        p = Path(path)
        try:
            p.write_bytes(body)  # 写临时 JSON 文件：避开 Windows shell 的引号/编码问题
            data = p.read_bytes()
            req = urllib.request.Request(
                self.daemon_url("/command"), data=data,
                headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8", "replace")
            except urllib.error.URLError as e:
                if isinstance(getattr(e, "reason", None), ConnectionRefusedError) or "refused" in str(e):
                    raise BridgeError(
                        f"连不上 WebBridge daemon（{DAEMON}）", EXIT_DAEMON,
                        "先启动 Kimi WebBridge：浏览器扩展需已安装并连接；"
                        "可跑 `kimi-webbridge status` 或访问 " + DAEMON + "/status 自检。") from None
                raise BridgeError(f"请求失败：{e}", EXIT_DAEMON) from None
        finally:
            try:
                p.unlink()
            except OSError:
                pass
        if self.trace:
            print(f"[trace] {payload['action']} → {len(raw)} bytes", file=sys.stderr)
        try:
            env = json.loads(raw)
        except ValueError:
            raise BridgeError(f"daemon 返回非 JSON：{raw[:200]}", EXIT_DAEMON) from None
        if not env.get("ok"):
            err = env.get("error") or {}
            raise BridgeError(f"{err.get('code', 'ERROR')}: {err.get('message', raw[:200])}", EXIT_DAEMON)
        return env.get("data")

    @staticmethod
    def daemon_url(path):
        return DAEMON + path

    # -- 命令
    def status(self):
        try:
            with urllib.request.urlopen(self.daemon_url("/status"), timeout=10) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            raise BridgeError(f"连不上 WebBridge daemon（{DAEMON}）：{e}", EXIT_DAEMON,
                              "先启动 Kimi WebBridge daemon 与浏览器扩展。") from None

    def navigate(self, url, new_tab=False, group_title=None):
        args = {"url": url, "newTab": bool(new_tab)}
        if group_title:
            args["group_title"] = group_title
        return self._post({"action": "navigate", "args": args, "session": self.session})

    def evaluate(self, code):
        data = self._post({"action": "evaluate", "args": {"code": code}, "session": self.session})
        if not isinstance(data, dict):
            return data
        return data.get("value", data)

    def list_tabs(self):
        return self._post({"action": "list_tabs", "args": {}, "session": self.session})


# --------------------------------------------------------------------------- 限流
def throttle(site):
    """跨进程节流：同一站点两次检索间隔 >= MIN_INTERVAL 秒。"""
    try:
        state = json.loads(STATE_FILE.read_text("utf-8")) if STATE_FILE.exists() else {}
    except Exception:
        state = {}
    last = state.get(site)
    now = time.time()
    if last:
        wait = MIN_INTERVAL - (now - last)
        if wait > 0:
            time.sleep(min(wait, MIN_INTERVAL))
    state[site] = time.time()
    try:
        STATE_FILE.write_text(json.dumps(state), "utf-8")
    except Exception:
        pass


# --------------------------------------------------------------------------- 检索
def js(name):
    p = JS_DIR / name
    if not p.exists():
        raise BridgeError(f"缺少 JS 资源 {p}", EXIT_USAGE, "skill 目录不完整，重装 skill。")
    return p.read_text("utf-8")


def eval_json(br, code):
    raw = br.evaluate(code)
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        raise BridgeError(f"页面返回值不是 JSON：{str(raw)[:200]}", EXIT_DAEMON) from None


def _taobao_read(br, max_items, max_scrolls, fallback=True):
    """调 playbook 的 taobao_get_search_results；返回 (items, data, raw, used_fallback, fb_params)。"""
    code = (
        js("taobao_search_fn.js")
        + "\n;(async () => {"
        + f"const r = await taobao_get_search_results({{maxItems: {max_items}, maxScrolls: {int(max_scrolls)}}});"
        + "const d = (r && r.data) || {};"
        + "if (Array.isArray(d.items)) { d.items = d.items.map(it => { delete it.rawText;"
        + " if (it.title) it.title = it.title.slice(0, 120); return it; }); }"
        + "return JSON.stringify(r); })()"
    )
    res = eval_json(br, code)
    data = res.get("data") if isinstance(res, dict) else None
    if not isinstance(data, dict):
        data = res if isinstance(res, dict) else {}
    items = data.get("items") or []
    used_fallback = False
    fb_params = None
    if not items and fallback:
        fb = eval_json(br, js("taobao_fallback.js"))
        used_fallback = True
        fb_params = fb.get("params")
        items = [
            {
                "itemId": it.get("itemId"), "url": it.get("url"), "title": it.get("title"),
                "price": {"value": it.get("priceNum"), "text": it.get("priceText")},
                "salesText": it.get("salesText"), "salesCount": it.get("salesNum"),
                "shop": {"name": it.get("shop")}, "location": it.get("loc"),
                "sponsored": it.get("sponsored"), "attributes": [],
            }
            for it in (fb.get("items") or [])
        ]
    return items, data, res, used_fallback, fb_params


def search_taobao(br, keyword, sort, limit, max_scrolls, fallback=True):
    cfg = {"minCards": 5, "waitMs": 15000}
    if sort == "sales":
        cfg["sortLabel"] = "销量"

    br.navigate(f"https://s.taobao.com/search?q={quote(keyword)}",
                new_tab=False, group_title=GROUP_TITLE)
    time.sleep(1.2)
    state = eval_json(br, "globalThis.__BOM_CFG = " + json.dumps(cfg) + ";\n" + js("taobao_prep.js"))

    if not state.get("ok"):
        if state.get("verifyWall"):
            raise BridgeError("淘宝要求人机验证（验证码/滑块）", EXIT_BLOCKED,
                              "到浏览器里人工过一次验证后重跑。")
        raise BridgeError(
            f"淘宝搜索结果为空（卡片 0，页面 {state.get('bodyLen')} 字符）", EXIT_BLOCKED,
            "多半是淘宝登录态过期：在浏览器打开 taobao.com 扫码登录后重跑；"
            "注意这不是反爬——登录墙下 window.__last_search_params 仍然正常。")

    max_items = min(200, max(48, limit * 2))

    def _wait_cards(seconds=12.0, floor=5):
        """等卡片回来：点排序 tab 会触发整页重渲染，卡片节点先消失再回来。"""
        end = time.time() + seconds
        while time.time() < end:
            n = eval_json(br, "JSON.stringify(document.querySelectorAll('[class*=\"Card\"]').length)")
            try:
                n = int(n)
            except (TypeError, ValueError):
                n = 0
            if n >= floor:
                return n
            time.sleep(0.6)
        return 0

    cards = _wait_cards()
    if not cards:
        # 点完 tab 结果区没回来（实测淘宝偶发：整页只有导航和 AI 摘要，卡片 0）。
        # 退回「不点 tab 的干净搜索页」重取，排序改由客户端做（sort_items 已支持）。
        br.navigate(f"https://s.taobao.com/search?q={quote(keyword)}",
                    new_tab=False, group_title=GROUP_TITLE)
        time.sleep(1.2)
        cards = _wait_cards(seconds=15.0)
        if cards:
            state["recovered"] = True
            state["clickFailed"] = True
    if cards:
        state["cardCount"] = cards

    items, data, res, used_fallback, fb_params = _taobao_read(br, max_items, max_scrolls, fallback)
    if fb_params is not None:
        state["fallbackParams"] = fb_params

    sort_note = None
    if sort == "sales":
        applied = (state.get("params") or {}).get("sort")
        if applied != "_sale":
            sort_note = (f"页面排序 tab 未切到「销量」（sort={applied}），"
                         f"结果由客户端按销量数值排序")
    elif sort in ("price_asc", "price_desc"):
        # 实测：「价格」tab 点击后既不改 __last_search_params.sort、也不改 active 类名、
        # 且卡片顺序不变（点击未真正生效），所以价格排序做在客户端当前页上。
        sort_note = (f"价格{'升' if sort == 'price_asc' else '降'}序：客户端对当前页 "
                     f"{len(items)} 条排序（页面「价格」tab 点击实测无效，未使用）")

    return {
        "items": items,
        "page": state,
        "raw": res,
        "sort_applied": (state.get("params") or {}).get("sort"),
        "sort_note": sort_note,
        "total": data.get("totalResults") or (state.get("params") or {}).get("totalResults"),
        "used_fallback": used_fallback,
        "url": state.get("href"),
    }


def search_1688(br, keyword, sort, limit):
    suffix = SITES["1688"].get("sort_suffix", {}).get(sort, "")
    url = f"https://s.1688.com/selloffer/offer_search.htm?keywords={quote(keyword)}{suffix}"
    br.navigate(url, new_tab=False, group_title=GROUP_TITLE)
    time.sleep(1.2)
    fb = eval_json(br, js("ali1688_search.js"))
    st = fb.get("state") or {}
    if st.get("isLoginPage"):
        raise BridgeError("1688 跳到了登录页", EXIT_BLOCKED, "浏览器里打开 1688 后重试。")
    items = [
        {
            "itemId": it.get("offerId"), "url": it.get("url"), "title": it.get("title"),
            "price": {"value": it.get("priceMin"), "text": it.get("priceText"),
                      "min": it.get("priceMin"), "max": it.get("priceMax")},
            "salesText": it.get("soldText"), "salesCount": it.get("soldCount"),
            "shop": {"name": it.get("company")}, "location": None, "sponsored": False,
            "repeatRate": it.get("repeatRate"), "badges": it.get("badges") or [],
            "attributes": [], "cardText": it.get("cardText"),
        }
        for it in (fb.get("items") or [])
    ]
    if not items:
        raise BridgeError(f"1688 没解析到商品（页面 {st.get('bodyLen')} 字符）", EXIT_EMPTY,
                          "关键词可能过窄（如「0805 10K 1% 电阻」会 0 结果），缩短成「0805 10K 电阻」。")
    return {
        "items": items, "page": st, "raw": fb, "sort_applied": ("va_sales360" if sort == "sales" else None),
        "total": None, "used_fallback": False, "url": st.get("href") or url,
    }


# --------------------------------------------------------------------------- 归一 + 排序
def _shop_name(it):
    """店铺名：DOM 抽取给 {"name": ...}，也兼容直接是字符串（不同站点/版本）。"""
    raw = it.get("shop")
    if isinstance(raw, dict):
        return raw.get("name") or ""
    return raw or ""


def _shop_badges(it):
    """店铺标签：{"badges": [...]} 或扁平 badges，两种都容忍。"""
    raw = it.get("shop")
    if isinstance(raw, dict) and raw.get("badges"):
        return raw["badges"]
    return it.get("badges") or []


def _shop_blacklist(shop):
    """店铺名查黑名单（data/knowledge/blacklist.yaml 的 shops）；坏掉不影响检索。"""
    try:
        import blacklist as _bl
    except Exception:  # noqa: BLE001
        return []
    return [{"name": h["name"], "alias": h["alias"], "reason": h["reason"]}
            for h in _bl.check_shop(shop)]


def normalize(items, site):
    out = []
    for it in items:
        price = it.get("price") or {}
        pv = price.get("value")
        title = it.get("title") or ""
        extra = it.get("cardText") or " ".join(it.get("attributes") or [])
        assort = detect_assortment(title, extra)
        if assort:
            pack, note, conf = None, "混装/套装（含多个不同型号，不做单只价归一）", "none"
        else:
            pack, note, conf = detect_unit(title, extra, pv)
        unit_price = round(pv / pack, 6) if (pv and pack) else None
        kind = classify_kind(title, extra)
        cond, _cond_hits = detect_condition(title, extra)
        raw = it.get("rawText") or it.get("cardText") or ""
        services = detect_services(title, extra, raw)
        if kind != "part":
            # 开发板/模块/混装/系列链接：单只价不成立
            unit_price, conf = None, "none"
            note = f"{KIND_CN.get(kind, kind)}（不参与单只价比较）"
        out.append({
            "title": title,
            "kind": kind,
            "kind_cn": KIND_CN.get(kind, kind),
            "condition": cond,
            "condition_risk": COND_RISK.get(cond, "未知"),
            "condition_evidence": "卖家标题自述（未核）",
            "condition_verified": False,
            "services": services,
            "free_shipping": "包邮" in services,
            "delivery": next((s for s in services if s.endswith("发") or s in ("24h发", "48h发")), None),
            "price_raw": price.get("text") or "",
            "price_value": pv,
            "price_min": price.get("min", pv),
            "price_max": price.get("max", pv),
            "price_label": price.get("label") or "",
            "price_qualifier": price.get("qualifier") or "",
            "assortment": assort,
            "pack_qty": pack,
            "unit_price": unit_price,
            "unit_note": note,
            "unit_confidence": conf,
            "sales_text": it.get("salesText") or "",
            "sales_count": it.get("salesCount"),
            "shop": _shop_name(it),
            "shop_badges": _shop_badges(it),
            "shop_blacklisted": _shop_blacklist(_shop_name(it)),
            "location": it.get("location"),
            "repeat_rate": it.get("repeatRate"),
            "sponsored": bool(it.get("sponsored")),
            "item_id": it.get("itemId"),
            "url": it.get("url") or "",
        })
    return out


def sort_items(items, sort):
    """按请求的排序整理结果；广告（sponsored）永远沉底。"""
    real = [x for x in items if not x["sponsored"]]
    ads = [x for x in items if x["sponsored"]]
    if sort == "sales":
        real.sort(key=lambda x: (x["sales_count"] is None, -(x["sales_count"] or 0)))
    elif sort in ("price_asc", "price_desc"):
        real.sort(key=lambda x: (x["price_value"] is None, x["price_value"] or 0),
                  reverse=(sort == "price_desc"))
    return real, ads


def filter_items(items, price_min=None, price_max=None, free_shipping=False):
    """价格区间 / 包邮筛选。返回 (kept, dropped)，dropped 里带原因。

    价格用**标价**（`price_value`）而不是单只价：大量链接的包装数量不可知，
    用单只价筛选会把没标数量的真链接误杀。单只价的可靠性由 `comparable` 字段单独表达。
    """
    kept, dropped = [], []
    for x in items:
        p = x.get("price_value")
        if price_min is not None or price_max is not None:
            if p is None:
                dropped.append((x, "标价缺失，无法按价格区间筛"))
                continue
            if price_min is not None and p < price_min:
                dropped.append((x, f"标价 {money(p)} < 下限 {money(price_min)}"))
                continue
            if price_max is not None and p > price_max:
                dropped.append((x, f"标价 {money(p)} > 上限 {money(price_max)}"))
                continue
        if free_shipping:
            if "包邮" not in (x.get("services") or []):
                dropped.append((x, "未标包邮"))
                continue
        kept.append(x)
    return kept, dropped


# --------------------------------------------------------------------------- 渲染
def render_md(res, site, keyword, sort, limit, elapsed, show_all=False):
    all_sorted = res["sorted"]
    # 默认只显示「真正可比的元器件」；开发板/成品模块/混装包/系列链接单列统计后剔除
    parts = [x for x in all_sorted if x.get("kind", "part") == "part"]
    others = [x for x in all_sorted if x.get("kind", "part") != "part"]
    items = (all_sorted if show_all else parts)[:limit]
    ads = res["ads"]
    page = res["page"] or {}
    site_name = SITES[site]["name"]
    print(f"## {site_name} · {keyword}")
    print()
    print("| # | 标题 | 价格 | 单只价 | 成色 | 销量 | 店铺 | 链接 |")
    print("|---|------|------|--------|------|------|------|------|")
    for i, x in enumerate(items, 1):
        price = money(x["price_value"])
        if x["price_max"] and x["price_max"] != x["price_value"]:
            price = f"{money(x['price_value'])}~{money(x['price_max'])}"
        if x["price_qualifier"]:
            price += f"（{x['price_qualifier']}）"
        unit = money(x["unit_price"]) + f"/只（{x['unit_note']}）" if x["unit_price"] else "—"
        if x.get("kind", "part") != "part":
            unit = x.get("kind_cn") or "非料件"
        elif not x["unit_price"] and (x["unit_note"] or "").startswith("数量区间"):
            unit = "区间价"
        cond = x.get("condition") or "未标明"
        risk = x.get("condition_risk") or "未知"
        cond_cell = cond if risk == "低" and cond != "未标明" else f"{cond}({risk})"
        sales = x["sales_text"] or ("月销/回头率 " + str(x["repeat_rate"]) + "%" if x["repeat_rate"] else "—")
        shop = cut(x["shop"], 18) or "—"
        if x.get("shop_blacklisted"):
            shop = "⛔" + shop
        print(f"| {i} | {cut(x['title'], 46).replace('|', '/')} | {price} | {unit} | {cond_cell} | "
              f"{sales} | {shop} | {x['url']} |")
    bl = [(i, x) for i, x in enumerate(items, 1) if x.get("shop_blacklisted")]
    if bl:
        print()
        for i, x in bl:
            why = "、".join(h["name"] + (f"（{h['reason']}）" if h["reason"] else "")
                            for h in x["shop_blacklisted"])
            print(f"- ⛔ 第 {i} 条店铺命中黑名单：{x['shop']} —— {why}（`python blacklist.py list`）")
    print()
    print(f"- 实际 URL：{res['url']}")
    if site == "taobao":
        clk = (page.get("click") or {})
        after = (clk.get("after") or {})
        sort_note = f"页面排序 tab：{page.get('activeLabel') or '综合'}（sort={res['sort_applied']}）"
        if after and after.get("elapsedMs") is not None:
            sort_note += f"，点击耗时 {after.get('elapsedMs')}ms"
        if res.get("sort_note"):
            sort_note += "；" + res["sort_note"]
    else:
        sort_note = ("URL 参数 sortType=va_sales360&descendOrder=true（实测生效）"
                     if sort == "sales" else "默认综合排序")
    print(f"- 排序：{sort_note}")
    print(f"- 条数：{len(items)}（页面识别 {len(res['sorted']) + len(ads)} 条，其中广告 {len(ads)} 条已沉底）")
    if res.get("total"):
        print(f"- 结果总数：{res['total']}")
        print(f"- 页面声明每页：{page.get('params', {}).get('n')}")
    print(f"- 用时：{elapsed:.1f}s")
    if res.get("used_fallback"):
        print("- 注意：playbook 抽取为空，已回退到自写 DOM 抽取（字段可能较少）")
    if res.get("client_sorted"):
        print(f"- 注意：价格排序由客户端完成，只覆盖本页 {len(res['sorted']) + len(ads)} 条，"
              f"不代表全网最低价；要更低价需翻页或改关键词。")
    if sort in ("price_asc", "price_desc"):
        print("- 注意：淘宝大量「乱标价」（低价引流、区间价、按包计价），价格排序不可靠 —— "
              "建议用默认排序（`--sort default`）多取几条，再用 `--price-min/--price-max` 卡区间。")
    if res.get("free_ship_note"):
        print(f"- 注意：{res['free_ship_note']}")
    if res.get("filtered_out"):
        fo = res["filtered_out"]
        print(f"- 已按筛选条件剔除 {len(fo)} 条（价格区间/包邮）："
              + "、".join(f"{cut(x.get('title'), 18)}（{why}）" for x, why in fo[:3])
              + ("…" if len(fo) > 3 else ""))
    if page.get("loginWall"):
        print("- 注意：页面有登录提示，抽取结果可能不完整")
    if site == "taobao":
        print("- 提示：淘宝需要浏览器已登录淘宝账号；卡片数为 0 通常表示登录态过期（不是反爬）。"
              "「单只价」由标题里的数量推断，conf=low 时请人工核对。")
    else:
        print("- 提示：1688 免登录；「单只价」由标题/卡片文本里的数量推断；"
              "阶梯价（1-9件/10-99件）在本机自动化下取不到，需人工询盘。")
    conf_low = [x for x in items if x["pack_qty"] and x["unit_confidence"] == "low"]
    if conf_low:
        print(f"- 注意：{len(conf_low)} 条的单只价来自标题小数量（<10），可能是一份多只，也可能是散卖。")
    if others and not show_all:
        by_kind = {}
        for x in others:
            by_kind[x.get("kind_cn") or x.get("kind")] = by_kind.get(x.get("kind_cn") or x.get("kind"), 0) + 1
        detail = "、".join(f"{k} {v}" for k, v in by_kind.items())
        print(f"- 已剔除 {len(others)} 条非料件（{detail}）—— 它们的价格不能折算单只价，"
              "要看全量加 `--all`。")
    conds = {}
    for x in items:
        c = x.get("condition") or "未标明"
        conds[c] = conds.get(c, 0) + 1
    if conds:
        detail = "、".join(f"{k} {v}" for k, v in sorted(conds.items(), key=lambda kv: -kv[1]))
        print(f"- 成色分布（卖家标题自述，未核实）：{detail}")
        risky = [x for x in items if x.get("condition") in ("翻新", "拆机", "散新")]
        if risky:
            print(f"- 其中 {len(risky)} 条是翻新/拆机/散新：**打样与维修可用（默认只标注）**；"
                  "量产/车规/高可靠场景必须排除这类卖家（本工具在 --production 下自动剔除）。")
    assort = [x for x in res["sorted"] if x.get("assortment")]
    if assort and show_all:
        print(f"- 注意：{len(assort)} 条是混装/套装（不同型号打包），已标「混装包」且不做单只价归一。")
    ranged = [x for x in res["sorted"] if (x["unit_note"] or "").startswith("数量区间")]
    if ranged:
        print(f"- 注意：{len(ranged)} 条标题写的是数量区间（起订/阶梯），已按「区间价」处理，未折算单只价。")


def dump_json(res, site, keyword, sort, limit, path):
    payload = {
        "meta": {
            "site": site, "site_name": SITES[site]["name"], "keyword": keyword, "sort": sort,
            "sort_applied": res["sort_applied"], "url": res["url"], "count": min(limit, len(res["sorted"])),
            "page_items": len(res["sorted"]), "ads": len(res["ads"]), "total_results": res.get("total"),
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "used_fallback": res.get("used_fallback"), "client_sorted": res.get("client_sorted", False),
        },
        "items": res["sorted"][:limit],
        "ads": [{k: v for k, v in x.items() if k != "cardText"} for x in res["ads"]],
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")
    return p


# --------------------------------------------------------------------------- 命令
def cmd_check(a):
    br = Bridge(session=a.session, timeout=a.timeout, trace=a.trace)
    try:
        st = br.status()
    except BridgeError as e:
        print(f"daemon: FAIL — {e}")
        if e.hint:
            print(f"hint: {e.hint}")
        print()
        print(daemon_start_hint())
        return e.exit_code
    print("daemon:")
    print(f"  running             = {st.get('running')}")
    print(f"  extension_connected = {st.get('extension_connected')}")
    print(f"  extension_version   = {st.get('extension_version')}")
    print(f"  version             = {st.get('version')}")
    print(f"  port                = {st.get('port')}")
    if not st.get("extension_connected"):
        print("  → 浏览器扩展未连接，先打开浏览器确认扩展已启用。")
        print()
        print(daemon_start_hint())
        return EXIT_DAEMON

    tabs = []
    try:
        tabs = br.list_tabs().get("tabs") or []
    except BridgeError:
        pass
    print(f"session tabs        = {len(tabs)}")

    code = 0
    print("\n淘宝登录态（打开 taobao.com 探测）：")
    try:
        br.navigate("https://www.taobao.com/", new_tab=False, group_title=GROUP_TITLE)
        time.sleep(1.5)
        probe = eval_json(br, js("taobao_login_probe.js"))
        print(f"  href        = {probe.get('href')}")
        print(f"  logged_in   = {probe.get('loggedIn')}")
        print(f"  nick        = {probe.get('nick') or '-'}")
        print(f"  markers     = {', '.join(probe.get('markers') or []) or '-'}")
        print(f"  bodyLen     = {probe.get('bodyLen')}")
        if not probe.get("loggedIn"):
            print("  → 未登录：淘宝检索会返回 0 条，请先扫码登录淘宝。")
    except BridgeError as e:
        print(f"  探测失败：{e}")
        code = e.exit_code

    print("\n依赖关系（不是「只要淘宝登录过就行」）：")
    print("  - 脚本本身不存淘宝 cookie，也不做扫码登录；它驱动的是**本机这台浏览器**")
    print(f"    （当前由 Kimi 扩展接管的那个 profile，daemon {DAEMON}）。")
    print("  - 所以需要同时满足三件事：① 本机 daemon 在跑；② 该浏览器装了 Kimi 扩展并连上；")
    print("    ③ **这个浏览器**里淘宝是登录态。换浏览器/换机器/清 cookie 都要重新配。")
    print("  - 换端口：KIMI_WEBBRIDGE_URL=http://127.0.0.1:<port> 后再跑本命令。")

    print("\n1688：免登录可检索（销量排序走 URL 参数）。")
    print(f"\n总结：{'OK' if code == 0 else '需要处理'} — "
          f"可用命令 `python scripts/taobao.py search \"<关键词>\" --site taobao|1688 --sort sales`")
    return code


def cmd_search(a):
    if a.limit < 1:
        print("--limit 必须 >= 1", file=sys.stderr)
        return EXIT_USAGE
    throttle(a.site)
    br = Bridge(session=a.session, timeout=a.timeout, trace=a.trace)
    t0 = time.time()
    try:
        if a.site == "taobao":
            res = search_taobao(br, a.keyword, a.sort, a.limit, a.max_scrolls, fallback=not a.no_fallback)
        else:
            res = search_1688(br, a.keyword, a.sort, a.limit)
    except BridgeError as e:
        print(f"[失败] {e}", file=sys.stderr)
        if e.hint:
            print(f"[提示] {e.hint}", file=sys.stderr)
        return e.exit_code

    real, ads = sort_items(normalize(res["items"], a.site), a.sort)
    # 价格区间 / 包邮筛选（用户可加；价格用标价，理由见 filter_items docstring）
    dropped_filter = []
    free_ship_note = ""
    if a.free_shipping and not any(x.get("free_shipping") for x in real):
        # 本页没有任何链接标「包邮」：淘宝搜索页大量链接不显示这个标签，直接筛等于清空
        free_ship_note = ("本页没有链接标「包邮」（淘宝搜索页多数卡片不显示包邮标识）——"
                          "包邮筛选已跳过；要看包邮请进详情页或换关键词")
        a.free_shipping = False
    if a.price_min is not None or a.price_max is not None or a.free_shipping:
        real, dropped_filter = filter_items(real, a.price_min, a.price_max, a.free_shipping)
    res["sorted"], res["ads"] = real, ads
    res["filtered_out"] = dropped_filter
    if free_ship_note:
        res["free_ship_note"] = free_ship_note
    # 价格排序是客户端排序（页面「价格」tab 点击实测不生效）
    if a.sort in ("price_asc", "price_desc"):
        res["client_sorted"] = True
    res["elapsed"] = time.time() - t0

    if not real:
        if dropped_filter:
            print(f"[失败] 筛选条件把 {len(dropped_filter)} 条全部剔除了（不是登录态问题）。")
            for x, why in dropped_filter[:5]:
                print(f"  - {cut(x.get('title'), 30)}：{why}")
            print("[提示] 放宽 --price-min/--price-max 或去掉 --free-shipping。")
            return EXIT_EMPTY
        print("[失败] 结果里没有可用的商品条目", file=sys.stderr)
        if a.site == "taobao":
            print("[提示] 多半是淘宝登录态过期，先在浏览器登录淘宝。", file=sys.stderr)
        return EXIT_EMPTY

    render_md(res, a.site, a.keyword, a.sort, a.limit, res["elapsed"], show_all=a.all)
    if a.json:
        p = dump_json(res, a.site, a.keyword, a.sort, a.limit, a.json)
        print(f"\nJSON 已写入：{p}")
    return EXIT_OK


def main(argv=None):
    _u8()
    ap = argparse.ArgumentParser(
        prog="taobao.py", description="淘宝 / 1688 检索（销量·价格排序 + 单价归一），走 Kimi WebBridge")
    ap.add_argument("--session", default=DEFAULT_SESSION, help=f"WebBridge session 名（默认 {DEFAULT_SESSION}）")
    ap.add_argument("--timeout", type=int, default=120, help="单条命令超时秒数")
    ap.add_argument("--trace", action="store_true", help="打印请求trace到 stderr")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="检查 daemon / 扩展 / 淘宝登录态")
    c.set_defaults(func=cmd_check)

    s = sub.add_parser("search", help="检索商品")
    s.add_argument("keyword", help="关键词，如 \"10k 0603 电阻\"")
    s.add_argument("--site", choices=sorted(SITES), default="taobao", help="站点（默认 taobao）")
    s.add_argument("--sort", choices=["default", "sales", "price_asc", "price_desc"], default="default",
                   help="default=综合 sales=销量 price_asc/price_desc=价格")
    s.add_argument("--limit", type=int, default=20, help="输出条数（默认 20）")
    s.add_argument("--max-scrolls", type=int, default=0, help="淘宝页面滚动次数（默认 0，只取当前页）")
    s.add_argument("--json", metavar="PATH", help="把结构化结果写到文件")
    s.add_argument("--no-fallback", action="store_true", help="playbook 抽取为空时不回退自写 DOM 抽取")
    s.add_argument("--all", action="store_true",
                   help="连开发板/成品模块/混装包/系列链接一起显示（默认只显示可比元器件）")
    s.add_argument("--price-min", type=float, default=None, metavar="Y",
                   help="只要标价 ≥ Y 元（按标价筛，不是单只价）")
    s.add_argument("--price-max", type=float, default=None, metavar="Y",
                   help="只要标价 ≤ Y 元（按标价筛，不是单只价）")
    s.add_argument("--free-shipping", dest="free_shipping", action="store_true",
                   help="只保留标了「包邮」的链接")
    s.set_defaults(func=cmd_search)

    a = ap.parse_args(argv)
    if a.cmd == "search" and getattr(a, "limit", 0) > 200:
        print("--limit 上限 200", file=sys.stderr)
        return EXIT_USAGE
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
