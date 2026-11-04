# 元器件商城渠道实测：淘宝 / 1688 / 京东

最后更新：2026-11-04

范围：验证三条渠道能否被 agent 稳定检索并抽出结构化结果（标题 / 价格 / 销量 / 店铺 / 地区 / 链接），重点验证**按销量排序**与**小批量 vs 批量价格**。所有结论来自本机实测，原始 JSON 见文末索引；未做的项目在「未验证 / 风险」里明确标出。

---

## 结论速览

| 渠道 | 可用性评级 | 检索 | 结构化抽取 | 按销量排序 | 登录 | 关键限制 |
|---|---|---|---|---|---|---|
| 淘宝 | **可直接用**（须有登录态的浏览器） | ✅ 关键词 | ✅ 16 字段全可用 | ⚠️ **URL 参数无效，必须点「销量」tab** | **必须已登录**，未登录结果区不渲染 | 单页只出 46~48 条；广告混入且销量为空；卡片价是「起价」 |
| 1688 | **可直接用**（免登录） | ✅ 关键词 | ✅ 价格/起批/销量/回头率 | ✅ **URL 参数 `sortType=va_sales360&descendOrder=true` 直接生效** | 免登录可搜可看详情（深度功能需登录） | 关键词过细直接 0 结果；同款单位混杂（只/包/盘） |
| 京东 | **可用**（免登录可看首屏） | ✅ 关键词 | ✅ 但**字段名与淘宝不同** | ⚠️ 未找到排序参数（**未验证**） | 免登录首屏可用；无登录态会被重定向到 passport | 结果以开发板/成品为主，裸片少；`truncated=true` |

一句话选路：**少量、要便宜 → 淘宝；走量、要批发价与起批 → 1688；少量但要正品+发票 → 京东。**

---

## 1 淘宝

### 1.1 前置条件

- 车子（浏览器）**必须是用户真实登录态**。同一个 URL，未登录浏览器（Tabbit Browser）里 `s.taobao.com/search` 结果是空白：`document.body.innerText.length = 162`，内容只有「亲，请登录 / 加载中 / 桌面版」，卡片数 0，官方 playbook 返回 `count=0` + 警告「页面声明每页 48 个结果，实际找到 0 个可识别商品卡片」，同时 `window.__last_search_params` 依然完整（q / sort / n=48 / totalResults=4800 / totalPage=100）。**判定方法：卡片数 0 但 params 有值 = 登录墙，不是反爬。**
- 本机走 **Kimi WebBridge**（daemon `http://127.0.0.1:10086`，扩展已连接）驱动 Edge；在 Edge 里淘宝是已登录的（昵称、我的淘宝、购物车、免费开店可见），`a[href*="item.htm"]` 39 条去重 39 个，无登录墙。
- Tabbit Browser 无淘宝登录态 → **淘宝这条路 Tabbit 不可用**；Tabbit 的淘宝 playbook 本身没坏，缺的是登录态。

### 1.2 可复用操作序列（精确命令）

工具：`probe\taobao\js\wb.ps1` —— 把 UTF-8 的 JS 文件封成 `{action:"evaluate",session,args:{code}}` JSON（写临时文件 + `curl.exe --data-binary @file`），解析 `data.value` 后以 UTF-8 落盘；`-NavUrl` 先 navigate（复用同一 tabId）。

```powershell
$d = "D:\WorkDesigns\3_WorkTools\Bom_Flow\probe\taobao\js"
cd $d
# ① 打开搜索页（关键词直接进 URL）
./wb.ps1 -NavUrl "https://s.taobao.com/search?q=STM32F103C8T6" -Js "$d\_ex_srp.js" -Out "..\tb_stm32_plain_<ts>.json"
# ② 点「销量」tab（URL 参数无效，必须点击）+ 调官方 playbook 抽结果
./wb.ps1 -Js "$d\_flow_sales_pb.js" -Out "..\tb_STM32F103C8T6_sales_pb_<ts>.json"
# ③ 详情页
./wb.ps1 -NavUrl "https://item.taobao.com/item.htm?id=<itemId>" -Js "$d\_flow_tb_detail3.js" -Out "..\tb_detail_<id>_<ts>.json"
```

`_flow_sales_pb.js` 内部三步：先读 `window.__last_search_params.sort`，若不是 `_sale` 就点 `.next-tabs-tab` 里文本为「销量」的 LI → 轮询 active 变「销量」→ `page.evaluate(taobao_get_search_results, {maxItems, maxScrolls})`（调用前 strip 每项 `rawText`、title 截断，控体积）。

抽取函数两种：**官方 playbook 函数**（`C:\Users\dell\AppData\Local\Tabbit\LocalAgent\skills\tabbit\playbooks\taobao\webmcp.js`，`taobao_get_search_results` 行 8–329、`taobao_get_product_details` 行 332–末尾），或**自写紧凑抽取** `probe\taobao\js\_ex_srp.js`（不依赖 playbook，作为兜底，见 §7）。

### 1.3 排序参数（关键结论）

| 尝试 | 结果 |
|---|---|
| URL `&sort=sale-desc` | ❌ **无效**。导航后 `__last_search_params.sort` 仍是 `_coefp`、active 仍是「综合」，46 条结果与综合序一致 |
| 点 `.next-tabs-tab` 文本「销量」 | ✅ `sort: _coefp → _sale`、active「综合 → 销量」、`totalResults 4800 → 8088`，耗时约 3.2s，**URL 不变**（SPA，不能靠改 URL 复现） |
| 排序 tab 文本 | 「综合」「销量」「价格」（价格可二次点击切升降） |

→ 可复用结论：**淘宝销量排序只能靠点击 tab 获得，没有可拼的 URL 参数；每次会话都必须点一次。** 点击前后的快照见 `tb_stm32_click_sales_20261104_1301.json`。

### 1.4 搜索结果字段表（`taobao_get_search_results`）

| 字段 | 覆盖 | 说明 / 形态 |
|---|---|---|
| `itemId` / `url` / `imageUrl` | 12/12 | `https://item.taobao.com/item.htm?id=…` |
| `title` | 12/12 | 常含单位说明（「(10个)」「100个」「卷盘」），需要单独解析 |
| `price.value` / `text` | 12/12 | **卡片价是最低价规格（起价）**，`qualifier` 可能是 `起` / `补贴后` / `平台加补后`；`price.original` 才是优惠前价 |
| `salesText` / `salesCount` | 12/12 | `「3人付款」「1000+人付款」「200+人收货」「1万+人付款」`；`salesCount` 已换算成数值（1万+ → 10000） |
| `shop.name` / `shop.badges` | 12/12 / 7/12 | 旗舰店 / 专营店 / 「深圳市××电子」这类企业店 |
| `location` | 12/12 | 省+市（发货地） |
| `sponsored` | 12/12 | **广告位，其 salesCount 为 null**，必须过滤 |
| `attributes` / `promotions` / `ranking` | 7/12 / 12/12 / 2/12 | ranking 稀疏，不要依赖 |
| 页面 meta | — | `sort` / `page` / `pageSize=48` / `totalResults` / `totalPages` / `complete` / `stopReason` / `warnings` |

### 1.5 详情页字段（`taobao_get_product_details`）

`data` 键：`itemId, canonicalUrl, source, title, description, sales, price, seller, endorsements, promotions, guarantees, delivery, parameters, sku, services, media, details, reviews`。

| 关注点 | 实测结果 |
|---|---|
| **阶梯价** | ❌ **没有阶梯价字段**。淘宝是零售定价，只有一个当前价 + `price.original`（优惠前） |
| SKU / 规格 | ✅ `sku.properties[]`（每维 `{id,name,values[{id,name,imageUrl,available}]}`）+ `sku.variants[]`（`{skuId,propertyPath,price,quantity,quantityText}`）。电阻这类可有 200+ 个规格值，**注意体积** |
| 库存 | ✅ `sku.availability{quantity, text:"有货", purchaseLimit}`；`variants[].quantity` 逐规格 |
| MOQ | ⚠️ **没有独立字段**。用 `price.qualifier="起"` 表达「起批量价」，真实 MOQ 写在标题/SKU 名（如「100个」）里，需自己解析 |
| 单价是每件还是每包 | **按卖家定义的「份」计价，必须看 SKU 名归一**。实例：天猫 risym旗舰店 ¥2.86，SKU 名「0805 1% 100个」→ 实际 **0.0286 元/只**；另一卖家标题带「(10个)」即以 10 只为一份 |
| 店铺类型 | ✅ `seller.type`: `"C"`=淘宝店，`"B"`=天猫 |
| 发货 | ✅ `delivery{from,to,freight:"快递: 免运费，可加价选顺丰",estimate}` |
| 其他 | `endorsements`「回头客724人」「超1千人加购」、`guarantees`、`promotions`、`parameters{name,value}`（品牌/型号/精度等） |

### 1.6 销量排序实测样本（5 个典型器件）

全部为「点销量 tab 后」的结果（`sort=_sale`），广告已从统计中剔除：

| 关键词 | 卡片 | 广告 | 价格 min/中位/max（元） | 销量 max | 旗舰店占比 | 备注 |
|---|---|---|---|---|---|---|
| STM32F103C8T6 | 46 | 3 | 0.94 / **2.48** / 142 | 800 | 12/43 | **前 3 名全是开发板套件（11.22 / 20.98 / 10.71）**；首个裸片是 ¥1.02「全新原装 LQFP48」200+ 付款 |
| 0805 10K 1% 电阻 | 48 | 3 | 0.79 / 1.78 / 20 | 1000 | 25/45 | 卡片价多为「100个/包」价；`totalResults` 94705 |
| NE555 | 46 | 3 | 0.02 / 2.28 / 37.83 | 100 | 8/43 | 混入「(10个)」整管与 SOP-8 贴片两种形态 |
| Type-C 16P 母座 | 46 | 4 | 0.03 / 1.56 / 4.2 | 1000 | 13/42 | 6P/16P/24P 混在一条链接里，**必须看 SKU 选具体型号** |
| AMS1117 3.3 | 46 | 3 | 0.04 / 1.5 / 4.7 | 800 | — | ¥0.17「原装正品 UMW AMS1117-3.3」300+ 付款 |

原始文件：`tb_STM32F103C8T6_sales_pb_20261104_1304.json`、`tb_0805_10K_1__电阻_sales_pb_20261104_1313.json`、`tb_NE555_sales_pb_20261104_1313.json`、`tb_Type_C_16P_母座_sales_pb_20261104_1313.json`、`tb_AMS1117_3_3_sales_pb_20261104_1313.json`、详情页 `tb_detail_624485237766_20261104_1338.json` / `tb_detail_res_529532295464_20261104_1357.json`。

### 1.7 限流建议

- 实测：整轮 40+ 次导航/求值（间隔 3~5s，含人工阅读停顿），淘宝/1688/京东均**未出现验证码、滑块或登录墙**。
- 建议参数：**同一站点串行，请求间隔 ≥3s，首页结果 1 页/关键词（48 条足够）**，连续不超过 20 次后停 30~60s；翻页一次只翻 1~2 页。
- 会话复用同一个 tabId（`wb.ps1` 默认复用），避免频繁开标签页。

### 1.8 坑（按踩坑代价排序）

1. **未登录 = 静默空结果**：卡片 0 + params 有值，误判成「反爬」会白折腾。先看登录态。
2. **`sort=` 参数是假的**，只有点击 tab 有效。
3. **广告位必须过滤**：`sponsored=true` 的项 `salesCount=null`，混在排序结果前部（位置 1/4/8）。
4. **销量排序会把「开发板/套件」顶到前面**（STM32 前 3 名全是套件），做 BOM 时必须加标题过滤词再排序。
5. **卡片价是起价**（最低规格），不能直接当器件单价用；必须进详情按 SKU 归一。
6. **单位陷阱**：电阻/电容按「包（100 个）」卖、芯片可能按「(10个)」一管卖；标题不写单位的链接（如 Type-C 6P/16P 混链）必须靠 SKU 判。
7. 详情页 `sku.properties` 可能 200+ 值，整段回传会撑爆上下文，抽取时只取前几个 SKU 或用 `variants` 定位目标规格。

---

## 2 1688

### 2.1 可复用操作序列

搜索页（免登录）：

```
https://s.1688.com/selloffer/offer_search.htm?keywords=STM32F103C8T6
```

**销量排序直接用 URL 参数，不需要点击**（点击「销量」后浏览器地址栏就变成这个形态）：

```
https://s.1688.com/selloffer/offer_search.htm?keywords=STM32F103C8T6&sortType=va_sales360&descendOrder=true&beginPage=1
```

抽取：`probe\market\js\_ex_1688.js`（取每个 offer anchor 自身的 innerText，去掉空白后正则解析；输出 `items{offerId,url,title,priceText,priceMin,priceMax,soldText,soldCount,repeatRate,company,badges,cardText}` + `priceStats`），详情用 `_ex_1688_detail2.js` / `_ex_1688_detail.js`。

### 2.2 字段表（搜索卡片）

| 字段 | 说明 |
|---|---|
| 标题 | 常带「100PCS」「卷盘」「1%」等单位/规格词 |
| `priceText` → `priceMin/priceMax` | 区间价，`¥` 前缀可能存在；实测无解析不出的价（`invalidPriceCount=0`） |
| `soldText` / `soldCount` | 形态多样：「全网400+件」「3.2万+件」「月浏览1000+」「售300+卷盘」→ 语义不同（成交量 / 浏览量 / 卷盘数），**不能一律当销量** |
| `repeatRate` | 回头率（%），1688 特有，比销量更能反映 B 端复购 |
| `company` | 公司名（不是店铺名） |
| `badges` | 退货包运费 / 先采后付 / 官方物流 / 7天无理由 / 好评率100% 口碑商品 / 热卖榜 TOPn |

### 2.3 起批量与价格（详情页）

- 价格面板选择器：`[class*="od-price"]` / `[class*="price-item"]` / `[class*="ladder"]` / `[class*="priceRange"]`，实测 `[class*="od-price"]` 命中 1 个、`[class*="offer-price"]` 命中 30 个。
- 实测三类表达：
  - `¥ 2.00  **1个起批**`（标题是「100PCS/包」→ 这里的 **1个 = 1 包 = 100 只**，折 0.02 元/只）
  - `¥ 0.02  **100PCS起批**` + 「60天老客价」
  - **价格区间 + 起批**：`¥ 2.00 ~ ¥ 17.00  1个起批  60天老客价`（offer 1056384196754，销量 5600+，回头率 55）→ 区间两端对应多规格（型号/容量），**不是数量阶梯**
- **多档阶梯价（1-9件 / 10-99件 / ≥100件）在 3 个样本里都没出现**（`ladderSeen=false`，且用正则扫全文 `\d+[-~—至]\d+件` 也为空）→ **1688 详情页在本机免登录自动化下拿不到数量阶梯价**，只有「价格区间 + 起批量」，批量单价必须靠询盘或第三方工具。这是走量比价的核心缺口。

### 2.4 样本

| 文件 | 条数 | 价格 min/中位/max | 销量 max | 备注 |
|---|---|---|---|---|
| `ali1688_STM32F103C8T6_20261104_1323.json` | 51 | 1.69 / 6.8 / 195 | 67000 | 综合排序；混入开发板（¥195）拉高上限 |
| `ali1688_stm32_salessort_20261104_1338.json` | 14 | 4.00 / 5.83 / 11.99 | 32000 | **销量排序 URL 生效**，soldCount ≈ 降序 32000/6000/5600/3900/3500… |
| `ali1688_res0805_v2_20261104_1331.json` | 15 | 0.02 / 8 / 260 | 2200 | 单位混杂：0.02 元/只、2 元/100PCS 包、42.5、260/盘 |

### 2.5 坑

1. **关键词太细 = 0 结果**：搜「0805 10K 1% 电阻」后点销量，页面直接变「没有相关商品，推荐试试搜这些」。应缩短为「0805 10K 电阻」或「0805电阻 10K 1%」。
2. **同一链接内单位混杂**（只 / 100PCS 包 / 卷盘），价格数量级差 100~1000 倍，比价前必须归一。
3. 搜索结果里的 `soldText` 语义不一致（浏览量 vs 成交量），排序 URL 用的是官方「销量」维度，自己的统计不要混用。
4. 未登录状态下会弹「立即登录」提示条，但结果照常渲染，可忽略；`_ex_1688.js` 的 `dir=""` 去空格处理是解析稳定的前提。

---

## 3 京东

### 3.1 登录与可达性

- 无登录态浏览器（Tabbit）访问 `search.jd.com/Search?keyword=…` 会被 302 到 `https://passport.jd.com/new/login.aspx?ReturnUrl=…`，此时官方 playbook 报 `UNSUPPORTED_ROUTE: Open a supported 京东 page for this recipe.`（exit=70）。
- **Edge（有登录态）直接可用**：`jd_edge_stm32_20261104_1317.json` 拿到 30 条，`isLoginPage=false`，无验证码，`truncated=true`（首屏 30 条）。

### 3.2 字段表（`jingdong_get_search_results`，**与淘宝 schema 完全不同**）

| 字段 | 说明 |
|---|---|
| `skuId` / `canonicalUrl` / `title` / `imageUrl` | 主键与展示 |
| `price.value` / `price.label` | label 常见 `到手价` / `补贴到手价`；`price.referenceText`/`referenceValue` 是划线原价（如 `¥158`） |
| `seller.name` | 店铺名（旗舰店 / 专营店 / 「××工业48店」） |
| `stockText` | 「有货」 |
| `sellingPoints[]` | 「900+人加购」「3千+人浏览」 |
| `badges[]` | 「京东物流」「明日达」「送货上门」「已售400+」 |
| `metrics` | `{texts, commentText:"200+", commentCount, favorableRate:85}` —— **好评率**是京东独有信号 |
| `rankText` / `sponsored` | 榜单文案 / 广告标记 |
| ❌ 缺失 | **没有 `salesText` / `salesCount` / `shop`（店铺对象）/ `location`**。按淘宝字段名读会全空 |

### 3.3 适配性

30 条样本里绝大多数是开发板/套件（¥135「野火小智 7天入门STM32学习板套件」、¥250.8 江科大套件、¥7.04 补贴价裸板、¥15.3 正点原子），**裸片器件少**。京东的强项是：正品保障、发票、京东物流、好评率，而不是 BOM 批量采购价比价。

限流：单轮 30 条 1 次请求正常；翻页与并发**未验证**。建议与淘宝同参数（间隔 ≥3s，每关键词 1 页）。

---

## 4 销量信号有效性

实测统计（广告已剔除）：

| 关键词 | 有效条数 | Spearman(价格, 销量) | 标题含「开发板/套件」 | 旗舰店 |
|---|---|---|---|---|
| STM32F103C8T6 | 43 | **+0.092** | 11/43 | 11/43 |
| 0805 10K 1% 电阻 | 45 | **−0.314** | 0 | 24/45 |
| NE555 | 43 | −0.072 | 0 | 7/43 |
| Type-C 16P 母座 | 42 | +0.078 | 0 | 13/42 |

读法：

- **价格与销量基本不相关**（|ρ| ≤ 0.32）。除了电阻类（便宜链接卖得多，弱负相关），「便宜就好卖」不成立 —— 淘宝的销量被**链接内容**（一个链接覆盖几十个规格）和**广告/运营**主导，不是单规格竞争力。
- **销量排序对 BOM 有系统性偏差**：STM32 销量前 3 名全是开发板/套件（¥10~21），裸片最高销量只有 200+。原因是套件是消费级爆款，裸片是 B 端零星采购。
- **店铺类型与销量**：旗舰店占据电阻类 24/45（大而全的「全阻值一个链接」模式），而芯片类旗舰店只占 11/43，主流是「深圳市××电子」企业店（原装现货/配单店）。企业店的单价通常更低（STM32 裸片 ¥1.02 来自「深圳市新纶电子」，旗舰店同类 ¥6.71）。
- 结论：**销量可作热度/可信度的辅助信号，不能作为选型主判据**；判据顺序应为「规格匹配 → 单位归一后的单价 → 销量/回头率 → 店铺类型」。

启发式规则（可直接编码）：

1. 先按标题/SKU 过滤掉 `开发板|套件|最小系统板|模块`（除非需求本来就是买板）。
2. 单位归一：从标题/SKU 名里抽 `(\d+)\s*(个|只|pcs|PCS)` 或 `包/盘/卷`，折算成「元/只」再比价。
3. 销量只作 tie-breaker：`salesCount ≥ 100` 视为有销量验证；`null`（广告）直接丢弃。
4. 店铺偏好：芯片类优先「原装/全新/代理」字样 + 企业店/旗舰店；电阻电容类优先旗舰店（一个链接全阻值，凑单省运费）。
5. 1688 用「回头率」替代销量做可信度（35% 以下慎选，45%+ 常见于老牌贸易商）。

---

## 5 少量 vs 批量的渠道判据

### 5.1 实测价差（同型号 STM32F103C8T6 裸片）

| 渠道 | 样本价 | 起批 / 单位 | 折合单价 |
|---|---|---|---|
| 淘宝（零售，包邮，含平台补贴） | ¥1.02 / ¥1.45 / ¥6.71 / ¥11.22 | 1 件起，无 MOQ | **≈1.0~1.5 元/只**（最低价档） |
| 1688（批发，免登录可看） | ¥4.00 / ¥5.15 / ¥6.80 | 有起批量（1 个起批或 N PCS 起批） | **≈4~5 元/只**（销量排序前列） |
| 京东（正品 + 发票 + 物流） | ¥7.04（补贴到手价，开发板）/ ¥135 套件 | 1 件起 | 裸片**未取到有效样本**，整体不便宜 |

**反直觉但可复现的结论：小批量时淘宝比 1688 更便宜**（淘宝零售链接有平台补贴 + 包邮 + 竞争激烈；1688 的「1个起批」价是批发挂牌价，量小不给阶梯折扣）。1688 的价值本应在**大数量 + 阶梯价 + 对公/开票**，但**阶梯价在本机自动化下取不到**（只有价格区间 + 起批量），所以「1688 走量更便宜」在当前工具能力下**无法用数据证实**，只能作为需询盘的假设。

### 5.2 阈值建议（基于上述实测）

| 数量 / 金额 | 首选 | 理由 |
|---|---|---|
| 单型号 ≤ 10 只，或单品总价 < 50 元 | **淘宝**（销量排序 + 单位归一后取低价） | 无 MOQ、包邮、单价最低，凑单容易 |
| 单型号 10 ~ 100 只 | **淘宝比价 + 1688 询价并看** | 两边都要看：淘宝仍可能更便宜，1688 需确认阶梯价是否存在 |
| 单型号 ≥ 100 只，或整单 ≥ 500 元 | **1688**（首选），立创商城做价格锚 | 起批量与对公开票才有意义；**阶梯单价自动化取不到，需人工询盘确认** |
| 必须正品 + 要发票 + 少量 | **京东**（次选立创） | 好评率/京东物流/发票齐全，价格溢价可接受 |
| 停产 / 缺货 / 无型号反向选型 | 淘宝销量排序找同封装同参数 → 1688 确认在产 | 反向选型靠销量热度，不靠参数表 |

> 立创商城的比价口径不归本节（另有渠道负责，未验证）。

---

## 6 给实现者的建议（默认检索流程）

```
输入：型号/规格串（如 "STM32F103C8T6"、"0805 10K 1%"）
1. 淘宝：导航 s.taobao.com/search?q=<kw>  → 点「销量」tab（必做，URL 参数无效）
   → taobao_get_search_results(maxItems=48) → 丢 sponsored → 标题过滤 开发板/套件
   → 单位归一 → 得到候选 Top-N（N=5~10）
2. 对候选里价格最低的 2~3 个开详情页 → 按 SKU 定位目标规格 → 拿 MOQ/单位/库存
   （淘宝无阶梯价字段，MOQ 只能从 qualifier="起" + SKU 名解析）
3. 1688：直接拼 sortType=va_sales360&descendOrder=true URL → 抽价格区间/起批/回头率
   → 若能解析到阶梯价则记录，拿不到就标 "阶梯价未验证"
4. 京东：同关键词跑一次，用于「正品价锚点」+ 好评率交叉验证（可选，成本 1 页）
5. 输出：每个候选带 {渠道, 单价(元/只), 单位来源, MOQ, 销量/回头率, 店铺, 发货地, 链接}
6. 全部原始 JSON 带时间戳落盘，抽取结论只引用落盘数据
```

工程注意：

- 淘宝必须复用同一个已登录 tab；**先探测登录态**（卡片数 > 0）再抽，卡片 0 直接判「需登录」返回给上层，不要重试。
- 抽取体积控制：`taobao_get_search_results` 结果的 `rawText` 先 strip；详情页 `sku.properties` 可能上百项，只取目标规格。
- 每次会话都要重新点「销量」（SPA，URL 不记忆）。

---

## 7 替代方案（若 playbook 失效）

| 方案 | 状态 | 说明 |
|---|---|---|
| **自写 DOM 抽取函数** | ✅ **已验证可用** | `probe\taobao\js\_ex_srp.js`：轮询卡片 15s，选择器 `a[class*="doubleCardWrapper"][href]` / `#mainsrp-itemlist .item` / `[data-spm-act-id][class*="Card"]` / `[data-nid].item`，按 `itemId` 去重；排序状态从 `window.__last_search_params`（`sort`/`page`/`n`/`totalResults`/`totalPage`）读，不用猜 DOM。1688 同理 `_ex_1688.js`。 |
| 淘宝联盟 API | ❌ **未验证** | 需要 appkey + 推广位资质，本轮未申请；无法确认是否给「按销量排序」原始数据 |
| 第三方聚合 API（聚合数据 / 极速数据等） | ❌ **未验证** | 本轮未注册取样，价格/配额/字段均未知 |
| 1688 开放平台 | ❌ **未验证** | 需要企业开发者资质与授权，普通账号拿不到 |

结论：**不依赖新申请的 API 也能做**——真登录浏览器 + DOM 抽取已经能满足「标题/价格/销量/店铺/地区/链接」，这也正是本轮走通的路径。

---

## 8 未验证 / 风险

1. **1688 完整阶梯价（1-9件 / 10-99件 …）未验证且大概率取不到**：3 个详情样本（含销量 5600+、回头率 55 的 B 端链接）只给出「价格区间 ¥2.00~¥17.00 + 1个起批 + 60天老客价」，正则扫全文无 `N-M件` 台阶。走量决策依赖这条，需人工询盘或第三方数据源补齐。
2. **京东销量排序参数未找到**；京东翻页、并发、登录态过期行为未测。
3. **淘宝翻页未验证**（playbook 只覆盖当前页，警告「结果只覆盖当前搜索结果页；不会自动翻到下一页」），多页抓取需自己点下一页。
4. **登录态会过期**：本轮 Edge 是已登录状态；过期后淘宝会回到「空白 + params 完整」的形态，需人工扫码。这是长期运行的**主要单点故障**。
5. **验证码/滑块未触发过**（40+ 次请求内），但阈值未知；一旦出现必须人工过，不要在自动流程里硬刚。
6. **价格是瞬时快照**：淘宝卡片价是「起价 + 补贴后」，1688 有「60天老客价」「活动价」，比价结论只在采集时刻有效。
7. **SKU 规格与型号的映射不可靠**：一条链接覆盖 6P/16P/24P、0603/0805/1206 是常态，型号对齐只能靠 SKU 名文本匹配，存在错配风险。
8. 京东价格字段名（`price.value` + `label`）与淘宝不同，实现里必须按渠道分 schema，不能共用一个解析器。

---

## 附录：原始数据索引

淘宝（`probe\taobao\`）：

| 文件 | 内容 |
|---|---|
| `tb_stm32_pb_default_20261104_1239.json` | 综合排序首批 12 条（字段完整度基线） |
| `tb_stm32_saledesc_20261104_1250.json` | `&sort=sale-desc` 无效性证据（46 条与综合序一致） |
| `tb_stm32_click_sales_20261104_1301.json` | 点击「销量」tab 前后 params 对比（sort `_coefp`→`_sale`） |
| `tb_STM32F103C8T6_sales_pb_20261104_1304.json` | STM32 销量排序 46 条 |
| `tb_0805_10K_1__电阻_sales_pb_20261104_1313.json` | 电阻 48 条 |
| `tb_NE555_sales_pb_20261104_1313.json` | NE555 46 条 |
| `tb_Type_C_16P_母座_sales_pb_20261104_1313.json` | Type-C 46 条 |
| `tb_AMS1117_3_3_sales_pb_20261104_1313.json` | AMS1117 46 条 |
| `tb_detail_624485237766_20261104_1338.json` | 芯片详情（¥1.02，SKU/库存/发货） |
| `tb_detail_res_529532295464_20261104_1357.json` | 电阻详情（¥2.86/100个 → 单位陷阱证据） |

1688 / 京东（`probe\market\`）：

| 文件 | 内容 |
|---|---|
| `ali1688_STM32F103C8T6_20261104_1323.json` | 1688 STM32 综合排序 51 条 |
| `ali1688_stm32_salessort_20261104_1338.json` | 1688 销量排序 URL 生效 14 条 |
| `ali1688_res0805_v2_20261104_1331.json` | 1688 电阻 15 条（单位混杂） |
| `ali1688_detail2_788584449045_20261104_1352.json` | 「¥2.00 1个起批」= 1 包 100 只 |
| `ali1688_detail2_1034729652170_20261104_1352.json` | 「¥0.02 100PCS起批」+ 老客价 |
| `ali1688_detail_1044800569969_20261104_1345.json` | 无阶梯价、多规格价表 |
| `ali1688_ladder_1056384196754_20261104_1410.json` | 阶梯价缺失证据：`¥2.00~¥17.00 1个起批 60天老客价`、`ladderSeen=false` |
| `jd_edge_stm32_20261104_1317.json` | 京东 STM32 30 条（真实字段名） |
| `jd_stm32_search_20261104_1313.json` | 京东无登录态被重定向的证据 |

脚本：

- `probe\taobao\js\wb.ps1`（WebBridge 调用封装）、`_ex_srp.js`（淘宝搜索兜底抽取）、`_flow_sales_pb.js` / `_flow_sort_pb.tmpl.js`（点销量 + playbook 抽取）、`_click_sort.tmpl.js`（点排序 tab）、`_flow_tb_detail3.js`（详情 + 单位线索）、`_fn_search.js` / `_fn_details.js`（playbook 函数源码副本）
- `probe\market\js\_ex_1688.js`、`_ex_1688_detail.js` / `_ex_1688_detail2.js`、`_ex_1688_ladder.js`（阶梯价探测）、`_flow_1688.js`
- `probe\market\js\_fn_jd_search.js` / `_fn_jd_details.js`、`_flow_jd_edge.js`、`_drive_jd.js`
