# 原厂官方商城（直营渠道）

> 目标是回答：**这行料，原厂自己卖不卖？原厂页面能给我什么？值不值得为它多花一次检索？**
> 全部结论为 2026-11 实测（`scripts/origin.py check` 可复现）；原厂政策会变，下单前以页面为准。

## 0. 一句话结论

**国内原厂绝大多数不直销、不公开价格**——官网是产品资料站，不是商城。
19 家里只有 **思瑞浦（3PEAK）** 一家是真商城（含税人民币阶梯价 + 实时库存全公开、免登录）；
**TI** 能拿美元 1ku 参考价，人民币价与库存要登录；
其余 16 家最多给到"型号 → 产品页"的检索能力，**没有任何一家公开库存**。

所以：**原厂渠道不是用来比价的，是用来确认「官方还供不供货 / 有没有停产 / 官方描述怎么写的」。**

## 1. 什么时候该去原厂（判定规则）

按下面的顺序判断，**命中任一条就去查原厂**：

| 触发条件 | 去原厂查什么 | 为什么不能只看分销商 |
|---|---|---|
| BOM 里出现 **思瑞浦 3PEAK** 的料 | 含税人民币阶梯价 + 库存 + MOQ | 3peakic 是原厂直营，**价格比任何分销商都准**，且免登录 |
| 出现 **TI** 的完整 OPN | 美元 1ku 参考价、生命周期、封装/数量/温度 | TI 官网是这些字段的权威源；分销商常滞后 |
| 料号疑似 **停产 / 换代 / NRND** | 生命周期状态（Active / NRND / Obsolete） | 分销商有货不代表原厂还产；买到最后一批会坑 |
| 分销商 **报价明显低于原厂 1ku 价** | 原厂价做基线 | 低于原厂价太多的，大概率是散新/翻新/拆机 |
| 需要 **样品 / 小批量试产** | 样品申请入口 | 多数国内原厂只走"申请样片"这条口子，没有线上小批量 |
| 需要 **官方 datasheet / 参考设计 / 封装库** | 产品页下载区 | 原厂文档永远比分销商转的版本新 |
| 料号 **分销商全线无货**（缺货潮） | 原厂库存 + 交期 | 原厂有货时分销商也可能没铺货 |

**不该去原厂的情况**（省时间）：
- 只是比价、且料号是通用料（LM358 / 0805 电阻 / 1N4148）→ **直接立创/淘宝**，原厂页没有价格。
- 只需要"有没有这个型号"→ 分销商检索更快，原厂站检索质量普遍更差（见 §3 的坑）。

## 2. 注册表（`python scripts/origin.py list`）

`access` 含义：`http` = 纯 HTTP 可取 / `browser` = 纯 HTTP 拿不到，必须真浏览器 / `none` = 实测不可达。

| key | 原厂 | 官方渠道 | access | 价格 | 库存 | 能拿到的字段 |
|---|---|---|---|---|---|---|
| `3peak` | 思瑞浦 3PEAK | www.3peakic.cn（**原厂直营商城**） | `http` | **含税 13% 人民币阶梯价** | **有** | mpn / 描述 / 品类 / 库存 / 封装 / MOQ / 阶梯价 / 状态 |
| `ti` | 德州仪器 TI 中国 | www.ti.com.cn | `http` | USD 1ku 参考价（JSON-LD） | 需登录（可走浏览器 API） | mpn / 全 OPN 变体 / 价格 / 封装 / 数量 / 温度 / 描述 |
| `mps` | MPS 芯源 | www.monolithicpower.cn | `http` | 无 | 无 | mpn / 产品页 |
| `silan` | 士兰微 Silan | www.silan.com.cn | `http` | 无 | 无 | mpn / 产品页 |
| `gigadevice` | 兆易创新 GigaDevice | www.gigadevice.com | `http` | 无 | 无 | mpn / 产品页 |
| `sgmicro` | 圣邦微 SGMICRO | www.sg-micro.com | `browser` | 无 | 无 | mpn / 品类 / 生命周期 / 描述 |
| `wch` | 沁恒 WCH | www.wch.cn | `browser` | 无 | 无 | mpn / 产品页 |
| `geehy` | 极海 Geehy | www.geehy.com | `browser` | 无 | 无 | mpn / 产品页 |
| `hdsc` | 小华半导体 HDSC | www.hdscmcu.com | `browser` | 无 | 无 | mpn / 产品页 |
| `novosense` | 纳芯微 NOVOSENSE | www.novosense.com | `browser` | 无 | 无 | mpn / 产品页 |
| `cmsemicon` | 中微半导体 CMSemicon | www.cmsemicon.com | `browser` | 无 | 无 | mpn / 产品页 |
| `nationstech` | 国民技术 Nationstech | www.nationstech.com | `browser` | 无 | 无 | mpn / 产品页 |
| `etek` | 力芯微 ETek | www.etek.com.cn | `browser` | 无 | 无 | mpn / 产品页 |
| `eta` | 钰泰 ETA | www.eta-semi.com | `browser` | 无 | 无 | mpn / 产品页 |
| `hsxp` | 航顺芯片 HSXP | www.hsxp-hk.com | `browser` | 无 | 无 | mpn / 产品页 |
| `southchip` | 南芯 Southchip | www.southchip.com | `browser` | 无 | 无 | mpn / 产品页 |
| `gd32` | 兆易 GD32（MCU 子站） | www.gd32mcu.com | `http` | 无 | 无 | 仅**下载**检索（datasheet/固件） |
| `prisemi` | 芯导科技 Prisemi | www.prisemi.com | `none` | — | — | 站内搜索已损坏 |
| `willsemi` | 韦尔半导体 WILLSEMI | www.willsemi.com | `none` | — | — | 域名不可达 |

可执行 `search` 的 6 家：`3peak` / `ti` / `mps` / `silan` / `gigadevice` / `sgmicro`。

## 3. 各家实测细节与坑

### 3PEAK 思瑞浦（唯一真商城）

- 入口是**独立域名** `www.3peakic.cn`，不是 `3peak.cn` 的子路径（`3peak.cn` 首页的"在线商城"链接指向它）。
- 两个免登录接口：
  - `POST https://www.3peakic.cn/api/bbb/goodsInfo` body `{"pageNum":N,"pageSize":100}` → 全量目录 **1591 条**。
  - 价格字段在 `goodsPriceObj.stepPrice.stepPriceRangeList`，`goodsPriceObj.taxRate = 0.13`，
    即**报价已含 13% 增值税**；库存字段 `singleGoodsStock`；起订量倍数在 `increasesParam[0].value`。
- **坑 1：`pageSize=2000` 返回空**（服务端上限），`pageSize=100` 稳定。
- **坑 2：offset 分页在 offset≈500 处有一页"毒记录"，整页返回空但 `total` 仍报 1591。**
  `origin.py` 用多 pageSize 并集补齐（100 → 10 → 1 定点细扫），可恢复到 **1590/1591**；
  剩下 1 条任何 offset 都取不到。
- **坑 3：`comprehensiveSearch` 的 `goodsName` 参数不生效**（试过 13 种参数名全部返回全量 1591 条）
  → 没有服务端关键词过滤，只能拉全量本地匹配。所以第一次 search 会慢（约 30 s），
  之后走 `%TEMP%\bom_origin_cache\3peak_catalog.json` 缓存（TTL 12 h）。

### TI 中国

- 产品文件夹页 `https://www.ti.com.cn/product/zh-cn/<基号>` 是**服务端渲染**的（约 330 KB），
  里面 `<script type="application/ld+json">` 的 `ProductGroup.hasVariant[]` 给全部 OPN 变体 +
  `offers.price` + `priceCurrency` + `availability`。
- **坑 1：只认基号**。`/product/zh-cn/TPS259470ARPWR` 是 404，必须裁成 `TPS25947`。
- **坑 2：JSON-LD 的 script 标签是多行的**，正则必须用 `<script[^>]*application/ld\+json[^>]*>(.*?)</script>`（DOTALL），
  写死 `<script type="application/ld+json"` 会 0 条。
- **人民币价与库存要登录**：part-details 页文案是「登录以查看库存」、价格表全是破折号。
  抓包确认未登录时**根本没有价格 API 请求**（只有 `cartmodel/mini-cart` 401），不是接口没找到。
- 库存可绕：浏览器内 fetch `GET /storeservices/cart/opninventory?opn=<完整OPN>`
  → `{"orderable_number":"...","inventory":11927}`。**必须给完整可订购 OPN**，基号返回 204。
  纯 HTTP 直接访问会撞 PerimeterX 机器人挑战页。

### 圣邦微 SGMICRO

- Nuxt 站。`/global-search?keyword=X` **纯 HTTP 恒返回「0 results」**（试过 8 种参数名），
  但**真浏览器打开就是 11 条结果** → 结果被 hydration 覆盖，必须走浏览器。
- 能拿到：型号、品类、**生命周期**（`Active` / `Not Recommended for New Designs`）、描述。
  生命周期对配单很有价值（NRND 要提醒换料）。无价格库存。

### 兆易 GigaDevice

- 站内搜索 `/product-search?wd=<MPN>` 纯 HTTP 可用（实测 `GD25Q64` → `GD25Q64C/E/H` + 汽车级 `GD25Q64C-AUTO`）。
- **坑：`/product-inventory-search` 那个"库存查询"是 `di.oemsecrets.com` 的第三方挂件**，
  显示的是分销商库存，**不是原厂库存**，不要当原厂数据引用。
- GD32 是独立子站，`/cn/download?kw=` 只是**下载检索**，查不到料号。

### 士兰微 Silan

- **https 回 502，必须用 http**（`http://www.silan.com.cn/index.php/search.html?search=<MPN>`）。
- 结果卡片整块包在 `<a>` 里，链接文本混着「产品 -->」和描述，需要从文本里正则抠型号。

### MPS 芯源

- Magento 站，`/cn/catalogsearch/result/?q=<MPN>` 正常出产品（`/cn/mp20073.html`）。
- 无价格库存。

### 不可用 / 需注意

| 厂 | 现象 |
|---|---|
| 芯导 Prisemi | 站内搜索服务端报错 `THE SERVER CANNOT FIND DATA FOR THE RESOURCE`，**真浏览器也一样**，无结果可用 |
| 韦尔 WILLSEMI | `willsemi.com` / `willsemi.cn` 直连与代理**全部超时**（WinError 10060），不可达 |
| 极海 Geehy | 纯 HTTP 一律 `405 Not Allowed`（WAF 返回 `{"traceid":...}`），必须浏览器 |
| 小华 HDSC / 纳芯微 NOVOSENSE / 中微 CMSemicon | 直连 `getaddrinfo failed`、代理 `SSL: UNEXPECTED_EOF_WHILE_READING`，只能浏览器 |
| 沁恒 WCH / 航顺 HSXP | 首页是纯 JS 壳（1815 B / 2151 B），必须浏览器 |
| 力芯微 ETek | 纯 HTTP 403（WAF） |
| 钰泰 ETA | 无站内搜索表单（`/search?keyword=` 404）；注意 `etasolution.com` 证书 hostname 不匹配 |
| 南芯 Southchip | `/search?keyword=` 会落到首页，无此路由 |
| 国民技术 | `/search?s=` 404，站内检索需 JS |
| GD32 | 只有下载检索，不是料号检索 |

## 4. CLI 用法

```powershell
# 注册表
python scripts\origin.py list

# 查单家（思瑞浦：含税人民币阶梯价 + 库存）
python scripts\origin.py search TPA7836B --vendor 3peak

# 查 TI（USD 1ku 参考价 + 全部 OPN 变体）
python scripts\origin.py search TPS259470ARPWR --vendor ti

# TI 库存（走真浏览器，约 10 s）
python scripts\origin.py search TPS259470ARPWR --vendor ti --browser

# 全厂扫（6 家，慢的会拉全量目录）
python scripts\origin.py search SLP74

# 落 JSON 证据
python scripts\origin.py search GD25Q64 --json origin_GD25Q64.json

# 站点可达性巡检（19 家，约 15 s）
python scripts\origin.py check
```

参数：`--vendor`（可多次）、`--limit N`（默认 8）、`--json FILE`、`--refresh`（无视缓存）、
`--browser`（TI 走浏览器取库存）。

## 5. 输出字段约定

| 字段 | 含义 |
|---|---|
| `mpn` | 原厂给出的订购型号（**不一定**等于你输入的型号，TI 会返回整个变体族） |
| `price` / `price_usd_1ku` / `price_cny_incl_tax` | 价格。3peak 是含税人民币阶梯价，TI 是美元 1ku |
| `stock` | 库存数量。**只有 3peak 与 TI（--browser）有值**，其余为 `null` |
| `stock_note` / `price_note` | 为什么没有价格/库存（"需登录" / "原厂不公开"），**不要忽略这行** |
| `status` | `not_found` / `error` 时该条不是料，是错误说明，别当结果用 |
| `url` | 产品页。相对路径需拼 `https://www.ti.com.cn` |

## 6. 与其它渠道的关系

- **原厂 ≠ 可买**：注册表里 16 家没有线上商城，只能申请样品或联系代理 → 真要买还是走立创/淘宝/分销商。
- **原厂价 ≠ 你能买到的价**：原厂 1ku 价是不含税、不含运费的参考价，且多数要求整盘（MOQ）。
  比价时只能当**基线**用，见 `references/channels.md`。
- **原厂库存 ≠ 分销商库存**：原厂有货不代表立创有货（铺货是分开的），反之亦然。
