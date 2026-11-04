# 配单 / BOM 采购：调研与实现报告

> 目的：给「按 BOM 配单、比价、比较指标、按量选渠道」这件事找到可行路径，并把可复用的部分做成 skill。
> 时间：2026-11-04。价格均为当日快照。

## 0. 一句话结论

**能做，而且不用造轮子。** 立创中文站有一个免登录的 JSON 检索接口（唯一暴露「销量」的入口），
淘宝/1688/京东没有可用的免费接口（只能靠带登录态的真浏览器），
中间那层「BOM 行 / 一句话需求 → 候选料 → 指标核对 → 阶梯价落档 → 渠道建议」才是必须自建的部分，
目前已实现并端到端跑通（16 行示例 BOM ¥28.84 + 5 组按意图找料）。

## 1. 交付物

| 位置 | 内容 |
|---|---|
| `C:\Users\dell\.agents\skills\bom-sourcing\` | 可触发 skill：`SKILL.md` + `scripts/` + `references/` |
| `scripts\lcsc.py` | 立创检索/取价/详情/对比/替代料，纯标准库、带缓存（约 800 行） |
| `scripts\bom.py` | BOM 解析 → 匹配 → 指标核对 → 报价单（Markdown/JSON） |
| `scripts\pick.py` | 按意图找料：一句话需求 → 品类 → 候选 → 指标过滤 → 排序（约 750 行） |
| `scripts\taobao.py` | 淘宝/1688 检索（走 Kimi WebBridge 登录态浏览器），元/包归一、混装包与区间价识别 |
| `scripts\spec.py` | 参数解析与指标比对，可单跑自测 |
| `data\categories.yaml` | 25 个 family 的品类 id、关键词、参数键与关键约束 |
| `references\lcsc-api.md` | 立创接口全部实测事实（含反例） |
| `references\spec-check.md` | 指标核对判据与替代风险分档 |
| `references\pick-intent.md` | 按意图找料的实现说明（品类解析、别名映射、比较语义） |
| `references\channels.md` | 渠道选择、采购执行、环境坑 |
| `research\spec-rules.yaml` | 32 个器件 family 的 critical/relaxable 参数、默认型号库、风险备注（2267 行） |
| `research\{github-tools,lcsc-probe,market-probe,cn-knowledge,spec-rules}.md` | 四路调研原始报告 |

## 2. 数据来源矩阵（实测）

| 来源 | 免登录 | 有销量 | 有阶梯价 | 结构化参数 | 替代料 | 结论 |
|---|---|---|---|---|---|---|
| `POST so.szlcsc.com/query/product`（中文站） | ✅ | ✅ `recentlySalesCount` | ✅ | ✅ `paramLinkedMap` | ❌ | **主力**，唯一有销量 |
| `POST list.szlcsc.com/substitute/simple/list`（替代料） | ✅ | ❌ | ✅ | ✅ `mainParamLinkedMap` | ✅ **36 条/C8734**，带 simScore | 替代料首选，比海外站全 7 倍 |
| `www.lcsc.com/product-detail/{C}.html`（海外站 `__NEXT_DATA__`） | ✅ | ❌ | ✅（USD） | ✅ 中文参数名 | ✅ `alternatePartList`（5 条） | 英文详情兜底 |
| `jlcpcb.com` website API v2 | ✅ | ❌ | ✅ | ✅ 属性筛选 | ❌ | 可作备用检索 |
| jlcparts 数据托管（`yaqwsx.github.io/jlcparts/data/`） | ✅ | ❌ | ✅ | ✅ 367k 件、110k 条带类型参数 | ❌ | 离线按指标反查 / 反向选型 |
| 淘宝 | ❌（登录壳） | 区间 | ❌ | ❌ | ❌ | 真浏览器 + 点「销量」标签 |
| 1688 | ❌（空壳） | ✅ `sortType=va_sales360` | ❌（只有价格区间） | ❌ | ❌ | 真浏览器；走量比价需人工询盘 |
| 京东 | ❌（302 风控） | ❌ | ❌ | ❌ | ❌ | 只适合少量正品要发票 |
| LCSC 官方 OpenAPI | ❌ 需 key（商务申请） | — | — | — | — | 长期路线，短期不可用 |

## 3. 现成轮子（调研结论：复用 vs 自建）

**可直接复用**
- `jlcpcb`（PyPI 0.1.0，免 key）：`jlcpcb part list -q/--attr/--package/--library`、
  `part get C8734` 返回 6 档阶梯价 + 12 项参数 + MSL/ECCN
- jlcparts 离线库 + 60 行 `decode_shard.py`：LDO「≥0.5A + SOT-23 + 库存≥1000」扫描 7016 条命中 215 条
- `easyeda2kicad`：C 号 → KiCad 符号/封装/3D（AGPL，只能独立进程调用）
- `lcsc`（PyPI 0.1.1）：海外站检索客户端

**不需要自建**：爬虫框架、参数表抓取、MCP 外壳、EDA 格式转换、分页/鉴权处理

**必须自建（已完成）**
1. BOM 行 → 候选料的匹配打分（型号规范化、封装一致性、替代策略、阶梯价落档、缺货退让）
2. 指标核对与降额判定（`spec.py`）
3. 渠道建议规则

**被否掉的**：`parts-mcp`（需付费账号，实测 403）、`lcsc-toolkit`（只有检索，无配单）、
KiCost（不含立创）、InvenTree/BOMist（无立创通道）、淘宝/1688 系 MCP（需 APIFY_TOKEN）

## 4. 关键实测事实（会直接影响结果正确性）

1. **排序陷阱**：完整型号检索时立创把「精准匹配组」钉最前，`sortNumber` 几乎无效；
   要按销量/价格挑必须用品类词。
2. **同型号多 C 号**：一个 MPN 可能十几个 C 号（原厂/国产替代/不同批次），库存差异极大
   （`W25Q64JVSSIQ` C179171 有 1383，另一 C 号 0）。
3. **参数是卖家填的**：`paramLinkedMap` 缺项常见，且**同一指标名不同品类不同**
   （`Rated Voltage` / `Supply Voltage` / `Voltage - Supply`），这是离线筛选必须建别名表的原因。
4. **必须带测试条件比参数**：`AO3400A` 一家标 48mΩ@Vgs2.5V、另一家 17mΩ@Vgs10V；直接比会得出错误结论。
5. **降额是硬阈值**：MLCC ≤85% 额定耐压（1µF/6.3V X5R 加 3V 只剩 0.36µF）、钽 50% 且失效短路。
6. **品牌是最安全的降本维度**：同规格实测价差 SS34 15×、1N4007 7×、AMS1117 5×、AO3400 3.2×。
7. **销量信号很弱**：淘宝 Spearman(价,销量) 仅 +0.09/+0.08/−0.07/−0.31，且排序会把开发板顶到裸片前
   → 销量只能当 tie-breaker。
8. **小批量淘宝可能更便宜**：STM32 裸片淘宝 ¥1.02–1.45 vs 1688 ¥4.00–5.15；1688 优势在大数量+对公，
   但它的阶梯价拿不到。
9. **立创商城 ≠ 嘉立创 SMT**：库存/价格两套系统，商城料不能随 PCB 寄；SMT 扩展库按型号数收费
   → 物料归一化直接省钱。
10. **代理坑**：`*.lcsc.com` 不能走代理；本机 `no_proxy` 含 `[::1]` 会让 httpx 崩。

## 5. 端到端验证（真实数据，2026-11-04）

16 行示例 BOM（`probe\bom\sample_bom.csv`）：**16 行全部匹配，合计 ¥28.84，1 行需人工确认**。
产物 `probe\bom\report_sample.md` + `result_sample.json`。

代表性结果：

| 行 | 落料 | 价格 | 说明 |
|---|---|---|---|
| STM32F103C8T6 | C8734 (ST) | ¥9.12@1 | 核心件，立创优先 |
| AMS1117-3.3 | C2992570 (国芯佳品) | ¥0.2308 | 同型号 14 个 C 号，原厂 AMS ¥1.26 |
| 10uF 0805 16V | C880609 (CCTC) | — | MLCC 降额提示 |
| SS34 | C51898099 (正芯) | — | 同型号 30 个 C 号 |
| W25Q64JVSSIQ | C179171 (Winbond) | ¥11.71 | 另一 C 号 0 库存，自动选有货 |

替代料验证：`lcsc.py alternate C8734 --qty 100` → **36 条**（国产 29 / 同品牌 7），带相似度与中文参数差异
（`程序存储容量:64KB→128KB`、`工作温度:-40~85℃→-40~105℃`）与人民币阶梯价。前几名：C2969777 `STM32F103C8T6TR`
¥8.58（sim 95，原厂卷带）、C279569/C8304 `STM32F103CBT6` ¥9.94/¥11.77（Flash 翻倍）、C1121900 `…C8T7` ¥26.91（工业温区）；
国产替代：APM32F103CBT6 ¥5.64、APM32F103C8T6 ¥5.82、CH32F103C8T6 ¥5.41、CKS32F103CBT6 ¥6.97、HK32F103CBT6A ¥7.61。

## 6. 按意图找料（`pick.py`，实测）

只给一句需求、还没定型号时的入口。链路：**意图 → 品类（`catalogIdFilter`）→ 候选 60 条 → 动态参数键 + 别名 → 过滤排序去重 → 可选淘宝比价**。

| 需求 | 品类/命中 | 结果 |
|---|---|---|
| `找 3.3V 1A 的 LDO` | 线性稳压器(LDO) 387，扫 53 | C6186 AMS1117-3.3 ¥0.7247@100、C485517 TLV75733PDBVR ¥0.7447、C347256 AMS1117-3.3S ¥0.1593 |
| `10uF 25V 0805 电容` | 贴片电容(MLCC) 313，扫 60 | C15850 三星 X5R ¥0.2574（库存 4.2 万）、C440198 村田 50V ¥0.8173 |
| `30V 5A N沟道 MOS` | 场效应管(MOSFET) 381，扫 46 | C20917 AO3400A ¥0.543、C2938367 AO3400 ¥0.1861、C19019 CJ3400 ¥0.225 |
| `8MHz 5032 无源晶振` | 无源晶振 537，扫 60 | C115962 X50328MSB2GI ¥1.50（销量 13564）、C5280575 ¥1.51（±10ppm） |
| `pick --family norflash --param "存储容量>=64Mbit"` | NOR FLASH 501，扫 55 | C97521 W25Q128JVSIQ ¥15.01、C179171 W25Q64JVSSIQ ¥11.71（库存 68）、C2928891 GD25Q128ESIGR ¥8.47 |

关键机制：
- **品类解析**：裸词检索只看 facet `catalogGroup[]`，`value` 就是 `catalogIdFilter`；`25` 个 family 已固化在 `data/categories.yaml`（无需现场解析）。
- **参数键随类目变**：LDO 是 `输出极性/工作电压/输出电压/输出电流`，MOS 是 `数量/漏源电压(Vdss)/连续漏极电流(Id)/导通电阻(RDS(on))`，MLCC 是 `容值/精度/额定电压/温度系数` —— 运行时从候选里聚键，不硬编码。
- **比较语义看极性**：`输出电压=3.3V` 等值、`额定电压>=25V` 下限（50V 的料合格）、晶振频率等值（要 8MHz 不能给 25MHz），`导通电阻` 上限。
- **缺参数视为不满足**（`--allow-unknown` 可放行）：立创参数是卖家填的，缺字段不能当合格。
- **落选主因**会写出来（`3.3V→输出电压=5V ×11`、`1A→输出电流=500mA ×10`），用来判断该放宽哪一项。

## 7. 已知限制

- 立创参数区间筛选**无服务端支持**（`parmeterValueList` 恒为空，`queryParameterValue` 返 0 条）→ 只能取一页候选后本地过滤
- **找料只能看到采样到的候选**（默认 2 页 60 条，单页上限 30）；`totalCount` 被服务端截到 1500，真实规模看 `catalogGroup[].count`
- BOM 一键配单（`bom.szlcsc.com/bom/upload`）有 HTTP 接口但需登录 Cookie，本 skill 未内置（避免要求 token）
- 淘宝/1688 无免登录脚本化通道：淘宝必须登录态浏览器且销量排序只能点 tab，1688 阶梯价拿不到 → 只能给操作配方
- 淘宝「价格」tab 点击实测无效 → 价格只能在客户端排序，且只覆盖本页样本
- 1688 阶梯价拿不到，走量价必须人工询盘
- 价格是快照，交付时必须带抓取时间

## 8. 相关文件

- 调研：`research\github-tools.md`（现成轮子 16 个）、`research\lcsc-probe.md`（立创接口）、
  `research\market-probe.md`（淘宝/1688/京东）、`research\cn-knowledge.md`（配单 SOP 与渠道）、
  `research\categories.md`（品类目录与参数键扫描）、`research\taobao-tool.md`（淘宝/1688 CLI 用法）
- 规则：`research\spec-rules.yaml` + `research\spec-rules.md`
- 找料数据：`D:\WorkDesigns\3_WorkTools\skills\bom-sourcing\data\categories.yaml`（25 family）
- 探针：`probe\lcsc\`（排序/facet/替代料/品类参数原始响应）、`probe\taobao\`、`probe\market\`、`probe\github\`
- 远端：<https://github.com/alwaysmy/bom-sourcing>（公开，main；由 `skills` 仓的 `bom-sourcing/` 子树发布）

## 9. 发布方式（skill 仓 → 独立仓库）

真源是 `D:\WorkDesigns\3_WorkTools\skills\bom-sourcing\`（`C:\Users\dell\.agents\skills\bom-sourcing` 是指向它的 junction）。
推送只取该子树，不动 `skills` 仓里别人的提交：

```powershell
cd D:\WorkDesigns\3_WorkTools\skills
git add bom-sourcing; git commit -m "..."          # 先落在 skills 仓
git branch -D bom-sourcing-standalone              # 重建子树分支
git subtree split --prefix=bom-sourcing -b bom-sourcing-standalone
git push https://github.com/alwaysmy/bom-sourcing.git bom-sourcing-standalone:refs/heads/main
```

验证：`git clone --depth 1 https://github.com/alwaysmy/bom-sourcing.git`，比对 `git ls-tree -r --name-only bom-sourcing-standalone` 的文件清单（当前 28 个文件）。
