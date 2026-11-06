# 配单工具「agent 化」需求评估

> 评估对象：傅师傅 m03065 提出的「skill + agent-based DSH 插件」需求。
> 结论口径：**需求合理，但形态要改** —— 不是「插件替人做判断」，而是
> 「skill 保底层能力 → 插件做交互与编排 → 判断交给接入的 agent → 人只审」。
> 本文所有数字都来自本机实测，原始数据在 `probe\` 下注明的文件里。
> 支撑材料：`research\dsh-plugin-architecture.md`（1,717 行）、`research\dsh-plugin-market-survey.md`（797 行）、
> `research\rbxlsx-spec.md`（800 行）、`research\mosfet-selection.md`（进行中）。

---

## 0. 一句话结论

合理。而且它解决的不是"好不好看"的问题，是三个**已被数据证实的硬问题**：
检索会漏料、判据拿不到、知识库会腐烂。三者都不是 UI 能解决的，都需要 agent 参与判断。

**而且市场是空的**：4,704 条 marketplace 记录里，**没有任何一个物料 / 元器件 / 电商类插件**。
唯一擦边的是 `dsh-pcb-parts-search`（只有"看起来像搜索"的能力，没有 BOM、没有参数、没有替代料）；
`dsh-bom` 这个 npm 名**已被占名包占用**（`0.0.1`，描述写"name reserved; first release in development"）。

---

## 1. 证据一：你问的「检索方法是不是有缺陷」——是，且能量化

### 1.1 实测数据

用 `probe\lcsc\probe_brand_coverage.py` 扫了 26 个品类的**品牌 facet**（`gradePlateGroup`，
立创在每次检索里都会返回"该品类下有哪些品牌、各多少条"），再和 `data\knowledge\vendors.yaml`
（144 个品牌 / 438 个名字含别名）求差：

| 指标 | 数值 |
|---|---|
| facet 品牌出现次数合计 | 3,538 |
| 去重后品牌数 | 1,296 |
| 我们知识库已覆盖 | 790 次 / **22.3%** |
| 未收录 | 2,748 次 / **1,167 个品牌** |

单品类抽样（已收录 / 该品类品牌总数）：

| 品类 | 覆盖率 |
|---|---|
| 场效应管(MOSFET) | 57 / 310 |
| 线性稳压器(LDO) | 59 / 257 |
| 单片机(MCU/MPU/SOC) | 17 / 212 |
| 肖特基二极管 | 55 / 198 |
| 无源晶振 | 12 / 98 |
| 功率继电器 | **3 / 70** |

### 1.2 Tokmas 在哪

`Tokmas(托克马斯)` **确实存在于立创的品牌 facet 里**，brand_id = **12489**，
出现在 12 个品类（comparator / dcdc / eeprom / esd / isolator / ldo / mcu / …），
合计 **322 条料**。

### 1.3 根因

知识库是**关键词驱动采样**建起来的：用 "稳压""电阻""SS34""AMS1117" 这类词去检索，
再从命中的结果里收品牌。这个方法的固有盲区是：

> 只卖冷门料（Tokmas 的 ULN2803 达林顿阵列）的品牌，**永远不会出现在热门关键词的结果里**，
> 于是永远进不了采样集合。

而立创的品牌 facet 是**按品类全量返回**的（单个品类 50–310 个品牌）。

### 1.4 已修（本轮完成）

新增 `scripts\brands.py` + `data\knowledge\brands.index.yaml`（276 KB / **1,296 品牌**）：

```
python brands.py build      # 扫 26 个品类品牌 facet，重建索引（约 40 秒）
python brands.py lookup tokmas
  brand_id  品牌                     料号数  品类
     12489  Tokmas(托克马斯)            322  comparator,dcdc,eeprom,esd,…
python brands.py coverage   # 索引 1,296 / vendors.yaml 覆盖 138（10.6%）
```

索引字段：`name / short / cn / aliases / families / part_count / in_vendors`。
**分工**：`brands.index.yaml` = 全集（谁在售、卖在哪些品类、多少条）；
`vendors.yaml` = 有证据的子集（tier / 价差 / 风险备注），两者用 brand_id 关联。

### 1.5 这条证据指向的结论

知识库的更新**本身就是一个检索 + 判断的任务**：跑 26 个品类的 facet、做去重/分层/取证、
把结果落成结构化条目。这正是"agent-based 知识库更新"要解决的问题 —— 需求不是拍脑袋来的。

---

## 2. 证据二：MOSFET 的判据缺口（你点的那几项）

### 2.1 实测：立创只给 4 个参数键

`probe\mosfet\probe_mosfet_keys.py`，场效应管品类（`catalogIdFilter=381`）按销量取 3 页 × 30 条，
聚合 `paramLinkedMap` 的键频次：

| 参数键 | 出现 | 样例 |
|---|---|---|
| 数量 | 90/90 | `1个N沟道` / `1个P沟道` |
| 漏源电压(Vdss) | 90/90 | `60V` |
| 连续漏极电流(Id) | 90/90 | `300mA` |
| 导通电阻(RDS(on)) | 90/90 | `5Ω@10V` / `900mΩ@10V` |

**就这 4 个，没有第五个。**

### 2.2 你提到的项，接口能给什么

| 工程判据 | 接口 | 说明 |
|---|---|---|
| 器件极性/通道 | ✔ 数量 | `1个N沟道` 可解析 |
| 耐压 Vdss | ✔ | 可直接筛 |
| 连续电流 Id | ✔ | 可直接筛 |
| 导通电阻 RDS(on) | ✔ 带测试条件 | `23mΩ@10V` vs `40mΩ@4.5V` **不可直接比** |
| 阈值电压 / 栅极电荷 / 输入电容 | ✘ | 接口无此键 |
| 热阻 / 结温 / 功率 | ✘ | 接口无此键 |
| **雪崩能量 EAS / SOA / 浪涌** | ✘ | 接口无此键 |
| **工艺类型（平面/沟槽/SGT/超结）** | ✘ | 接口无此键 |
| 体二极管反向恢复 | ✘ | 接口无此键 |

### 2.3 这条证据指向的结论

- **电气初筛可以程序化**（现有 `pick.py` 已能跑，实测命中 3 条：`C369599 30N06` 60V/30A/23mΩ ¥0.4915@100、`C108639 NCE6020AK`、`C2566 IRF540NPBF`）；
- **抗冲击是否够、工艺选哪种、做线性还是做开关、要不要缓启动** —— 这些**必须靠 datasheet + 经验规则**，
  接口给不了，程序也推不出来；
- 所以知识库要能存「判据 + 出处 + 置信度 + 人工确认状态」，而且**必须能被人审核**。

---

## 3. 证据三：市场是空的，生态范式是现成的

### 3.1 全市场扫描结果

| 结论 | 证据 |
|---|---|
| 物料 / 元器件 / 电商类插件 | **0 个**（4,704 条 marketplace 记录） |
| 唯一擦边先例 | `dsh-pcb-parts-search`（repo MIT；**未发 npm**，只走 GitHub 源安装；只有搜索，没有 BOM/参数/替代/比价/报价单） |
| 名字被占 | `dsh-bom` `0.0.1` = 占名包（"first release in development"），**npm 名不可用** |
| 真正的护城河位置 | **已经在 `bom-sourcing` skill 里**（8 个脚本 + 6 个知识库），插件不该重写它 |

### 3.2 可复用的成熟范式（不用从零造）

| 需求 | 复用什么 | 怎么接 |
|---|---|---|
| 面板壳 / 右侧栏 / 文件预览 | `dsh-better-sidebar` | `inject = ['betterSidebar']` → `registerTab()` / `registerFileViewer()` |
| 执行队列 / 定时 / 人工复核门 | `@linxin666/dsh-client-ui-task-board` | `ctx.taskBoard.registerExtension({id, apiVersion: 1, start(host){…}})` |
| 持久化（每张 BOM 一条记录） | `dsh-storage-json` + `dsh-storage-domain` | `ctx.storageDomain.open(defineDomain({…}))` |
| 长跑任务（比价） | `dsh-jobs` | 跑成 job，`job_output` 拉 |
| 交付物（报价单） | `present` 工具 | `present([{path}])` |
| 模型调用（判断） | `ctx.llm.prepareCall()` | **别用** `ctx.llm.stream` |
| HTTP 路由（给外部接口） | `ctx.webServer.register({kind:'exact', path, handler})` | —— |

---

## 4. 我的判断：三层架构

```
L3 交互层   侧边栏 / 设置页面板
            物料搜索 · 比价结果 · 黑名单 · 知识库浏览 · 红黑榜导入预览
                 │  （只读展示 + 触发动作）
L2 服务层   DSH 插件（profile 级包，双面：host 半 + client 半）
            暴露 tool（给 agent 调） + service（给别的插件用） + 只读 HTTP 路由
                 │  （不做判断、不内嵌提示词）
L1 能力层   skills/bom-sourcing/scripts/*.py + data/knowledge/*.yaml
            lcsc · pick · bom · spec · taobao · origin · distributor · blacklist · brands
```

### 4.1 插件长什么样（实测骨架，非推测）

```js
// lib/index.js —— ESM，导出四个具名绑定，没有 export default
import z from "@deepseek-ai/schemastery";
const name = "bom-flow";                  // 必须与 patch 里 id 一致
const inject = ["tools", "webServer", "storageDomain"];
const Config = z.object({ lcscQps: z.number().default(1) });
function apply(ctx, config) { /* 注册工具 / 路由 / 座位 */ }
export { Config, apply, inject, name };
```

```jsonc
// package.json 关键字段
{
  "type": "module",
  "main": "lib/index.js",
  "exports": { ".": "./lib/index.js", "./client": "./lib/client.js" },
  "dsh": {
    "bundle": { "patch": "./cordis.patch.yml" },   // 只 insert 自己，12 行以内
    "client": { "platform": "web", "inject": ["betterSidebar"] }
  },
  "engines": { "dsh": ">=0.2.1-rc.3 <0.3.0-0" }
}
```

安装：`dsh plugin --profile web add link:<绝对路径>`（**本地链接装，不发布**）。

### 4.2 为什么判断放 L2 外面

| 方案 | 判断在哪 | 问题 |
|---|---|---|
| A. 全塞进插件（插件内调 LLM） | 插件里 | 插件要管密钥/模型/提示词，DSH 一升级就炸一片 |
| B. 全留在 skill（现在） | 会话里 | 没有 UI，红黑榜/知识库没法"看" |
| **C. 混合（推荐）** | **接入的 agent** | 插件只做"暴露 + 展示"，agent 做判断，人做审核 |

方案 C 正好对上你说的：「不一定非要给人类用，但是有接口」。
**插件是接口，agent 是判断者，脚本是执行者。**

### 4.3 防炸六条（对应你说的"避免手写配置把 DSH 改炸"）

1. **不改 DSH 安装目录**（`app.asar` 只读，改了就等于是分叉）；
2. `cordis.patch.yml` **只做 insert，不做替换型条目**（替换型会整段覆盖默认 config，这是最危险的操作）；
3. 插件作为 **profile 级包**，用 `dsh plugin add link:` 安装，**不手改 profile 的 package.json / patch**；
4. 插件**不内嵌模型调用**：判断交给当前会话 agent（走 `ctx.llm.prepareCall` 也只在 host 侧受控调用）；
5. 写操作（黑名单、知识库）走「agent 提议 → 人确认 → 脚本落盘」，插件不直接写；
6. 先做**只读 PoC**，跑通再开写；回滚靠 patch 改名（`sanitizeProfile()` 会留 `.bak-<时间戳>`）。

### 4.4 发布路径

1. **先不发 npm**（`dsh-bom` 名字被占，别去撞）；
2. 走 **GitHub 源安装**（钉 commit，像 `dsh-pcb-parts-search` 那样）；
3. 想进市场要过 `plugin_manager` 预检：`engines.dsh` 写 `>=0.2.1-rc.3 <0.3.0-0`；
4. 提审到 `awesome-dsh-plugin.com`（`dshmarket` 唯一数据源）或 `dshplugin.net`。

---

## 5. 待你拍板的 6 件事

1. **插件边界**：只读展示 + 工具暴露，写操作走"提议→确认→落盘"，同意吗？
2. **红黑榜 Excel**：先做「解析 → 预览 → 你确认后写入」，**不自动裁决**，对吗？
   （解析规格已交付：`research\rbxlsx-spec.md`，17 条测试用例，`probe\rbxlsx\` 7 个自造样例全过）
3. **知识库审核流**：新条目默认 `draft`，你确认后转 `verified`（带出处链接），可以吗？
4. **物料面板 MVP**：搜索 / 比价 / 黑名单 / 知识库浏览 —— 四块够不够？还要不要红黑榜导入？
5. **品牌索引**：**已建好**（1,296 品牌，`data\knowledge\brands.index.yaml`）。
   要不要把它接进 `pick.py` 的品牌列（显示 tier / 是否在售），还是只留 CLI 查询？
6. **MOSFET 判据**：研究仍在跑（`research\mosfet-selection.md`），出来后我先给你**草案 + 5 个测试用例**审，
   还是直接入库？

---

## 6. 本轮已推进（不需要等批准）

- ✅ 品牌索引 `scripts\brands.py` + `data\knowledge\brands.index.yaml`（1,296 品牌，修复 22.3% 覆盖缺陷）
- ✅ 需求评估（本文）
- ✅ 三份研究：插件架构 / 市场范式 / 红黑榜 Excel 规格
- ⏳ MOSFET 判据研究（进行中）

---

## 附：相关文件

| 文件 | 内容 |
|---|---|
| `research\dsh-plugin-architecture.md` | 1,717 行：插件骨架、package.json 字段、ctx API 面、安装/调试/回滚、风险面 |
| `research\dsh-plugin-market-survey.md` | 797 行：4,704 条市场记录扫描、4 个先例拆解、可复用 service 表、分层建议 |
| `research\rbxlsx-spec.md` | 800 行：红黑榜 Excel 解析规格、v2 schema、17 条测试用例 |
| `research\mosfet-selection.md` | MOSFET 判据（进行中） |
| `scripts\brands.py` | 品牌索引构建/查询/覆盖率体检 |
| `data\knowledge\brands.index.yaml` | 1,296 品牌（brand_id → 名称/品类/料号数） |
| `probe\lcsc\probe_brand_coverage.py` | 品牌覆盖度探针 |
| `probe\mosfet\probe_mosfet_keys.py` | MOSFET 参数键覆盖率探针 |
