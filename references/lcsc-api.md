# 立创商城接口事实（szlcsc / lcsc）

> 全部结论均为 2026-11-04 本机实测。售价为人民币含税单价，会变动，引用时带日期。
> 脚本：`scripts/lcsc.py`（纯标准库，免登录）。

## 1. 搜索接口（免登录，最重要）

```
POST https://so.szlcsc.com/query/product
Content-Type: application/json
Origin: https://so.szlcsc.com
Referer: https://so.szlcsc.com/global.html
User-Agent: 任意现代浏览器 UA
```

请求体（完整键，缺省用空串）：

```json
{
  "currentPage": 1,
  "pageSize": 30,
  "keyword": "STM32F103C8T6",
  "sortNumber": 0,
  "brandIdFilter": "",
  "standardFilter": "",
  "catalogIdFilter": "",
  "startPrice": "",
  "endPrice": "",
  "demandNumber": "",
  "spotFilter": 1,
  "discountFilter": 1,
  "hasDataFile": false,
  "queryParameterValue": "",
  "lastParamName": ""
}
```

实测要点：

| 项 | 结论 |
|---|---|
| 鉴权 | 不需要。无 cookie 直接 curl 可用（反例见 §6） |
| `pageSize` | 上限 **30**；传 100/200 返回空列表 |
| 分页 | `currentPage` 从 1 起；翻页数在 `result.searchResult.countPage` |
| 总数 | 在 `result.searchResult.totalCount`（`result.totalCount` 为 null）；宽泛词会封顶（`10k 电阻 0805`→1500） |
| 代码块 | 返回 `code: 200` 才是成功；其它 code 带 `msg` |

### sortNumber 实测语义

| sortNumber | 含义 | 备注 |
|---|---|---|
| 0 | 综合 | 销量权重高（等同网页默认） |
| 1 | 价格升序 | 阶梯首档单价 |
| 2 | 价格降序 | — |
| 3 | 库存升序 | 0 库存排最前 |
| 4 | 库存降序 | — |
| 6 | **近期销量降序** | `recentlySalesCount` 严格递减，对应网页「销量」排序 |

响应里的 `result.searchResult.querySortBySign` 会回显当前排序号，可用于自检。

**排序坑**：检索词若是**精确型号**（如 `STM32F103C8T6` 只有 8 条），立创把「精准匹配组」钉在最前，sortNumber 几乎不改变顺序；
只有**品类/参数关键词**（`stm32f103`、`10k 0603 1%`）排序才严格生效。
→ 要"卖得最多的"必须用品类词，别用完整型号。

## 2. 响应结构（取用得上的字段）

`result.searchResult.productRecordList[]` 每项：

- `productVO`：`productCode`(C8734)、`productModel`、`productName`、`encapsulationModel`、`productGradePlateName`(品牌)、
  `stockNumber`/`validStockNumber`/`totalStockNumber`、`recentlySalesCount`、`minBuyNumber`、`maxBuyNumber`、
  `productPriceList[]`（阶梯价）、`productMinEncapsulationNumber`+`productMinEncapsulationUnit`（整盘数量/单位）、
  `deliveryTimeWayDays`、`pdfDESProductId`、`productId`、`hasStockNow`、`smtLabel`、`productType`
- `paramLinkedMap`：**结构化参数表**，键随类目变（电阻：`电阻类型/阻值/精度/功率`；MLCC：`容值/精度/额定电压/温度系数`；
  晶振：`频率/常温频差/负载电容`；MCU：`CPU内核/CPU最大主频/程序存储容量`…）。值可能含高亮 HTML：
  `<SPAN CLASS='LUCENE_HIGHLIGHT_CLASS'>…</SPAN>`，必须去标签。
- `gradePlateGroup[]`：品牌 facet，`{label:"ST(意法半导体)", value:"74", count:2}`，`value` 即 `brandIdFilter` 的取值
- `encapsulationGroup[]`：封装 facet，`label`（如 `"LQFP-48(7x7)"`）可直接作 `standardFilter`

阶梯价：`productPriceList[]` 的 `startPurchasedNumber`/`endPurchasedNumber`/`productPrice`；
`endPurchasedNumber = -1` 表示无上限。

## 3. 筛选参数（实测有效/无效）

| 参数 | 实测 | 说明 |
|---|---|---|
| `brandIdFilter` | ✅ | 用 facet 的 `value`（`"74"`），不是品牌名。`STM32F103` + `74` → 123 条全 ST |
| `standardFilter` | ✅ | 用封装 facet 的 `label` 原文 |
| `startPrice` / `endPrice` | ✅ | 单位元，按阶梯首档 |
| `demandNumber` | ⚠️ | 不改变返回的阶梯价，只影响部分展示字段 |
| `queryParameterValue` + `lastParamName` | ❌ | 试了多种写法都返回 0 条，用法未明，暂不使用；参数区间筛选改用「关键词 + 本地 `paramLinkedMap` 过滤」 |
| `catalogIdFilter` / `brandPlaceFilter` / `labelFilter` / `authenticationFilter` / `arrangeFilter` | ✅ | 类目/品牌产地/标签/认证/包装方式，取值同样来自 facet |
| `spotFilter` | ✅ | 1=只看现货（默认），0=含无货 |
| `discountFilter` | 未证实差异 | 默认 1 |

**多值分隔符是 `$` 不是逗号**：`brandIdFilter: "91$842"`（两个品牌）、`standardFilter: "0805$0603"`。
用逗号会**静默返回 0 条**，不报错。`pageSize > 30` 同理静默返 0 条。

**参数区间筛选没有服务端支持**（`parmeterValueList` 在关键词检索下恒为 `[]`）。
需要按参数范围选型时：先用品类关键词拉一页（30 条）候选，再用 `paramLinkedMap` 在本地过滤 —
`bom.py` 的 `match_param()` 就是这么做的。

## 4. 直链（都不用鉴权）

| 用途 | URL |
|---|---|
| 商品页 | `https://item.szlcsc.com/{productId}.html`（200，无需 JS；**用数字 productId 不是 C 号**） |
| 数据手册 | `https://datasheet.lcsc.com/{pdfDESProductId}.pdf`（200，直接 PDF） |
| 手册（OSS 签名直链） | `atta.szlcsc.com` + `pdfFileDetailVO.fileUrl` + `urlSign`（原样拼接即可，实测 2MB PDF） |
| 海外站详情 | `https://www.lcsc.com/product-detail/{C编号}.html` |

## 5. 替代料接口（推荐，比海外站全得多）

```
POST https://list.szlcsc.com/substitute/simple/list?productCode=C8734
Content-Type: application/json
body: {}
```

- 免登录；返回 `result.mainProduct`（源料 + `mainParamLinkedMap`）与四组 `all` / `domestic` /
  `internation` / `sameBrand`，每组含 `substitutes[]` + `paramGroup`（该参数的取值分布，适合做筛选 UI）
- 每条 substitute 带：`simScore`（74~95）、`subLabel`、`productModel`、`productGradePlateName`、
  `encapsulationModel`、`stockNumber`/`validStockNumber`/`totalStockNumber`、
  `smtStockNumber`、`gdWarehouseStockNumber`/`jsWarehouseStockNumber`、`productPriceList`（人民币阶梯）、
  `paramLinkedMap`（可直接与源料 diff）、`pdfDESProductId`、`deliveryTimeWayDays`
- 实测覆盖：`C8734` → 36 条（国产 29、同品牌 7），含 APM32/HK32/CH32/CKS32 等国产替代；
  海外站 `alternatePartList` 同料只有 5 条
- 海外站 `__NEXT_DATA__.webData.alternatePartList` 仍然保留作为兜底（英文、只有 5 条、价格是美元）

## 6. 缓存与限流

`scripts/lcsc.py` 默认：

- 每次真实请求先查缓存，键为完整请求体 SHA1，默认目录 `%LOCALAPPDATA%\bom-sourcing\cache\lcsc`，TTL 6 小时
- 请求间隔 1 秒（`Lcsc(rate_limit=...)` 可调），失败重试 3 次，指数退避
- `--no-cache` 关闭缓存；环境变量 `BOM_CACHE` / `BOM_CACHE_TTL` 可覆盖

> 缓存不是可选项：一次 16 行 BOM 配单会发几十次请求，二次运行几乎全命中缓存。价格是快照数据，
> 交付给用户时必须带抓取时间。

## 7. 反例（别再试）

| 尝试 | 结果 |
|---|---|
| `GET https://so.szlcsc.com/global.html?k=...` | HTTP **203** + 混淆 JS 反爬（`tws2_` cookie 挑战），脚本拿不到结果，必须走 API |
| `GET https://wmsc.lcsc.com/wmsc/search/global?...` | `{"code":404,"msg":"The static resource is unavailable…"}`，不可用 |
| `GET https://cart.jlcpcb.com/shoppingCart/smtGood/getComponentDetail?componentCode=C8734` | 200 可用，但字段少（datasheet 直链、图片），中文参数与替代料都没有；已被 §1+§4 取代 |
| LCSC 官方 OpenAPI（`https://www.lcsc.com/docs/openapi/`） | 需 apikey，否则 401；文档可读但无 key 无法调用 |

## 8. 同型号多 C 号（配单必踩）

同一 MPN 在立创常有多个 C 号：不同品牌（原厂/国产替代）、不同封装、不同批次；
库存差异可能极大（实测 `W25Q64JVSSIQ`：C179171 有货 1383，另一 C 号 0）。
`bom.py` 的处理：同型号候选按「有货 > 满足数量 > 价格」排序，并在备注里列出其它品牌与价格差。
