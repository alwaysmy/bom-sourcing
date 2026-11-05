# 原厂官方商城调研（2026-11-05）

> 目的：给 `bom-sourcing` skill 补「原厂官方商城」检索能力，用于**已知型号/批量需求**时查原厂库存、价格、样品。
> 调研时间：2026-11-05 14:09 – 16:35（Asia/Shanghai）。
> 探针脚本与原始证据：`D:\WorkDesigns\3_WorkTools\Bom_Flow\probe\origin\`（`evidence/` 下每步都落 JSON/HTML）。
> 交付物：`skills\bom-sourcing\scripts\origin.py` + `skills\bom-sourcing\references\origin-stores.md`。

## 0. 纪律

**没有一家价格/库存是估算或推测出来的。** 拿不到就写"需登录 / 需人工 / 不可达"；
本文件里每个数字都附了产生它的命令与原始响应片段。

## 1. 环境

| 项 | 值 |
|---|---|
| 工作目录 | `D:\WorkDesigns\3_WorkTools\Bom_Flow` |
| Python | 3.14.6（PATH 里的 `python`） |
| 浏览器桥 | Kimi WebBridge daemon `http://127.0.0.1:10086`，`v2.0.23`，`extension_connected: true` |
| 代理 | `127.0.0.1:7890`（国内原厂站一律**直连绕代理**） |
| 控制台编码 | PowerShell 控制台是 GBK → 所有脚本必须 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` |

## 2. 探测方法（四个阶段）

### 阶段 1：域名与可达性

`probe\origin\http_probe.py` 纯 HTTP 抓首页，记录 `status / final_url / bytes / title / script_count`。

```powershell
python http_probe.py --batch recon_home.txt --interval 1.5
```

**结果**：19 家里 13 家纯 HTTP 200；极海 405；小华/纳芯微/中微 DNS 失败；韦尔超时；
芯导/沁恒/航顺首页是几百字节的 JS 空壳。

### 阶段 2：找站内搜索入口

`probe\origin\form_find.py` 抽 `<form>` 与 JS 里的 search URL 正则。

```powershell
python form_find.py forms_batch.txt
```

**踩的坑**：`grep` 工具对 1.3 MB 单行的压缩 JS 直接返回 No matches
→ 另写 `probe\origin\pygrep.py` 用 Python `re` 搜。

### 阶段 3：验证搜索是否真出结果

`probe\origin\search_verify.py` 统计关键词命中的 `<a>`、结果计数文案、价格/库存线索。

**关键教训**：HTTP 200 ≠ 检索可用。
- `sg-micro.com/global-search?keyword=X` HTTP 200，但正文写「Search by product, **0 results in total**」；
- `prisemi.com/?s=X` HTTP 200，但结果区是空的；
- `wch.cn/search.html` HTTP 200，但只有 1815 B 的壳。

### 阶段 4：JS 站走真浏览器

`probe\origin\br_probe.py`（`--url --name --wait --chars`）走 WebBridge 打开页面再取 `innerText`。
`probe\origin\dom_search.py` 会真的往搜索框打字 + 回车，再抓 XHR。

## 3. 关键突破

### 3.1 3PEAK 官方商城：唯一能拿到含税人民币价 + 库存的原厂

从 `3peak.cn` 首页发现「在线商城」指向**独立域名** `www.3peakic.cn`：

```powershell
python links.py evidence/br_3peak_home.html 在线商城
#  <a href="https://www.3peakic.cn" ...>在线商城</a>
```

`3peakic.cn` 首页只有 679 B 的 SPA 壳，`<script src=/js/app.8f22f03c.js>`（**属性不带引号**，
所以原来的 `js_grep.py` 正则匹配不到 → 改成 `<script\b[^>]*\bsrc\s*=\s*["']?([^"'\s>]+)`）。
在 1.3 MB 的 app.js 里 `pygrep.py` 搜到 12 个 API 端点，其中两个免登录可用：

```powershell
python peak_sweep.py
```

```
page= 1 total=1591 n=100 first=TPA7836B
page= 2 total=1591 n=100 first=TPC2201
...
page= 6 total=None n=  0 first=—
page= 7 total=1591 n=100 first=TPQ50551
...
page=16 total=1591 n= 91 first=CMSH1590M
page=17 total=0    n=  0 first=—
累计: 1491
```

**坑：offset 分页在 offset≈500 处有一页"毒记录"**，整页返回空但 `total` 仍报 1591。
换 pageSize 试试（`peak_size.py`）：

```
pageSize= 50 pages=32 取到=1541 空页=[11]
pageSize= 99 pages=17 取到=1492 空页=[6]
pageSize=101 pages=16 取到=1490 空页=[6]
pageSize=200 pages= 8 取到=1391 空页=[3]
```

→ 空洞窗口固定落在 offset 500–600。定点补（`peak_recover.py`）：

```
pageSize=100 -> 1491  空页=[6, 17]
空洞窗口 offset = [500, 600)
pageSize=10 窗口页 51..60 -> +90  累计 1581  空页=[52]
pageSize= 1 窗口页 501..600 -> +9  累计 1590  空页=[514]

最终: 1590 / 1591  仍缺 1
```

`origin.py` 用的就是这个「100 → 10 → 1 定点细扫并集」策略，**1590/1591**。

**`comprehensiveSearch` 的 `goodsName` 不生效**（`peak_param.py` 试了 13 个参数名，
全部返回全量 1591 条）→ 没有服务端关键词过滤，只能拉全量本地匹配。

实测商品（`python origin.py search TPA7836B --vendor 3peak`）：

```
思瑞浦 3PEAK | MPN=TPA7836B | 库存=1000 | 封装=TQFP10X10-64 | MOQ=50 | 状态=Production
    价格: 20-500:¥60.0 / 501-999:¥55.0 / 1000-1000000000:¥50.0   (含税13%人民币价)
    Analog monitor control solution
    https://www.3peakic.cn/appdetail?id=TPA7836B
```

### 3.2 TI 中国：JSON-LD 拿价格，浏览器 API 拿库存

`https://www.ti.com.cn/product/zh-cn/TPS25947`（**基号**，完整 OPN 是 404）纯 HTTP 200，约 330 KB。
JSON-LD 里 `ProductGroup.hasVariant[]` 给 6 个 OPN 变体，全部 `price=0.69`、`priceCurrency=USD`：

```
TPS259470ARPWR / TPS259470LRPWR / TPS259472ARPWR / TPS259472LRPWR /
TPS259474ARPWR / TPS259474LRPWR
```

**正则坑**：JSON-LD 的 script 标签是**多行**的

```html
<script
      type="application/ld+json"
    >
```

写死 `<script type="application/ld+json"` 会 0 条，必须
`<script[^>]*application/ld\+json[^>]*>(.*?)</script>` + DOTALL。

**人民币价与库存要登录**：part-details 页
`https://www.ti.com.cn/product/cn/TPS25947/part-details/TPS259470ARPWR` 纯 HTTP 200（11.8 KB），
正文是「正在供货」「包装数量 | 包装 3,000 | LARGE T&R」「库存：」「**登录以查看库存**」
「定价 数量 价格 — — —」（价格表全是破折号）。
抓包该页只有 `cartmodel/mini-cart` 401，**没有任何价格 API 请求** → 未登录时价格表本来就空，
不是接口没找到。

库存能绕：浏览器内 fetch

```
GET https://www.ti.com.cn/storeservices/cart/opninventory?opn=TPS259470ARPWR
→ {"orderable_number":"TPS259470ARPWR","inventory":11927}
```

- 基号 `TPS25947` 返回 **204 无内容**，必须给完整可订购 OPN。
- 纯 HTTP 直接访问返回 1636 B 的 **PerimeterX 机器人挑战页**（`Powered and protected by Privacy`）。
- 两次实测分别 8137 / 11927 → 是**实时库存**，会变。

试过但不存在的端点（全 404）：`/storeservices/cart/pricing`、`/cart/opnprice`、
`/cart/price`、`/cart/opnpricing`。

### 3.3 圣邦微：纯 HTTP 恒 0 结果，浏览器 11 条

```powershell
# 纯 HTTP：8 种参数名全是 0
q / search / searchKeyword / keyword / kw / name / partNumber / productName → 0 results
```

```powershell
python br_probe.py --url "https://www.sg-micro.com/global-search?keyword=SGM2019" --name sg_search --wait 8
```

```
Filter conditions  All  Low-dropout Regulators (LDO) (11)  Search by product, 11 results in total
Low-dropout Regulators (LDO)  SGM2019  Not Recommended for New Designs  Low Power, Low Dropout, RF Linear Regulator  Detail
Low-dropout Regulators (LDO)  SGM2092  New  Active  500mA, Fast Transient Response, Low Voltage, Low Noise...
```

→ 必须浏览器；能拿到型号、品类、**生命周期**、描述。无价格库存。

### 3.4 其余可用检索

| 厂 | 命令 | 实测输出 |
|---|---|---|
| MPS | `python origin.py search MP20073 --vendor mps` | `MP20073` → `https://www.monolithicpower.cn/cn/mp20073.html` |
| 士兰微 | `python origin.py search SLP74 --vendor silan` | `SLP74HCT574` / `SLP74AVC4T245` / `SLP74AUP1G07` / `SLP74LVC573A` → `/index.php/product/details/2773.html` 等 |
| 兆易 | `python origin.py search GD25Q64 --vendor gigadevice` | `GD25Q64C` / `GD25Q64E` / `GD25Q64H` / `GD25Q64C`（汽车级）→ `/product/flash/spi-nor-flash/gd25q64c` 等 |

## 4. 失败与不可达（含原因）

| 厂 | 现象 | 证据 |
|---|---|---|
| 芯导 Prisemi | 真浏览器打开 `?s=ESD5V0&type=` 也只显示 `THE SERVER CANNOT FIND DATA FOR THE RESOURCE` | `evidence/br_prisemi_search.json` |
| 韦尔 WILLSEMI | `willsemi.com` / `willsemi.cn` 直连与代理**全部 `WinError 10060` 超时** | `evidence/*.json` 的 `error` 字段 |
| 极海 Geehy | GET 一律 `HTTP 405 Not Allowed`，body 是 `{"traceid":...}` | `python origin.py check` |
| 小华 HDSC | 直连 `getaddrinfo failed`、代理 `SSL: UNEXPECTED_EOF_WHILE_READING` | 同上 |
| 纳芯微 NOVOSENSE | 同上 | 同上 |
| 中微 CMSemicon | 同上 | 同上 |
| 力芯微 ETek | `search.html?query=` → HTTP **403**（WAF） | `form_find` 阶段 |
| 钰泰 ETA | `/search?keyword=` → **404**，无站内搜索表单 | 同上 |
| 南芯 Southchip | `/search?keyword=` → 200 但落到首页（394 字） | 同上 |
| 国民技术 | `/search?s=` → **404** | 同上 |
| 沁恒 WCH | 首页 1815 B 纯 JS 壳，`/search?q=` 302 到 `/search.html?q=...&t=all` | 同上 |
| 航顺 HSXP | 首页 2151 B 纯 JS 壳 | 同上 |
| GD32 | `/cn/download?kw=` 是**下载检索**（datasheet/固件），不是料号检索 | 同上 |
| 兆易"库存查询" | `/product-inventory-search` 是 `di.oemsecrets.com` 的**第三方分销库存挂件**（`distributor-inventory_0.3.0.min.js`），**不是原厂库存** | 抓包 |

## 5. 环境坑（复用价值高）

1. **WebBridge daemon 调用方式**：`POST http://127.0.0.1:10086/command`，
   body `{"action": "...", "args": {...}, "session": "bom-sourcing"}`。`/` 路径是 404。
2. **`network` action 的 `cmd` 必须放在 `args` 里**：`{"action":"network","args":{"cmd":"start"}}`；
   放顶层报 `network: cmd is required (start/stop/list/detail)`。
3. **抓包是全局的**，会混入其它标签页（淘宝、立创、szlcsc）的请求 → 必须按目标域过滤。
4. **PowerShell 内联 `python -c` 里带正则极易 ParserError**（`[\"\x27]`、`|` 被 PowerShell 解析）
   → 一律写成 `.py` 文件再跑。
5. **`grep` 工具对 1.3 MB 单行压缩 JS 失效** → 用 `pygrep.py`。
6. **Python 打印 `Ω` 等字符会 `UnicodeEncodeError: 'gbk' codec can't encode character '\u2126'`**
   （TI 的 `28mΩ` 描述）→ 脚本必须 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`。
7. **Windows 下 `curl` 是别名**，脚本里要写 `curl.exe`。

## 6. 探针脚本清单（`probe\origin\`）

| 脚本 | 用途 |
|---|---|
| `http_probe.py` | 纯 HTTP 抓页面 + 结构摘要，`--batch <文件 name<TAB>url[<TAB>1=noproxy]>` |
| `br_probe.py` | 真浏览器打开页面取 `innerText`，`--url --name --wait --chars` |
| `net_probe.py` | 抓包找接口，`--url --name --wait --filter` |
| `form_find.py` | 自动发现站内搜索 `<form>` 与 JS 里的 search URL |
| `search_verify.py` | 校验搜索页是否真出结果，`<name> <url> <kw>` |
| `api_find.py` | 抽页面里的 `<form>` / `fetch` / `axios` 线索 |
| `links.py` | 列出所有 `<a>`（文本 → href），可按关键词过滤 |
| `xhr_dump.py` / `xhr_detail.py` | 抓包并按域打印 XHR / 取单个请求详情 |
| `js_grep.py` | 下载页面全部 `<script src>` 后在 JS 里 grep |
| `pygrep.py` | 在超长单行文件里用 Python 正则搜索 |
| `bfetch.py` | 在浏览器页面上下文里 fetch（绕过 CORS / 反爬 / 借登录态） |
| `dom_search.py` | 模拟输入 + 回车 + 点搜索按钮，再抓 XHR |
| `peak_pages.py` / `peak_sweep.py` / `peak_size.py` / `peak_gap.py` / `peak_recover.py` | 3peakic 目录分页与空洞恢复试验 |
| `link_raw.py` / `prisemi_dump.py` / `prisemi_ajax.py` / `sg_form.py` / `search_gd_sg.py` | 各站链接/表单结构探查 |

## 7. 遗留

- 3peak 目录 **1590/1591**，剩 1 条任何 offset 都取不到（offset≈513 那条"毒记录"，页面本身打不开）。
  除非原厂修 API，否则无法补全。
- 12 家 `browser` 站只验证了"浏览器渲染后能出结果"（圣邦微），
  其余 11 家**没有逐个做检索验证**——它们的搜索 URL 是推断的，`origin.py` 里没有注册 handler，
  只作可达性记录。要启用需要逐个补 handler 并实测。
- TI 的人民币价在**登录态**下才有。本机 WebBridge 有用户登录态，但 SKILL 里没有针对 TI 登录态的
  定价抓取实现（只做了库存）。
