# Lead 实测发现（2026-11-04）

> 证据等级：【实测】= 本机 curl 亲自打通并核对过返回内容；【文档】= 只看到文档/源码未实测。

## 0. 一句话结论

**立创商城有一个可直接 curl 的 JSON 搜索接口，无需登录、无 JS 挑战**（`POST https://so.szlcsc.com/query/product`），
返回商品编码/型号/品牌/封装/库存/**阶梯价**/**近期销量**；`sortNumber=6` 即**按销量降序**。
另外 JLCPCB 的元件详情接口（含 datasheet PDF 链接）也无需鉴权。
→ 立创这条线**不需要浏览器**就能做"搜索 + 销量排序 + 比价"，只有"参数筛选/替代料/BOM 配单"还需进一步确认。

## 1. 立创商城搜索接口【实测】

```
POST https://so.szlcsc.com/query/product
Content-Type: application/json
Origin: https://so.szlcsc.com
Referer: https://so.szlcsc.com/global.html
User-Agent: Mozilla/5.0 ... Chrome/131 ...

{"currentPage":1,"pageSize":30,"keyword":"STM32F103C8T6",
 "sortNumber":0,"spotFilter":1,"discountFilter":1,"hasDataFile":false}
```

返回：`result.searchResult.productRecordList[].productVO`，关键字段：

| 字段 | 含义 |
|---|---|
| `productCode` | 立创编号 C8734 |
| `productModel` / `productName` / `remark` | 型号 / 描述 / 规格参数文本 |
| `productGradePlateName` | 品牌（如 `ST(意法半导体)`） |
| `encapsulationModel` | 封装（`LQFP-48(7x7)`） |
| `stockNumber` / `validStockNumber` / `usableTransitNum` | 库存 / 有效库存 / 在途可用 |
| `productPriceList[]` | **阶梯价**：`startPurchasedNumber`/`endPurchasedNumber`/`productPrice`（另有 `minEncapsulationUnitPrice` 整盘价） |
| `recentlySalesCount` | **近期销量**（销量排序依据） |
| `minBuyNumber` / `maxBuyNumber` | 起订量 / 限购 |
| `deliveryTimeWayDays` | 交期（天） |
| `productType` | 分类（`贴片电阻`、`单片机(MCU/MPU/SOC)`） |
| `lcedaProjectUrl` / `fileTypeVOList` | 立创EDA 工程引用 / 附件（数据手册等） |
| `smtLabel` | SMT 基础库/扩展库标签 |
| `productStockStatus` / `hasStockNow` | 现货状态 |
| `isHot`（记录级） | 热门标记 |

### 分页与限制【实测】
- `pageSize` 上限 **30**（传 100/200 返回空）。`currentPage` 从 1 开始。
- `totalCount` 对宽泛词会封顶（`10k 电阻 0805` → 1500；`stm32` → 99，`countPage` 4），
  说明"总量"是搜索索引的截断值，翻页到 `countPage` 为止。

### 排序 sortNumber 对照【实测】
| sortNumber | 行为 | 证据 |
|---|---|---|
| 0 | 综合排序（销量权重大，近似但非严格降序） | 销量序列 5739,1982,416,321,299,346… |
| 1 | 价格升序 | 0.01→0.0127→0.0132→0.0159 |
| 2 | 价格降序 | 136.1→95→46.31→34.25 |
| 3 | 库存升序（0 库存在前） | stock=0,0,0 |
| 4 | 库存降序 | 39.5M→9.0M→6.5M |
| **6** | **销量降序（严格单调递减）** | 5739,1982,416,346,321,299,191,153 |
| 12 | 未知（新品？） | 4,3,10,75,118,1… |

> 注：3/5/7/8/9/10/11 语义待定（部分与 4/6 结果集相近，可能含"只看现货""只看折扣"等叠加位），由 lcsc-probe 复核。

### 一个真实返回片段（节选）
```json
{"code":200,"result":{"searchResult":{
  "totalCount":1500,"querySortBySign":6,
  "productRecordList":[{"productVO":{
    "productCode":"C2907219","productModel":"FRC0805F1002TS",
    "productGradePlateName":"FOJAN(富捷)","encapsulationModel":"0805",
    "stockNumber":9021182,"recentlySalesCount":5739,
    "productPriceList":[{"startPurchasedNumber":1,"endPurchasedNumber":9,"productPrice":0.0159}]
  }}]}}}
```
原始样本：`probe/lcsc/sort_more_6.json`、`probe/lcsc/sort_probe_*.json`、`probe/lcsc/pagesize_*.json`

## 2. 反证：网页与旧路径不可用【实测】
- `GET https://so.szlcsc.com/global.html?k=...` → **203**，body 是混淆 JS 反爬（`tws2_` cookie 挑战）。
  → 抓网页 HTML 需要浏览器；但 **JSON 接口本身不设防**。
- `GET https://wmsc.lcsc.com/wmsc/search/global?...` → 404 `The static resource is unavailable`（路径已废/需其他参数）。

## 3. JLCPCB 元件详情（免鉴权）【实测】

```
GET https://cart.jlcpcb.com/shoppingCart/smtGood/getComponentDetail?componentCode=C8734
```
返回：`componentBrandEn`、`componentModelEn`、`dataManualUrl`（**数据手册 PDF 直链**）、`dataManualOfficialLink`、
图片、`componentName` 等。适合补 datasheet / 品牌英文名；参数表可能还另有接口。

## 4. 其他线索（待验证）
- `parts-mcp`（PyPI）：声称是"多分销商比价 + BOM 处理"的 MCP 服务器 —— 若能装，可直接当现成轮子。
- `lcsc-toolkit`（PyPI）：LCSC 登录态/订单客户端，含 `capture_session.py`。
- `harry10086/kicad-jlcpcb-tools`：KiCad 插件，`lcsc_api.py` 里就是上面这个 API 的封装（本发现的来源）。
- LCSC 官方 OpenAPI：`https://www.lcsc.com/docs/openapi/`（需 API key，含 Keyword Search List API，可能需企业资质）。

## 4.5 【实测·第二轮】参数表 / 筛选 / 直链（2026-11-04 12:3x）

### 参数表 `paramLinkedMap`（关键：这就是"比指标"的数据源）
每条 `productRecordList[].paramLinkedMap` 直接给出该类目的结构化参数，例如：
- MCU：`{"CPU内核":"ARM Cortex-M3","CPU最大主频":"72MHz","CPU位数":"32 Bit","程序存储容量":"64KB"}`
- 电阻：`{"电阻类型":"厚膜电阻","阻值":"10kΩ","精度":"±1%","功率":"100mW"}`

注意：
1. 值里可能带高亮 HTML `<SPAN CLASS='LUCENE_HIGHLIGHT_CLASS'>10kΩ</SPAN>`，需去标签。
2. 参数键**随类目变化**，没有统一 schema —— 必须先按关键词搜一轮，收集该批结果的键集合，再按 `spec-rules.yaml` 的 family 规则映射。
3. `paramLinkedMap` 是"商品行显示参数"，比筛选面板少；深度参数（如 LDO 压差、MOS 的 Rds(on)）可能只在详情页/数据手册里。

### 分面（facet）信息也直接返回
- `searchResult.gradePlateGroup[]`：`{label:"ST(意法半导体)", value:"74", count:2}` —— **value 就是 brandIdFilter 的值**。
- `searchResult.encapsulationGroup[]`：`{label:"LQFP-48(7x7)", count:5}` —— 直接作为 `standardFilter` 传字符串。
- 另有 `arrangeGroup`（交期/发货仓）、`labelGroup`（标签）、`authenticationGroup`（认证），语义待 lcsc-probe 复核。

### 筛选参数实测
| body 字段 | 作用 | 实测 |
|---|---|---|
| `brandIdFilter` | 品牌 | ✅ `"74"` → STM32F103 只剩 ST，123 条 |
| `standardFilter` | 封装 | ✅ `"LQFP-48(7x7)"` → 13 条，全是该封装 |
| `startPrice` / `endPrice` | 单价区间（元） | ✅ `5`~`10` → 只剩 C8734（9.12） |
| `queryParameterValue`+`lastParamName` | 参数筛选 | ❌ 传 `64KB`/`程序存储容量` → 0 条（用法不对，可能要吃参数 ID；待 lcsc-probe） |
| `demandNumber` | 需求量 | ⚠️ 不影响返回的阶梯价（求解价仍需本地按阶梯匹配），只轻微影响结果集 |

### 直链（都实测 200）
- 商品页：`https://item.szlcsc.com/{productId}.html`（`productId` 在 productVO，如 9243）
- 数据手册：`https://datasheet.lcsc.com/{pdfDESProductId}.pdf`（如 `2FA3B73CEB662785`）——**不必再调 JLCPCB 接口就能拿到 PDF 直链**
- 立创EDA 工程：`lcedaProjectUrl`

### 排序的一个坑（重要）
对**精确型号**（如 `STM32F103C8T6`，仅 8 条），`sortNumber` 几乎不改变顺序（精准匹配块被钉在最前）；
对**品类词**（`stm32f103`、`10k 0603 1%`），`sortNumber` 严格生效（1=价升、6=销量降）。
→ 结论：拿"卖得最多"要用**品类/参数关键词**检索，不要用精确型号检索后排序。

### 其他结构
- 计数在 `result.searchResult.totalCount` / `countPage`，**不在** `result.totalCount`（后者为 null）。
- `productPriceList[].endPurchasedNumber = -1` 表示最后一档无上限。
- `productMinEncapsulationNumber`（如 250）+ `productMinEncapsulationUnit`（如"托盘"）= 整盘规格；`minEncapsulationUnitPrice` = 整盘价。

## 5. 给实现者的建议（初稿）
1. 立创搜索走 `POST /query/product`，**排序直接用 sortNumber=6 拿"卖得最多"**，即傅师傅要的"没思路时按销量选型"。
2. 一次抓 30 条 × 2~3 页足够比价；按 `productCode` 去重、按 `recentlySalesCount` 复核排序。
3. 比价时用**目标数量落在哪个阶梯**的单价，而不是起售价（`productPriceList` 区间匹配）。
4. 库存/在途/MOQ 必须一起看：便宜但 0 库存/长交期的要降权。
5. 参数筛选（如"耐压≥25V""精度±1%"）先确认接口是否支持结构化 param 过滤；否则用 `remark` 文本 + 本地规则兜底（spec-rules.yaml）。
