# 配单 / 选料方法论调研报告

> 目的：为 `skills/bom-sourcing/references/methodology.md` 与 `data/knowledge/*.yaml` 提供**有出处的判断依据**。
> 本文只回答两件事：①别人怎么把「配单」做成流程/工具；②哪些做法值得抄、哪些必须避坑。
> 采集时间：2026-11-05。所有来源均为当天真实访问。

---

## 0 调研方法与可信度分级

### 0.1 来源筛选

- **只收「有可复现流程」的来源**：能说清「输入什么 → 做什么判断 → 输出什么」的工具文档、厂商 playbook、工程社区长文。纯卖货页、纯参数罗列页一律不收。
- **不收二手转述**：如「某乎说降额要 50%」这类无原文链接的说法，一律回溯到原始规范/原文。
- **明确区分口径**：厂商官方口径（可当硬约束）与个人经验（只能当启发式），在文中逐条标注。

### 0.2 可信度标记（与 `data/knowledge/*.yaml` 的 `evidence` 字段一致）

| 标记 | 含义 | 使用方式 |
|---|---|---|
| `【官方】` | 厂商/标准组织正式文档 | 可作硬约束，进判据 |
| `【实测】` | 本仓 `probe/` 下脚本跑出的真实数据 | 可作硬约束，进判据 |
| `【二手】` | 第三方文章转述，未回溯原始规范 | 只作提示，需标注 |
| `【经验】` | 行业通行的经验值，无单一出处 | 只作启发式，必须可被人工推翻 |

### 0.3 一个前置结论

调研了 20+ 个来源后，**没有一个开源工具把「中国境内小批量配单」做完整**：

- 海外工具（KiCost / BOMIST / InvenTree / Octopart / parts-mcp）全部围绕 **DigiKey / Mouser / Farnell / Octopart** 的价格与库存 API 建，**没有立创商城通道**；
- 立创侧的工具（lcsc-toolkit / kicad-tools 的 `LCSCClient`）只做「按 LCSC 号查」这一层，**不覆盖「从模糊需求到型号」的选型**；
- 嘉立创 SMT 侧的配单工具（EasyEDA SMT 选型、手动配单）是**闭环在自己平台内**的，且明确「只做贴片、不单独寄料」。

这正是本仓 `scripts/` 存在的理由：**把「中文需求 → 立创候选 → 指标核对 → 渠道分流」这条链自己接起来**。下面所有「该抄什么」都是为这条链服务的。

---

## A 类：开源 / 商业工具的配单实现

### A1 KiCost

- 来源：<https://kicost.readthedocs.io/en/latest/readme.html>
- 做什么：从 **KiCad BOM XML**（也支持 Altium / Proteus / Eagle / Upverter / 手工 CSV）生成一张**成本表**，自动抓多家分销商的价格与库存；表里填「要建几块板」就自动重算总价；可导出**可直接粘贴到分销商下单页**的型号+数量清单。

**该抄什么**

1. **「BOM → 成本表」是唯一正确的主产物形态**。不是「搜索结果列表」，而是**逐行带位号、数量、单价、小计、库存状态**的表格。本仓 `bom.py --md` 的报价单结构与此一致。
2. **数量是参数，不是常量**：`--qty N` 把「我要做几块」变成一次重算，而不是让用户自己乘。本仓已实现。
3. **导出格式对齐下游**：KiCost 导出的是「分销商购物车能直接吃的」格式。本仓对应的是 `bom.py --columns` 输出嘉立创手动配单可粘贴的列。
4. **多 EDA 输入的适配层**：KiCost 把「不同 EDA 的 BOM 列名」抽象成一层 parser。本仓 `bom.py --columns` 的列名嗅探是同一思路。

**不该抄什么**

1. **KiCost 不含立创通道** —— 这是它在中国境内的致命短板（本仓 `research/BOM-配单-调研报告.md` 已实测否掉）。照抄它的「分销商 API 聚合」架构会直接撞墙，因为立创**没有公开的免登录价格 API**，本仓走的是 `so.szlcsc.com/query/product` 这条**非官方但免登录**的路子。
2. **它不做「指标核对」**。KiCost 只比价格和库存，**不判断「这个 10µF 的耐压够不够」**。本仓 `spec.py` 的指标核对是超出 KiCost 的部分，必须保留。
3. **它假设 BOM 已经是干净的**。KiCost 不处理「型号写错一字母」「封装写成 SOT-23 但实际是 5 脚」这类问题。这些恰恰是中文配单最高频的坑（见 `cn-knowledge.md` D1/D2）。

---

### A2 BOMIST

- 来源：<https://bomist.com/> 、<https://docs.bomist.com/>
- 做什么：桌面端、**离线优先**的电子制造管理应用。集成 DigiKey / Mouser / Farnell API 取实时价格与库存；管库存 / BOM / 采购 / 生产；**BOM 多版本**；**Deadlines Heatmap**（哪些料快断货，用热力图铺在时间轴上）；条码扫描；**Inventory Value Report**（库存值多少钱）。

**该抄什么**

1. **「离线优先 + 本地缓存」是正确架构**。价格是**瞬时快照**（`market-probe.md` §8.6 明确说比价结论只在采集时刻有效），所以必须落盘带时间戳，不能每次现查。本仓 `%LOCALAPPDATA%\bom-sourcing\cache` 6 小时 TTL 是同一思路。
2. **Deadlines Heatmap 这个交互值得抄成「风险排序」**：把「哪些料有交期/停产/断货风险」做成一张按紧急度排序的表，而不是让用户自己一格格看。本仓 `bom.py` 的把握列 `✔ / ≈ / ? / ! / ✘` 就是它的简化版 —— **`!` 和 `✘` 必须排到最前面**。
3. **BOM 多版本**：同一个项目会有「打样版 BOM / 小批版 BOM / 量产版 BOM」，差异必须可对比。本仓目前只有单次解析，这是**已知缺口**（见 §F 差距 3）。
4. **Inventory Value Report 的思路**：配单的终点不是「买到了」，而是「知道这批料值多少钱、占多少现金」。报价单里必须有**整单合计**（本仓已算，16 行示例 ¥28.84）。

**不该抄什么**

1. **桌面 GUI 应用**。本仓是 agent 可调用的 CLI + YAML 知识库，**不引入 GUI 依赖**。
2. **它同样只有海外分销商 API**。BOMIST 的价值在「管理」，不在「中国境内选型」。
3. **条码扫描 / 库位管理**：这是仓库管理（WMS）范畴，超出「配单/选料」的任务边界。**不做**。

---

### A3 InvenTree

- 来源：<https://docs.inventree.org/en/stable/>
- 做什么：Python/Django 开源库存管理系统。parts 结构化分类、供应商与 supplier item 映射、级联库位（location）、BOM 多格式上传/下载、build 消费库存、REST API + 原生 Python binding、插件系统。

**该抄什么**

1. **「一个器件 = 一个 part，关联多个 supplier item」这个数据模型**。同一个 STM32F103C8T6 在立创、淘宝、Mouser 各有各的编号和价格 —— **part 是抽象，supplier item 是具体报价**。本仓 `spec-rules.yaml` 的 `critical[].key` 就是 part 侧的抽象参数，`lcsc.py` / `taobao.py` / `distributor.py` 各自返回的是 supplier item 侧的报价。**这个分离必须在 methodology.md 里讲清楚**，否则会出现「拿淘宝的价去比立创的库存」这种错配。
2. **结构化分类优于关键词匹配**。InvenTree 强制 part 挂在 category 下。本仓对应的是 `pick.py` 的「意图 → family → catalog_id」链路（`data/categories.yaml` 25 个 family 带 `catalog_id`），**family 就是 category**。
3. **插件系统 = 渠道可插拔**。InvenTree 用插件接不同供应商。本仓 `scripts/` 下每个渠道一个脚本（`lcsc.py` / `taobao.py` / `distributor.py`），是**同一思想的手工版**，够用。
4. **REST API + Python binding 双出口**：CLI 给人看，JSON 给 agent 吃。本仓所有脚本都有 `--json`，**这条必须坚持**。

**不该抄什么**

1. **Django 那套重框架**。本仓是脚本集合，不引 Web 框架。
2. **InvenTree 没有立创通道**（同上）。
3. **它的 BOM 上传是「格式解析」不是「配单」**：InvenTree 解析完就结束了，不判断可采性、不给替代料。**本仓的 A3–A7（降额/可采性/替代/损耗/渠道）是 InvenTree 完全没有的段**，不能因为「InvenTree 只做解析」就把自己的范围砍到只做解析。

---

### A4 Octopart BOM Tool

- 来源：<https://octopart.com/zh/bom-tool>
- 做什么：上传 BOM → 自动匹配器件 → 展示多家分销商的价格/库存/交期 → **智能导出保持原列结构并带超链接** → 可一键转购物车直连分销商（Octocart 一键下单）。

**该抄什么**

1. **「保持原列结构」是硬要求**。用户给的 BOM 可能有 12 列（含位号、备注、替代型号、供应商料号），导出时必须**原样保留 + 追加报价列**，不能重排。本仓 `bom.py --columns` 的输出要遵守这条：**原列在前，追加列在后**。
2. **每一行都要能点回原始商品页**。这是可审计性的底线 —— 用户要能自己复核「你说的这个价是哪个链接」。本仓报价单必须带**立创商品链接**（`https://item.szlcsc.com/<code>.html`）。
3. **一键转购物车**：配单的终点是下单。能生成「可直接粘进购物车」的清单就省一次手工录入。本仓 `bom.py --columns` 输出「立创编号 + 数量」两列就是干这个的。

**不该抄什么**

1. **Octopart 的数据源在中国境内不可用**（它聚合的是海外分销商）。
2. **它的「智能匹配」是黑箱**。本仓必须做**可解释的匹配**：每一行给出「为什么匹配 / 为什么存疑」，用 `✔ / ≈ / ? / ! / ✘` 五档而不是一个分数。**可解释性优先于准确率** —— 因为配单错了要报废整板。

---

### A5 parts-mcp

- 来源：<https://pypi.org/project/parts-mcp/>
- 做什么：MCP server。工具面极完整：`search_parts` / `get_part_details` / `get_part_pricing` / `check_availability` / `find_alternatives` / `process_bom` / `match_components` / `find_kicad_projects` / `generate_kicad_bom`。支持 KiCad / Altium / Fusion360 / Eagle / PADS / Protel99 六种 EDA 格式。**AI-powered matching with confidence scoring**，本地缓存 24h。需 `SOURCE_PARTS_API_KEY`。

**该抄什么**

1. **工具命名就是方法论**。它把配单拆成 8 个动词：`search → details → pricing → availability → alternatives → process_bom → match → generate`。本仓 `scripts/` 的动词集合（`pick` / `search` / `price` / `detail` / `compare` / `alternate` / `bom`）与它**几乎一一对应**，说明这个切分是行业共识。methodology.md 的步骤命名应对齐这套动词。
2. **`confidence scoring` 这个字段必须有**。匹配结果不是一个布尔值，而是「有多确定」。本仓的 `✔/≈/?/!/✘` 五档就是 confidence 的离散化，**比连续分数更适合人复核**。
3. **本地缓存 24h** 与 BOMIST 同理。
4. **`find_kicad_projects` 这个「反向找项目」的工具**：配单经常需要「这个工程用的是哪版 BOM」。本仓暂不需要（无 EDA 集成），但**如果将来接原理图，这个入口是对的**。

**不该抄什么**

1. **它需要付费 API key**（`SOURCE_PARTS_API_KEY`），本仓已实测 403 无法使用（见 `research/BOM-配单-调研报告.md`）。**不能把整条链的可用性押在一个需付费的第三方 API 上**。
2. **六种 EDA 格式的解析器**是巨大维护成本。本仓只吃 **CSV/Excel 表格**（`bom.py`），这是**主动的范围收缩**，正确。
3. **它把「AI 匹配」交给服务端**。本仓的匹配必须**本地可复现**（同一个 BOM 跑两次结果必须一样），否则无法审计。

---

### A6 lcsc-toolkit / kicad-tools 的 LCSC 客户端

- 来源：<https://pypi.org/project/lcsc-toolkit/> 、<https://github.com/rjwalters/kicad-tools>
- 做什么：
  - lcsc-toolkit：`LcscSession.load("session.json")` + `OrdersClient(session).list_orders()` —— **靠会话 cookie 读立创订单/购物车**。
  - kicad-tools：`LCSCClient` 按 LCSC 号查询，**遇到 403 会熔断**（抛 `LCSCForbiddenError`）。

**该抄什么**

1. **403 熔断是必须的**。立创的风控会在请求过密时返回 403，**继续重试只会把 IP 打黑**。本仓所有脚本必须有「连续 N 次 403 → 停止并报错」的逻辑。这是**可靠性要求，不是优化**。
2. **会话可以落盘复用**（`session.json`）。本仓淘宝脚本的 `--session NAME` 是同一思路。**但立创的公开查询不需要登录**，所以本仓对立创走免登录路径（`so.szlcsc.com/query/product`），**只对淘宝/1688 用会话**。
3. **「按料号精确查」和「按关键词模糊搜」是两个不同的入口**。本仓对应 `lcsc.py detail <code>`（精确）与 `lcsc.py search <kw>`（模糊），**不能混用**。

**不该抄什么**

1. **靠 cookie 读订单/购物车**：这要求用户交出立创登录态，**在 agent 自动化里是不可接受的安全边界**。本仓明确不做。
2. **把「查不到」当成「不存在」**：LCSC 的搜索有 `pageSize > 30` 静默返 0 的坑（见 `research/lcsc-probe.md`），必须**先排除「分页参数错」再判定无货**。

---

### A7 Apify Octopart Scraper（付费第三方）

- 来源：<https://apify.com/crawloop/octopart-scraper>
- 做什么：别人把 Octopart 抓下来做成付费 API 卖。

**该抄什么**：只抄一个判断 —— **「抓取 + 缓存 + 卖」是被验证过的商业模式**，说明「结构化元器件价格数据」确实有需求。

**不该抄什么**：**不依赖任何付费第三方**。本仓的价值恰恰是**免登录、免付费、可自己跑**。一旦引入付费 API，整个 skill 的可用性就绑在别人的账单上。

---

## B 类：立创 / 嘉立创生态的官方口径

> 这一类的价值最高：它是**平台自己承认的规则**，可以直接当硬约束。

### B1 EasyEDA Pro — JLCPCB SMT 选型工具

- 来源：<https://prodocs.easyeda.com/en/pcb/tools-jlcpcb-smt-part-selection-tool/>
- 做什么：在 EDA 里选 SMT 器件 → **自动生成 BOM** → 校验（哪些料不在贴片库里）→ 导出可直接上传的 BOM。

**该抄什么**

1. **「配单前先做贴片库可采性校验」是官方流程**，不是可选项。原理图上标了型号 ≠ 嘉立创能贴。本仓对应 **A4 可采性复核**：`lcsc.py search --include-out-of-stock` 看现货，再加「基础库 / 扩展库」判定（扩展库 **20 元/型号**换料费）。
2. **「校验 → 导出」的顺序不能反**。先校验再导，避免导出了一份错的再回头改。本仓 `bom.py` 的流程也是「解析 → 匹配 → 核对 → 出报价单」，**报价单是最后一步**。

**不该抄什么**：**它绑定 EasyEDA 工程文件**。本仓吃的是通用表格，不能要求用户先有 EDA 工程。

---

### B2 JLCPCB 自备料 / Consign（官方帮助文档）

- 来源：<https://jlcpcb.com/help/article/how-to-use-my-own-parts-for-pcb-assembly-order>
- 关键官方规则（**全部可当硬约束**）：

| 规则 | 原文要点 | 对配单的直接影响 |
|---|---|---|
| 三条供料路径 | Pre-Order / Global Sourcing / Consign 都走「My Parts Lib」 | 用户自备料也要先进库 |
| 库存优先 | 库存够 → 优先用自有料；不够 → 用公共库补 | **「自备料」不是全有或全无，可以混** |
| 合并规则 | **Consign 先匹配、不足再 Global Sourcing**；公共库存与 Pre-Order 可合，Global + Consign 可合 | **其它组合不支持** → 配单时必须按这个组合拆分 |
| 只做贴片 | 只做贴片，不单独寄料 | **立创商城的料不能随 PCB 一起寄**（对应 `cn-knowledge.md` D12） |

**该抄什么**

1. **「先匹配、不足再补」的兜底链**。这是官方的降级顺序，配单的替代料策略应采用同一顺序：**原型号现货 → 同参数替代 → 公共库补 → 询盘**。
2. **组合规则是硬约束**。给用户建议渠道时，**不能推荐一个平台不支持的组合**（比如「公共库存 + Consign」是不行的）。
3. **「只做贴片不寄料」这条必须写进风险清单** —— 这是最高频的误解。

**不该抄什么**：无。这是纯官方口径，全收。

---

### B3 嘉立创「器件匹配业务说明」+ 手动配单输入格式

- 来源：<https://member.jlc.com/portal/server_guide_48551.html> 、<https://www.jlc.com/portal/server_guide_19875.html>
- 官方定义：BOM 配单 = **把原理图 BOM 里的器件匹配到立创商城 / 嘉立创 SMT 的库存**；建议 **Layout 期间就提前备料**；Layout 团队会协助提供**备选料**。
- 手动配单输入格式（官方口径原文）：`10K 5%` / `100PF 10V`，「**IC 直接输入型号；阻容直接输入值，值 + 参数用空格区分，用别的符号可能找不出来**」。

**该抄什么**

1. **「空格分隔」这条格式规则必须硬编码**。这是官方明说的「用别的符号可能找不出来」—— 直接决定 `pick.py` / `bom.py` 的输入串构造方式。
2. **「Layout 期间备料」= 时间窗口前置**。对应 `cn-knowledge.md` A4 的 BOM 变更窗口：**工程资料阶段改成本最低**。methodology.md 必须把「什么时候该停下来改 BOM」写成一个时间轴判据。
3. **「提供备选料」是平台承诺的动作**，说明替代料不是可选项。本仓 `lcsc.py alternate <code>`（`list.szlcsc.com/substitute/simple/list`，带 `simScore`）就是对这条的自动化。
4. **三色配单状态**（绿/黄/红）：`cn-knowledge.md` A7 已收录 —— **红色必须人工干预**，这条是「必须停下来问人」的判据之一。

**不该抄什么**：**手动配单的 UI 操作流程**（点哪个按钮）—— 本仓不需要 GUI 步骤。

---

## C 类：降额与可靠性方法论

### C1 PCBSync 降额指南（引用 IPC-9592B）

- 来源：<https://pcbsync.com/component-derating-guidelines/>
- 价值：**唯一一份把「商业档 vs 高可靠档」两套降额百分比逐器件列全的公开材料**，且明确标注 IPC-9592B 的出处。

**该抄什么**（已全部落进 `data/knowledge/industry-norms.yaml` 的 `derating:` 段）

1. **两档并列而不是给一个数**。商业档（消费/工业）与高可靠档（车规/军工）差 10–20 个百分点，**只给一个数会导致过度降额**（更大的封装 = 更易弯曲开裂，PCBSync 明确警告）。
2. **钽电容电压 50% 是强制项**，不是建议 —— 因为钽的失效模式是**热失控 + 短路**，不是开路。这条必须进 YAML 的 `mandatory: true`。
3. **保险丝的温度降额是「每高于 25℃ 再降 0.5%/℃」这种公式型规则**，不是单一百分比。YAML 里要用 `formula` 字段表达，不能塞进 `max_ratio`。
4. **「MLCC 直流偏压容值损失」是最反直觉、也最容易翻车的一条**：0402 10µF/6.3V X5R 在 5V 下只剩 **约 1.5µF（−85%）**。这条直接影响「10µF 的电容到底该买多少 V 的」。**必须写进 methodology.md 的 A3 参数复核步骤**，并在 YAML 里带那条真实事故。
5. **六步降额分析法**（定标准 → 定最坏工况 → 逐件算应力 → 比限值 → 查隐藏应力 → 留档）是**可执行的检查清单**，methodology.md 的「指标核对」步骤直接照它的顺序。
6. **7 条常见错**直接就是风险清单条目，尤其「缺货换料后不重跑降额」—— 这是替代料流程里最容易漏的一步。

**不该抄什么**

1. **不抄它的「高可靠档」为默认**。本仓服务的是小批量/打样/工控类，**默认走商业档**，高可靠档作为可选参数。
2. **不抄「全面降额更安全」的直觉** —— 原文明确说过度降额会因封装变大而更容易弯曲开裂。**降额是定值判据，不是越大越好**。

---

### C2 CSDN《嵌入式硬件工程师成长之路·2026（1）：元件选型不是看参数，是看降额》

- 来源：<https://yunxuan.blog.csdn.net/article/details/169935648>
- 价值：中文语境下把「六大类器件降额」讲得最系统的长文；核心命题 **「绝对最大值 ≠ 安全工作值」**。

**该抄什么**

1. **「绝对最大值 ≠ 安全工作值」这个表述**要原样写进 methodology.md 的开头 —— 它是整个指标核对步骤的**动机**。用户看到 `Vds = 30V` 就以为「24V 系统没问题」，实际 24V 系统的**瞬态**经常到 40V+。
2. **六大类器件分类法**（阻容 / 分立半导体 / IC / 电感变压器 / 继电器保险丝 / 连接器）与 PCBSync 一致，可交叉验证。

**不该抄什么**：**CSDN 特有的「三段式标题 + 大量铺垫」文风**。知识库要短句、可 grep。

---

### C3 EET-China 选型六维度

- 来源：<https://www.eet-china.com/mp/a83089.html>
- 六维度：**复用性 / 成熟性 / 适配性 / 替代性 / 采购性 / 归一性**（`cn-knowledge.md` A3 已收录）。

**该抄什么**

1. **「归一性」是唯一一个「越少越省钱」的维度**：物料种类越少 → 换料费越少（嘉立创扩展库 **20 元/型号**）、库存管理越简单、议价能力越强。这条要写进方法论，因为它是**唯一能主动降本而不牺牲性能**的维度。
2. **「替代性」要在选型阶段就设计进去**：选型时优先选 **PIN TO PIN 有多个国产品牌**的型号，避免被单一供应商卡死。这是「预防」而非「补救」。
3. **「成熟性」= 不要用刚发布的型号**：新料没有第二货源、没有验证过的失效数据。

**不该抄什么**：六维度是**定性清单**，不能当数值判据。methodology.md 里要**明确它用于生成「追问清单」而不是「通过/不通过」**。

---

## D 类：生命周期与停产（EOL / LTB）

### D1 Cadence《When Your Component Is Unavailable: Alternates, Last Buys, and Counterfeits》

- 来源：<https://resources.pcb.cadence.com/component-information-portal-cip/col/component-information-portal-cip/when-your-component-is-unavailable-alternates-last-buys-and-counterfeits>
- 核心：**EOL 公告 → 90 天 LTB（Last Time Buy）窗口**；如何做「能扛量产的替代料认证」；LTB 决策；假货识别。

**该抄什么**

1. **「90 天 LTB 窗口」是一个可执行的判据**：收到 EOL 通知后，**90 天内必须下最后一批订单**，否则只能改板。这要写进风险清单，并让 `bom.py` 能在备注里标「LTB」。
2. **「LTB 数量 = 剩余项目生命周期需求 + 安全库存」**，不是「买一年」。安全库存用 §E3 的公式算。
3. **假货识别与 `cn-knowledge.md` D6/D7 的「打磨翻新料七条外观法」是同一件事的两套说法**，可以互相补充（Cadence 更强调**供应链来源**，中文经验更强调**外观**）。

**不该抄什么**：**它的「认证流程」是车规级的**（PPAP 式），小批量配单用不上。降级成「四步验证法」（`cn-knowledge.md` B 节已收录）。

---

### D2 晶发 / CTP《Managing Display Obsolescence》

- 来源：<https://crystal-display.com/download/104219/>
- 核心：**LTB 只在「需求与衰减不确定度可界定、且存储条件可信」时才合理**；**FFF（Form-Fit-Function）替代需要结构化的 delta 认证**，不能只对参数表。

**该抄什么**

1. **LTB 不是万能解**：存储条件不可信（潮湿、无干燥柜）时，**囤料本身就是风险**。这条要进风险清单的「反直觉项」。
2. **「FFF 替代要 delta 认证」= 替代料必须逐项列出「哪里不一样」**，而不是「参数都满足所以可以」。本仓 `lcsc.py alternate` 返回的 `simScore` 只是**相似度**，不等于**可替换** —— 这条必须在 methodology.md 里写死：**`simScore` 高 ≠ 可直接替换**。

**不该抄什么**：它的行业（显示屏）特殊性太强，只取方法论，不取具体数值。

---

### D3 Hackaday《How Do You Fill The 1N34 Void?》

- 来源：<https://twiar.net/2024/05/31/via-hackaday-how-do-you-fill-the-1n34-void/>（转自 Hackaday）
- 核心：锗管（1N34 等）**全面 EOL** 后的替代困境 —— 有些老器件**没有真正等价的替代品**，只能「让老设计走」。

**该抄什么**

1. **承认「没有替代料」是合法结论**。配单工具最危险的失败模式是**硬凑一个替代品**。methodology.md 必须有一个明确的出口：**当参数无法匹配时，输出「建议改设计」而不是「推荐一个勉强能用的」**。
2. **「改设计」的成本要如实报**：改板 = 重新打样 + 重新验证 + 工期。这个成本对比（改板 vs 囤料 vs 换方案）应写进方法论的「决策出口」段。

**不该抄什么**：无。

---

## E 类：BOM 成本治理与工程权衡

### E1 EEVblog《My bill of materials tries to break my spirit》

- 来源：<https://www.eevblog.com/forum/projects/my-bill-of-materials-tries-to-break-my-spirit/>
- 金句：**「商业量产的技艺是知道能把设计糙化到什么程度还能刚好工作，以此压 BOM 成本。」**

**该抄什么**

1. **「刚好够用」是配单的目标函数，不是「最好」**。选型不是选性能最好的，而是**选满足需求的最便宜的那个**。这条要写进方法论的第一性原理。
2. **「糙化」必须有边界**：降额、安规、认证项不可糙化。**这个边界就是 `data/knowledge/risk-checklist.yaml` 里的 `severity: blocker` 项**。

**不该抄什么**：无。这是价值观层面的正确表述。

---

### E2 EEVblog《Tradeoff: when to add a new value of resistor to BOM vs combining existing》

- 来源：<https://www.eevblog.com/forum/projects/tradeoff-when-to-add-a-new-value-of-resistor-to-bom-vs-combining-existing/msg5890214/>
- 结论：**先用现有值凑网络，先跑通再谈省几分钱**；新增一个阻值 = 新增一个料号 = 新增一次换料费 + 一次上料风险。

**该抄什么**

1. **「新增料号的隐性成本」要量化**：嘉立创扩展库 **20 元/型号**（`cn-knowledge.md` D13）。一个 BOM 如果有 40 个料号，其中 10 个是扩展库，就是 **200 元** —— 这在小批量时比器件本身还贵。
2. **「归一化」是可执行的降本动作**：把 10K/12K/15K 三个值合并成 10K + 15K 两个（用串联/并联或改设计），能直接省钱。methodology.md 的「成本优化」步骤要给这个检查项。

**不该抄什么**：**不要为了归一化牺牲精度**。0.1% 的精密电阻不能随便合并。

---

### E3 安全库存公式

- 来源：<http://essay.utwente.nl/100620/1/Rietman_BA_BMS.pdf>
- 公式：`SS = k · σ'`，其中 `CV_LTD = σ_ITD / μ_LTD`（提前期内需求的变异系数），`k` 由目标服务水平查正态分位数。

**该抄什么**

1. **安全库存不是拍脑袋的「多买 10%」**，而是 `服务水平 × 需求波动`。这条要落进 YAML 的 `spares:` 段，与 `cn-knowledge.md` A6 的经验值**并列给出**：
   - 经验值（`【经验】`）：阻容 0.3%–0.5%、0201 0.5%–1.0%、连接器 0.5%–2.0%、IC 零损耗
   - 公式（`【二手】`）：`SS = z · σ_LTD`，`z` 取 1.65（95%）/ 2.33（99%）
2. **「IC/BGA 不允许丢料」这条与公式冲突时以经验值为准** —— 因为 BGA 拆盘即报废，这是**物理事实**不是统计问题。YAML 里要用 `override` 字段表达。

**不该抄什么**：**不引入完整的库存管理理论**。本仓只算「这一次该买多少」，不管「仓库里该留多少」。

---

### E4 IPC-1752A 物料声明

- 来源：<https://help.exchange.3eco.com/en/articles/6125027-create-an-ipc-1752a-report> 、<https://www.ipc.org/system/files/technical_resource/E41%26S05_01%20-%20Roger%20Franz%20.pdf>
- 做什么：**物料声明标准**（RoHS / REACH / 冲突矿产 / 合规声明的结构化交换格式）。

**该抄什么**

1. **合规信息是 BOM 的一等公民**，不是备注。BOM 表里应有「RoHS / 无铅」列。本仓 `bom.py --columns` 的列名嗅探应能识别这类列。
2. **「物料声明」的字段设计**（制造商、料号、描述、合规状态、证据链接）可以作为**风险清单里「合规」类的字段模板**。

**不该抄什么**：**不做完整 IPC-1752A XML 导出**。小批量配单用不上，只需在报价单里给一句「RoHS 状态：待确认 / 已确认」。

---

## F 横向对比：该抄 / 不该抄速查表

| # | 来源 | 类型 | 该抄（1 条核心） | 不该抄（1 条核心） |
|---|---|---|---|---|
| 1 | KiCost | 开源工具 | 「BOM → 成本表」是唯一正确主产物 | 分销商 API 聚合架构（立创无公开 API） |
| 2 | BOMIST | 商业工具 | 离线优先 + 价格快照带时间戳 | 桌面 GUI 依赖 |
| 3 | InvenTree | 开源系统 | part / supplier-item 两级数据模型 | Django 重框架 |
| 4 | Octopart | 商业工具 | 导出保持原列结构 + 每行可点回 | 黑箱匹配（要可解释） |
| 5 | parts-mcp | MCP server | 8 个动词的工具切分 | 付费 API key 依赖 |
| 6 | lcsc-toolkit | 开源库 | 403 熔断 | 靠 cookie 读订单 |
| 7 | kicad-tools | 开源库 | 精确查 vs 模糊搜两个入口 | 把「查不到」当「不存在」 |
| 8 | Apify Scraper | 付费服务 | （仅佐证需求真实） | 付费第三方 |
| 9 | EasyEDA SMT 工具 | 官方 | 先校验可采性再导出 | 绑定 EDA 工程文件 |
| 10 | JLCPCB Consign | 官方 | 「先匹配、不足再补」兜底链 | 不支持的渠道组合 |
| 11 | 嘉立创器件匹配 | 官方 | 空格分隔的输入格式硬编码 | 手动配单 GUI 步骤 |
| 12 | PCBSync / IPC-9592B | 标准解读 | 商业档 / 高可靠档两档并列 | 高可靠档当默认 |
| 13 | CSDN 降额长文 | 二手 | 「绝对最大值 ≠ 安全工作值」 | 三段式文风 |
| 14 | EET 六维度 | 二手 | 归一性 = 唯一纯降本维度 | 把定性清单当数值判据 |
| 15 | Cadence EOL | 二手 | 90 天 LTB 窗口 | 车规级 PPAP 认证流程 |
| 16 | CTP 停产管理 | 二手 | `simScore` 高 ≠ 可替换 | 显示行业具体数值 |
| 17 | Hackaday 1N34 | 社区 | 「没有替代料」是合法结论 | — |
| 18 | EEVblog BOM | 社区 | 「刚好够用」是目标函数 | — |
| 19 | EEVblog 阻值 | 社区 | 新增料号的隐性成本要量化 | 为归一化牺牲精度 |
| 20 | 安全库存论文 | 学术 | `SS = z·σ` 公式化补货 | 完整库存管理理论 |
| 21 | IPC-1752A | 标准 | 合规信息是一等公民 | 完整 XML 导出 |

---

## G 最有价值的 5 条「别人做对了但我们还没做」

> 这 5 条是本轮调研的**净增量**，直接对应 `references/methodology.md` 与 `data/knowledge/*.yaml` 的新增段落。

### G1 「可解释的匹配分档」取代「一个匹配/不匹配」

- **谁做对了**：Octopart（保持原列 + 每行可点回）、parts-mcp（`confidence scoring`）。
- **我们的现状**：`bom.py` 已有 `✔ / ≈ / ? / ! / ✘` 五档，但**没有把「为什么是这个档」写成结构化理由**。
- **该补什么**：每一行的判定理由要是**机器可读的**（`{level, reasons: [...], checked: [...], unchecked: [...]}`），这样才能在报价单里解释、也才能被 `--strict` 用来决定是否阻断。
- **落地位置**：`references/methodology.md` §A3；`data/knowledge/risk-checklist.yaml` 的 `detect` 字段。

### G2 「降额是定值判据，不是越大越安全」—— 两档并列表

- **谁做对了**：PCBSync / IPC-9592B（商业档 vs 高可靠档逐器件列出）。
- **我们的现状**：`spec-rules.yaml` 的 `critical[].margin` 只给了一个数（如电阻功率 2.0×），**没有区分档位**，也没有「过度降额有害」的提示。
- **该补什么**：`industry-norms.yaml` 的 `derating:` 段给每个器件 **`commercial` / `high_reliability` 两档**，并显式记录「过度降额的代价」（封装变大 → 易弯曲开裂；成本上升）。
- **落地位置**：`data/knowledge/industry-norms.yaml`；methodology.md §A3 的「判据」列。

### G3 「MLCC 直流偏压容值损失」这条隐性应力

- **谁做对了**：PCBSync（给了 0402 10µF/6.3V X5R 在 5V 下只剩 1.5µF 的实测，以及 3000 台网关 8 个月批量复位的真实事故）。
- **我们的现状**：`spec.py` 只核对**额定耐压 vs 需求**，**完全不考虑偏压导致的容值损失** —— 也就是说它会认为「10µF/6.3V 在 5V 轨上余量 26%，通过」，而实际有效容值只有 1.5µF。
- **该补什么**：**电源轨上的 Class II MLCC 至少用 2× 工作电压的额定值**这条硬判据；以及「10µF 级 Class II 电容的标称容值不可直接用于设计」的提示。
- **落地位置**：`data/knowledge/industry-norms.yaml` 的 `hidden_stress:` 段；methodology.md §A3 的「常见错误」。

### G4 「LTB / EOL 是一个有窗口期的决策，不是一次性动作」

- **谁做对了**：Cadence（**90 天 LTB 窗口**）、CTP（LTB 只在存储条件可信时合理）。
- **我们的现状**：完全没有 EOL / LTB 概念。`bom.py` 遇到停产料只会标 `✘`。
- **该补什么**：①`✘` 要区分「暂时缺货」与「已 EOL」；②EOL 时给 **LTB 数量建议**（`剩余需求 + SS`）与 **90 天倒计时**；③**囤料风险提示**（存储条件不可信时别囤）。
- **落地位置**：`data/knowledge/risk-checklist.yaml` 的 `lifecycle` 类；methodology.md 新增「停产与 LTB」段。

### G5 「新增料号的隐性成本必须量化」

- **谁做对了**：EEVblog 阻值讨论（先跑通再省几分钱）、嘉立创扩展库收费（**20 元/型号**）。
- **我们的现状**：`bom.py` 只算「器件单价 × 数量」，**不算换料费**，所以「用 3 个不同阻值 vs 用 1 个」在报价单上没有区别。
- **该补什么**：报价单里加一行 **「物料归一化成本」**：`扩展库型号数 × 20 元`。小批量时这一行经常比器件总价还大，是**最容易被忽略的降本点**。
- **落地位置**：`data/knowledge/industry-norms.yaml` 的 `cost:` 段；methodology.md §A7 渠道分流的「成本口径」。

---

## H 结论：本仓方法论的三条设计原则

1. **可解释 > 准确**。配单错了要报废整板，所以每一行判定都必须能说清「查了什么、没查什么、为什么存疑」。宁可给 `?`，不给错的 `✔`。
2. **两档并列 > 单一阈值**。降额、损耗、渠道阈值全部有「商业档 / 高可靠档」或「少量 / 批量」两套，且**各自带出处**。单一数字会诱导误用。
3. **承认能力边界**。立创阶梯价取不到、1688 阶梯价取不到、京东销量排序参数未知 —— 这些**全部写进知识库的 `limitations` 字段**，而不是假装知道。**agent 说「我不知道，需要人工询盘」比编一个数安全得多。**

---

## 附录：来源清单（21 条，2026-11-05 访问）

| # | 来源 | URL | 可信度 |
|---|---|---|---|
| 1 | KiCost 文档 | https://kicost.readthedocs.io/en/latest/readme.html | 【官方】 |
| 2 | BOMIST 官网 / 文档 | https://bomist.com/ · https://docs.bomist.com/ | 【官方】 |
| 3 | InvenTree 文档 | https://docs.inventree.org/en/stable/ | 【官方】 |
| 4 | Octopart BOM Tool | https://octopart.com/zh/bom-tool | 【官方】 |
| 5 | parts-mcp (PyPI) | https://pypi.org/project/parts-mcp/ | 【官方】 |
| 6 | lcsc-toolkit (PyPI) | https://pypi.org/project/lcsc-toolkit/ | 【官方】 |
| 7 | kicad-tools (GitHub) | https://github.com/rjwalters/kicad-tools | 【官方】 |
| 8 | Apify Octopart Scraper | https://apify.com/crawloop/octopart-scraper | 【官方】 |
| 9 | EasyEDA Pro SMT 选型工具 | https://prodocs.easyeda.com/en/pcb/tools-jlcpcb-smt-part-selection-tool/ | 【官方】 |
| 10 | JLCPCB 自备料帮助 | https://jlcpcb.com/help/article/how-to-use-my-own-parts-for-pcb-assembly-order | 【官方】 |
| 11 | 嘉立创器件匹配业务说明 | https://member.jlc.com/portal/server_guide_48551.html | 【官方】 |
| 12 | 嘉立创手动配单 | https://www.jlc.com/portal/server_guide_19875.html | 【官方】 |
| 13 | 嘉立创EDA 下单流程 | https://docs.lceda.cn/cn/PCB/Order-PCB/index.html | 【官方】 |
| 14 | PCBSync 降额指南（IPC-9592B） | https://pcbsync.com/component-derating-guidelines/ | 【官方】 |
| 15 | Cadence EOL/LTB/假货 | https://resources.pcb.cadence.com/component-information-portal-cip/col/component-information-portal-cip/when-your-component-is-unavailable-alternates-last-buys-and-counterfeits | 【二手】 |
| 16 | CTP 停产管理 | https://crystal-display.com/download/104219/ | 【二手】 |
| 17 | CSDN 降额长文 | https://yunxuan.blog.csdn.net/article/details/169935648 | 【二手】 |
| 18 | EET-China 选型六维度 | https://www.eet-china.com/mp/a83089.html | 【二手】 |
| 19 | EEVblog BOM 精神 | https://www.eevblog.com/forum/projects/my-bill-of-materials-tries-to-break-my-spirit/ | 【经验】 |
| 20 | EEVblog 阻值权衡 | https://www.eevblog.com/forum/projects/tradeoff-when-to-add-a-new-value-of-resistor-to-bom-vs-combining-existing/msg5890214/ | 【经验】 |
| 21 | 安全库存公式（UTwente 论文） | http://essay.utwente.nl/100620/1/Rietman_BA_BMS.pdf | 【二手】 |
| 22 | IPC-1752A 物料声明 | https://help.exchange.3eco.com/en/articles/6125027-create-an-ipc-1752a-report | 【官方】 |
| 23 | Hackaday 1N34 停产困境 | https://twiar.net/2024/05/31/via-hackaday-how-do-you-fill-the-1n34-void/ | 【经验】 |

> 内部来源（本仓 `probe/` 实测，可信度【实测】）：`research/cn-knowledge.md`、`research/market-probe.md`、`research/lcsc-probe.md`、`research/spec-rules.md`、`research/BOM-配单-调研报告.md`。
