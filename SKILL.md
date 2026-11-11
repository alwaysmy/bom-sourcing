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
python scripts/pick.py "找 3.3V~21V 5A 的负载开关" --package "SOT-23-6"   # 有封装要求
python scripts/pick.py "找 3.3V 1A 的 LDO" --verify 3            # 选完主动核对（库存/价格/手册/功能）
python scripts/pick.py resolve 稳压                            # 看关键词 → 品类树
python scripts/pick.py cats                                    # 列出已知品类索引（family / catalogId / 参数键）

# ── 单点查询 ────────────────────────────────────────────────
python scripts/lcsc.py search "10k 0603 1%" --sort sales_desc --limit 10
python scripts/lcsc.py price C25804 --qty 100
python scripts/lcsc.py compare C25804 C98220 --qty 100
python scripts/lcsc.py alternate C8734 --qty 100           # 找替代（相似度+参数差异+国产替代）
python scripts/lcsc.py detail C8734 --pdf                   # 数据手册 PDF 直链
python scripts/lcsc.py detail C8734 --download ./datasheets # 下载手册（存成 C8734.pdf）
```

> **要读懂手册内容时，交给 `read-pdf` skill**（本 skill 只负责把手册链接/文件拿到手，不解析 PDF）。
> 典型链路：`detail --download` 拿 PDF → `read-pdf` 读引脚/时序/降额曲线 → 回到 `spec-check.md` 做指标裁决。
> 注意：`https://datasheet.lcsc.com/{pdfDESProductId}.pdf` 这条老直链已失效（只回跳转页），
> 用 `--pdf` 走商品页里的 `atta.szlcsc.com` 签名直链；没上传手册的料会明确报"没有 PDF"。

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
  │             参数键缺失时再试商品名里的数值（很多料只在名字里写 5.5V、1.5A）
  ├─ 功能闸门   参数满足 ≠ 功能对：商品名里的功能词再判一次（见下节）
  ├─ 过滤排序   全部约束通过 → 缺参数的直接排除（`--allow-unknown` 放行）
  │             → 按销量或价格排序，同型号多 C 号按库存去重
  └─ 可选比价   --taobao N：前 N 个型号再去淘宝/1688 查单只价
```

支持的写法（`--param`）：`输出电压=3.3V`、`输出电流>=1A`、`漏源电压>=30V`、`容值=10uF`、
`阻值=10k`、`精度<=1%`、`频率=8MHz`、`接口类型=SPI`、`数量=N沟道`；封装用 `--package 0805`。
无单位数字按品类落到对应物理量（LDO 的 `3.3V` → 输出电压，MOS 的 `30V` → 漏源电压，电容的 `25V` → 耐压）。
**区间需求**：负载开关这类"工作电压"是区间量，写 `3.3V~21V` 表示候选区间必须覆盖这两头。

**参数区间筛选立创没有服务端接口，只能在客户端做**，所以 `--pages` 越大越全、但请求越多（QPS ≤ 1）。
输出里的"落选主因"会告诉你哪个约束卡掉最多（例：`3.3V→输出电压=5V ×11`），方便判断是放宽还是换参数。

## 封装（展示、筛选、回退）

封装直接影响能不能贴、占多大面积，**必须展示**。`pick.py` 的封装列带面积（`0805 2.5mm²`、
`LQFP-48(7x7) 49mm²`），没有尺寸代号的封装（`SOP-8-208mil`）只显示名字、面积留空。

三种情况：

| 用户说了什么 | 行为 |
|---|---|
| **没提封装** | 不筛，**全部列出**，并给「封装分布」一行（`SOT-223×4  SOT-89×3  SOT-23-5×1 …`），让用户按面积/体积自己取舍 |
| **提了封装且能满足** | 硬筛，只留匹配的（命中即不再列回退，避免噪音） |
| **提了封装但一条都不满足** | 主表为空 → **回退段**「封装回退候选（需求 X；其余约束全部满足，仅封装不同）」，逐条给实际封装 + 差异（面积倍数 / 引脚数变化）+ 价格库存 |

回退段的取舍口径（写进输出，不能只丢数据）：

- 面积**更小** → 焊盘、散热、爬电距离要复核；
- 面积**更大** → 看板上空间与钢网；
- **引脚数不同** → 必须改 PCB，不是"替代"；
- 封装不符的料**不能直接替代**，一律人工确认。

参数：`--pkg-fallback N`（回退条数，默认 3，`0` 关闭）、`--no-pkg-fallback`（完全硬筛）。

## 主动核对（选完不等于能用）

`--verify N` 把选出来的前 N 条**回立创实时复核**（不吃缓存），逐条给结论：

| 核对项 | 怎么核 | 不过关的含义 |
|---|---|---|
| 库存复核 | 重新取一次，与扫描时比对（`8,106` / `（+120）`） | 0 = 不可下单；少于采购量 = 需分批或换料 |
| 价格复核 | 按数量重算阶梯价 | 变动说明快照过期，报价要重出 |
| 生命周期 | 商品名/在售状态（"停售""停产"字样） | 停产 = 不可用，转 `alternate` |
| 手册可得 | `datasheet_pdf()` 取签名直链 | 没手册 = 规格无法核对，需原厂确认 |
| 功能符合 | `function_check()` 正/反向词 | `mismatch`=不可用；`conflict`/`unknown`=需人工 |
| 结论 | 上述合并 | 可下单 / 需人工确认 / 不可用（附原因） |

**仍需人工的一步**：手册里的绝对最大额定值、封装焊盘图、EOL/PCN 公告 —— 这些接口没有，
`--verify` 只做到"接口能核的都核了"。要把手册内容也核掉，走
`detail --download` → `read-pdf` skill → 回 `spec-check.md` 裁决。

## 功能符合性（参数满足 ≠ 功能对）

立创的品类归类很粗：`功率电子开关(969)` 里同时挂着**负载开关 / eFuse / 过压保护开关 / 同步降压转换器 /
理想二极管 ORing**，`productType` 是 catalog 级标签、零区分力。只按「工作电压 + 最大连续电流」筛，
会把 `MP4316GRE-Z`（45V/6A **同步降压转换器**）当成 5A 负载开关推出去。

所以 `pick.py` 默认在参数通过后再做一次功能闸门，四态：

| 判定 | 依据 | 处理 |
|---|---|---|
| `ok` | 商品名命中正向功能词，且无反向词 | 正常输出 |
| `mismatch` | 只命中反向词（如"降压转换器"） | **直接剔除**，并写进落选主因 |
| `conflict` | 正反都命中（如"集成TVS的…过压保护开关"） | 保留 + 打警告，人工确认 |
| `unknown` | 商品名只有型号/纯参数，没功能描述 | 保留 + 提示必须查手册（`--pdf`）或原厂页面 |

关键：**「正向没命中」不等于「功能不符」**——很多料（如 `HS2950P.M`）商品名只有型号。
这类必须降级到数据手册第一段或原厂/分销商描述（`distributor.py search "<型号>"`）才能定论。
正向/反向词表在 `data/categories.yaml` 每个 family 的 `function_keywords` / `exclude_keywords`，
`--no-func` 可关闭该闸门（不建议）。

## 黑名单 / 白名单（谁不买）

选型不只要"满足参数"，还要"能买"。有些品牌/店铺/料号是**已知的坑**（批次一致性差、拆机翻新、被客户点名拉黑），
这些不该每次靠人记。名单落在 `data/knowledge/blacklist.yaml`，三组：`brands` / `shops` / `codes`。

```bash
python scripts/blacklist.py list                              # 看名单（品牌/店铺/料号）
python scripts/blacklist.py check "Tokmas(托克马斯)"            # 查一个名字（子串别名，大小写无关）
python scripts/blacklist.py import entries.yaml --kind shop --authorized "傅师傅 2026-11-06"
python scripts/blacklist.py remove "Tokmas(托克马斯)" --kind brand --authorized "傅师傅 2026-11-06"
```

> **写入门禁（硬规则）**
> 黑名单是**采购策略事实**，不是演示数据。只有**用户明确授权**的条目才能进名单：
> 所有写操作（`import` / `add` / `remove`）必须带 `--authorized "<谁 / 什么时候 / 为什么>"`，
> 缺这个参数直接拒绝执行；授权说明会写进条目的 `authorized` 字段，作为审计依据。
>
> **不要手工编辑 `data/knowledge/blacklist.yaml`**。走 `blacklist.py import` —— 它负责校验 schema、
> 去重、补 `added` / `source` / `authorized` 字段；手工改文件会丢审计信息，也无法复现。
> 单测或演示只用虚构名字（如 `示例电子商行`），**绝不拿真实店铺/品牌试**。

匹配口径：**归一化后按别名子串命中**（`Tokmas(托克马斯)` 归一成 `tokmas托克马斯`，`tokmas`、`托克马斯` 都算命中），
不做模糊纠错（`Tokma` 不命中 `Tokmas`）—— 宁可漏杀，不可误杀。

接入位置（都是默认开）：

| 入口 | 行为 |
|---|---|
| `pick.py` | 排序前剔除，输出 `黑名单已剔除 N 条：型号（品牌｜原因）`；`--no-blacklist` 本次放行 |
| `bom.py` | 逐行匹配后剔除，报价单出「## 黑名单剔除」段 |
| `taobao.py` | 每条结果带 `shop_blacklisted`，命中店铺名打 `⛔` 并单列原因 |
| `pick.py --taobao` | 比价前先排除黑名单店铺，**不让"最便宜"落在被拉黑的店** |

**店铺名**（淘宝 `it.shop.name` / 1688 `it.company`）本来就抓得到，所以淘宝侧可以按店做黑名单：
店名常带"全场包邮""电子元件 专用"等营销后缀，所以只能子串匹配、不能整串相等。
白名单目前是"未拉黑即放行"的语义；需要指定优先店铺时，在 `blacklist.yaml` 里另建 `shops` 之外的分组（脚本不硬编码）。

## 品牌索引（这个牌子是什么 / 值不值得用）

遇到不认识的品牌（如 `Tokmas(托克马斯)`），不要靠猜——查索引：

```bash
python scripts/brands.py lookup tokmas     # 按名字/中文名/别名/品牌号查
python scripts/brands.py coverage         # 覆盖率体检（索引 vs vendors.yaml）
python scripts/brands.py list --family mosfet   # 某品类有哪些品牌
python scripts/brands.py build            # 重建索引（扫 26 个品类的品牌 facet，约 40 秒）
```

`data/knowledge/brands.index.yaml` 是**立创在售品牌全集**（1,296 个品牌，按品类枚举品牌 facet 得到），
字段 `name / short / cn / aliases / families / part_count / in_vendors`。

**与 `vendors.yaml` 的分工**（重要）：

| 文件 | 是什么 | 谁维护 |
|---|---|---|
| `brands.index.yaml` | **全集**：谁在售、卖在哪些品类、多少条料 | `brands.py build` 自动重建 |
| `vendors.yaml` | **有证据的子集**：tier / 价差 / 风险备注 | 人工 + 实测，144 个品牌 |

两者用 brand_id 关联；查不到 tier 时回落 `unknown`（按"不可信"处理，不给推荐加权）。

> **为什么要有索引**：`vendors.yaml` 早期是**关键词驱动采样**建的（用 "稳压""电阻" 去搜再收品牌），
> 只卖冷门料的品牌（如只卖 ULN2803 的 Tokmas）**永远进不了采样集合**。
> 实测覆盖率只有 22.3%（3,538 次品牌出现里 2,748 次未收录）。
> 索引改为**按品类全量枚举**后，Tokmas 这类品牌才查得到（brand_id 12489，12 个品类，322 条料）。

## 品牌背调（这个牌子能不能用、能不能追溯）

**索引只回答"这个牌子在不在售"，回答不了"能不能用"。** 判断品牌可信度必须**上网查资料**：

```bash
cd scripts
python brand_dossier.py new 12489 --name "Tokmas(托克马斯)" --alias 托克马斯 --authorized "<谁/何时/为什么>"
python brand_dossier.py add 12489 --channel trademark --url "https://..." \
    --claim "商标 18357895 归属广州托克马斯电子有限公司" --grade fact --confidence high --authorized "..."
python brand_dossier.py add 12489 --channel agent_site --url "https://..." \
    --claim "宣称 1995 年成立、年销售额 6 亿美元，多站同文" --grade claim --confidence low --authorized "..."
python brand_dossier.py tier 12489 --authorized "..."      # 按证据算建议分层
python brand_dossier.py render 12489                        # 出证据链报告
```

**取证渠道**（按可信度排序，详见 `references/brand-due-diligence.md`）：品牌官网 · 官方文档/认证 ·
商标公告 · 工商登记 · 授权代理公告 · IC 资料站 · 立创品牌页 · 分销商页 · 社区口碑 · 代理商自述 · 推论。

**三级标注是硬约束**（`CLAIM_ONLY` 渠道写 `--grade fact` 直接报错）：

| 等级 | 含义 | 例 |
|---|---|---|
| `fact` | 可点开链接复核 | 商标注册号 18357895 归属该主体 |
| `claim` | 对方自述，无第三方佐证 | 「1995 年成立、年销售额超 6 亿美元」 |
| `inference` | 由事实推出 | 「自述流片封装均代工 + 有授权代理 → fabless」 |

> **inference 不得单独作为「可用」判据**，只能作进一步查证的方向；结论靠 inference 撑着时必须写进 `gaps`。

**分层判定**（只认 fact 级证据）：自有产线证据 → `original_idm`；自有品牌 + 代工/授权代理 →
`original_fabless`；只有品牌资料无产线 → `domestic_second`；只有目录/分销页 → `trader`；
什么都没有 → `unknown`。人工可覆盖，但 `--tier` 必须配 `--reason`。

> **写操作门禁**：`new / add / meta / gaps / conclusion / tier` 全部要求
> `--authorized "<谁/什么时候/为什么>"`——品牌结论属知识库写操作，只有用户明确指定的核查才能落库
> （与 `blacklist.py` 同一套纪律）。

档案落 `data/knowledge/brands.dossier/<brand_id>-<slug>.yaml`，`vendors.yaml` 条目的
`dossier` 字段指回档案；样例：`data/knowledge/brands.dossier/12489-tokmas.yaml`
（Tokmas：8 条证据 = 5 事实 + 2 自述 + 1 推论，5 条 gaps，tier=original_fabless）。

## 品牌白名单（品牌 × 品类放行 —— 不是品牌整体放行）

**背调通过 ≠ 这个牌子的所有料都能用。** 同一品牌下不同品类的实际生产方、产线、质量体系都可能不同
（贴牌/代理尤其如此），所以白名单的粒度是 **「品牌 + 物料类别」这一对**：

> **规则（用户 m03469）**：每次引入新品牌，或者已有品牌进入**非同类物料**，都必须先做背调或知识库核对；
> 引入的品牌存进白名单。没核过的品牌不能当结论。

```bash
cd scripts
python whitelist.py check "Tokmas(托克马斯)" --family connector   # ✅ 已背调
python whitelist.py check "Tokmas(托克马斯)" --family bjt         # ⏳ 待背调（只见过 ULN2803 贴牌）
python whitelist.py approve "Tokmas(托克马斯)" --family connector --label 连接器/排针 \
    --basis "圣禾堂 2026-08-18 官方授权代理公告" --grade fact --authorized "傅师傅 2026-11-06 允许放行"
python whitelist.py list                                           # 看全量
```

**五态判定**（`check()` 的 `status`）：

| 状态 | 含义 | 能不能推荐 |
|---|---|---|
| `approved` | 该品牌在本品类已背调通过 | ✅ 可以 |
| `kb_known` | 白名单没有，但 `vendors.yaml` 有分层（知识库核对过），**本品类未单独背调** | 可以，但要说明"本品类未单独背调" |
| `pending` | 本品类已登记待背调（见过料号但证据不足） | ❌ 不能当结论 |
| `approved_other_family` | 品牌在别的品类通过了，本品类没核过 | ❌ 需补该品类证据 |
| `unknown` | 白名单和知识库都没有 | ❌ 必须先背调 |

接入位置（默认开，`--no-whitelist` 关闭）：

| 入口 | 行为 |
|---|---|
| `pick.py` | 输出「## 品牌白名单核对」段：已背调 / 知识库已知 / 需先背调 N 个品牌（带 C 号样例与处置命令）；`--strict-brand` 只保留已背调+知识库已知 |
| `bom.py` | 报价单出同款段落，逐行按 `_family()` 判品类，**同一品牌在不同行可能是不同状态** |

写操作同样要 `--authorized`（与 `blacklist.py` / `brand_dossier.py` 一套门禁）。
档案落 `data/knowledge/whitelist.yaml`；方法论见 `references/brand-whitelist.md`。

### 三种「不必逐品类核」的例外

| 例外 | 命令 | 适用 |
|---|---|---|
| **免背调**（公认大厂） | `python whitelist.py preclear "TOSHIBA(东芝)" "Wurth(伍尔特)" --basis "<为什么>" --authorized "..."` | 业界公认原厂/IDM，多年在售、主流渠道常备、知识库已有分层；产品线覆盖全线，不存在需逐次核实的代工关系。写 `grade: common_knowledge` + `precleared: true` |
| **判不推荐**（停业/假冒） | `python whitelist.py reject "NTE Electronics" --reason "2024 年停业 + 重铸贴牌" --authorized "..."` | 品牌整体判死，**优先于品类**；`pick.py` / `bom.py` 会显示 🚫 而不是静默推荐 |
| **品牌归并**（立创拆成两条） | `python brands.py apply-aliases` | 立创同一家公司拆成多个 brand_id（如 `ADI(亚德诺)` 与 `ADI(亚德诺)/MAXIM(美信)`）；登记表 `data/knowledge/brand-aliases.yaml` 的 `merges` / `ambiguous` 由**人工复核**后写，脚本只负责应用 |

免背调的判据是「**不确定就老老实实背调**」—— 免背调是省时间，不是省证据。

### 从哪开始背调：品牌队列

1,296 个品牌不可能一次背完，`brand_queue.py` 按「**料号数量 × 品类广度 × 采购频次**」排优先级：

```bash
cd scripts
python brand_queue.py --limit 20            # 待背调队列（按分数降序）
python brand_queue.py --pending           # 只看还没背调的
python brand_queue.py --family mosfet     # 按品类过滤
```

分数口径：`2.0*log10(料号数+1) + 0.4*品类数 + 1.5*常用品类命中数 + 6.0*已登记待背调 - 3.0*已覆盖 - 1.0*知识库已有分层`。
「常用品类」= 电阻/电容/电感/磁珠/LED/二极管/肖特基/TVS/ESD/MOSFET/BJT/LDO/DC-DC/MCU/晶振/连接器/EEPROM/Flash 这 18 类，作为采购频次的代理。
状态里 `🏅 免背调` / `🚫 不推荐` / `✅ 已全部背调` 都算已处理，不会再占队列；`merge_into` 的重复条目直接跳过。

**一批的做法**：`brand_queue.py --limit 8` → 逐个 `web_search` 取证（工商/官网/授权代理/商标/社区）→
`brand_dossier.py new/add/gaps/conclusion/render` 建档案 → `whitelist.py approve` 放行 →
`brand_dossier.py list` + `whitelist.py list` 复核 → 提交。IDM 原厂（自有晶圆/封测产线）
用 `family="*"` 全线放行；非 IDM 必须逐个品类核。

## 判据边界（立创给不了什么 —— 以 MOSFET 为例）

立创的 `paramLinkedMap` **只对少部分器件有完整参数**。实测场效应管品类（`catalogIdFilter=381`）
330 条去重记录，**只有 4 个键覆盖 100%**：

| 键 | 覆盖 | 解析注意 |
|---|---|---|
| `漏源电压(Vdss)` | 100% | 1 条 `1.5kV` 需处理 |
| `连续漏极电流(Id)` | 100% | 21 条 `mA`（需换算）；`32A；17A` 双值取大 |
| `导通电阻(RDS(on))` | 100% | **100% 带 `@Vgs` 条件**（@10V 72% / @4.5V 20% / @2.5V 5%），跨条件直接比是错的 |
| `数量` | 99% | 实为沟道类型（`1个N沟道` / `1个P沟道`） |

加上封装（99.4% 非空但有 **49 种写法**，须归一）+ 价格库存 → **只有 6 项能全自动判定**。

**以下全部 0% 覆盖，必须查手册**（`lcsc.py detail <C号> --pdf` 取 atta 签名直链，再交 `read-pdf`）：

> `Qg` `Qgs` `Qgd` `Ciss` `Coss` `Crss` `Qrr` `trr` `Vgs(max)` `Rθja` `Rθjc` `Tjmax`
> `EAS`（雪崩能量） `SOA`（安全工作区） `工艺类型`（平面/沟槽/SGT/超结） `AEC-Q101` 状态 `EOL`

**结论口径（重要）**：

- 自动判定只能覆盖"电气初筛"，**不能给"通过"结论**；
- 抗冲击（EAS / SOA）、工艺类型、线性 vs 开关、缓启动 —— 这些**必须落到手册 + 人工确认**；
- 输出里对 C/D 级判据只能写"待确认"，不能写"满足"。

**判据已入库**：`data/knowledge/mosfet.yaml`（机读，6 条 critical + 16 条 datasheet_only +
9 类应用语义 + EAS/SOA 校核式 + 工艺反推 8 条规则），人读版 `references/mosfet-rules.md`。

**EAS / SOA / 工艺** 三条最容易踩的：

- **EAS**：`E_AS = ½·L·i_AS(0)²·V_DS,peak/(V_DS,peak−V_DD)`，余量 2.0×；VDD 是否在雪崩中断开会差 20%；
  缺 EAS 额定值 → 只能 `NEED_DATASHEET`。
- **SOA**：**必须查手册**。①SOA 是实测曲线不是算出来的；②线性区低于 ZTC 点时 `∂I_D/∂T > 0` 是正反馈，
  "平均结温 < Tjmax 所以安全"物理上就是错的（Spirito 2005 判据）；③SOA 前提是单元一致性 + 焊层完整 +
  热阻均匀，立创一条字段都反映不了。
- **工艺类型**：手册首页（Planar/Trench/SGT/Superjunction）= **fact**；型号家族名 / 命名规律 /
  Vdss 与 RDS 横向对比 = **inference**。应用是线性/缓启动/热插拔时，只有 inference 的必须写
  「疑似 X，需查手册确认」。

**已知接口限制**：参数区间**无服务端筛选**；关键词里的数字是**精确等于**不是 `≥`
（`N沟道 30V 5A` 只返 Vdss=30 且 Id=5，5.7A 的料反而不出现）；
`totalCount` 有 **1500 硬上限**；`spotFilter=0` 静默返 0 条。

## 反向电流阻断（防倒灌）—— 说了就筛，没说只标

立创对「功率电子开关(969)」只给 `类型/工作电压/通道数/输入控制逻辑/最大连续电流/导通电阻` 六个键，
**没有「反向电流阻断」这个字段**，只能查手册后登记进 `data/knowledge/load-switch.yaml`。

```bash
cd scripts
python loadswitch.py check C47345802        # ❌ 不阻断（手册 Rev1.5 §OTG：反向经体二极管导通）
python loadswitch.py check C3662799         # ✅ 有阻断（TI TPS25947 True Reverse Current Blocking）
python loadswitch.py classes                # 各类器件默认能力（单管/背对背/eFuse/OVP/理想二极管…）
python pick.py "找 3.3V~21V 5A 防倒灌的负载开关"   # 句子里有"防倒灌" → 筛选（只认 fact 级）
python pick.py "找 3.3V~21V 5A 的负载开关"         # 没说 → 只标注一列，不淘汰
```

| 用户怎么说 | 行为 |
|---|---|
| 提到 防倒灌 / 防反灌 / 反向电流阻断 / 不许倒流 / ORing / 理想二极管，或用 `--require-reverse-block` | **筛选**：只留 `reverse_block=yes` 且 `grade=fact`；其余进「反向电流阻断筛选」段并给原因 |
| 没提，但品类是功率电子开关 | **只标注**：多一列 ✅有 / ❌无 / ❔未核，不据此淘汰；`--no-reverse-block` 可把要求降级为标注 |

**理想二极管也要单独核**：名字不等于参数表结论 —— 控制器+外部单管的阻断靠快速关断（`t_rev` 窗口内倒流），
只有外部双管才硬阻断；带 reverse polarity protection 的型号边界也不同。`loadswitch.py infer` 只给类别提示。

判据与实例见 `references/load-switch-rules.md`；登记写操作需 `--authorized`（与黑名单/白名单同一套门禁）。

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
| **A5'** | **主动核对：库存/价格/生命周期/手册/功能回查** | ✅ `pick.py --verify N` |
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

**淘宝比价的三条口径**（`taobao.py` / `pick.py --taobao` 已实现）：

| 情况 | 处理 |
|---|---|
| 标题没写一包多少只 | 单只价只是按 1 只的假设 → 标 **不可比**，不许直接跟立创比 |
| 开发板 / 成品模块 / 混装包 / 系列链接 | 价格不能折算单只价 → 默认剔除（`taobao.py --all` 才显示） |
| 成色（拆机 / 散新 / 翻新 / 国产替代 / 原装自述） | **默认只标注**（拆机件打样/维修可用）；句子里出现「量产 / 车规 / 高可靠 / 不要拆机」或 `--production` → 翻新/拆机/散新从比价里剔除 |

- 「原装正品」是**卖家自述**，不是证据；淘宝单价 < 立创 40% 时额外标「价差异常（可能非全新原厂）」。
- 实测：`STM32F103C8T6` 标题「全新原装」¥1.02–1.84 vs 立创 ¥9.12（5–9×），不可能是全新原厂。
- 详见 `references/channels.md` §5.1。

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
| `scripts/distributor.py` | 海外分销商检索：Mouser 中国 / DigiKey 中国（型号、库存、含税人民币价） | Kimi WebBridge daemon（两站都拦纯 HTTP） |
| `scripts/origin.py` | **原厂官方商城**检索：19 家注册（3PEAK/TI/MPS/士兰微/兆易/圣邦微…），拿原厂价与库存基线 | 纯标准库（TI 取库存需 `--browser`） |
| `scripts/blacklist.py` | 品牌/店铺/料号黑名单（选型与比价的硬闸门） | 纯标准库 + pyyaml |
| `scripts/brands.py` | **品牌索引**：按品类枚举立创品牌 facet（1,296 品牌），查品牌/覆盖率体检 | 纯标准库 + pyyaml |
| `scripts/brand_dossier.py` | **品牌背调档案**：多渠道取证 + 事实/自述/推论三级标注 + 分层判定 + 出报告 | 纯标准库 + pyyaml |
| `scripts/whitelist.py` | **品牌白名单**：按「品牌 × 品类」放行（approved/kb_known/pending/跨品类/unknown），写操作需授权 | 纯标准库 + pyyaml |
| `scripts/brand_queue.py` | **品牌背调队列**：按料号数 × 品类广度 × 采购频次排优先级，回答"下一步该背谁" | 纯标准库 + pyyaml |
| `scripts/loadswitch.py` | **功率开关功能判据**：反向电流阻断（防倒灌）/ 理想二极管能力查询与登记，写操作需授权 | 纯标准库 + pyyaml |

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

- `references/lcsc-api.md`：立创接口全部实测事实（请求体、sortNumber、facet、替代料接口、反爬处置、反例）
- `references/pick-intent.md`：**按意图找料**的实现细节（品类解析、参数别名表、约束语法、采样边界）
- `references/spec-check.md`：指标核对判据（测试条件、降额表、替代风险分档）与标记释义
- `references/channels.md`：渠道与采购执行细节
- `references/methodology.md`：**配单方法论**（D0–D9 十步决策链，每步的输入/动作/判据/常见错误）
- `references/vendors.md`：**厂商可信度**（tier 分层、维护流程、复核周期、降级条件），机读版 `data/knowledge/vendors.yaml`
- `references/brand-whitelist.md`：**品牌白名单规则**（为什么是「品牌 × 品类」、五态判定、引入新品牌/跨品类复核流程、写入门禁）
- `references/brand-due-diligence.md`：**品牌背调方法论**（为什么不能只靠料号反推、11 个取证渠道、
  事实/自述/推论三级标注、分层判定规则、操作手册、落地到采购动作）
- `references/mosfet-rules.md`：**MOSFET 判据速查**（立创能判/不能判、EAS 与 SOA 校核式、
  工艺反推的 fact/inference 分级、9 类应用语义、已修缺陷），机读版 `data/knowledge/mosfet.yaml`
- `references/load-switch-rules.md`：**功率开关功能判据**（反向电流阻断/防倒灌/理想二极管：为什么立创查不到、
  七类器件默认能力、理想二极管的三层差异、「说了就筛、没说只标」语义、已登记实例、已知边界），
  机读版 `data/knowledge/load-switch.yaml`（`loadswitch.py` 维护）
- `data/spec-rules.yaml`：32 个器件 family 的可机读规则（critical/relaxable 参数、默认型号库、风险备注），
  人读版见 `references/research/spec-rules.md`
- `data/categories.yaml`：品类索引（26 个 family → 中文品类名、立创 `catalogId`、真实参数键与取值样例、
  功能正/反向词），是 `pick.py` 的品类解析表；人读版见 `references/research/categories.md`
- `data/knowledge/`：`channels.yaml`（渠道选择规则）、`risk-checklist.yaml`（风险硬门）、
  `industry-norms.yaml`（降额与隐性应力）、`workflow.yaml`（D0–D9 机读版）、`vendors.yaml`（145 品牌 tier）、
  `blacklist.yaml`（品牌/店铺/料号黑名单，`blacklist.py` 维护）、`brands.index.yaml`（**1,296 品牌全集**，
  `brands.py build` 自动重建，与 `vendors.yaml` 用 brand_id 关联）、`mosfet.yaml`（MOSFET 判据库）、
  `brands.dossier/`（**品牌背调档案**，每条证据带渠道/链接/等级/把握，`brand_dossier.py` 维护）、`whitelist.yaml`（品牌 × 品类放行表，`whitelist.py` 维护）、
  `load-switch.yaml`（**功率开关功能判据**：反向电流阻断等立创没有的字段，`loadswitch.py` 维护）
- `references/research/`：调研证据链（`BOM-配单-调研报告.md` 总报告、`lcsc-probe.md` 立创接口、
  `market-probe.md` 淘宝/1688 实测、`taobao-pick.md` 淘宝比价实测、`github-tools.md` 现成轮子、
  `cn-knowledge.md` 行业方法论、`spec-rules.md`、`categories.md`、`methodology-survey.md`、`vendors.md`）
- `references/examples/load-switch-3v3-21v-5a.md`：完整选型样例（3.3V 起 / ≥21V / ≥5A 负载开关），
  含短名单、功能符合性核对、渠道比价、排除项与风险——照着它写自己的选型结论
- 探针原始响应（排序/facet/替代料/淘宝详情/PDF 等 JSON，约 20 MB）：`D:\WorkDesigns\3_WorkTools\Bom_Flow\probe\`

## 已验证 / 未覆盖（用前先看）

**已验证可用**
- 立创中文站搜索、阶梯价、库存、销量排序、结构化参数、商品页与 datasheet 直链（全部免登录）
- **反向电流阻断（防倒灌）**：`loadswitch.py` 知识库 + `pick.py` 门禁（说"防倒灌"就筛选、没说只标注）；
  实测 LP5280SHVF 判 ❌（手册 §OTG：反向经体二极管导通）、TPS259470/472 判 ✅（TI True Reverse Current Blocking）
- **按意图选型**：品类解析（`catalogGroup` → `catalogIdFilter`）+ 客户端参数筛选 + 排序去重
  （实测：`"找 3.3V 1A 的 LDO"` → AMS1117-3.3 / TLV75733 等；`"10uF 25V 0805 电容"` → 三星 CL21A106KAYNNNE；
  `MOS 30V 5A N 沟道` → AO3400A / AO3400 / CJ3400；约束卡掉多少条会逐条报"落选主因"）
- 替代料：`list.szlcsc.com/substitute/simple/list` 免登录直接返回相似度、参数差异、人民币阶梯价
  （`C8734` 实测 36 条，含 APM32/CH32/HK32/CKS32 等国产替代；海外站同料只有 5 条）
- BOM 解析：CSV/TSV/XLSX/纯文本，中英列名
- **黑名单**：品牌（`Tokmas(托克马斯)` 实测剔除 `C53133678 ULN2803CDW(TOKMAS)` 并给替代 `C7494313`）、
  店铺（淘宝店铺名带"全场包邮"等营销后缀时子串命中）、料号三组，pick/bom/taobao 默认生效
- **品牌白名单**：按「品牌 × 品类」五态判定（`approved` / `kb_known` / `pending` /
  `approved_other_family` / `unknown`），实测 `Tokmas` 在连接器上 `approved`、在 BJT 上 `pending`
  （同一品牌不同品类给不同结论）；`pick.py` / `bom.py` 默认输出「品牌白名单核对」段，`--strict-brand` 只留已核过的
- **淘宝店名**：`taobao.py search` 结果带店铺列（可直接做店铺黑白名单）
- 指标核对：阻值/容值/电感/耐压/精度/功率/频率/封装 + MLCC/钽降额提示
- 淘宝/1688：`taobao.py`（需真浏览器 + 淘宝登录态，走 Kimi WebBridge）；销量排序按 tab 点击，
  1688 用 `sortType=va_sales360`；单只价由标题数量归一（混装包/套装会被剔除，不当作有效比价）
- 海外分销商：`distributor.py` 读 Mouser 中国 / DigiKey 中国（`--site mouser|digikey|both`），
  返回型号、库存、**含税人民币**阶梯价。两站纯 HTTP 均被拦（DigiKey 403 Akamai、Mouser 403 DataDome），
  必须走真浏览器；实测同一颗 TPS259472ARPWR：立创 ¥3.38@1000 vs Mouser ¥11.38@25 vs DigiKey ¥17.43@1
- **功能符合性闸门**：`spec.function_check()` + `data/categories.yaml` 的正/反向功能词（25+1 个 family，
  129 正向词 / 238 反向词）；实测挡掉 `MP4316GRE-Z`（同步降压转换器冒充负载开关），
  对 `LP5280SHVF`（集成 TVS 的过压保护开关）判 ok、对 `HS2950P.M`（商品名只有型号）判 unknown 并提示查手册
- **封装展示与回退**：封装列带面积（`0805 2.5mm²`）；没提封装给分布，提了封装但满足不了给「封装回退候选」
  并说明面积倍数/引脚数差异（实测：`--package 1206` 对 LDO 无匹配 → 回退列出 SOT-89 / WSON-6 并标 `面积 0.78×`）
- **主动核对**：`pick.py --verify N` 回立创实时复核库存/价格/生命周期/手册/功能，给「可下单 / 需人工确认 / 不可用」
- **数据手册**：`lcsc.py detail <C> --pdf --download <目录>` 取 `atta.szlcsc.com` 签名直链并下载
  （旧 `datasheet.lcsc.com/{id}.pdf` 已失效）；没上传手册的料会明确报"没有 PDF"
- 反爬处置：203/EdgeOne 挑战会被识别成 `AntiBotError` 并给处置建议；`lcsc.py cookie` 可用真实浏览器取 cookie

**未覆盖 / 需人工**
- 立创**参数区间筛选**：`queryParameterValue`+`lastParamName` 实测返回 0 条，用法未明。
  需要按参数范围选型时，改用「品类关键词 + 本地过滤 `paramLinkedMap`」（`pick.py` / `bom.py` 均此法）
- `pick.py` 只能看到**采样到的候选**（默认 2 页 60 条，立创单页上限 30）：要更全就加 `--pages`，
  但请求会变多（QPS ≤ 1）。按销量排序时"最便宜的料"可能压根没进候选
- 跨型号替代的最终裁决：`alternate` 给候选 + 参数差异，是否可用仍按 `references/spec-check.md` 的风险档人工确认
- 立创历史价格曲线、批量议价、交期承诺：接口没有
- 淘宝/1688 的阶梯价（1688 详情只给价格区间，没有 N–M 件台阶）
- **原厂官方商城**（TI / MPS / 3PEAK / 圣邦微 等直营店）：索引中，未完成前按"需登录/需人工"处理
- 立创接口**没有 SLA**：请求过密会被 EdgeOne 拦成 203，只能退避重试或取 cookie
- 海外站只做**检索比价**：含增值税、无人民币议价、交期按官网；DigiKey 搜索会先落到"品类卡片页"再点进品类
  （`distributor.py` 已自动处理），任意型号不保证命中
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
5. **参数满足 ≠ 功能对**：立创 `功率电子开关(969)` 里混着负载开关、eFuse、过压保护开关、
   **同步降压转换器**。只按参数筛会把 `MP4316GRE-Z`（降压转换器）当 5A 负载开关。`pick.py` 默认开功能闸门；
   `bom.py`/手工检索时自己用 `spec.function_check()` 核一遍商品名。

另有两个环境坑：`*.lcsc.com` **不能走代理**（`lcsc.py` 已内置绕开）；淘宝结果空白多半是**登录态过期**，
不是反爬。完整清单见 `references/channels.md` §7。

**反爬（HTTP 203 / EdgeOne 挑战）**：立创会对脚本流量返回 203 + `tws2_` 挑战页，`lcsc.py` 会直接报
「触发了反爬」并给处置建议，不会抛 `JSONDecodeError`。按代价从低到高：① `--rate 2`（甚至 3）重试、
等 3~10 分钟；② `python lcsc.py cookie` 用真实浏览器取一次 cookie 存盘（之后自动带上）；
③ 换网络。**不要短时间高频重试**，只会延长封禁。
