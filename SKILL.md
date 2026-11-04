---
name: bom-sourcing
description: 配单 / BOM 采购助手：两件事——①解析 BOM 表格，到立创商城（szlcsc）检索比价并按指标核对，给替代料候选与「少量买淘宝、批量走立创/1688」的渠道建议；②**按意图找料**：只有一句需求（"3.3V 1A 的 LDO"、"30V 5A 的 N 沟道 MOS"、"10uF 25V 0805 电容"）也能选型出候选清单。触发词：配单、BOM、元器件选型、比价、替代料、找料、找个料、选型、要一个 XX 芯片、立创商城、嘉立创、淘宝买元件、批量采购、器件参数对比、这个料多少钱、有没有替代、按参数找料。English - BOM sourcing, part selection, LCSC price lookup, alternate parts, component comparison, pick a part by spec.
metadata:
  version: "0.2.0"
---

# 配单 / BOM 采购

一句话：**把"一列 BOM"或"一句话需求"变成可下单的候选清单**——每行落到一个立创编号，带按数量取的阶梯价、
库存、指标核对结论、替代候选，以及按数量的渠道建议。

## 两种入口（先判断手里有什么）

| 入口 | 手里有什么 | 用哪个脚本 |
|---|---|---|
| **BOM 出发** | 料表 / 原理图导出的器件清单 | `bom.py`（逐行匹配 + 报价单） |
| **意图出发** | 只有需求：参数、品类词、用途 | `pick.py`（意图 → 品类 → 候选 → 参数筛选） |

两者共用 `lcsc.py`（取数）与 `spec.py`（参数解析比对），可互相串联：`pick.py` 选出的型号可以直接丢回 `bom.py` 核价。

## 何时用

- 手里有 BOM / 料表 / 原理图导出的器件清单，要报价、要比价、要找替代
- 只有一个型号或品类词（"STM32F103C8T6 多少钱"、"10k 0603 哪家便宜"）
- **只有一个需求，还没定型号**（"我要一个 3.3V 1A 的 LDO，SOT-23 优先"、"30V 5A 的 N 沟道 MOS"）
- 要判断"这个料该在淘宝买还是立创买、买多少"

不适合：采购下单（本项目只读比价，不登录不下单）、PCB 制造报价（走嘉立创官方报价器）。

## 30 秒开始

```bash
# ── 从 BOM 出发 ─────────────────────────────────────────────
python scripts/bom.py 我的BOM.csv --columns              # 1) 先看认不认得（不联网）
python scripts/bom.py 我的BOM.csv --qty 10 --md 报价单.md --json 结果.json
python scripts/bom.py 我的BOM.csv --qty 10 --alternate    # 带替代候选

# ── 从意图出发（最重要的一条路）──────────────────────────────
python scripts/pick.py "找 3.3V 1A 的 LDO" --qty 100           # 自然语言直接问
python scripts/pick.py pick --family mosfet \
       --param "漏源电压>=30V" --param "连续漏极电流>=5A" --param "数量=N沟道"
python scripts/pick.py "10uF 25V 0805 电容" --sort price --limit 5
python scripts/pick.py "找 3.3V 1A 的 LDO" --qty 10 --taobao 3   # 顺带比淘宝零售价
python scripts/pick.py resolve 稳压                            # 看关键词 → 品类树
python scripts/pick.py cats                                    # 列出已知品类索引（family / catalogId / 参数键）

# ── 单点查询 ────────────────────────────────────────────────
python scripts/lcsc.py search "10k 0603 1%" --sort sales_desc --limit 10
python scripts/lcsc.py price C25804 --qty 100
python scripts/lcsc.py compare C25804 C98220 --qty 100
python scripts/lcsc.py alternate C8734 --qty 100           # 找替代（相似度+参数差异+国产替代）
```

BOM 支持 `.csv` / `.tsv` / `.xlsx` / 纯文本（一行一个型号，可带 `x2` 数量）。
Excel 导出时选「CSV UTF-8」，中文列名能自动识别（型号/Comment/Value/MPN、数量/Qty、封装/Footprint、位号/Designator）。

## 按意图找料怎么工作（pick.py）

```
一句话需求
  ├─ 品类解析   关键词 → 立创 catalogGroup → catalogIdFilter（387 = 线性稳压器(LDO)）
  │             data/categories.yaml 有就直接用，没有就动态解析
  ├─ 取候选     catalogIdFilter + 排序（sales / price）+ 翻页，默认 2 页 = 60 条
  ├─ 参数约束   **从候选自带的 paramLinkedMap 动态聚键**，再用别名表把
  │             Vout/Vdss/输出电流/耐压 映射到真实中文键（键随类目变，不硬编码）
  ├─ 过滤排序   全部约束通过 → 缺参数的直接排除（`--allow-unknown` 放行）
  │             → 按销量或价格排序，同型号多 C 号按库存去重
  └─ 可选比价   --taobao N：前 N 个型号再去淘宝/1688 查单只价
```

支持的写法（`--param`）：`输出电压=3.3V`、`输出电流>=1A`、`漏源电压>=30V`、`容值=10uF`、
`阻值=10k`、`精度<=1%`、`频率=8MHz`、`接口类型=SPI`、`数量=N沟道`；封装用 `--package 0805`。
无单位数字按品类落到对应物理量（LDO 的 `3.3V` → 输出电压，MOS 的 `30V` → 漏源电压，电容的 `25V` → 耐压）。

**参数区间筛选立创没有服务端接口，只能在客户端做**，所以 `--pages` 越大越全、但请求越多（QPS ≤ 1）。
输出里的"落选主因"会告诉你哪个约束卡掉最多（例：`3.3V→输出电压=5V ×11`），方便判断是放宽还是换参数。

## 配单流程（脚本已实现的部分标 ✅）

| 步 | 做什么 | 脚本 |
|---|---|---|
| A0 | BOM 体检：列完整性、位号、量级、型号逐字符 | ✅ `bom.py --columns`（列与行解析）+ 人工核对高风险项 |
| A1 | 型号正名：把规格描述归一成"型号 / 参数行" | ✅ `bom.py` 的 `classify()` |
| **A1'** | **还没型号时选型：意图 → 品类 → 候选** | ✅ `pick.py`（catalogGroup + 参数约束 + 排序） |
| A2 | 检索取候选 | ✅ `lcsc.py search` / `bom.py` / `pick.py` |
| A3 | 指标核对 + 降额 | ✅ `spec.py`（阻值/容值/电感/耐压/精度/功率/频率/封装） |
| A4 | 替代料 | ✅ `lcsc.py alternate`（立创 substitute 接口：相似度 + 参数差异 + 国产替代，海外站兜底）；同型号多 C 号自动换（按有货+价格） |
| A5 | 数量与备料 | ✅ `bom.py`（阻容感 0.3% 至少 +5，IC 不加） |
| A6 | 渠道分流 | ✅ `bom.py` 的 `channel_advice()` / `pick.py --taobao` |
| A7 | 下单检查 | ❌ 不下单；只给建议与链接 |
| A8 | 到货验收 | ❌ 不在范围 |

## 渠道怎么选（结论，附理由）

| 场景 | 渠道 | 理由 |
|---|---|---|
| 阻容感、二极管、LED，≤10 件 | **淘宝** | 散卖包邮；立创有最低运费与起订/整盘约束 |
| 同品类 10~100 件 | 立创 vs 淘宝 比价 | 立创正品有票可贴片；淘宝同型号常有更低价 |
| >100 件 | 立创阶梯价 / 1688 | 阶梯价与批发价差会拉开；1688 阶梯价接口拿不到，走量价要人工询盘 |
| MCU / 电源芯片 / 晶振 / 连接器 | **立创优先** | 淘宝同型号存在翻新、散新、拆机，核心件踩坑成本远高于差价 |
| 成品模块 / 开发板 | 淘宝 | 立创主要卖芯片，不做成品模块 |

实测校正（2026-11）：STM32 裸片淘宝 ¥1.02–1.45 vs 1688 ¥4.00–5.15 → **小批量淘宝更便宜**，
1688 的优势在大数量 + 对公，但它的阶梯价取不到，只能人工询盘。
淘宝比价必须把「元/包」折算成「元/只」（电阻常按 100 个/包卖）。

硬事实：立创商城与嘉立创（SMT）的**库存和价格互相独立**，商城买的料不能随 PCB 一起寄；
贴片料必须在 SMT 下单时选基础/扩展/推荐库，**扩展库按型号数收费**→ 物料归一化（合并同值同封装）直接省钱。

## 脚本

| 文件 | 作用 | 依赖 |
|---|---|---|
| `scripts/lcsc.py` | 立创检索/取价/详情/多料对比/替代料，带缓存 | 纯标准库（urllib） |
| `scripts/pick.py` | **意图 → 品类 → 候选**：按参数约束选型，可选淘宝比价 | lcsc.py + spec.py（比价时另需 taobao.py） |
| `scripts/bom.py` | BOM 解析 → 匹配 → 指标核对 → 报价单 | lcsc.py + spec.py |
| `scripts/spec.py` | 参数解析与指标比对（可单跑自测） | 纯标准库 |
| `scripts/taobao.py` | 淘宝/1688 检索（销量/价格排序、元/包→元/只归一），走真实浏览器 | Kimi WebBridge daemon |

公共约定：价格为**人民币含税单价**并按数量取阶梯；结果带抓取时间；缓存默认 6 小时
（`%LOCALAPPDATA%\bom-sourcing\cache`，`--no-cache` 关闭）。

`bom.py` 的把握列：

| 标记 | 含义 |
|---|---|
| ✔ | 型号完全命中或参数行全部核对通过 |
| ≈ | 未找到完全同型号，取最接近（必须人工确认） |
| ? | 参数行靠参数推断匹配，有未标参数 |
| ! | 出错或指标有警告 |
| ✘ | 未匹配 |

## 数据与知识

- `references/lcsc-api.md`：立创接口全部实测事实（请求体、sortNumber、facet、替代料接口、反例）
- `references/pick-intent.md`：**按意图找料**的实现细节（品类解析、参数别名表、约束语法、采样边界）
- `references/spec-check.md`：指标核对判据（测试条件、降额表、替代风险分档）与标记释义
- `references/channels.md`：渠道与采购执行细节
- `data/spec-rules.yaml`：32 个器件 family 的可机读规则（critical/relaxable 参数、默认型号库、风险备注），
  人读版见 `references/research/spec-rules.md`
- `data/categories.yaml`：品类索引（family → 中文品类名、立创 `catalogId`、真实参数键与取值样例），
  是 `pick.py` 的品类解析表；人读版见 `references/research/categories.md`
- `references/research/`：调研证据链（`BOM-配单-调研报告.md` 总报告、`lcsc-probe.md` 立创接口、
  `market-probe.md` 淘宝/1688 实测、`github-tools.md` 现成轮子、`cn-knowledge.md` 行业方法论、`spec-rules.md`）
- 探针原始响应（排序/facet/替代料/淘宝详情 JSON，约 18 MB）：`D:\WorkDesigns\3_WorkTools\Bom_Flow\probe\`

## 已验证 / 未覆盖（用前先看）

**已验证可用**
- 立创中文站搜索、阶梯价、库存、销量排序、结构化参数、商品页与 datasheet 直链（全部免登录）
- **按意图选型**：品类解析（`catalogGroup` → `catalogIdFilter`）+ 客户端参数筛选 + 排序去重
  （实测：`"找 3.3V 1A 的 LDO"` → AMS1117-3.3 / TLV75733 等；`"10uF 25V 0805 电容"` → 三星 CL21A106KAYNNNE；
  `MOS 30V 5A N 沟道` → AO3400A / AO3400 / CJ3400；约束卡掉多少条会逐条报"落选主因"）
- 替代料：`list.szlcsc.com/substitute/simple/list` 免登录直接返回相似度、参数差异、人民币阶梯价
  （`C8734` 实测 36 条，含 APM32/CH32/HK32/CKS32 等国产替代；海外站同料只有 5 条）
- BOM 解析：CSV/TSV/XLSX/纯文本，中英列名
- 指标核对：阻值/容值/电感/耐压/精度/功率/频率/封装 + MLCC/钽降额提示
- 淘宝/1688：`taobao.py`（需真浏览器 + 淘宝登录态，走 Kimi WebBridge）；销量排序按 tab 点击，
  1688 用 `sortType=va_sales360`；单只价由标题数量归一（混装包/套装会被剔除，不当作有效比价）

**未覆盖 / 需人工**
- 立创**参数区间筛选**：`queryParameterValue`+`lastParamName` 实测返回 0 条，用法未明。
  需要按参数范围选型时，改用「品类关键词 + 本地过滤 `paramLinkedMap`」（`pick.py` / `bom.py` 均此法）
- `pick.py` 只能看到**采样到的候选**（默认 2 页 60 条，立创单页上限 30）：要更全就加 `--pages`，
  但请求会变多（QPS ≤ 1）。按销量排序时"最便宜的料"可能压根没进候选
- 跨型号替代的最终裁决：`alternate` 给候选 + 参数差异，是否可用仍按 `references/spec-check.md` 的风险档人工确认
- 立创历史价格曲线、批量议价、交期承诺：接口没有
- 淘宝/1688 的阶梯价（1688 详情只给价格区间，没有 N–M 件台阶）
- 下单、支付、订单跟踪：不做

## 三个最常见的坑

1. **精确型号下排序失效**：立创对完整型号把"精准匹配组"钉在最前，`sortNumber` 几乎不改变顺序；
   要按销量/价格挑，必须用品类词（`stm32f103` 而不是 `STM32F103C8T6`）——`pick.py` 走的就是品类词。
2. **同型号多 C 号**：同一 MPN 可能有十几个 C 号（不同品牌/批次），库存差异极大；
   报价前必须按 C 号确认，不能只看型号。
3. **参数字段是卖家填的**：`paramLinkedMap` 缺项、单位不规范很常见；核对列出现 `?` 时必须回原厂手册，
   尤其是耐压、精度、测试条件。`pick.py` 对"缺该参数"的料默认排除，正是为了不把"没写"当成"满足"。
4. **筛选写错是静默失败**：多值筛选的分隔符是 `$`（`brandIdFilter: "91$842"`），用逗号会**静默返回 0 条**；
   `pageSize > 30` 同样静默返 0 条而不是报错。`lcsc.py` 已把这些参数包好，自己直接拼 body 时要注意。

另有两个环境坑：`*.lcsc.com` **不能走代理**（`lcsc.py` 已内置绕开）；淘宝结果空白多半是**登录态过期**，
不是反爬。完整清单见 `references/channels.md` §7。
