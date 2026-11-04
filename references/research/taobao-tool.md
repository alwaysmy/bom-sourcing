# taobao.py —— 淘宝 / 1688 检索与比价客户端

`skills/bom-sourcing/scripts/taobao.py`：通过本机 Kimi WebBridge daemon（`127.0.0.1:10086`）驱动用户真实浏览器（带登录态）做淘宝 / 1688 商品检索，输出 Markdown 表格 + 可选 JSON，重点解决「按销量排序」和「阻容按包卖导致单价失真」两件事。

纯标准库（`urllib` + `json` + `re` + `subprocess` 不用），不引入第三方依赖，Python 3.10+ 可跑。

## 前置条件

| 条件 | 检查方式 | 说明 |
|---|---|---|
| WebBridge daemon 在跑 | `python scripts/taobao.py check` | 二进制 `%USERPROFILE%\.kimi-webbridge\bin\kimi-webbridge.exe`，默认端口 10086 |
| 浏览器扩展已连接 | 同上（`extension_connected`） | 当前环境：v2.0.30 / skill v2.0.23 |
| 淘宝已登录 | 同上（`logged_in` / `nick`） | **淘宝必须登录**；1688 免登录即可搜、可看详情 |
| 代理无关 | — | 走浏览器自身网络，`taobao.py` 不发外部 HTTP 请求 |

`check` 返回 0 = daemon/扩展正常（淘宝登录态只打印结论：`logged_in` 为 false 时给提示，但**不改变返回码**）；返回 3 = daemon 或扩展不可用。

## 快速上手

```powershell
cd D:\WorkDesigns\3_WorkTools\skills\bom-sourcing

# 登录态自检
python scripts\taobao.py check

# 淘宝：默认综合排序
python scripts\taobao.py search "STM32F103C8T6" --limit 20

# 淘宝：按销量排序（会点击页面「销量」tab）
python scripts\taobao.py search "10k 0603 电阻" --sort sales --limit 12

# 淘宝：价格排序（客户端排序，见下）
python scripts\taobao.py search "10k 0603 电阻" --sort price_asc --limit 6

# 1688：按销量（URL 参数直接生效，免登录）
python scripts\taobao.py search "STM32F103C8T6" --site 1688 --sort sales --limit 10

# 同时落结构化结果
python scripts\taobao.py search "AMS1117 芯片包" --sort sales --limit 12 --json out.json
```

### 参数

| 参数 | 取值 | 默认 | 说明 |
|---|---|---|---|
| `keyword` | 任意 | — | 位置参数；淘宝支持空格分词 |
| `--site` | `taobao` \| `1688` | `taobao` | |
| `--sort` | `default` \| `sales` \| `price_asc` \| `price_desc` | `default` | `sales` 走页面 tab（淘宝）/ URL 参数（1688）；`price_*` 只做客户端排序 |
| `--limit` | 正整数 | 20 | 输出条数；也是 `--json` 里 `items` 的截断长度 |
| `--max-scrolls` | 整数 | 0 | 淘宝滚动次数（每滚一次约多 48 条候选） |
| `--json` | 路径 | — | 写结构化结果（UTF-8） |
| `--no-fallback` | flag | 关 | playbook 抽取为空时不回退到自写 DOM 抽取 |
| `--session` | 字符串 | `bom-sourcing` | WebBridge session 名；同一 session 复用同一个 tab |
| `--timeout` | 秒 | 见 `--help` | 单条命令超时 |
| `--trace` | flag | 关 | 打印请求 trace 到 stderr |

### 退出码

| 码 | 含义 | 典型处理 |
|---|---|---|
| 0 | 成功 | — |
| 2 | 用法错误 / skill 目录不完整 / 淘宝未登录（`check`） | 修命令或先登录 |
| 3 | daemon 连不上、扩展未连接、请求失败 | 启动 Kimi WebBridge |
| 4 | 被拦：人机验证（验证码 / 滑块）、淘宝卡片 0、1688 跳登录页 | 人工过验证 / 重新登录 |
| 5 | 搜索页正常但没解析到商品 | 换关键词（1688 常见于过长组合词） |

> 补充：`search` 抓到卡片但过滤后无可用条目也返回 5，stderr 会提示「多半是淘宝登录态过期」（仅 taobao）。

## 排序能力实测矩阵

| 渠道 | 排序 | 实现 | 实测结果 |
|---|---|---|---|
| 淘宝 | 综合（默认） | 直接打开 `https://s.taobao.com/search?q=<kw>&tab=all` | `sort=_coefp`，4800 条（STM32F103C8T6） |
| 淘宝 | **销量** | 点击 `.next-tabs-tab` 中文本为「销量」的 LI，等 `__last_search_params.sort` 变为 `_sale` | 生效：`sort=_coefp → _sale`，点击耗时 530–1107ms，总数 4800 → 8120（同关键词） |
| 淘宝 | 价格 | **页面 tab 点击实测无效**（见下）→ 客户端对已抓到的 N 条排序 | footer 标注「客户端排序，只覆盖本页」 |
| 1688 | 综合 | `?keywords=<kw>` | — |
| 1688 | **销量** | URL 追加 `&sortType=va_sales360&descendOrder=true&beginPage=1`，**免登录直接生效** | soldCount 严格降序（32000,6000,5600,4300,3900,3500,3500,3400,3100,3100） |
| 1688 | 价格 | 同淘宝：客户端排序（URL 不加排序参数，仍为综合序） | footer 打「默认综合排序」+ 客户端排序提示 |

### 淘宝「价格」tab 为什么只做客户端排序

对「价格」tab 尝试了：click、完整 MouseEvent 序列（pointerdown/mousedown/pointerup/mouseup/click）、多候选副本依次试、`forceClick` 二次点击 —— 点击后 `window.__last_search_params.sort` 仍为 `_coefp`、active 仍为「综合」、卡片顺序指纹不变。判定该 tab 由脚本点击无效，因此：

- 价格排序 = 把当前页已抓到的 N 条（默认 48）按价格重排，**只代表本页最低价，不是全网最低价**；
- footer 会明写「页面「价格」tab 点击实测无效，未使用」+「只覆盖本页 N 条」。

要更大覆盖面就把 `--max-scrolls` 调大，或分多页抓取后自行合并。

### 排序 URL 参数备忘

| 参数 | 是否有效 | 证据 |
|---|---|---|
| 淘宝 `&sort=sale-desc` | **无效**（`sort` 仍 `_coefp`，卡片顺序与综合一致） | `probe/taobao/tb_stm32_saledesc_20261104_1250.json` |
| 淘宝 `?page=N&tab=all` | 有效（翻页） | 同上 |
| 淘宝 tab 点击 → `sort=_sale` | 有效 | `probe/taobao/tb_stm32_click_sales_20261104_1301.json` |
| 1688 `&sortType=va_sales360&descendOrder=true&beginPage=1` | 有效、免登录 | `probe/market/ali1688_stm32_salessort_20261104_1338.json` |

## 单价归一规则

阻容 / 连接器常按「包」「100PCS」卖，标题里的数字既可能是包装量，也可能是起订区间，还可能是混装套装。`normalize()` 的输出分四类：

| 类型 | 触发 | 输出 | 例子 |
|---|---|---|---|
| 包装量 → 单只价 | 标题含 `N 个/只/片/支/条/粒/颗/pcs` 或 `共N个` | `pack_qty=N`、`unit_price=price/N`、`unit_note="N个/份"`、`unit_confidence=high` | `贴片电阻 0603 10K 1% (100个)` ¥1.28 → `¥0.0128/只` |
| **数量区间**（不做归一） | `N-M 片/个/只…`（`-`、`~`、`—`、`－`、`–`、`至`、`到`） | `pack_qty=null`、`unit_price=null`、`unit_note="数量区间 1-100（起订/阶梯，非包装数量）"` | `1-100片 TLV75733PDBVR …` ¥0.99 → 不折算 |
| **混装/套装**（不做归一） | `芯片包\|元件包\|阻容包\|元器件包\|套装\|套餐\|组合装\|混装\|样品盒\|样品包\|整包\|一盒\|散装包\|分类盒\|N种` | `assortment=true`、`pack_qty=null`、`unit_price=null`、`unit_note="混装/套装（含多个不同型号，不做单只价归一）"` | `稳压管芯片包AMS1117-3.3V 5.0V 2.5V 1.8V…` ¥3.50 → 表格显示「混装包」 |
| 整盘 / 散装，无数量 | 只有「整盘」「散装」「包邮」等 | `pack_qty=null`、`unit_price=null`、note 提示未标注数量 | `贴片电阻 整盘包邮 0603 10K` |

表格里「单只价」列会分别显示 `¥0.0128/只（100个/份）`、`区间价`、`混装包`、`—`。

**为什么不把区间当包装量**：`1-100片` 是起订量区间，若取最近的 100 当包装量，0.99/100 ≈ 0.0099 元/只，比立创同类 LDO（¥0.98 级）低两个数量级，是典型假信号。

**为什么混装必须单独标记**：套装里含多个不同型号，整包价除以件数得到的「单只价」不可用于同型号比价（实测比立创便宜 95%，纯噪音）。

### 单元回归（`detect_unit` + `detect_assortment`，7 例全对）

| 标题 | assortment | pack_qty | unit_price | conf |
|---|---|---|---|---|
| `1-100片 TLV75733PDBVR 全新原装正品SOT-23-5` | false | null | null（区间价） | none |
| `贴片电阻 0603 10K 1% (100个)` | false | 100 | 0.0128 | high |
| `稳压管芯片包AMS1117-3.3V 5.0V 2.5V 1.8V` | **true** | null | null | none |
| `0603贴片电阻系列 精度1% 1K 10K` | false | null | null | none |
| `26种0805电阻5%各20共520个（1包）` | **true** | null | null | none |
| `RC0603JR-0710KL 0603 10kΩ 5%(100个)` | false | 100 | 0.006 | high |
| `贴片电阻 整盘包邮 0603 10K` | false | null | null | none |

## 实测输出样本

### 1) 淘宝销量排序（`10k 0603 电阻`）

```
## 淘宝 · 10k 0603 电阻

| # | 标题 | 价格 | 单只价 | 销量 | 店铺 | 链接 |
| 1 | 0603贴片电阻 精度1% 1K1.2K… | ¥1.30 | — | 1000+人收货 | 深圳市讯鸿电子科技有限公司 | https://item.taobao.com/item.htm?id=525777943950 |
...

- 实际 URL：https://s.taobao.com/search?page=1&q=10k%200603%20%E7%94%B5%E9%98%BB&tab=all
- 排序：页面排序 tab：销量（sort=_sale），点击耗时 530ms
- 条数：12（页面识别 48 条，其中广告 3 条已沉底）
- 结果总数：136938
- 页面声明每页：48
- 用时：约 5s
```

注意 `结果总数` 会随排序 tab 变化（综合 4800 / 销量 136938），两套口径的「总数」不可横向比较。

### 2) 淘宝价格升序（客户端）

```
| 1 | NTC贴片热敏电阻0603 10K 1% SDNT1608X… | ¥0.0300 | — | 79人付款 | 深圳市坚信达电子有限公司 |
| 2 | 千分之一 精密电阻 0603 0.1% 0R 10R… | ¥0.0500 | — | 100+人付款 | 深圳柏阳鑫电子 |
| 3 | RC0603JR-0710KL贴片电阻0603 10kΩ 103 5%(100个) | ¥0.6000 | ¥0.00600/只（100个/份） | 13人付款 | 深圳市亿利科技电子 |
...
- 排序：页面排序 tab：综合（sort=_coefp）；价格升序：客户端对当前页 48 条排序（页面「价格」tab 点击实测无效，未使用）
```

### 3) 数量区间（`TLV75733PDBVR`，--limit 24）

```
- 注意：1 条标题写的是数量区间（起订/阶梯），已按「区间价」处理，未折算单只价。
```

对应 JSON 条目：

```json
{"title": "1-100片 TLV75733PDBVR 全新原装正品SOT-23-5固定输出电压芯片",
 "price_value": 0.99, "pack_qty": null, "unit_price": null,
 "unit_note": "数量区间 1-100（起订/阶梯，非包装数量）",
 "unit_confidence": "none", "assortment": false}
```

### 4) 混装包（`AMS1117 芯片包`）

```
| 1 | 稳压管芯片包AMS1117-3.3V 5.0V 2.5V 1.8V 1.5V 1.2V A… | ¥3.50 | 混装包 | 47人收货 | 深圳市允易达电子商行 |
| 2 | SOT-223稳压管芯片包AMS1117-3.3V 5.0V 2.5V 1.8V 1.5V… | ¥7.90 | 混装包 | 4人收货 | 允易达旗舰店 |
| 3 | 稳压管芯片包AMS1117-3.3V 5.0V 2.5V 1.8V 1.5V 1.2V A… | ¥2.50 | 混装包 | 2人收货 | 凯拓达电子配件批发 |
| 6 | AMS1117-1.2V-5.0V-ADJ 7种 每种10只 贴片SOT-223稳压电源芯… | ¥7.80（优惠后） | 混装包 | 1人收货 | 电子爱好者之家元器件 |
...
- 注意：N 条是混装/套装（不同型号打包），已标「混装包」且不做单只价归一。
```

> 这里的 N 统计的是**整页归一后的条目**（例如整页 41 条混装、`--limit` 只显示前 12），所以可能大于表格行数。

### 5) 1688 销量排序（`STM32F103C8T6`）

```
- 实际 URL：https://s.1688.com/selloffer/offer_search.htm?keywords=STM32F103C8T6&sortType=va_sales360&descendOrder=true&beginPage=1
- 排序：1688 URL 参数 va_sales360（销量降序，免登录）
```

soldCount：32000, 6000, 5600, 4300, 3900, 3500, 3500, 3400, 3100, 3100（价格 6.80 / 5.15 / 4.00 / 6.50 / 6.99 / 5.30 / 11.99 / 5.83 / 4.50 / 5.80）。

## `--json` 输出结构

```json
{
  "meta": {
    "site": "taobao", "site_name": "淘宝", "keyword": "10k 0603 电阻",
    "sort": "sales", "sort_applied": "_sale",
    "url": "https://s.taobao.com/search?page=1&q=...&tab=all",
    "count": 12, "page_items": 45, "ads": 3, "total_results": 136938,
    "fetched_at": "2026-11-04T16:01:48",
    "used_fallback": false, "client_sorted": false
  },
  "items": [ { ... } ],
  "ads": [ { ... } ]
}
```

### `items[]` 字段（21 个）

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | str | 商品标题（未截断） |
| `price_raw` / `price_value` | str / float | 页面价文本 / 数值 |
| `price_min` / `price_max` | float | 价格区间（有区间时两者不等） |
| `price_label` | str | 如「到手价」「补贴后」 |
| `price_qualifier` | str | 如「起」「优惠前」 |
| **`assortment`** | bool | **混装/套装标记；true 时不要用它的价格做单只价比较** |
| `pack_qty` | int \| null | 推断的包装数量 |
| `unit_price` | float \| null | 归一后的单只价 |
| `unit_note` | str | 归一依据 / 「区间价」「混装」说明 |
| `unit_confidence` | `high` \| `low` \| `none` | 归一可信度；`low` 请人工核对 |
| `sales_text` / `sales_count` | str / int \| null | 「1000+人付款」「3.2万+件」→ 数值；广告条目常为 null |
| `shop` / `shop_badges` | str / list | 店铺名 / 店铺标（企业店、天猫等） |
| `location` | str | 发货地（淘宝） |
| `repeat_rate` | float \| null | 1688 回头率 |
| `sponsored` | bool | 广告（直通车）。按销量排序时**必须排除 sponsored=true** |
| `item_id` / `url` | str | 商品 id 与链接 |

`meta.client_sorted=true` 表示价格排序是客户端做的（不覆盖全网）；`meta.used_fallback=true` 表示 playbook 抽取为空、走了自写 DOM 抽取。

`--json` 只写 `items[:limit]`：想事后核查第 N 名之后的命中，请把 `--limit` 放大（如 24）。

## 限制与失败模式

| 现象 | 原因 | 处理 |
|---|---|---|
| `淘宝搜索结果为空（卡片 0）`，exit 4 | 浏览器淘宝登录态过期（页面显示「亲，请登录」） | 浏览器里重新登录淘宝；**这不是反爬** |
| `淘宝要求人机验证（验证码/滑块）`，exit 4 | 触发风控 | 人工过一次验证，或停一段时间 |
| `1688 跳到了登录页`，exit 4 | 会话掉了 | 浏览器里打开 1688 后重试 |
| `1688 没解析到商品`，exit 5 | 关键词过长/组合过细，页面变「没有相关商品」 | 缩短关键词（「0805电阻」> 「0805 10K 1% 电阻」） |
| `连不上 WebBridge daemon`，exit 3 | daemon 没启动 | 启动 `%USERPROFILE%\.kimi-webbridge\bin\kimi-webbridge.exe` |
| 表格条数少于 `--limit` | 当前页可识别卡片不足（含广告过滤） | 增大 `--max-scrolls` 或换关键词 |

其他已知特性：

- **1688 召回很松**：搜「0805电阻」前几名可能是电容 / LED，需按标题二次过滤或加长关键词。
- **淘宝销量口径随 tab 变**：销量 tab 是「N人收货」（近 30 天），综合 tab 是「N人付款」（累计），同款商品两处数字不可直接比。
- **广告**：淘宝 sponsored 条目位置靠前且销量常为空，`sort_items()` 会把广告沉底并在 footer 报数量；1688 也有「实力商家」等标记位，未单独过滤。
- **淘宝无阶梯价字段**：搜索页与详情页都不返回阶梯价，`price_qualifier="起"` 只表示「起售价」；批量价要去 1688 或立创看。
- **限流尚未打满**：实测每站点间隔 ≥3s（`MIN_INTERVAL=3.0`，状态文件 `%TEMP%\bom-sourcing-taobao-state.json` 跨进程生效），整轮 40+ 次请求未触发验证码/滑块。连续高频（<1s 一次）未测。

## 文件清单

| 文件 | 作用 |
|---|---|
| `scripts/taobao.py`（616 行） | CLI、WebBridge 客户端、URL 构造、排序逻辑、单价归一、渲染 |
| `scripts/js/taobao_prep.js`（5.9KB） | 等卡片就绪、读 `__last_search_params`、点排序 tab、登录/验证墙检测、卡片顺序指纹 |
| `scripts/js/taobao_search_fn.js`（12.6KB） | 从 Tabbit playbook 抽出的 `taobao_get_search_results` 源码 |
| `scripts/js/taobao_fallback.js`（3.8KB） | 自写 DOM 兜底抽取（playbook 返回 0 条时用） |
| `scripts/js/ali1688_search.js`（3.6KB） | 1688 搜索卡片抽取 |
| `scripts/js/taobao_login_probe.js`（1KB） | 淘宝登录态探测（nick / 标记文字） |

## 原始样本（`Bom_Flow/probe/`）

| 文件 | 内容 |
|---|---|
| `taobao/tb_STM32F103C8T6_sales_pb_20261104_1304.json` | playbook 销量序 46 条（含 sponsored 空洞） |
| `taobao/tb_stm32_click_sales_20261104_1301.json` | 点「销量」tab 前后 sort/总数对比 |
| `taobao/tb_stm32_saledesc_20261104_1250.json` | `&sort=sale-desc` 无效的证据 |
| `taobao/tb_tlv75733_range24_20261104_1634.json` | 区间价样本（`1-100片 …`） |
| `taobao/tb_ams1117_pack_20261104_1638.json` | 混装包样本（11/12 条 assortment） |
| `taobao/tb_detail_624485237766_20261104_1338.json` | 淘宝详情页字段结构（chip，含 sku/price/seller） |
| `taobao/tb_detail_res_529532295464_20261104_1357.json` | 电阻按「100个/包」计价证据 |
| `market/taobao_10k0603_sales_20261104_1602.json` | `--json` 销量序样本 |
| `market/ali1688_stm32_sales_20261104_1608.json` | 1688 销量序样本（soldCount 降序） |

## 未验证 / 风险

1. **价格排序的覆盖面**：客户端排序只覆盖当前页（默认 48 条），不代表全网最低价；要更全需多页抓取。**未验证**多页合并的稳定性。
2. **1688 价格排序**：`--sort price_asc/price_desc` 对 1688 走客户端排序（URL 不带排价参数，footer 显示「默认综合排序」）；1688 自身的价格排序 URL 参数**未验证**。
3. **1688 阶梯价**：两份详情样本均无完整多档阶梯价表（`¥2.00~¥17.00 1个起批` 这类只给一段区间），批量价需人工看详情页价目表。
4. **风控阈值未知**：只在 ≥3s 间隔下跑过 40+ 次；更密请求、连续多页抓取是否触发滑块**未验证**。
5. **销量口径**：淘宝「人收货（近30天）」与「人付款（累计）」不可比；1688「全网 N 件」「月浏览」「售 N 卷盘」单位不一，跨店铺比较只能当量级参考。
6. **登录态依赖**：整个工具依赖用户浏览器保持淘宝登录；无登录时的降级路径（如 1688 免登录）已通，淘宝无替代方案。
