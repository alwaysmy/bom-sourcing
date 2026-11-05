# 立创商城（szlcsc.com / lcsc.com）数据接口摸底报告

> 实测环境：Windows 11 + pwsh 7 + Python 3.14（urllib，无第三方库）+ 本机真浏览器（Edge，已登录账号 416461A）。
> 所有"实测成功"项均为**浏览器外、无 Cookie、直连**复放通过；样本与本报告同目录 `probe/lcsc/`。
> 时间：2026-11-04。价格/库存等业务数值会变，接口形状不会。

---

## 一、可直接用的结论

### 1.1 能用的接口（按价值排序）

| # | 用途 | method | URL | 关键参数 | 鉴权 | 证据 |
|---|---|---|---|---|---|---|
| 1 | 关键词搜索/比价/排序/分页 | POST | `https://so.szlcsc.com/query/product` | JSON body（见 §2） | **免登录** | 【实测成功】 |
| 2 | 商品详情（参数表/阶梯价/手册/库存） | GET | `https://item.szlcsc.com/{productId}.html` | productId=数字内部 id | 免登录 | 【实测成功】 |
| 3 | **替代料**（含相似度/参数差异/报价） | POST | `https://list.szlcsc.com/substitute/simple/list?productCode=C46634460` | body 必须 `{}` | **免登录** | 【实测成功】 |
| 4 | 相似/推荐商品 | GET | `https://item.szlcsc.com/product/relation/recommend?productId={id}` | — | 免登录 | 【实测成功】 |
| 5 | 数据手册 PDF 直链 | GET | `https://atta.szlcsc.com` + `fileUrl` + `urlSign` | 来自详情页 `webData.pdfFileDetailVO` | 免登录（OSS 签名） | 【实测成功】 |
| 6 | BOM 上传解析 | POST | `https://bom.szlcsc.com/bom/upload` | multipart：`bomFile`=文件 | **需登录 Cookie** | 【实测成功】 |
| 7 | BOM 行数据/匹配状态 | GET | `https://bom.szlcsc.com/async/bom/match/page?bomUuid=…` | bomUuid, currentPage, pageSize | **需登录 Cookie** | 【实测成功】 |
| 8 | BOM 触发匹配（AI/一键） | POST | `https://bom.szlcsc.com/async/bom/ai/match` | form-urlencoded | 需登录 Cookie | 【抓包/JS 可见未复放】 |
| 9 | 登录态校验 | GET | `https://bom.szlcsc.com/cas/user/info` | — | 200=已登录 / **401=未登录** | 【实测成功】 |
| 10 | 额外报价（带签名） | GET | `https://item.szlcsc.com/product/stock/price/sign?...&cvt=&nonce=&sign=` | cvt/nonce/sign | 需签名算法 | 【抓包可见未复放】 |
| 11 | 国际站数据 | — | `www.lcsc.com` 页面 SSR | — | — | 【实测：无公开 JSON API】 |
| 12 | 官方 OpenAPI | — | `open.jlc.com` / `open.szlcsc.com` | — | 需商务申请 key | 【推测，Lead 已确认需资质】 |

### 1.2 三个被点名问题的结论

**Q1：参数区间筛选（阻值/精度/功率…）有没有可用参数名？**
**没有服务端参数筛选。** 关键词搜索下 `searchResult.parmeterValueList` 恒为 `[]`（试过 `贴片电阻`、`0805 电阻`、`电容`、`STM32F103C8T6` 四组）；`queryParameterValue` + `lastParamName` 传值返回 **0 条**。参数维度筛选只存在于"商品目录"页，不在关键词搜索页。
→ 正确做法：**用搜索结果里已带的结构化参数 `paramLinkedMap`（"参数名:值" 扁平对象）在客户端过滤/比较**，不需要也拿不到服务端参数过滤。证据【实测成功】。

**Q2：BOM 配单有没有免登录 HTTP 接口？**
**有 HTTP 接口，但必须登录态。** `POST https://bom.szlcsc.com/bom/upload`（multipart，字段 `bomFile`）带用户 Cookie → HTTP 200 返回解析结果；**不带 Cookie → HTTP 200 但空 body（静默拒绝）**，`/cas/user/info` 返回 `code:401`。没有免登录路径，也不需要浏览器——**只要拿到 Cookie 就能纯 HTTP 跑完整条链路**。证据【实测成功】。

**Q3：`substitute/simple/list` 与海外站 `alternatePartList` 的差别？**
`substitute` 是**立创国内站自己的替代料接口，免登录可复放**，比海外站 `__NEXT_DATA__.webData.alternatePartList` **更全、更快、字段更多**：

| | `list.szlcsc.com/substitute/simple/list` | 海外站 `alternatePartList` |
|---|---|---|
| 获取方式 | 纯 JSON API（POST，body `{}`） | 抓 SSR 页面 `__NEXT_DATA__`，需整页渲染 |
| C8734 替代料条数 | **36 条**（all）/ 7 条同品牌 / 29 条国产 | 5 条 |
| 相似度 | `simScore` 74~95 + `subLabel`（如 `["封装相同"]`） | 无（或仅文字） |
| 定价 | `productPriceList` 阶梯价 + `priceDiscount` 折扣活动价 | 一般只有单价 |
| 库存 | `stockNumber`/`validStockNumber`/`totalStockNumber`/`gd`/`js`/`smt` 六件套 | 有限 |
| 参数差异 | 主料 `mainParamLinkedMap` + 替代料 `paramLinkedMap` + `paramGroup`，可直接 diff | 中文参数文本 |
| 认证/手册 | `fileTypeVOList`（RoHS/REACH/HF 认证 PDF + 手册）、`pdfDESProductId` | 无 |
| 批量 | 不支持（`productCodeList` 无效） | 不支持 |

结论：**配单的替代料首选这个国内站接口**，海外站只在需要英文参数/海外库存时补充。证据【实测成功】。

### 1.3 能不能做不依赖浏览器的 CLI？——**能，且大部分免登录**

| 能力 | 浏览器外可行 | 条件 |
|---|---|---|
| 检索/比价/排序/筛选/分页 | ✅ 完全可行 | 无 Cookie |
| 详情/参数表/阶梯价/库存/交期/MOQ | ✅ | 无 Cookie（用 productId） |
| 数据手册 PDF | ✅ | 无 Cookie（OSS 签名 URL） |
| 替代料 + 相似度 + 参数差异 | ✅ | 无 Cookie |
| BOM 上传解析 + 行数据 | ✅（纯 HTTP） | **需用户 Cookie**（可从浏览器导出） |
| BOM 触发匹配 | ⚠️ 未复放 | 需 Cookie + AI 匹配配额 |
| 加购/下单 | ❌ 本阶段不做 | — |

唯一需要浏览器的东西：**拿 BOM 用的 Cookie**，以及逆向签名接口（`price/sign`）——后者非必需（该接口对普通商品返回 `null`）。

---

## 二、搜索接口（核心）

### 2.1 请求

```
POST https://so.szlcsc.com/query/product
Content-Type: application/json
Origin:  https://so.szlcsc.com
Referer: https://so.szlcsc.com/global.html
User-Agent: <任意现代浏览器 UA>
```

请求体 28 个字段（实测抓包原文，缺省值原样带上是安全的）：

```json
{"currentPage":1,"pageSize":30,"catalogIdFilter":"","brandIdFilter":"","standardFilter":"",
 "arrangeFilter":"","labelFilter":"","authenticationFilter":"","keyword":"STM32F103C8T6",
 "sortNumber":6,"satisfyStockType":"","startPrice":"","endPrice":"","demandNumber":"",
 "spotFilter":1,"discountFilter":1,"hasDataFile":false,"brandPlaceFilter":"","secondKeyword":"",
 "queryParameterValue":"","lastParamName":""}
```

样本：`probe/wide_sort_00.json`、`probe/probe_sort_06.json`、`probe/probe_filter_verify.json`（Lead 与我各一份）。

### 2.2 响应结构

```jsonc
{"code":200,"msg":null,"result":{
  "searchResult":{
     "productRecordList":[...],          // 结果行
     "totalCount":8, "countPage":1,      // ★ 真实总数在这里（外层 result.totalCount 为 null）
     "catalogGroup":[...], "gradePlateGroup":[...], "encapsulationGroup":[...],
     "arrangeGroup":[...], "labelGroup":[...], "authenticationGroup":[...],
     "parmeterValueList":[],             // ★ 关键词搜索恒为空（无参数筛选）
     "querySortBySign":6 } }}
```

**结果行 `productRecordList[i]` 关键字段**

| 字段 | 含义 |
|---|---|
| `productVO.productCode` | C 编号（C8734） |
| `productVO.productId` | **数字内部 id**（9243）——详情页/推荐接口要用它 |
| `productVO.productModel` | 厂家型号 |
| `productVO.productGradePlateName` | 品牌（`ST(意法半导体)`） |
| `productVO.encapsulationModel` | 封装（`LQFP-48(7x7)`） |
| `productVO.productType` | 中文类目 |
| `paramLinkedMap` | ★ **结构化参数**：`{"CPU内核":"ARM Cortex-M3","CPU最大主频":"72MHz",...}` |
| `productVO.productPriceList[]` | ★ 阶梯价：`startPurchasedNumber`/`endPurchasedNumber`(-1=无上限)/`productPrice`/`thePrice`/`minEncapsulationUnitPrice` |
| `productVO.stockNumber` / `totalStockNumber` / `smtStockNumber` | 现货 / 总库存 / 嘉立创 SMT 库存 |
| `productVO.recentlySalesCount` | ★ 销量（真实数字，见 §9） |
| `productVO.minBuyNumber` | MOQ 起订量 |
| `productVO.deliveryTimeWayDays` | 交期天数 |
| `productVO.smtLabel` | 贴片标签（`SMT扩展库`/`smt基础库`） |
| `productVO.pdfDESProductId` / `hasDataFile` | 有无数据手册 |
| `replaceProductId` / `maybeLook` | 替代料 / 相似商品线索 |
| `lightCatalogName` / `lightProductModel` | ⚠️ **含高亮 HTML**：`贴片<SPAN CLASS='LUCENE_HIGHLIGHT_CLASS'>电阻</SPAN>`，必须剥离 |

### 2.3 分页与上限（实测）

- `pageSize` **≤ 30 是硬上限**：传 40/50/60/80/100 全部返回 `code:200` 但 **0 条记录**（不是报错，容易踩）。
- `currentPage=2` 与 page1 **不重叠**，分页正常。
- `totalCount` 对宽泛词**封顶 1500**（`电阻`→1500，`countPage` 也是按 1500 算）；对窄词返回真实值（`STM32F103C8T6`→8，`labelFilter=smt基础库`→185）。
  → 需要"全量"时：按 `catalogIdFilter` / `standardFilter` / `brandIdFilter` **切片递归**，而不是翻 50 页。

---

## 三、排序（sortNumber）

页面排序栏文案：`综合排序 | 价格 | 库存 | 销量 | 价格/库存筛选`（DIV，非链接，点击纯 XHR，不改 URL）。
真浏览器逐个点击抓到的映射：综合→`0`、价格→`1`（升序）、再点价格→`2`（降序）、销量→`6`；"库存"点击未触发 XHR（DOM 匹配到但无请求）。

用宽泛关键词 `电阻`（1500 条）对 `sortNumber=0..12` 全跑一遍，按 `recentlySalesCount`/`price`/`stockNumber` 单调性判定：

| sortNumber | 语义 | 单调性 | 建议 |
|---|---|---|---|
| 0 | 综合（≈销量降序） | sales desc | ✅ 用 |
| 1 | 价格升序 | price asc | ✅ 用 |
| 2 | 价格降序 | price desc | ✅ 用 |
| 3 | 分桶子集（head 全 stock=0/sales=0） | flat | ❌ 不用 |
| 4 | 库存降序 | stock desc | ✅ 用 |
| 5 | 分桶子集（同 3 的另一顺序） | flat | ❌ |
| 6 | **销量降序** | sales desc | ✅ 用（傅师傅要的） |
| 7 | 新品/低销量子集（集合不同） | 集合变化 | ❌ |
| 8 | 库存降序（与 4 同 head） | stock desc | ❌ 重复 |
| 9/11/12 | 分桶子集 | flat | ❌ |
| 10 | 库存降序（同 4/8） | stock desc | ❌ 重复 |

**实现只用 `0 / 1 / 2 / 4 / 6`**。注意 sort=6 不保证有货（实测第 3 条 `C25744` stock=0），需要"有货 + 高销量"时在客户端二次过滤。

样本：`probe/probe_sort_semantics.json`、`probe/probe_wide_sort_00..12.json`、`probe/probe_sort_clicks.json`。

---

## 四、筛选参数（全部 curl 直连实测成功）

| 请求字段 | 取值格式 | 取值来源 | 实测验证 |
|---|---|---|---|
| `brandIdFilter` | 品牌 id，**多值用 `$` 分隔**：`91$842` | `searchResult.gradePlateGroup[].value` | 30/30 命中 VISHAY\|KOA；⚠️ 用逗号 `91,842` → **0 条** |
| `standardFilter` | 封装 label，`$` 分隔：`0805$0603` | `encapsulationGroup[].label` | 30/30 命中 |
| `catalogIdFilter` | 类目 id 数字：贴片电阻=439 / 电阻=308 / 可调电阻=520 | `catalogGroup[].value` | 30/30 命中 |
| `brandPlaceFilter` | 产地：`中国大陆$中国台湾` | 页面"国产品牌"勾选框 | 通过 |
| `labelFilter` | 标签：`smt基础库` / `车规级` / `aec-q200` | `labelGroup[].label` | totalCount=185 |
| `authenticationFilter` | `RoHS认证` | `authenticationGroup[].label` | 通过 |
| `arrangeFilter` | 包装：`编带`/`袋装`/`托盘`/`盒装`/`管装`/`箱装` | `arrangeGroup[].label` | 通过 |
| `startPrice` / `endPrice` | **字符串**数字：`"0.01"`/`"0.02"` | — | 30/30 价格 ≤0.02 |
| `spotFilter` | `1`=只看现货（默认）/`0`=不限 | — | ⚠️ 只筛掉 2~4 条，**不能当"库存>0"用** |
| `discountFilter` | `1`（默认） | — | — |
| `hasDataFile` | `true`/`false` | — | true→30/30 有 `pdfDESProductId`；false→0/30 |

> **"只看有货"没有专用字段**：`spotFilter=1` 语义不等于 `stockNumber>0`。要严格有货，取回后按 `stockNumber>0`（或 `hasStockNow=="yes"`）本地过滤。

样本：`probe/probe_filters_raw.json`（674KB，含全部筛选维度原文）、`probe/probe_filter_verify.json`、`probe/probe_filter_clicks.json`。

---

## 五、商品详情

```
GET https://item.szlcsc.com/{productId}.html        # 注意：productId 是数字 id，不是 C 编号
# C8734 → 9243；C46634460 → 48788262
```
免登录、无 Cookie，HTTP 200（159KB HTML），Next.js SSR，数据在 `<script id="__NEXT_DATA__">` → `props.pageProps`。

| 数据 | 位置 |
|---|---|
| **结构化参数表** | `webData.paramList[]`：`{"parameterName":"CPU内核","parameterCode":"param_13056","parameterDetailValue":"ARM Cortex-M3","parameterValue":"ARM Cortex-M3"}`（C8734 共 12 项） |
| 主数据 | `webData.productRecord`（50 字段：stockNumber / minBuyNumber / productMinEncapsulationNumber / deliveryTimeWayDays / smtLabel / productWeight / encaptionPrice / lcedaProjectUrl / bomMainUuid…） |
| **手册 PDF** | `webData.pdfFileDetailVO`：`{fileName, fileUrl:"/upload/public/pdf/source/…pdf", urlSign:"?Expires=…&OSSAccessKeyId=LTAI…&Signature=…%3D&response-content-disposition=attachment%3Bfilename%3D…"}` → 完整 URL = `https://atta.szlcsc.com` + `fileUrl` + `urlSign`，**urlSign 里每个 query 都必须原样带上**（漏了 → OSS 403 `SignatureDoesNotMatch`）。实测 C8734 手册下载成功 2,077,497 字节 `application/pdf` |
| 认证/分类手册 | `webData.fileTypeVOList`（RoHS / REACH / HF 认证 PDF） |
| 手册文字摘要 | `pageProps.productPdfDesc.productPDFDescVO`（`productFeatures` ~887 字） |
| 相似/推荐 | `pageProps.similarProductRecommend`（similar 14 / other 21，只有 id+型号） |
| 轻量备选 | HTML 里的 `application/ld+json`：`sku`/`mpn`/`brand`/`offers.price`/`offers.inventoryLevel`/`subjectOf.url`（**无签名**手册直链，但无参数表） |

样本：`probe/probe_item_9243_nextdata.json`、`probe/probe_item_48788262.html`、`probe/probe_C8734_datasheet.pdf`、`probe/probe_pdf_url.txt`。

---

## 六、替代料（配单最值钱的能力）

### 6.1 请求（关键：参数在 query，body 必须是空对象）

```bash
curl -X POST "https://list.szlcsc.com/substitute/simple/list?productCode=C46634460" \
  -H "Content-Type: application/json" -H "Origin: https://item.szlcsc.com" \
  -H "Referer: https://item.szlcsc.com/" --data-binary "{}"
```

- **免登录、免 Cookie**（带不带 Cookie 响应完全一致，21966 字节）。
- ⚠️ 两个坑：把 `productCode` 放进 body → 返回 `code:200` 但所有子列表为 `null`；用 GET → `code:500 系统异常`。
- 不支持批量（`productCodeList` 无效）。

### 6.2 响应结构

```jsonc
{"code":200,"result":{
  "mainProduct":{ "productCode":"C46634460","productId":"48788262","productModel":"JER2512F3R005",
                  "mainParamLinkedMap":{...},"paramLinkedMap":{...},
                  "productPriceList":[阶梯价],"priceDiscount":{活动折扣价},
                  "stockNumber":160537,"validStockNumber":32107,"totalStockNumber":160535,
                  "gdWarehouseStockNumber":160535,"smtStockNumber":169136,"theRatio":5 },
  "all":        {"substitutes":[...],"paramGroup":{"阻值":["5mΩ"],"精度":["±1%"],...}},
  "domestic":   {"substitutes":[...],"paramGroup":{...}},   // 国产替代
  "internation":{"substitutes":[...],"paramGroup":{...}},   // 国外品牌替代
  "sameBrand":  {"substitutes":[...],"paramGroup":{...}}    // 同品牌替代
}}
```

每条 `substitutes[i]` 关键字段：`simScore`（相似度 74~95）、`subLabel`（差异标签，如 `["封装相同"]`）、`productCode`/`productId`/`productModel`/`productGradePlateName`/`encapsulationModel`、`productPriceList`（阶梯价）、`priceDiscount`、`stockNumber`/`validStockNumber`/`totalStockNumber`/`smtStockNumber`、`paramLinkedMap`（该替代料参数，可与 `mainParamLinkedMap` 直接 diff）、`pdfDESProductId`、`fileTypeVOList`（手册+认证 PDF）、`deliveryTimeWayDays`、`productStockStatus`、`usableTransitNum`、`isDomestic`。

### 6.3 实测样本

- **C8734（STM32F103C8T6）→ 36 条替代料**：sim 95 `C2969777 STM32F103C8T6TR`、sim 90 `C8304 STM32F103CBT6`（差异仅"程序存储容量 64KB→128KB"）、sim 85 国产兼容 `C526178 APM32F103CBT6` / `C393540 APM32F103C8T6` / `C907710 HK32F103CBT6A` / `C2687451 CH32F103C8T6` / `C556577 CKS32F103CBT6`。
- **C46634460（采样电阻）→ 1 条**：`RE2512F3R005` / JIERR / 2512 / 相似度 76% / 封装相同 / 现货 19,335 / ¥0.2492。

样本：`probe/probe_substitute_C8734_nocookie.json`（351KB）、`probe/probe_substitute_C46634460_nocookie.json`、`probe/probe_substitute_inbrowser.json`。

### 6.4 "相似商品"是另一回事

`GET https://item.szlcsc.com/product/relation/recommend?productId={id}` 免登录可复放，返回 `associateVOList[8]`，但会混入无关品类（C46634460 里混了 0603 电阻/电容）→ 是"买了又买/推荐"，**不能当替代料**。

---

## 七、BOM 配单

### 7.1 入口与链路

- 入口：`https://bom.szlcsc.com/`（Next.js，"立创BOM智能云表"）；工作区 `https://bom.szlcsc.com/member/bom-sheet.html?bomUuid=…`
- 支持格式：`xls / xlsx / csv / jpg / png / jpeg`，**单文件 ≤10MB**
- 基址来自前端配置 `lcscBomUrl`（`_app` chunk 内硬编码 `"https://" + env + "bom.szlcsc.com"`，pro 环境 env 为空）
- 所有 POST 请求由 axios 拦截器自动追加 `pageSource=sheet`

### 7.2 上传解析（实测成功）

```bash
curl -X POST "https://bom.szlcsc.com/bom/upload" \
  -H "Cookie: <浏览器 Cookie>" \
  -F "pageSource=sheet" -F "bomFile=@bom.csv;type=text/csv"
```

响应**不是纯 JSON**，前面带了脚本前缀，必须剥掉：

```
<script>document.domain='szlcsc.com';</script><body>{"bomCode":"BOM261104003828","bomItemSize":6,
"bomUuid":"B7269EE5A7005A30CC80A53F997A498C","matchSize":6}</body>
```

- 无 Cookie → **HTTP 200 空 body**（静默失败，不报 401）。
- CSV 表头用中文即可（`位号,数量,型号,封装,品牌`），解析器能自动识别列序（`reorderedTitle` 回显它认的列）。

### 7.3 行数据 / 匹配状态

```
GET https://bom.szlcsc.com/async/bom/match/page?bomUuid={uuid}&currentPage=1&pageSize=500
Cookie: <同上>
```
返回 `result.bom`：`matchState`、`bomAiMatchStatus`、`applyMatchStatus`、`reorderedTitle`、`bomItemList[]`。

`bomItemList[i]`：`serialNo`、`tagNo`（位号 R1）、`tagNoFlag`（R/C/U…）、`tagNoCatalog`（推断类目）、`quantity`、`pack`、`productCode`（原始型号）、`param`、`userOriginalInfo{productCode,param,model,brand,pack}`、`rawData`（原始行文本）、`reorderedCells[]`、`rowValidStatus`、`lossNum`（备损）、`bomItemId`。

匹配状态枚举（来自前端过滤逻辑）：`perfect`=完全匹配 / `wait_match`=AI识别·待确认 / `cannot_match`=无法匹配；`matchState:"wait"` 表示**尚未触发匹配**（刚上传时就是它）。

### 7.4 触发匹配（未复放，谨慎）

| 用途 | method | 路径 | 备注 |
|---|---|---|---|
| 触发 AI/一键匹配 | POST | `/async/bom/ai/match` | form-urlencoded，**消耗 AI 配单配额**（`aiCurrentUsage`），故本报告只记录未执行 |
| 匹配进度 | GET | `/async/bom/ai/match/progress` | 轮询 |
| 终止匹配 | POST | `/async/bom/ai/match/termination` | form |
| 匹配结果分页（旧版） | POST | `/async/bom/match/finished/v2` | form-urlencoded |
| BOM 内搜料 | GET | `/async/bom/search/item/page` | keyword |
| BOM 内替代料 | GET | `/async/bom/substitute/list` | 需 bomUuid + productCode |
| 导出报价单 | GET | `/bom/item/export?bsuuid={uuid}&bomUuid={uuid}` | 直接下载 |

样本：`probe/probe_bom_test.csv`、`probe/probe_bom_upload_resp.json`、`probe/probe_bom_match_page_final.json`、`probe/probe_bom_sub_async_bom_match_page.json`。

---

## 八、限流实测

连续 20 次 `POST /query/product`（固定间隔 0.5s，无 Cookie）：**20/20 全部 HTTP 200**，无 429、无 403、无 `X-RateLimit-*` 头、无 IP 封禁迹象；延迟 370~1654ms（首次 1.65s 为冷启动，随后稳定 ~400ms）。

**建议**：常驻单线程 **QPS ≤ 1**（间隔 0.6~1.0s + 抖动）；批量抓取 200 条以上时每 50 次插入 3~5s 停顿；并发不要超过 2。这是礼貌值，不是被限后的退避。

---

## 九、鉴权边界与 Cookie

| 能力 | 未登录 | 备注 |
|---|---|---|
| 搜索（含价格、阶梯价、库存、销量） | ✅ 可见 | 与登录态结果一致，无差异化 |
| 详情页（参数/价格/库存/手册） | ✅ 可见 | SSR 直出 |
| 替代料 `substitute/simple/list` | ✅ 可见 | 带/不带 Cookie 响应字节数相同 |
| 相似推荐 `relation/recommend` | ✅ 可见 | — |
| BOM 全站（上传/行数据/匹配/导出） | ❌ 401 | `/cas/user/info` 返回 `code:401` |

- 浏览器请求头里**没有** `x-auth-token` 之类自定义鉴权头；认证完全靠 Cookie。
- Cookie 关键项（名字口径）：`isLoginCustomerFlag`（账号号）、`JSESSIONID`、`_lcsc_fid`、`lccsid`、`acw_tc`、`ssxmod_itna`/`ssxmod_itna2`（腾讯 EdgeOne 反爬）、`noLoginCustomerFlag`。**登录态 cookie 有效期为会话级**，脚本化时从浏览器导出即可；具体值不入库。
- 仅有的签名接口：`item.szlcsc.com/product/stock/price/sign?productId=&cvt=&nonce=&sign=`。不带签名 → `{"code":110101,"ok":false}`；带浏览器签名 → 响应体 `null`（普通商品无额外报价）。**非必需**。
- `https://so.szlcsc.com/global.html?k=…` 页面本身返回 **203 + JS 反爬挑战**（`_xvasu`/`_xvtsc`/`tws2_` cookie），但这是**页面外壳**；同域 XHR `POST /query/product` 不受影响 → 直接打接口即可，不要抓页面。
- `wmsc.lcsc.com` 系列路径全部 404（`{"code":404,"msg":"The static resource is unavailable."}`）——老接口已下线。

---

## 十、字段语义（销量 / 库存 / 在途）

| 字段 | 含义 | C8734 实测值 |
|---|---|---|
| `recentlySalesCount` | **真实销量数字**（近期口径，非"仅排序"），搜索结果与详情页都带 | 13365 |
| `stockNumber` | 现货库存 | 31387 |
| `totalStockNumber` | 总库存（= 各仓合计口径） | 9252 |
| `validStockNumber` | 可用/有效库存 | — |
| `smtStockNumber` | 嘉立创 **SMT 贴片库存**（能直接上产线的量） | 229919 |
| `gdWarehouseStockNumber` | 广东仓 | 9252 |
| `jsWarehouseStockNumber` | 江苏仓 | 0 |
| `usableTransitNum` | **在途可用量**（已订货未入库、可被占用） | 0 |
| `deliveryTimeWayDays` | 交期（天） | — |
| `minBuyNumber` | MOQ 起订量 | 1 |
| `productMinEncapsulationNumber` | 整盘/整包数量 | 250（托盘） |
| `theRatio` / `convesionRatio` | 换算比（1 盘 = N 个） | 5（替代料样例） |
| `hasStockNow` / `productStockStatus` | 现货标记 | yes / yes |
| `smtLabel` | 贴片库标签 | SMT扩展库 |

C8734 阶梯价（6 档，`endPurchasedNumber=-1` 表示无上限）：1-9 ￥9.12 / 10-29 ￥7.92 / 30-249 ￥7.07 / 250-499 ￥6.30 / 500-999 ￥5.94 / 1000+ ￥5.79。

---

## 十一、国际站与开放平台

- `https://www.lcsc.com/api/global/additional/search?q=C8734` → **返回 885KB 的 SSR HTML**（Nuxt 外壳），不是 JSON API；`/api/products/search` 同样返回 HTML。国际站**没有可直接调用的公开 JSON 搜索接口**，只能解析页面 `__NEXT_DATA__`（Lead 已用这条路拿 `alternatePartList`）。
- `wmsc.lcsc.com/wmsc/search/global` 与 `/wmsc/product/detail` → 全部 `code:404`。
- `open.szlcsc.com` 直连 TLS 失败（`SSL: UNEXPECTED_EOF`，需代理/可能已停用）；`open.jlc.com` HTTP 200（嘉立创开放平台）。官方 OpenAPI 需**商务申请 key/企业资质**（Lead 侧已确认）。

---

## 十二、可复放 API 清单

| 用途 | method | URL | 关键参数 | 鉴权 | 证据 |
|---|---|---|---|---|---|
| 搜索/排序/分页 | POST | `https://so.szlcsc.com/query/product` | JSON：keyword, sortNumber(0/1/2/4/6), currentPage, pageSize≤30, `*Filter` | 免 | 实测成功 |
| 品牌筛选 | — | 同上 | `brandIdFilter:"91$842"`（$ 分隔） | 免 | 实测成功 |
| 封装筛选 | — | 同上 | `standardFilter:"0805$0603"` | 免 | 实测成功 |
| 类目筛选 | — | 同上 | `catalogIdFilter:"439"` | 免 | 实测成功 |
| 价格区间 | — | 同上 | `startPrice:"0.01", endPrice:"0.02"`（字符串） | 免 | 实测成功 |
| 有手册 | — | 同上 | `hasDataFile:true` | 免 | 实测成功 |
| 商品详情 | GET | `https://item.szlcsc.com/{productId}.html` | `__NEXT_DATA__.props.pageProps.webData` | 免 | 实测成功 |
| 参数表 | — | 同上 | `webData.paramList[]` | 免 | 实测成功 |
| 阶梯价 | — | 同上 / 搜索行 | `productPriceList[]` | 免 | 实测成功 |
| 手册 PDF | GET | `https://atta.szlcsc.com` + `fileUrl` + `urlSign` | 三个片段原样拼接 | OSS 签名 | 实测成功 |
| **替代料** | POST | `https://list.szlcsc.com/substitute/simple/list` | `?productCode=C8734`，body `{}` | 免 | 实测成功 |
| 相似推荐 | GET | `https://item.szlcsc.com/product/relation/recommend` | `?productId=9243` | 免 | 实测成功 |
| 额外报价(签名) | GET | `https://item.szlcsc.com/product/stock/price/sign` | productId, cvt, nonce, sign | 需签名 | 抓包未复放 |
| BOM 登录态 | GET | `https://bom.szlcsc.com/cas/user/info` | — | Cookie | 实测成功 |
| **BOM 上传解析** | POST | `https://bom.szlcsc.com/bom/upload` | multipart `bomFile` + `pageSource=sheet` | **Cookie** | 实测成功 |
| BOM 行数据 | GET | `https://bom.szlcsc.com/async/bom/match/page` | bomUuid, currentPage, pageSize | Cookie | 实测成功 |
| BOM 触发匹配 | POST | `https://bom.szlcsc.com/async/bom/ai/match` | form-urlencoded | Cookie+配额 | 抓包未复放 |
| BOM 匹配进度 | GET | `https://bom.szlcsc.com/async/bom/ai/match/progress` | — | Cookie | 抓包未复放 |
| BOM 导出报价 | GET | `https://bom.szlcsc.com/bom/item/export` | bsuuid, bomUuid | Cookie | 抓包未复放 |
| 国际站替代料 | — | `www.lcsc.com` 页面 `__NEXT_DATA__` | — | 免 | 他人已验证 |
| 官方 OpenAPI | — | `open.jlc.com` | key | 商务申请 | 推测 |

---

## 十三、给实现者的建议

1. **只用 `sortNumber ∈ {0,1,2,4,6}`**；3/5/7/9/11/12 是"分桶子集"，会静默改变结果集，看起来像排序其实是换了一批货。
2. **参数比较不要开详情页**：搜索结果的 `paramLinkedMap` 已含结构化参数，详情页 `paramList[]` 只在需要"参数编码/完整参数表"时用。一条 BOM 配 50 个料，省 50 次请求。
3. **HTML 必须清洗**：`lightCatalogName`/`lightProductModel` 里塞了 `<SPAN CLASS='LUCENE_HIGHLIGHT_CLASS'>`；另外 JSON 里还有 `&lt;` 之类的转义残留（型号列见过），入库前统一 unescape + strip tag。
4. **"有货"要自己判**：`spotFilter=1` ≠ `stockNumber>0`。用 `stockNumber>0 || usableTransitNum>0` 组合，并区分 `smtStockNumber`（能否 SMT 直贴）。
5. **缓存分层**：商品静态信息（型号/品牌/封装/参数/手册 URL）TTL 7 天，按 C 编号做 key；价格/库存/交期 TTL 30~60 分钟（价格活动按天变，库存分钟级）；搜索结果按 `hash(keyword+sort+page+filters)` TTL 1 天但**剔除价格字段**；替代料 TTL 7 天。
6. **`totalCount` 封顶 1500**：要全量就按 `catalogIdFilter`/`standardFilter`/`brandIdFilter` 递归切片，别盲目翻页（`pageSize≤30`，50 页也才 1500）。
7. **BOM 链路用纯 HTTP**：Cookie 从浏览器导出（会话级），上传 → `match/page` 轮询 `matchState`；不要用无头浏览器，省大量开销。Cookie 失效检测就打 `/cas/user/info`（401 即过期）。
8. **礼貌值**：单线程 QPS ≤1、并发 ≤2、每 50 请求停 3~5s；替代料与详情页是重接口（C8734 替代料响应 351KB），批量时优先用搜索接口一次拿 30 条。

---

### 附：本报告引用的样本文件（`probe/lcsc/`）

`probe_bom_match_page_final.json`、`probe_bom_sub_async_bom_match_page.json`、`probe_bom_test.csv`、`probe_bom_upload_resp.json`、`probe_cookie_browser.txt`、`probe_C8734_datasheet.pdf`、`probe_filter_verify.json`、`probe_filters_raw.json`、`probe_item_9243_nextdata.json`、`probe_item_48788262.html`、`probe_pdf_url.txt`、`probe_relate_48788262.json`、`probe_sort_clicks.json`、`probe_sort_semantics.json`、`probe_substitute_C46634460_nocookie.json`、`probe_substitute_C8734_nocookie.json`、`probe_wide_sort_00..12.json`。
复放脚本：`so_query.py`（搜索）、`probe_substitute_nocookie.py`（替代料）、`probe_bom_upload.py` + `probe_bom_poll.py`（BOM）、`probe_ratelimit_intl.py`（限流/国际站）、`wb.ps1`（浏览器抓包助手）。
