# 现成轮子调研（GitHub / PyPI / npm / MCP）

> 调研：gh-research / 2026-11-04。证据等级：
> **【实测可用】**= 本机亲自 curl / pip / node 跑通并核对返回内容；**【代码可见未实测】**= 读到源码真实 endpoint/参数但未跑通；
> **【疑似失效】**= 按代码或文档试过失败；**【仅文档】**= 只有 README/文档说法。
> 原始响应在 `probe/github/`，各节引文件名。

## 结论速览

| 排序 | 复用对象 | 用在哪一环 | 一句话理由 |
|---|---|---|---|
| 1 | **jlcparts 数据托管**（`yaqwsx.github.io/jlcparts/data/`） | 离线参数筛选 / 反向选型 / 比指标 | 367,295 个元件、**结构化带单位的参数**（110,808 条参数 LUT）、阶梯价、库存、焊点数、datasheet 全都有，今天 08:53 刚更新过，免 key 直连下载 |
| 2 | **`lcsc.com` 产品详情页 `__NEXT_DATA__`** | 单件详情：中文参数名、替代料明细、分仓库存、阶梯价、datasheet | 一个 GET 拿到 70+ 字段，**含 `alternatePartList` 替代料**（这是其它接口都没有的），免登录免 key |
| 3 | **立创中文站搜索**（Lead 已打通）+ jlcparts 参数 | 关键词检索 + 中文商品名 + **销量排序** | 我实测的两个海外站/嘉立创接口都**不暴露销量**，只有 `so.szlcsc.com` 有 `recentlySalesCount` 和 `sortNumber=6` |
| 4 | **`jlcpcb`（PyPI 0.1.0 CLI）** | 关键词检索 + **属性筛选** + 详情/阶梯价/datasheet | 实测免 key 可用；`--attr NAME=VALUE` 直接做参数筛选、`--limit` 服务端上限 72；专门为 agent 设计（自带 `agent-context` + skill 清单） |
| 5 | **`jlcpcb-mcp`（npm 0.3.3）** | 现成 MCP 壳：8 个免鉴权工具 + 官方 API 工具 | 实测启动成功、列出 28 个工具；可直接给 agent 用，省掉 MCP 封装工作 |
| 6 | **`easyeda2kicad`** | 立创编号 → KiCad 符号/封装/3D | 实测一条命令产出 symbol+kicad_mod+step+wrl 四件套 |

**要自建的只有一小块**：BOM 行 → 候选料匹配打分（型号规范化、封装/参数一致性、替代料决策）+ 阶梯价按目标数量落档。
数据获取、参数筛选、MCP 外壳、EDA 落地全部有现成轮子，**不需要写爬虫**。

---

## 主表

| 名称 | 类型 | 链接 | 星/活跃 | 覆盖商城 | 能力 | 证据等级 | 适配度 |
|---|---|---|---|---|---|---|---|
| jlcparts 数据托管 | 数据库 | https://yaqwsx.github.io/jlcparts/data/ | 每天 3 更（今天 08:53 已更新） | JLCPCB SMT 库（=立创元件子集） | 367,295 件、结构化参数、阶梯价、库存 | 【实测可用】 | **5** |
| lcsc 产品详情页 `__NEXT_DATA__` | 网页内嵌 JSON | `https://www.lcsc.com/product-detail/{C}.html` | 站点活跃 | LCSC 海外站 | 中文参数、替代料、分仓库存、阶梯价、datasheet | 【实测可用】 | **5** |
| 立创中文站搜索（Lead） | HTTP API | `POST https://so.szlcsc.com/query/product` | — | 立创中文站 | 关键词检索、**销量排序**、人民币阶梯价 | 【实测可用】（Lead） | **5** |
| `lcsc` (PyPI 0.1.1) | CLI+库 | https://pypi.org/project/lcsc/ | 2026-05-27 | LCSC 海外站 | 检索、参数筛选、分类树、折扣、datasheet | 【实测可用】 | 4 |
| **`jlcpcb` (PyPI 0.1.0)** | CLI+库 | https://pypi.org/project/jlcpcb/ | 2026-05-28 | JLCPCB/LCSC | 检索 + **属性筛选** + 详情 + 阶梯价 + datasheet/图片/符号 SVG；自带 agent skill | 【实测可用】 | 5 |
| **`decode_shard.py`（我方 60 行 demo）** | 脚本 | `probe/github/decode_shard.py` | 本机 | jlcparts 离线库 | 按参数数值范围+库别+库存筛选，按库存/价格排序 | 【实测可用】 | 5 |
| JLCPCB website API v2 | HTTP API | `jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList/v2` | — | JLCPCB/立创 | 关键词搜、阶梯价、库存、参数、datasheet | 【实测可用】 | 4 |
| `jlcpcb-mcp` (npm 0.3.3) | MCP | https://github.com/Eyalm321/jlcpcb-mcp | MIT / 2026-06-03 | JLCPCB+LCSC | 28 工具：本地目录检索+实时价+官方 API | 【实测可用（启动/工具面）】 | 4 |
| `lcsc-toolkit` (PyPI 0.3.0) | 库 | https://github.com/superhouse/lcsc-toolkit | MIT / 2026-10-13 | LCSC | 检索 + 登录态订单历史 | 【实测可用（检索）】 | 3 |
| `SpectraSynq/mcp-lcsc` | MCP | https://github.com/SpectraSynq/mcp-lcsc | MIT | LCSC 官方 API | 2 个工具：search / item | 【代码可见未实测】 | 3 |
| LCSC 官方 OpenAPI | HTTP API | https://www.lcsc.com/docs/openapi/ | 官方 | LCSC | 分类/品牌/参数列表/详情/关键词搜索/下单 | 【仅文档+实测 424 Key Is Required】 | 3 |
| `easyeda2kicad` (PyPI 1.0.1) | CLI | https://github.com/uPesy/easyeda2kicad.py | 2026-04-06 / **AGPL-3.0** | 立创/LCSC | 符号+封装+3D | 【实测可用】（见 §7） | 4 |
| `harry10086/kicad-jlcpcb-tools` | KiCad 插件 | https://github.com/harry10086/kicad-jlcpcb-tools | — | 立创 | `lcsc_api.py`：szlcsc 搜索 + 详情 | 【代码可见】 | 3 |
| `hildogjr/KiCost` | CLI | https://github.com/hildogjr/KiCost | — | DigiKey/Mouser/… | 多分销商 BOM 报价（**不支持立创**） | 【代码可见】 | 2 |
| `parts-mcp` (PyPI 0.5.3) | MCP | https://github.com/SourceParts/parts-mcp | MIT | 仅 SourceParts 自有 | 需付费账号 | 【实测：403】 | 2 |
| Apify 系 1688/淘宝 MCP | MCP（远程） | registry: `io.github.zen-studio-labs/*`、`io.github.serenido/1688-product-details` | — | 淘宝/天猫/1688 | 搜索+详情+SKU+评价 | 【仅文档（需 APIFY_TOKEN 付费）】 | 3 |
| `1688-cli` / `1688-claw` (npm) | CLI（Playwright） | https://github.com/superjack2050/1688-cli | MIT / 2026-06-27 | 1688 | 搜索、供应商研究、**购物车/订单/物流** | 【代码可见未实测（需登录态）】 | 3 |
| InvenTree / BOMist / Part-DB | 库存管理 | https://inventree.org / bomist.com / part-db.github.io | InvenTree 0.25.0(2026-10) | **均无立创通道** | 元件柜/库存/BOM 管理，接商城要自己写插件 | 【实测 PyPI 404 判定】 | 1 |

---

## 1. jlcparts 数据托管 —— 可下载的全量元件库【实测全链路】

**最重要的发现。** 不是仓库，而是它发布的**数据分发站点**（GitHub Pages），可以直接当 CDN 用：

```
BASE = https://yaqwsx.github.io/jlcparts/data/
```

| 文件 | 实测大小 | 内容 |
|---|---|---|
| `manifest.json` | 4,132,648 B | `version=4`、`created=2026-11-04 08:53:12`（**今天**）、`totalComponents=367295`、688 个 subcategory、每个 subcategory 的 `shards[]` 与 `browseShards[]`、`attributesLut`、`searchIndex=search-index.tsv.gz`（`format=tsv-v1`，另有 trigram 分片索引） |
| `attributes-lut.json.gz` | 997,483 B（解压 16.8 MB） | **110,808 条参数定义**（见下） |
| `components-<subcat>-001.jsonl.gz` | 每个 ~2 KB 起，最大的几十 MB | 元件数据，**JSONL，首行是 schema，之后每行是一个数组** |
| `browse-components-*.jsonl.gz` | — | 前端浏览用的精简分片 |

**数据格式（实测逐字）**：

第 1 行 schema：
```json
{"lcsc":0,"mfr":1,"joints":2,"description":3,"datasheet":4,"price":5,"img":6,"url":7,"attributes":8,"stock":9,"subcategory":10}
```
第 2 行起的行：
```json
["C266127","TIOL1113DMWR",10,"7V~36V VSON-10(2.6x3.1) ADCs/DACs - Special Purpose ROHS",
 "https://www.ti.com/cn/lit/gpn/tiol1113",
 [{"qFrom":1,"qTo":9,"price":7.4711},{"qFrom":10,"qTo":29,"price":6.6613},…],
 null, null, [0,1,2,3,4,5,6,7], 20, 1]
```
- `joints` = **焊点数**（SMT 报价用）；`price` = 阶梯价数组（USD，嘉立创 SMT 价）；`stock` = 嘉立创装配库存；
- `attributes` = **指向 attributes-lut 的索引数组**（省体积的关键设计）；`subcategory` = manifest 里 categories 的下标。

**参数 LUT 才是金矿**（`attributes-lut.json.gz` 解压后是 JSON 数组，110,808 项）：
```json
[0] ["Features",{"format":"${feature 1}, ${feature 2}, …","primary":"feature 1",
                "values":{"feature 1":["Programmable gain","identifier"],…}}]
[1] ["Operating Temperature",{"format":"${temperature min} ~ ${temperature max}","primary":"temperature min",
                "values":{"temperature max":[125.0,"temperature"],"temperature min":[-40.0,"temperature"]}}]
[3] ["Supply Voltage",{"…":"…","values":{"voltage":[36.0,"voltage"]}}]
[4] ["Basic/Extended",{"values":{"catalog class 1":["Extended","identifier"]}}]
[10] ["Package",{"values":{"identifier":["VSON-10-EP(2.5x3)","identifier"]}}]
[7] ["Manufacturer",{"values":{"identifier":["Texas Instruments","identifier"]}}]
```
→ **每个参数带类型**（`temperature` / `voltage` / `current` / `count` / `identifier` / `string`），
所以可以**数值化筛选与排序**：`Supply Voltage ≥ 25V`、`Operating Temperature max ≥ 105`、只取 Basic 库、只取某个封装。
这正是"按指标筛选"和"无型号时反向选型"要的东西，**不需要自己抓参数表**。

**新鲜度**：`manifest.created` 今天 08:53，GitHub Actions `cron: 0 3,11,19 * * *`（每天 3 次）。
**许可**：仓库 MIT；数据本身归嘉立创/LCSC，商用需自行判断。
**坑**：① 不要下 `cache.zip` 那套 253MB 分卷（7z split，必须 z01–z05 齐了才能解），**用这套 JSONL 分片**；② 没有目录 listing，文件清单只能从 `manifest.json` 取；③ 只下某个子类只需 1 个分片（KB~MB 级），很适合按需。

原始文件：`probe/github/jlcparts_manifest.json`、`jlcparts_attr_lut.json.gz`、`jlcparts_shard_sample.jsonl.gz`。

---

## 2. `www.lcsc.com/product-detail/{code}.html` 内嵌 `__NEXT_DATA__`【实测可用，细节最全】

```
GET https://www.lcsc.com/product-detail/C8734.html      # 必须直连，走代理失败
```
实测：HTTP 200、446,010 B HTML、`<script id="__NEXT_DATA__">` 内 **109,403 B JSON**，
路径 `props.pageProps.webData`（另有 `props.pageProps.hotList` / `overviewData` / `catalogList`）。

`webData` 里 **70+ 字段**，对我们有用的：

| 字段 | 内容 |
|---|---|
| `productCode` / `productModel` / `brandNameEn` | C8734 / STM32F103C8T6 / ST |
| `paramVOList[]` | **`paramName` 是中文**（"ADC(位数)"、"I/O数量"）+ `paramNameEn` / `paramValue` / `paramValueEn` / `isMain` / `sort` |
| `alternatePartList[]` | **替代料明细**：每个都有 productCode / model / 封装 / 品牌 / 库存 / 自己的阶梯价 |
| `productPriceList[]` | 阶梯价 `{ladder, productPrice, usdPrice, cnyProductPriceList, discountRate, currencySymbol}` |
| `domesticStockVO` / `overseasStockVO` | `{total, shipImmediately, ship3Days}` 分仓库存 |
| `pdfUrl` | `https://datasheet.lcsc.com/datasheet/pdf/<hash>.pdf?productCode=C8734` —— 实测直下 **2,077,497 B 真 PDF** |
| `minBuyNumber` / `minPacketNumber` / `minPacketUnit` / `productArrange` | 起订量、整包数、包装（Tray / Tape & Reel） |
| `reelPrice` / `productLadderPrice` / `ladderDiscountRate` | 整卷价、折扣率 |
| `smtLabel` / `isHot` / `isRohsCert` / `authenticationList` | 基础/扩展库、热卖、认证 |
| `productWeight` / `encapsulationModel`(=`encapStandard`) / `productUnit` | 重量/封装/单位 |

**能力对照**：库存 ✅ 阶梯价 ✅ 参数表（**中文**）✅ 替代料 ✅ datasheet ✅ 销量 ❌（该页没有销量字段）。

**坑**：
1. **必须直连**：`*.lcsc.com`（`www` 和 `wmsc`）走 127.0.0.1:7890 都会 `HTTP 000` / `SSLEOF`；`curl.exe --noproxy "*"` 或 `NO_PROXY=lcsc.com` 后 1.4s 返回。
2. 只能按 **C 编号**查，不能按关键词搜；搜索要走 `so.szlcsc.com`（中文站）或 `wmsc.lcsc.com`（海外站）。
3. 这是国际站页面：`productPriceList` 默认 USD（`cnyProductPriceList` 为 null），但**参数名是中文**。
4. 页面 446 KB，抓 1000 个型号 ≈ 450 MB 流量，批量时不如 API。

原始文件：`probe/github/lcsc_nextdata_C8734.json`、`lcsc_detail_noproxy.html`、`lcsc_ds_C8734.pdf`。

---

## 3. `lcsc` (PyPI 0.1.1) —— 立创海外站 API 的完整开源封装【实测可用】

**安装**：`pip install --index-url https://pypi.org/simple lcsc`
（坑：本机默认 pip 源是清华镜像，实测**取不到包**，必须显式 `--index-url https://pypi.org/simple`）

YoseiUshida / MIT / 2026-05-27 / Python ≥3.13。CLI `<noun> <verb>` + 全局 `--json`，明显是给 agent 用的。

**endpoint（源码 `lcsc/client.py`、`lcsc/api/*.py`，`DEFAULT_BASE_URL = "https://wmsc.lcsc.com"`）**：

```
POST /ftps/wm/search/v3/global             # 场景判定搜索（FULL_MATCH / PARTIAL_MATCH / REDIRECT_PRODUCT_DETAIL / REDIRECT_BRAND_DETAIL / NO_RESULT）
POST /ftps/wm/product/query/list           # 商品列表 + 参数筛选 + 排序 + 分页
POST /ftps/wm/product/query/param/group    # 参数筛选选项（catalogIdList 必填）
GET  /ftps/wm/product/detail?productCode=&productId=   # 两个参数都必填
GET  /ftps/wm/product/category/tree
GET  /ftps/wm/product/brand/detail/{id}
POST /ftps/wm/discount/product/search/list
GET  /ftps/wm/search/v2/pre?keyword=
POST /ftps/wm/search/third                 # 第三方库存
```

`product/query/list` 请求体（源码逐字）：
```json
{"keyword":"","globalKeyword":"","scene":"","catalogIdList":[],"brandIdList":[],
 "encapValueList":[],"productArrangeList":[],"paramNameValueMap":{},
 "isStock":false,"isOtherSuppliers":false,"isAsianBrand":false,"isDeals":false,
 "isEnvironment":false,"currentPage":1,"pageSize":25,"sortField":"price","sortType":"desc"}
```
- `paramNameValueMap` = **结构化参数筛选**（先 `param/group` 拉选项，再填值）→ 满足"按指标筛选"。
- 硬限制（源码注释，作者 HAR 实证）：`pageSize ≤ 100`；`totalRow` 封顶 **5000**；`sortField` 仅 `price/stock/brand/model/encapStandard/productArrange` 有效。

**实测**：
```powershell
$env:no_proxy=$null; $env:NO_PROXY=$null     # 必须！本机 no_proxy 含 [::1]，httpx 会崩：InvalidURL: Invalid port ':1]'
lcsc --json --quiet search "STM32F103C8T6"
```
→ `kind=product, scene=FULL_MATCH`、`product_code=C8734`、`stock_number=31387`、
`product_price_list` 6 档（1/10/30/250/500/1000 → 1.5084…0.9577 USD）、`pdf_url`、`hasAlternatePart`、`smtLabel=EXPAND`、`is_hot`、`param_vo_list`。
原始：`probe/github/lcsc_cli_search_stm32.json`。

**坑**：① 走代理连不上，必须直连；② 海外站英文/美元；③ **无销量**。

---

## 4. `lcsc-toolkit` (PyPI 0.3.0) / `mcp-lcsc` / 官方 OpenAPI【部分实测】

**`lcsc-toolkit`**（superhouse / MIT / 2026-10-13）实测：`SearchClient().search("C8734")` 在 `NO_PROXY=lcsc.com` 下**成功**，
返回 `product_code / product_model / stock_number / price_breaks / moq / product_arrange / product_images`。
- `search` 走 `POST https://wmsc.lcsc.com/ftps/wm/global` 同款 v3 接口；
- 当场景是 `REDIRECT_PRODUCT_DETAIL` 时，它会去抓 `https://www.lcsc.com/product-detail/{C}.html` 的 `__NEXT_DATA__` 取 `webData`（= 上面 §2 那条路）；
- `orders` 子模块：用 Playwright 抓登录态 cookie 存 `session.json`，之后用 requests 调订单接口（`client.list_orders()` / `get_order_detail(uuid)` → `order_code / web_order_status / order_amount / product_code / purchase_quantity / real_price`）。**需要用户真实登录，有账号风险，我们不需要**。
- 作者默认限速 **3 秒/请求**（`DEFAULT_MIN_REQUEST_INTERVAL = 3.0`），值得沿用。

**`mcp-lcsc`**（SpectraSynq，10 KB）只有 2 个工具，是官方 OpenAPI 的薄壳：
```python
BASE_URL = os.environ.get("LCSC_BASE_URL", "https://ips.lcsc.com")
API_KEY  = os.environ.get("LCSC_API_KEY", "")     # 未设置则 424 "Key Is Required ."
# 签名 = sha1("key={key}&nonce={nonce}&secret={secret}&timestamp={ts}")
GET /rest/wmsc2agent/search/product?keyword=&is_available=&page_size=
GET /rest/wmsc2agent/product/info/{product_number}
```

**LCSC 官方 OpenAPI**（`https://www.lcsc.com/docs/openapi/`，实测 200 / 132,321 B，Redocly 渲染，纯文本已存 `probe/github/lcsc_openapi_docs.txt` 452 行）：
- host `https://ips.lcsc.com`；**所有接口**都要 4 个 query：`key`(API key)、`nonce`(16 位随机串)、`signature`、`timestamp`。
- Products：`GET /rest/wmsc2agent/category`、`GET /rest/wmsc2agent/brand`、Categorical Item List API（`category_id` 必填 int32、`currency`=USD/CNY/**EUR**/HKD、`current_page`、`page_size` 默认 100、`is_available`、`is_pre_sale`）、Item Details API、Keyword Search List API。
- Orders：`POST Order Create API`（`pros=[{"Pro":"C2653","Qty":5}]`）、`GET Check Order API`；Shipment：`POST /rest/wmsc2agent/get/shipment`。
- 实测未带签名：`GET https://ips.lcsc.com/rest/wmsc2agent/product/info/C8734` → 200 `{"success":false,"code":424,"message":"Key Is Required ."}`
  → endpoint 真实存在，只缺 key。
- **准入**：文档页面没有公开申请入口/限额说明，需走 LCSC 商务（与 JLCPCB 的 `api.jlcpcb.com` 一致，官方声明"按订单历史审批"）。→ 判为**长期合法路线，短期不可用**。

---

## 5. JLCPCB 网页 API v2（免 key）【实测可用】

```
GET  https://jlcpcb.com/api/overseas-pcb-order/v1/getAll      → 拿 Set-Cookie: XSRF-TOKEN=<uuid>
POST https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList/v2
     Header: X-XSRF-TOKEN: <uuid>
```
请求体（`probe/github/src/jlcparts/jlcparts-HEAD/jlcparts/jlcpcb.py:236` 逐字）：
```json
{"currentPage":1,"pageSize":25,"keyword":"C8734","searchSource":"search","searchType":2,
 "componentBrandList":[],"componentSpecificationList":[],"componentAttributeList":[],"paramList":[]}
```
返回 `data.componentPageInfo.list[]` 90+ 字段：`componentCode`、`stockCount`、`componentPrices[]`（阶梯）、
`buyComponentPrices[]`、`attributes[]`（10 项 `attribute_name_en/value`）、`dataManualUrl`、`componentAlternativesCode` + `replaceUrlSuffix`、`smtLabel`、`minPurchaseNum`…

**坑**（全部实测）：① 不取 token → `code:200` 但 `total:0`（静默空结果）；② 排序参数无效（`stockSort`/`sortType` 都不生效）；
③ 宽松匹配，`keyword="0603 100nF"` → total=16000（pageSize=100 可用），`"STM32F103C8T6"` → total=25；
④ 不暴露销量。
原始：`probe/github/jlc_v2_search.json`、`jlc_A_0603_100nF.json`、`jlc_B_stockSort.json`、`jlc_C_sortType.json`。

---

## 6. `jlcpcb-mcp` (npm 0.3.3) —— 现成 MCP 壳【实测启动 + 28 工具】

https://github.com/Eyalm321/jlcpcb-mcp ｜ MIT ｜ 2026-06-03 ｜ 依赖 `@modelcontextprotocol/sdk` + `better-sqlite3` + `zod`。

**实测**：`npm i --prefix %TEMP%\bomprobe\npm jlcpcb-mcp` 成功（better-sqlite3 12.11.1 直接用预编译，无需编译）；
以 stdio 喂 `initialize` + `tools/list` → 正常返回 **28 个工具**：
- 免鉴权 8 个：`jlcpcb_search_components`（关键词 + 分类/封装/基础库/最小库存 + **参数化筛选**，结果按 Basic→库存→价格排序）、
  `jlcpcb_get_component_details`、`_stock`、`_pricing`、`_datasheet_url`、`jlcpcb_list_categories`、`_database_status`、`_refresh_database`；
- 需 JLCPCB 官方 API（`JLCPCB_APP_ID/ACCESS_KEY/SECRET_KEY`，`open.jlcpcb.com`，HMAC-SHA256）：4 个元件库工具 + 8 个 PCB/钢网工具 + 6 个 3D 打印工具，
  其中 `jlcpcb_pcb_create_order` / `jlcpcb_tdp_create_order` 默认禁用（要 `JLCPCB_ENABLE_ORDERS=true`）。

**它的架构值得直接抄**：本地 SQLite（`components` + `prices` 两张表，来自 jlcparts）做参数检索，
实时数据（库存/阶梯价/datasheet）逐条打 `wmsc.lcsc.com`，并把**两套库存分开命名**：
`lcsc_retail_stock`（零售）vs `jlc_assembly_stock`（贴片装配）——**板厂生产要用后者，这是个真坑，README 明确写了**。

原始：`probe/github/jlcpcb_mcp/out.jsonl`（tools/list 全量返回）、`jlcpcb_mcp/err.txt`。

---

## 7. `easyeda2kicad` / KiCost / 其它 EDA 侧【部分实测】

- **`easyeda2kicad`（PyPI 1.0.1，AGPL-3.0，2026-04-06）【实测可用】**：立创编号 → KiCad 符号 + 封装 + 3D。
  ```powershell
  pip install --index-url https://pypi.org/simple easyeda2kicad
  easyeda2kicad --lcsc_id=C8734 --full --overwrite --output e2k_out\probe.kicad_sym
  ```
  实测产出四件套（`probe/github/e2k_out/`）：
  `probe.kicad_sym` 11,895 B（符号名 `STM32F103C8T6`）、
  `probe.pretty/LQFP-48_L7.0-W7.0-P0.50-LS9.0-BL.kicad_mod` 6,037 B、
  `probe.3dshapes/*.step` 978,290 B、`*.wrl` 308,564 B。
  **坑：AGPL-3.0** —— 如果我们的配单工具要对外分发，直接 import 会传染，只能当独立 CLI 进程调用。
- **库存/BOM 管理系统补位评估**（只需回答"能不能接立创"）：
  - **InvenTree**：PyPI `inventree` 0.25.0（2026-10-26，MIT），Django 插件化确实能接第三方商城，但生态里只有
    `inventree-digikey 0.0.1a0`（2022 年 alpha），**`inventree-lcsc` 在 PyPI 上不存在（404）** → 要自己写插件。
  - **BOMist**：桌面 App（不在 PyPI，404），含 Octopart 集成与 KiCad 支持，**无立创**通道，且是增量式商业产品。
  - **Part-DB**：PHP/Web（不在 PyPI，404），元件柜/库存管理，**无立创**通道。
  - **KiCost**：见上，只有 DigiKey/Mouser/Element14/Nexar/TME。
  → 结论：**这四个都不是"开箱接立创"的方案**，当"我们自建之后要不要往库存系统里落"的候选还早。真要用先看 InvenTree 的插件 API。
- **`hildogjr/KiCost`**（实测仓库结构）：`kicost/distributors/` 只有 `api_digikey.py` / `api_element14.py` / `api_mouser.py` / `api_nexar.py` / `api_partinfo_kitspace.py` / `api_tme.py` / `dist_local_template.py`。
  → **不支持立创/LCSC/淘宝**，且需要各分销商 key（Mouser/DigiKey/Nexar 都是要申请的）。对我们只有"BOM 报价表结构"可参考。
- **`harry10086/kicad-jlcpcb-tools`**（`lcsc_api.py` 逐字读过）：两个接口封装
  1. `GET https://cart.jlcpcb.com/shoppingCart/smtGood/getComponentDetail?componentCode={C}`（=datasheet 直链、英文品牌名）
  2. `POST https://so.szlcsc.com/query/product`（= 立创中文站搜索，与 Lead 打通的是同一个；body 里 `sortNumber:0` 可改成 6 拿销量降序）
  它把 `vo.pdfUrl`（**中文站搜索结果里直接带 datasheet 链接**）和 `productId` → `https://item.szlcsc.com/{productId}.html` 用上了。

---

## 8. 淘宝 / 1688 / 京东 —— "自己爬 vs 买 API"

**结论：没有免费的公开 JSON API；公开可用的现成件全是「浏览器自动化」或「付费聚合」。**

**先说不带登录态直连公开搜索页的实测结果（全部被拦，这就是为什么必须"自动化"或"买 API"）**：

| 站点 | 请求 | 实测返回 | 判定 |
|---|---|---|---|
| 淘宝 | `GET https://s.taobao.com/search?q=STM32F103C8T6` | **200 但只有 34,331 B**，页面里没有任何商品，只有 `mtb/lib-login` 一类脚本 → 登录壳 | **被拦** |
| 1688 | `GET https://s.1688.com/selloffer/offer_search.htm?keywords=…` | **200 但只有 2,349 B** 的空壳 | **被拦** |
| 京东 | `GET https://search.jd.com/Search?keyword=…` | **302** → `https://cfe.m.jd.com/privatedomain/risk_handler/03101900/?evApi=color-mesh_A_SC_pc_search_java_Search…` | **风控拦截** |
| 京东移动 | `GET https://so.m.jd.com/ware/search.action?keyword=…` | **302** | **被拦** |

（原始 HTML 存 `probe/github/tb_search.html`、`alibaba1688_search.html`、`jd_search.html`，UA 已模拟桌面 Chrome 131，走本机代理。）

1. **npm 官方 SDK 全死**：`taobao@1.0.9`（2016-05）、`taobao-openapi@1.4.3`（2016-10）、`taobao-sdk@2.0.5`（2018-01）、`node-taobao-topclient@0.1.7`（2016-11）
   —— 都是淘宝开放平台 TOP SDK，**必须商家 appkey + appsecret + 授权**，读不到公开搜索结果。
2. **npm 上的活项目（2026 年，全部基于 Playwright/puppeteer-stealth 驱动真浏览器）**：
   - `1688-cli@0.1.47`（2026-06-27，MIT）：`1688.com CLI for humans, Codex, and Claude Code. Product search, supplier scraper/research, inquiry, cart, orders, logistics, and seller chat.`
     依赖 `playwright + playwright-extra + puppeteer-extra-plugin-stealth + proper-lockfile`；
   - `1688-claw@0.1.1`（2026-07-15，read-only）：`keyword, image, offer, official similar searches`；
   - `@petercjl/tbcli@0.13.0`（2026-11-02）：淘宝/千牛**卖家后台**工作流（不是采购）；
   - `@petercjl/1688-product-sourcing@0.2.0`、`@petercjl/1688-opportunity-sourcing-research@0.1.1`：1688 选品 skill（同样是自动化壳）。
   - `@optima-chat/scout-cli`、`@petercjl/taobao-search-product-form`：带"real sales data"字样的商业化 CLI。
   → 都是"用你的登录态驱动浏览器"，**没有免登录的公开接口**；判定为**代码可见未实测**（需要登录，且会触发风控）。
3. **MCP 生态（官方 registry `registry.modelcontextprotocol.io`，实测**不需要鉴权**即可查询）**：
   - `io.github.zen-studio-labs/taobao-tmall-mcp`：淘宝/天猫 商品搜索/详情/SKU/评价/店铺目录 —— 但 remote 是 `https://mcp.apify.com/?tools=…/taobao-search-scraper`，
     **必须 Apify OAuth 或 `Bearer <APIFY_TOKEN>`**（按次计费）；
   - `io.github.serenido/1688-product-details`：1688 按链接/id 取「阶梯价、SKU 库存、规格、供应商、英文」，remote 同样是 `mcp.apify.com`（付费）；
   - `io.github.zen-studio-labs/alibaba-1688-mcp`：同上（Apify）；
   - registry 里搜 `lcsc` / `jlcpcb` **0 条**；`pinduoduo` 0 条；`jd` 关键词请求直接 422。
   → 「买 API」路线 = Apify actor 按次收费；「自己爬」路线 = Playwright + 用户登录态 + 风控对抗。
4. **目录站 API**：`glama.ai/api/mcp/v1/servers` → **401**（要 key）；`registry.smithery.ai/servers?q=` → **500**；`mcp.so/api/search` → **404**。
   → 只有 **官方 MCP registry** 可免鉴权查询（`https://registry.modelcontextprotocol.io/v0/servers?search=<kw>&limit=25`），这个可以用。

---

## 9. `parts-mcp` (PyPI 0.5.3) —— 不是免费轮子【实测 403】

SourceParts 的 SaaS 客户端：所有数据走 `https://api.source.parts/v1/`，未鉴权 → **403 `{"error":"Forbidden"}`**；
hosted server `https://mcp.source.parts`：`GET /`=405、`POST /mcp`=404（要 OAuth）。
`tools/sourcing.py` docstring 逐字：
> "Per-supplier comparison (DigiKey, Mouser, …) is NOT supported — a `suppliers` list is acknowledged with a warning, never silently honored."

→ "多商城比价"名不副实。**可复用**：`utils/bom_parser.py`、`utils/component_matcher.py`、`utils/matching.py`（`verify_mpn_match`）、
`utils/value_parser.py`、`utils/footprint_matcher.py`、`tools/search.py`（每条结果打 `match_verified`）—— 正是我们要自建的那块的参考实现。

---

## 10. `jlcpcb` (PyPI 0.1.0) —— 免 key、**带属性筛选**的嘉立创 CLI【实测可用，最实用的一件】

```powershell
pip install --index-url https://pypi.org/simple jlcpcb
$env:no_proxy=$null; $env:NO_PROXY=$null        # 必须！否则 httpx 崩 InvalidURL: Invalid port ':1]'
jlcpcb --json part list -q "0603 100nF" --limit 2
jlcpcb --json part get C8734
```

命令面：`part {autocomplete,datasheet,get,image,list,svg}`、`category`、`brand`、`hot`、`fx`、`profile`、`job`、
`agent-context`（吐出机器可读的 CLI 全量描述）、`skill-path`（附带 **agent skill 清单目录**）、`feedback`。
全局 `--json / --table / --profile`。

**`part list` 的筛选维度（`--help` 逐字，这是它最值钱的地方）**：
`-q/--keyword`、`--category-id`、`--subcategory-id`、`--brand`（可重复）、`--package`（可重复）、
**`--attr NAME=VALUE`（可重复，服务端属性筛选，例 `--attr='Mounting Type=Panel Mount'`）**、
`--library base|expand`、`--preferred`、`--in-stock`、`--min-stock N`、`--has-datasheet`、`--has-photo`、
`--presale stock|buy|post|all`、`--page`、`--limit`（**服务端上限 72**）。

实测 `part list -q "0603 100nF" --limit 2` → `{"total": 2253, ...}`，每条：
`component_code / brand / model / package / library(base|expand) / stock / initial_price / data_manual_url / first_sort_name / second_sort_name`。

实测 `part get C8734` → 完整详情（90+ 字段）：
`stock_count=229678`、`can_presale_number=125949`、`encapsulation_number=250`、`component_library_type="expand"`、
`prices[]` 6 档 **人民币** 1.4957 / 1.2989 / 1.1595 / 1.0333 / 0.9742 / 0.9496（1/10/30/250/500/1000+）、
`attributes[]` 12 项（**英文名 + 字符串值**：Operating Temperature `-40~+85`、`Voltage - Supply` `2V~3.6V`、Number of I/O `37`、ADC (Bit) `12bit`…）、
`describe`（长描述）、`data_manual_url`、`lcsc_goods_url`、`component_designator="U"`、`assembly_mode="smtWeld"`、
`eccn_code`、`moisture_sensitivity_level_en="MSL 3"`、`warehouse_code="sz"`、`overseas_stock_count`。

**实现**（`jlcpcb/constants.py`）：`BASE = "https://jlcpcb.com"`，路径前缀
`/api/overseas-pcb-order`、`/api/overseas-core-platform`、`/api/overseas-smt`、`/api/overseas-basic-data`；
`DETAIL = "{CORE_PLATFORM}/shoppingCart/smtGood/getComponentDetail"`。→ 就是 §5 那套网页 API 的工程化封装，
但**它替我们解决了 XSRF token、分页、属性筛选、签名 URL 解析**，还定义了 0–9 的退出码（`auth_required=3`），明显是给 agent 用的。

**坑**：① 必须清 `no_proxy`（同 `lcsc`）；② 控制台里 `erp_component_name`/`describe` 的中文是乱码（GBK/UTF-8 输出问题，与数据无关，`--json` 落文件后再读就正常）；
③ 参数是**字符串**（`2V~3.6V`），要数值比较得自己 parse，或者用 §1 的 jlcparts 离线库；
④ **无销量**（`recent_buy_num: null`），替代料字段 `component_alternatives_code` 本次为 null 未验证到有值的情况。

---

## 11. 离线按参数筛选 —— 可行性已用 60 行脚本验证【实测可用】

`probe/github/decode_shard.py`（本机实测，读 jlcparts 公开数据，无需任何 key）：

```powershell
# 场景A：5V→3.3V LDO，输出电流 ≥0.5A，SOT-23 封装，库存 ≥1000，按库存降序
python decode_shard.py --subcat "Low Drop Out" --num "Output Current>=0.5" `
    --flag "Package=SOT-23" --min-stock 1000 --sort stock --top 6 --json-out jlcparts_query_ldo.json

# 场景B：MLCC ≥1µF、额定电压 ≥25V、库存 ≥5000，按库存降序
python decode_shard.py --subcat "MLCC - SMD" --num "Capacitance>=1e-6" `
    --num "Rated Voltage>=25" --min-stock 5000 --sort stock --top 6 --json-out jlcparts_query_mlcc.json
```

实测输出（场景A）：`scanned=7016 matched=215`，
`C47773 RT9013-33GB stock=281574 pads=5 @100=$0.1177 | Richtek, SOT-23-5, Extended, Supply Voltage=5.5V, OpTemp=125C~-40C, Output Current=0.5A`
（Top6 依次 RT9013-33GB / ME6211C33M5G-N / RT9013-33GB-MS / TLV75533PDBVR / ME6217C33M5G / TPRT9013-33GB —— **都是真实在卖的 500mA LDO，结果可核对**）。
实测输出（场景B）：`scanned=15961 matched=524`，
`C15849 CL10A105KB8NNNC stock=9868521 pads=2 @100=$0.0152 | Samsung, 0603, Basic, 1µF, ±10%`。

→ **结论**：全量离线库 + 类型化参数表 ⇒ "按指标筛选 / 反向选型 / 按库存排序 / 按目标数量取阶梯价" 全部可以在本地完成，不依赖任何商城接口的稳定性。

**坑（真实存在）**：① **参数名按品类不同**：电容的耐压叫 `Rated Voltage`，而 LDO 叫 `Supply Voltage`，电阻叫 `Resistance` —— 必须按品类建"参数别名表"，这是我们要自建的那一小块；
② 一个分片 1000 行，热门子类几十个分片（电阻 59 个）→ 首次全量抓取要遍历 `manifest.files`（3672 个文件），建议只按需抓子类；
③ `Operating Temperature` 这类参数是"范围型"（`tolerance min/max`、`temperature min/max`），要按 primary 字段比较，不能直接读第一个数。

原始输出：`probe/github/jlcparts_query_ldo.json`、`jlcparts_query_mlcc.json`；缓存分片在 `probe/github/cache/`。

---

## 12. 推荐技术路线

```
BOM 行(型号/描述/数量)
   │
   ├─[1] 型号规范化 + 值解析（可抄 parts-mcp 的 value_parser / footprint_matcher）
   │
   ├─[2] 搜候选（三路并行，按需要选）：
   │       a) 立创中文站 POST so.szlcsc.com/query/product        ← 有**销量**、人民币、中文商品名
   │       b) jlcpcb CLI `part list -q/--attr/--package/--library` ← 免 key、属性筛选现成
   │       c) wmsc.lcsc.com /ftps/wm/search/v3/global             ← 英文站，paramNameValueMap 结构化筛选
   │       d) 离线：decode_shard.py + jlcparts                      ← 不依赖接口稳定性，指标反查首选
   │
   ├─[3] 单件详情：www.lcsc.com/product-detail/{C}.html 的 __NEXT_DATA__.webData
   │         └ 中文参数名 + 替代料明细 + 分仓库存 + 阶梯价 + datasheet PDF
   │
   ├─[4] 离线比指标 / 反向选型：jlcparts JSONL 分片 + attributes-lut（367k 件，带类型参数）
   │
   ├─[5] 匹配打分：封装一致性 + 关键参数 ±容差 + Basic/Extended + 库存/交期 → 排序
   │
   └─[6] 阶梯价按目标数量落档；替代料用 alternatePartList 展开；导出 BOM/下单表
```

- **复用**：立创中文站搜索（Lead 已通，唯一有销量）、`jlcpcb` PyPI CLI（免 key 属性筛选 + 详情，直接当后端用）、
  `lcsc` PyPI 客户端（海外站 `paramNameValueMap` 结构化筛选）、lcsc 详情页 `__NEXT_DATA__`（替代料 + 中文参数名）、
  jlcparts 数据托管 + `probe/github/decode_shard.py`（离线参数库，367k 件）、
  `jlcpcb-mcp` 的工具划分与"两套库存"区分、`easyeda2kicad`（落 EDA，AGPL 需隔离调用）。
- **不需要自己写**：爬虫框架、参数表抓取、MCP 外壳、EDA 格式转换、分页/鉴权/token 处理。
- **必须自建（小）**：① BOM 行→候选料的**匹配打分与决策**（型号规范化、封装一致性、替代料策略、阶梯价落档、缺货退让）；
  ② **参数别名表**（同名指标在不同品类叫不同名字：`Rated Voltage` / `Supply Voltage` / `Voltage - Supply`），这是离线筛选落地的关键；
  ③ 渠道建议规则（少量→淘宝/立创零售，批量→1688/立创批发）。
- **淘宝/1688**：短期建议**不做**自动检索（无合法免费接口）；按需用「用户给链接 → `serenido/1688-product-details` 类 Apify actor 解析」这种"人工指路 + 机器解析"的折中。

---

## 附：环境坑（会浪费时间的，先记下）

1. `pip` 必须加 `--index-url https://pypi.org/simple`（清华源实测取不到任何包）。
2. `*.lcsc.com`（`www` 与 `wmsc`）**不能走 127.0.0.1:7890**：curl 返回 000、Python 报 `SSLEOFError`。
3. 本机 `no_proxy=localhost,127.0.0.1,::1,[::1]` 会让 httpx 直接崩：`InvalidURL: Invalid port ':1]'` → 用前先 `$env:no_proxy=$null`。
4. `curl -sI` 的第一行是代理的 `HTTP/1.1 200 Connection established`，**不是真实状态码**。
5. GitHub REST API 本机已耗尽（`remaining=0/60`）→ 用 `https://codeload.github.com/{o}/{r}/zip/HEAD` 下源码，
   星数从仓库 HTML 正则 `repo-stars-counter-star[^>]*title="(\d+)"` 取。
6. 官方 MCP registry 免鉴权可用：`https://registry.modelcontextprotocol.io/v0/servers?search=<kw>&limit=25`。
