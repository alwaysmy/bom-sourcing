# DSH 插件市场调研：agent 化「BOM 配单插件」的先例与可复用能力

> 调研性质：**只读**。全程未安装、未卸载、未改任何插件配置，只读取包文件、市场索引与官方 SDK 文档。
> 调研对象：本机 profile 已装的 42 个 bundle / 241 条 plugin 行 + 社区全量索引 4,704 条 + DSH 核心 40 个 `@deepseek-ai/*` 包。
> 配套文档：需求侧评估见 `research\agent-plugin-assessment.md`；立创接口探测见 `research\lcsc-probe.md`、`research\market-probe.md`。
>
> 本文所有结论都标注了可复查的证据路径。**没有编造的插件名、service 名或 API**——凡是推断，都写成推断。

---

## 0. 结论摘要（五个问题，五个答案）

| # | 问题 | 结论 |
|---|---|---|
| 1 | 市场里有没有「agent-based + 面板 UI + 数据流」的成熟先例 | **有，而且不止一个。** `task-board` 是最完整的范式（host 权威账本 + 真实 session 执行 + 前端面板 + 定时 + 对外扩展契约）；`better-sidebar` 是「把 UI 位置当 API 卖」的范式；`dshmarket` 是「四件套分层」的范式 |
| 2 | 有没有物料/元器件/电商类插件 | **全市场 4,704 条里零命中**。`dsh-bom` 这个 npm 名已被占但**只有占名声明、无实现**。唯一的真实先例在 dshplugin.net（不是 awesome-dsh-plugin 索引）：`Huaqiu-Electronics/dsh-pcb-parts-search`。而**业务逻辑其实已经在 `bom-sourcing` skill 里** |
| 3 | 可复用的横切 service | 20 个 host service + 20 个 client slot + 5 个「插件之间互相提供」的 service。其中 `taskBoard` 与 `betterSidebar` 是唯二**明确为第三方插件设计**的扩展点 |
| 4 | 插件能直接调 LLM 吗 | **能。** `ctx.llm.stream()` 是受支持路径；`ctx.llm.prepareCall().stream()` 是官方 agent loop 用的更稳路径。另有 `ctx.agents.create()` 开子 agent、`ctx.commands.execute()` 跑斜杠命令。三条链路都存在 |
| 5 | BOM 配单插件该自写什么、复用什么都 | 自写：业务判断、知识库、Excel 解析、比价策略、黑名单。复用：面板壳（better-sidebar）、任务队列与执行（task-board）、文件预览（excel-panel / office）、存储（storage-json）、发布（dshmarket） |

**一句话**：这不是「从零造一个插件生态」，而是「**把已有的 `bom-sourcing` skill 挂到一个已经存在的双面插件范式上**」——host 半边做取数与判断，浏览器半边只做面板，两边用 cordis service 通信。

---

## 1. 调研方法与证据来源

### 1.1 四个证据面

| 证据面 | 位置 | 用它回答什么 |
|---|---|---|
| 本机已装插件 | `C:\Users\dell\.dsh\profiles\desktop\node_modules\` | 真实可运行代码长什么样 |
| 社区全量索引 | `https://cdn.jsdelivr.net/npm/dsh-plugin-catalog/index.json`（4.7 MB，4,704 条） | 市场里到底有什么、有没有同类 |
| DSH 核心 SDK | `app.asar` 内的 40 个 `@deepseek-ai/*` 包 README | 插件能调用哪些 service、契约是什么 |
| 插件评审站 | `dshplugin.net` | 索引外的、走 GitHub 源安装的插件 |

### 1.2 为什么必须解包 app.asar

早期假设 `~/.dsh/node_modules` 是 DSH 核心，**错了**：该目录不存在。DSH 核心全部打进
`C:\Users\dell\AppData\Local\Programs\DeepSeek Harness\resources\app.asar`（213,202,918 字节）。

`app.asar.unpacked\dsh\node_modules\@deepseek-ai\` 只有 3 个包（`dsh-session-log-export`、`libreoffice-kit`、
`libreoffice-kit-win32-x64`），其余 40 个包都在 asar 里。

已抽出 108 个文件（README + package.json + cordis.patch.yml）到
`C:\Users\dell\AppData\Local\Temp\dsh_asar_probe\out\dsh\node_modules\@deepseek-ai\<pkg>\`。

> **关键限制**：`@deepseek-ai/*` 包**不发布 `.d.ts`**。`lib/types/*.js` 是编译后 JS 带 JSDoc。
> 所以 API 事实只能从各包 `README.md` 取，不能靠 TypeScript 类型推断。

### 1.3 三个自建只读工具（可复用）

| 工具 | 作用 |
|---|---|
| `%TEMP%\dsh_asar_probe\asar_read.py` | 只读 ASAR 检查器。子命令 `top <path>` / `grep <substr>` / `extract <outdir> <substr...>` |
| `%TEMP%\dsh_asar_probe\asar_extract_pkgs.py` | 批量抽 `@deepseek-ai/*` 的 README + package.json + cordis.patch.yml |
| `%TEMP%\dsh_asar_probe\svc.py` / `svc2.py` / `slots.py` | 扫全 profile 的 `provide(` / `extends Service` / `slots.register(` 调用点 |

ASAR 布局（自己写工具时需要）：
`[0:4]uint32=4`、`[4:8]uint32=headerSize`、`[8:12]uint32=jsonSize+4`、`[12:16]uint32=jsonSize`、
`[16:16+jsonSize]` 是 UTF-8 JSON 目录树，文件载荷基址 = `8+headerSize`。
`walk()` 产出的路径**带前导 `/`**，取 key 时要 `.lstrip("/")`。

---

## 2. 前提：DSH 插件的双面结构

不理解这一层，会误以为「插件 = 一个跑在浏览器里的 JS」。实际不是。

### 2.1 一个 npm 包 = 两个进程里的两段代码

以 `@linxin666/dsh-client-ui-task-board@0.4.15` 的 `package.json` 为例：

```json
{
  "main": "lib/index.js",                      // host 半边：Node 进程
  "exports": { "./client": "lib/client.js" },  // 浏览器半边
  "dsh": {
    "bundle": { "patch": "./cordis.patch.yml" },
    "client": { "platform": "web", "inject": ["@deepseek-ai/dsh-client-locale", "...共 8 个"] }
  },
  "peerDependencies": { "@deepseek-ai/dsh": ">=0.2.2-rc.1", "react": "^18.2.0" }
}
```

- `main` 那半边在 **host 进程**（Node）里跑，能读文件、能调 LLM、能开 session。
- `exports["./client"]` 那半边在**浏览器**里跑，由宿主在 `/plugins/<id>/client.js` 提供，只能用 React 与客户端 service。
- **两边不能直接共享内存**，通信只有三条路：HTTP 路由（`ctx.webServer.register`）、
  类型化 RPC（`ctx.typertGateway`）、以及 cordis 的**同名 service**（两边各 `provide` 一次，靠名字对上）。

### 2.2 五个声明位

| 声明位 | 作用 | task-board 的实际值 |
|---|---|---|
| `dsh.bundle.patch` | 让 launcher 把这一行插进 cordis 装配 | `./cordis.patch.yml`（12 行，只有一个 `insert`） |
| `dsh.client.platform` | 声明「我有浏览器半边」 | `"web"` |
| `dsh.client.inject` | 浏览器半边的客户端依赖 | 8 个 `@deepseek-ai/dsh-client-*` |
| `dsh.bundle.platforms` | 可选，限定 Node 平台 | 省略（即全平台） |
| `dsh.bundle.listedByDefault` | 是否进默认 GUI 列表 | 省略（即 true） |

> 注意：`engines.dsh` 只是**作者声明**的兼容范围，**当前安装器与 loader 并不强制** `dsh.manifestVersion` 或 `engines.dsh`。
> 真正会拦的是 `plugin_manager` 在 pnpm 跑之前做的 `engines.dsh` + peerDependencies 检查（见 §5.5）。

### 2.3 三层注册点（这是「插件能挂什么」的完整清单）

```
第 1 层：host 进程的 service
  ctx.provide(name, face)          ← 发布自己的 service 给别人用
  ctx.get(name) / inject = [...]   ← 消费别人的 service
  ctx.webServer.register(route)    ← 暴露 HTTP 路由给浏览器半边
  ctx.systemPrompt.section({...})  ← 往模型提示词里塞一段
  ctx.tools.register(defineTool)   ← 注册 agent 工具
  ctx.commands.register({...})     ← 注册斜杠命令
  ctx.on('tools/pre-execute', ...) ← 拦截工具执行

第 2 层：浏览器进程的 slot
  ctx.slots.register({ name, key, locale, inject }, render)
  ctx.slots.inject(name, () => ...)   ← 往别人的槽位里挂

第 3 层：浏览器进程的 service
  ctx.provide(name, face)   ← 目前只有 5 个插件这么做
```

---

## 3. 问题 1：市场里有没有「agent-based + 面板 UI + 数据流」的成熟先例

### 3.1 结论

**有。** 而且这四个先例恰好覆盖了「BOM 配单插件」需要的四种能力，可以**分别抄**：

| 先例 | 它解决的业务问题 | 对 BOM 配单的对应 |
|---|---|---|
| `task-board` 0.4.15 | 任务要「关浏览器还在跑」、要有人审、要有执行历史 | 批量配单的**执行队列** + 人工复核门 |
| `skill-explorer` 0.4.14 | 知识/能力要能被浏览、启停、增删 | 元器件知识库、封装库、规则库的**管理面板** |
| `dshmarket` 1.73.9 | 生态内容要能被发现和安装 | 插件**发布与分发** |
| `better-sidebar` 0.28.2 | 面板位置本身要能当 API 卖 | 配单面板**挂载点** |

### 3.2 先例一：task-board —— 最完整的范式

#### 它解决什么问题

把「agent 任务」从**对话的附属品**变成**独立账本**：任务有自己的生命周期（todo → running → done/failed）、
自己的执行 session、自己的定时规则，**关掉浏览器仍然在 host 里跑**。

这正是 BOM 配单需要的形态：一张 BOM 表进来，几十行料要逐行判断，不能让用户盯着浏览器等。

#### 用了哪些注册点

`src/index.ts`（927 行）里的 `inject`：

```js
export const inject = [
  'systemPrompt', 'typertGateway', 'workspaceRegistry',
  'webServer', 'agents', 'commands'
];
```

另外**可选解析**（`ctx.get(name)`，缺了降级不报错）：`llm`、`tools`、`attachments`、`timer`、
`permissionPresets`、`sessionController`、`connection`。

发布自己的 service：

```js
const TASK_BOARD_SERVICE_NAME = "taskBoard";
ctx.provide(TASK_BOARD_SERVICE_NAME, { /* TaskBoardHostFace */ });
```

浏览器半边通过**同名 service** 对上：

```js
// lib/client.js:12
const TASK_BOARD_SERVICE_NAME = "taskBoard";
```

#### 代码结构怎么分层

```
packages/dsh-task-board/src/
├── index.ts             ← 装配：inject / provide / Config / apply
├── host-service.ts / host-ledger.ts / host-routes.ts    ← service / 权威账本 / HTTP 路由
├── host-runner.ts / host-ai.ts / host-spend.ts          ← 执行器 / LLM 裁决 / 额度
├── power-inhibitor.ts / mount-once.ts                   ← 防休眠 / HMR 幂等
├── core/                ← 纯逻辑，host 与 client 共享
│   ├── controller.ts / store.ts / tasks.ts
│   ├── schedule.ts      ← 5 段 cron；  subtask.ts ← 子任务深度 1..3
│   ├── verification.ts  ← 验收契约
│   └── use-cases/       ← task-create / task-update / task-archive / ...
├── host/                ← 只有 host 能做的事
│   ├── agent-tools.ts   ← 注册 task_board_* 工具
│   ├── llm-dispatch.ts  ← 调 LLM 的唯一入口
│   └── verification-gate.ts / workspace-evidence.ts
└── client/              ← 只有浏览器能做的事
    ├── service.ts       ← 发布 client 侧 service
    ├── host-api.ts      ← 打 host 的 HTTP
    └── native-panel.tsx + board/  ← TaskBoard / TaskCard / TaskDetail / ...
```

**这个分层值得直接抄**：`core/` 纯逻辑（可测）、`host/` 与 `client/` 各自只放本进程能做的事、
`index.ts` 只做装配。

#### 可抄的七个设计

1. **`mountOnce`** —— `export const apply = mountOnce('@linxin666/dsh-client-ui-task-board', applyImpl)`，HMR 重载不会重复注册。
2. **`Config` 用 schemastery** —— 标注成 volatile 的字段可在 GUI 热改不重启。
3. **service 名两边各定义一次常量** —— 不 import 对方的包，只对字符串。
4. **账本与执行分离** —— 账本是唯一权威，执行器只是消费者；重启后从账本恢复。
5. **`ctx.on('loader/volatile-update', () => sync())`** —— 配置变了主动同步，不轮询。
6. **工具族命名空间化** —— `task_board_list/get/create/update/set_parent/run/manage/schedule` 八个工具，前缀统一。
7. **给模型写整段中文公告** —— `TASK_BOARD_GUIDANCE`（`src/index.ts:60`），通过 `ctx.systemPrompt.section` 注入，
   告诉模型「有这个看板、怎么用、有什么约束」，而不是让模型自己从工具 schema 里猜。

### 3.3 先例二：skill-explorer —— 知识资产的管理面板

`@linxin666/dsh-client-ui-skill-explorer@0.4.14`（只有 `lib/`，已编译无 src）。

```js
// lib/index.js:1947
const name = "skill-explorer";
const inject = ["webServer", "skills", "sessions"];
```

它还额外 `ctx.get('loader', false)` 拿 loader entries，从里面反推 `skill-filesystem` 行声明的自定义 skill 根
（`lib/index.js:1970-1979` 的 `customSkillDirs()`）——**不去读别人的配置，而是读它注册进 loader 的行**。

> 这一点对 BOM 配单很有用：知识库目录（`data/knowledge/*.yaml`、`data/spec-rules.yaml`）
> 如果也走 `skill-filesystem` 的 provider 行声明，管理面板就能自动发现，不需要硬编码路径。

用户界面挂载点：`main`（主视图）+ `sidebar.panellist`（侧栏入口）。

### 3.4 先例三：plugin-market —— 四件套分层

市场不是一个插件，是**四个包各管一段**：

| 包 | 角色 | 关键事实 |
|---|---|---|
| `dshmarket` 1.73.9 | **GUI 与安装编排** | 56 个 `lib/` 模块；运行时依赖只有 `js-yaml` + `undici` |
| `@deepseek-ai/dsh-plugin-manager` | **profile 级管理服务 + `plugin_manager` 工具** | 装/卸/启停/版本兼容/锁 |
| `@deepseek-ai/dsh-plugin-market` | **索引读取器 + `plugin_market` 工具** | 索引源用户可配 |
| `@deepseek-ai/dsh-plugin-market-index` | **零依赖 format 1 校验库** | `parseMarketIndex` / `marketInstallTarget` |

`dshmarket` 的数据源：`lib/registry.js` 头注释写得很直白——

> 「Registry access: the curated list from awesome-dsh-plugin.com, **fetched fresh on every request**.
> See `loadRegistry` for why there is nothing behind it any more.」

即：**没有本地缓存**，每次请求现取 `https://awesome-dsh-plugin.com/plugins.json`。
（本机 `~/.dsh/dsh-market/` 只有 2 字节的 `printed-build-keys.json`，确认无 catalog 缓存。）

索引格式（实测）：

```jsonc
{
  "format": 1,
  "title": { "en": "Awesome DSH Plugin", "zh": "Awesome DSH Plugin 插件精选" },
  "metadata": { "categories": { "agi": {"title": {"en":"AGI Architecture Exploration","zh":"AGI 架构探索"}},
                                "ui":  {"title": {"en":"UI Enhancements","zh":"UI 增强"}},
                                /* 还有 usage theme model identity session memory tools
                                   workflow skill docs market fun vision security notify
                                   voice remote dev git browser 等 */ } },
  "plugins": [{
    "name": "dsh-foo", "title": "owner/repo",
    "description": { "en": "...", "zh": "..." },
    "homepage": "https://awesome-dsh-plugin.com/p/owner/repo/",
    "repository": { "url": "https://github.com/owner/repo", "directory": "optional" },
    "metadata": { "category": "tools", "keywords": [], "labels": [], "sortKeys": {} },
    "versions": [{ "version": "1.0.0", "publishTimestamp": 1793888987,
                   "source": { "type": "npm" }, "engines": { "dsh": ">=0.2.0 <0.3.0" } }]
  }]
}
```

`plugin_manager` 的版本兼容语义值得照抄：不满足时**在 pnpm 运行前**拒绝（`incompatible-version`，
带 `name/version/runtimeVersion/requirements` 四个字段）；豁免写在 profile 的 `compatibility.json`，
键是 `package-name@version` → 精确 DSH 版本列表，授予需要 `acceptRisk: true`。

### 3.5 先例四：better-sidebar —— 把 UI 位置当 API 卖

`dsh-better-sidebar@0.28.2`（另有 `@model-arena/dsh-better-sidebar@0.24.3`，同一插件两个作用域副本）。

文件头注释把定位写清楚了：

> 「The BetterSidebar client service: a registry that external plugins use to contribute sidebar tab types
> and file previewers. The service is published to the cordis context as `ctx.betterSidebar`; consumers
> declare it in `inject` and call `registerTab` / `registerFileViewer`, both returning a disposer that
> cordis auto-invokes on fiber disposal (HMR-safe).」

```ts
// lib/types/client/service.d.ts
export interface TabDescriptor {
  id: string;                                  // 也是 SidebarTab.type，如 'explorer' / 'my-plugin:db'
  title: string | (() => string);
  description?: string | (() => string);       // 新标签列表里的一行说明
  icon?: ReactNode | ((size: number) => ReactNode);
  order?: number;                              // + 菜单排序，默认 100
  hidden?: boolean;  bottomOnly?: boolean;     // 只在底部工作台出现
  available?: (ctx, scope, state) => boolean;  // 菜单里是否可选
  single?: boolean;                            // 单实例
  dedupeKey?: (tab: SidebarTab) => string | undefined;
  createTab?: (state) => { tab: SidebarTab; patch?: Partial<SidebarState> } | null;
  urlTarget?: (url: URL) => boolean;           // 认领外部链接点击
}
registerTab(descriptor: TabDescriptor): () => void;                            // service.ts:608
registerFileViewer(descriptor: FileViewerDescriptor): () => void;              // :609
openTab(seed: OpenTabSeed, scope?: SessionScope): void;                        // :692
matchFileViewer(path: string, head?: Uint8Array): FileViewerDescriptor | undefined;  // :669
```

版本协商与特性位：

```ts
export declare const SIDEBAR_SERVICE_VERSION = "0.28.2";
export declare const SIDEBAR_FEATURES = ["badge", "tabLifecycle", "updateTab", "openFile",
  "targetedOpen", "stateSubscription", "tabMeta", "pluginSettings", "urlTarget", "settingSelect",
  "fileIcons", "rightActions", "settingPatterns", "hostRouteUrl"] as const;
```

外部插件接入范式（`README.md:125-137`）：

```tsx
import type {} from 'dsh-better-sidebar';
export const inject = ['betterSidebar'];
ctx.effect(() => ctx.betterSidebar.registerTab({
  id: 'my-plugin:db', title: 'Database',
  component: ({ scope }) => <DbView sessionId={scope.sessionId} />,
}));
```

**安全边界（重要，`README.md:216-222`）**：路由在 Host header 信任栅栏后；
**自 v0.23.0 起 fs 路由不做 workspace 包含性检查**（能读写 host 用户可达的任意路径）；
HTML 预览走 opaque-origin sandbox iframe。做 BOM 插件如果复用它的 fs 路由，要自己加路径白名单。

### 3.6 四个先例的分层对照

| | task-board | skill-explorer | dshmarket | better-sidebar |
|---|---|---|---|---|
| host `inject` | systemPrompt / typertGateway / workspaceRegistry / webServer / agents / commands | webServer / skills / sessions | （有 host 半边） | —（纯 client） |
| 自己 `provide` | `taskBoard` | 无 | `market`（client 侧） | `betterSidebar` |
| HTTP 路由 | `host-routes.ts` | 有（`routes.map(r => ctx.webServer.register(r))`） | 有 | 有 |
| 系统提示词 | 有（`TASK_BOARD_GUIDANCE`） | 无 | 无 | 无 |
| agent 工具 | 8 个 `task_board_*` | 无 | `plugin_market`（在 core 包） | 无 |
| 斜杠命令 | 有（`ctx.commands.execute`） | 无 | 无 | 无 |
| 定时 | 5 段 cron（`core/schedule.ts`） | 无 | 无 | 无 |
| 持久化 | 账本文件 | — | profile package.json | 会话存储 |
| 前端挂载点 | `main` + `sidebar.panellist` | `main` + `sidebar.panellist` | `plugins.tab` + `settings.plugins.tab` + `sidebar.panellist` + `shell.overlay` | `sidebar.right.pane.tab` + `conversation.session.header.utilities` |
| 对外扩展契约 | ✅ 有（API version 1 + 3 个 seat） | ✗ | ✅ 有（`market.render`） | ✅ 有（`registerTab`） |

---

## 4. 问题 2：物料 / 元器件 / 电商类插件

### 4.1 本机：零

扫 `desktop\node_modules` 与 `web\node_modules` 顶层，**没有任何** lcsc / bom / component / parts /
datasheet / inventory 命名的包。

已装的 scope 目录：`@antfu @borewit @braintree @chevrotain @codemirror @deepseek-ai @formkit @iconify
@img @jimp @lezer @linxin666 @liustack @marijn @matrix-org @mermaid-js @model-arena @openviking
@pinojs @selderee @standard-schema @tencent-connect @tencent-qqmail @tokenizer @tt-a1i @types @upsetjs
@wecom @xmanrui @xterm @zone-eu`。
非 scope 插件包只有 8 个：`billion-context ds-bot dsh-better-sidebar dsh-context dsh-market-peek
dsh-plugin-upgrade dsh-rewind-plugin dshmarket`。

### 4.2 全市场 4,704 条：零

对 `dsh-plugin-catalog/index.json` 的 `plugins[]` 做 name + description(en/zh) 关键词扫描：

| 关键词 | 命中 | 说明 |
|---|---|---|
| `lcsc` / `szlcsc` / `立创` / `嘉立创` | **0** | — |
| `元器件` / `物料` / `元件` / `配单` | **0** | — |
| `datasheet` / `规格书` | **0** | — |
| `BOM` | 5 | **全是假阳性**：`dsh-fs-encoding` 的「UTF-8 BOM 原样保留」、`dsh-code-security` 的「SBOM-lite」等 |
| `digikey` / `mouser` | **0** | — |
| `easyeda` / `kicad` / `pcb` / `schematic` / `footprint` | **0** | — |
| `inventory` | 10 | 全是「数据资产清单」「依赖清单」，与库存无关 |
| `采购` | 1 | `dsh-ap-three-way`（应付三单匹配） |
| `报价` | 4 | 全是外贸/股市/设计报价，与元器件议价无关 |

> 复现脚本：`%TEMP%\dsh_asar_probe\scan2.py` 与 `scan3.py`，输出在 `bom_hits.txt` / `bom_hits2.txt`。

### 4.3 擦边但值得看的 8 个

| 插件 | 版本 | 做了什么 | 缺什么 |
|---|---|---|---|
| `@noob-stupid/dsh-breadboard` | 0.6.0 | 3D 面包板沙盒：摆 ESP32 / BME280 / PIR / LED，按协议与电压校验接线，Python 代码在环跑虚拟 I2C/GPIO | **不做选型与采购**，只做接线正确性 |
| `dsh-electro-lab` | 0.13.0 | 电气电子计算（SI 单位自描述复数值对象），附隔离计算 agent preset + 记录面板 | 不做取数与比价 |
| `multisim-mcp-dsh-plugin` | 1.3.1 | 接 Multisim MCP：生成电路、跑仿真、诊断优化、导出实验报告 | 仿真，不是配单 |
| `@aliangbaby/dsh-fusion-lean` | 0.9.3 | 接 Fusion 360 的 MCP（含 electronics 子域） | 机械/EDA，不是采购 |
| `dsh-ap-three-way` | 0.1.1 | 应付三单匹配：发票 / 采购订单 / 收货单，按容差策略匹配并导出异常底稿，4 个 `ap.*` 工具 | 电商采购流程，不是元器件 |
| `dsh-einvoice` | 0.2.1 | 中文电子发票（OFD/XML）收件箱：导入解析去重、复核队列、回执、本地归档，10 个 `invoice.*` 工具 | 发票，不是报价单 |
| `dsh-plugin-demian-trade-suite` | 1.0.1 | 外贸工作台：报价单、PI/CI/PL/合同/报关、装柜方案 | 外贸单证，不是物料 |
| `mackorn-cone-crusher` | 0.2.2 | 单缸液压圆锥破碎机**选型**与整线配置：需求表→设备选型→方案书→粒度仿真，21 工具 6 技能 1 MCP | 「选型」方法论可借，领域完全不同 |

**共同缺口**：没有一个碰到「**l 检索取数 → 参数比对 → 替代料 → 多渠道比价 → 报价单**」这条链。

### 4.4 唯一的真先例：`dsh-pcb-parts-search`

来源是 `dshplugin.net`（**不是** awesome-dsh-plugin 索引，是另一个评审站）：

- 地址：`https://dshplugin.net/zh/plugins/huaqiu-electronics-dsh-pcb-parts-search/`
- 仓库：`Huaqiu-Electronics/dsh-pcb-parts-search`，固定 commit `7b02c0492e06530c3c58638639351ea7878dde3e`
- 描述：**「从立创商城与 EDA 元件服务搜索电子器件和 IC 的模型工具」**
- 许可证：repo MIT / package MIT
- 状态：已审核，category 混合 `Search & Research`
- **安装生命周期：存在 `prepack` 脚本**（安全上要留意）
- 包身份：未记录
- `npm view @huaqiu-electronics/dsh-pcb-parts-search` → **404**，即**只走 GitHub 源安装，未发布到 npm**

**它做了什么**：把「立创 + EDA 元件搜索」包成模型工具。
**它缺什么**：只有搜索，没有 BOM 表格解析、没有参数比对、没有替代料推理、没有多渠道比价、没有报价单。
换句话说，它停在我们 `bom-sourcing` skill 的 `lcsc.py` 那一层。

### 4.5 `dsh-bom`：名字被占，没有实现

```
npm view dsh-bom
version: 0.0.1
description: Bom - the bill of materials - name reserved; first release in development.
```

**用它之前必须知道**：这是个**占名包**，`dsh-bom` 这个 npm 名已经不可用了。同套件还有
`dsh-workflow` / `dsh-selfrepair` / `dsh-finder`，同样只是占名。

### 4.6 真正的业务逻辑不在插件里，在 skill 里

`D:\WorkDesigns\3_WorkTools\skills\bom-sourcing\SKILL.md`（v0.2.0，25,711 B）已经是**完整实现**：

| 脚本 | 大小 | 职责 |
|---|---|---|
| `scripts/lcsc.py` | 42.6 KB | 检索 / 取价 / 详情 / 多料对比 / 替代料 + 6 小时缓存 |
| `scripts/pick.py` | 64.8 KB | 意图→品类→候选，`--param` 约束、`--package`、`--verify N`、`--taobao N` |
| `scripts/bom.py` | 26 KB | CSV/TSV/XLSX/纯文本解析 → 匹配 → 报价单 |
| `scripts/spec.py` | 22.2 KB | 阻值/容值/电感/耐压/精度/功率/频率/封装 + `function_check()` |
| `scripts/taobao.py` | 29.7 KB | 走 Kimi WebBridge 真浏览器比价 |
| `scripts/distributor.py` | — | Mouser 中国 / DigiKey 中国 |
| `scripts/origin.py` | — | 19 家原厂官方商城 |
| `scripts/blacklist.py` | — | 品牌/店铺/料号黑名单，写操作强制 `--authorized` |

数据层：`data/spec-rules.yaml`（113 KB，32 个 family 规则）、`data/categories.yaml`（32 KB，26 个 family
→ 中文品类名 + 立创 `catalogId` + 真实参数键 + 正向功能词 129 条 / 反向 238 条）、
`data/knowledge/{channels,risk-checklist,industry-norms,workflow,vendors,blacklist}.yaml`（`vendors.yaml` 144 个品牌）。

**已经踩过的坑（插件层不要再踩一遍）**：

- 立创 `catalogGroup` → `catalogIdFilter`（387 = 线性稳压器 LDO）；
- 参数区间筛选**立创没有服务端接口**，只能客户端过滤 `paramLinkedMap`；
- 多值筛选分隔符是 `$`，**用逗号会静默返回 0 条**；
- `pageSize > 30` 同样静默 0 条；
- QPS 上限 1；
- 精确型号下 `sortNumber` 几乎无效，要用品类词；
- 参数字段是**卖家填的**，缺项必须回手册；
- 参数满足 ≠ 功能对：`功率电子开关(969)` 里混着负载开关 / eFuse / 过压保护 / 同步降压转换器，
  实测 `MP4316GRE-Z` 会被误推；
- `*.lcsc.com` **不能走代理**；
- `datasheet.lcsc.com/{id}.pdf` 老直链已失效，要用 `atta.szlc.com` 签名直链。

明确未覆盖：立创参数区间服务端筛选、跨型号替代最终裁决（人工）、历史价格曲线/议价/交期、
1688 阶梯价、原厂商城（未完成）、**下单支付不做**。

探针原始响应（约 20 MB JSON）在 `D:\WorkDesigns\3_WorkTools\Bom_Flow\probe\`。

### 4.7 结论

- **市场里没有「BOM 配单」同类先例**，也没有任何元器件/物料/电商类插件。
- 最接近的是 `dsh-pcb-parts-search`（只有搜索）和 `easyeda-agent` / `dsh-kicad`（EDA 侧的 BOM 归一化）。
- **真正的护城河（知识库 + 参数判据 + 渠道策略 + 黑名单）已经在 `bom-sourcing` skill 里**，
  插件要做的不是重写它，而是**给它套一个 host 半边 + 一个面板**。

---

## 5. 问题 3：可复用的横切能力

### 5.1 host 侧 service 表

证据目录：`%TEMP%\dsh_asar_probe\out\dsh\node_modules\@deepseek-ai\<pkg>\README.md`

| service | 包 | 关键方法 | 对 BOM 配单的用途 |
|---|---|---|---|
| `ctx.llm` | `dsh-llm` | `stream()` / `prepareCall()` / `listProviders()` / `resolveModelInfo()` | **agent 判断的唯一入口**（见 §6） |
| `ctx.tools` | `dsh-tools` | `register()` / `execute()` / `restrict()` / `guard()` / `schemas()` | 注册 `bom_*` 工具 |
| `ctx.systemPrompt` | `dsh-system-prompt` | `section({name, order, text})` / `variable()` | 注入配单准则 |
| `ctx.commands` | `dsh-commands` | `register({name, description, handler, definitionId})` / `execute()` | `/bom`、`/pick` 斜杠命令 |
| `ctx.agents` | `dsh-agent` | `create()` / `resume()` / `get()` / `list()` / `withInitiator()` | 开子 agent 做逐行判断 |
| `ctx.fs` | `dsh-fs` | `resolve` / `readText` / `readBytes` / `editText` / `writeText` / `patchText` / `list` / `watch` / `moveFile` / `deleteFile` | 读 Excel、写报价单 |
| `ctx.storageDomain` | `dsh-storage-domain` | `await open(workspaceSpec)` | 打开存储域 |
| `json` backend | `dsh-storage-json` | 配置 `{root}`，`single` 或 `per-record` 布局 | 存 BOM 台账、缓存、黑名单 |
| `ctx.jobs` | `dsh-jobs` | `job_output` / `job_list` / `job_kill` | 长跑比价任务 |
| `ctx.attachments` | `dsh-attachment` | `saveFile` / `readFileStream` / `admitEncodedFile` / `imageHostPath` | 上传 Excel / 截图 |
| `ctx.fileUpload` | `dsh-client-file-upload` | `upload(sessionId, body, name, signal, onProgress)` | 浏览器拖文件进来 |
| `ctx.fileReferences` | `dsh-file-reference` | `list(agent, query, signal)` | @ 文件补全 |
| `ctx.workspaceRegistry` | `dsh-workspace` | `create(path, name)` / `list()` | 建配单工作区 |
| `ctx.sessionPersistence` | `dsh-session-persistence` | `create` / `open` / `stat` / `list` / `flush` | 执行历史 |
| `ctx.goals` | `dsh-goal` | `get(agent)` → detached 视图 | 长跑目标 |
| `ctx.skills` | `dsh-skill` | `register()` / `registerProvider()` | 把 `bom-sourcing` 包成插件内置 skill |
| `ctx.webServer` | `dsh-host-webserver` | `register(route)` / `port` / `getOrigin()` | 面板的 HTTP 后端 |
| `ctx.typertGateway` | `dsh-api-gateway` | `invoke()` / `stream()` | 类型化 RPC（比手写 HTTP 稳） |
| `ctx.web` | `dsh-web-search-deepseek` | `search()` | 查原厂资料 |
| `present` 工具 | `dsh-tool-present` | 入参 `files: [{path, description?}]` | 交报价单 |

### 5.2 client 侧 slot 表

扫全 profile 的 `ctx.slots.register/inject` 调用点（`%TEMP%\dsh_asar_probe\slots.py`）：

| slot 名 | 谁在用 | 用途 |
|---|---|---|
| `main` | task-board / skill-explorer / dsh-im | 主视图区 |
| `sidebar.panellist` | task-board / skill-explorer / dsh-im / dshmarket | 侧栏入口列表 |
| `sidebar.right.pane.tab` | better-sidebar ×2 | 右侧栏标签体 |
| `sidebar.right.pane.tab.title` | better-sidebar ×2 | 标签标题 |
| `sidebar.session.row.leading` | dsh-im | 会话行左侧图标 |
| `conversation` | dsh-plugin-upgrade | 对话区 |
| `conversation.view` | billion-context | 对话视图替换 |
| `conversation.input.dock` | git-graph | 输入框下方 |
| `conversation.chat.turnTail` | deep-view | 回合尾部 |
| `conversation.user.text.node` | deep-view | 用户消息文本节点 |
| `conversation.session.header` | ds-bot | 会话头 |
| `conversation.session.header.leading` | dsh-plugin-upgrade | 会话头左 |
| `conversation.session.header.utilities` | better-sidebar ×2 | 会话头工具区 |
| `settings.section` | better-sidebar ×2 / dsh-im / billion-context / dshmarket | 设置页分区 |
| `settings.plugin.item` | modsearch / dshmarket | 设置页插件条目 |
| `settings.plugins.tab` | dshmarket | 设置页插件标签 |
| `plugins.tab` | dshmarket | 插件页标签 |
| `plugins.bundle.config` | modsearch / billion-context / rewind / dshmarket | bundle 配置卡 |
| `plugins.detail.actions` | dsh-im | 插件详情动作 |
| `shell.overlay` | billion-context / better-sidebar / dshmarket | 全局浮层 |

### 5.3 插件之间互相提供的 service（只有 5 个）

这是「**给别的插件用**」的完整清单（`%TEMP%\dsh_asar_probe\services.txt` / `services2.txt`）：

| service 名 | 提供者 | 面 | 调用方式 | 证据 |
|---|---|---|---|---|
| `taskBoard` | `@linxin666/dsh-client-ui-task-board` | `TaskBoardHostFace`（host）/ `TaskBoardClientFace`（browser） | `ctx.taskBoard.registerExtension(ext)` | `lib/types/core/extension.d.ts:18,333` |
| `betterSidebar` | `dsh-better-sidebar` / `@model-arena/dsh-better-sidebar` | `BetterSidebarService` | `ctx.betterSidebar.registerTab(desc)` / `registerFileViewer(desc)` | `lib/types/client/service.d.ts:608-609` |
| `openvikingMemory` | `@openviking/dsh-memory-plugin` | runtime | `ctx.get('openvikingMemory')` | `lib/*/index.js`（`provide("openvikingMemory", runtime)`） |
| `dshIm` / `dshImClient` | `@xmanrui/dsh-im` | 宿主面 / 客户端面 | `ctx.get('dshIm')` | `lib/*/index.js`（`provide("dshIm", ...)` / `provide("dshImClient", Object.freeze({version:1, render}))`） |
| `market` | `dshmarket`（**client 侧**） | `{version:1, setSettingsVisible, settingsVisible, render}` | `ctx.get('market').render(props)` | `client\client.js:18502` |

### 5.4 重点：`taskBoard` 的扩展契约（最值得抄）

`lib/types/core/extension.d.ts` 是一份**教科书级的「插件给插件用」设计**：

```ts
/** Cordis service name the host and browser halves each publish. */
export declare const TASK_BOARD_SERVICE_NAME = "taskBoard";
/** Contract version. A provider declares the version it was built against;
 *  the board refuses (visibly) any other version instead of guessing at a stale shape. */
export declare const TASK_BOARD_API_VERSION = 1;
/** 三个子槽位 */
export declare const TASK_BOARD_DETAIL_SECTION   = "task-board.detail.section";
export declare const TASK_BOARD_SETTINGS_SECTION = "task-board.settings.section";
export declare const TASK_BOARD_CARD_DECORATION  = "task-board.card.decoration";
export declare const TASK_BOARD_PAYLOAD_LIMIT_BYTES: number;   // 单个 payload 的 JSON 字节上限
export declare const TASK_BOARD_MESSAGE_MAX_LENGTH = 4000;     // 推给模型的一条消息上限

export interface TaskBoardExtension {
  readonly id: string;                 // 稳定 id，也是 payload 的 key
  readonly apiVersion: number;
  enabled?(): boolean;                 // 使用时刻读，不在注册时快照
  start?(host: TaskBoardExtensionHost): void;
  stop?(): void;                       // 只释放工作，不清数据
  handleAction?(req: TaskBoardExtensionActionRequest): unknown | Promise<unknown>;
}
export interface TaskBoardExtensionHost {
  tasks: TaskBoardTasksFace;             // list / get / create / patchContent / setStatus / linked / rework?
  sessions?: TaskBoardSessionsFace;      // followUp(taskId, text)
  integration: TaskBoardIntegrationFace; // read / write（本插件私有的 payload）
  events: TaskBoardEventFace;            // onStatusChanged / onExecutionSettled / onTaskDeleted
  publish(summary: TaskBoardExtensionPayload): void;  // 给浏览器半边渲染用
  registerTool(definition: ToolDefinition): () => void;
}
```

**六个可以直接抄的设计决定**：

1. **API version 显式协商**——「refuses (visibly) any other version instead of guessing at a stale shape」。
2. **payload 是不透明 JSON**——board 只存不解释，且限字节数，防止一个 provider 撑爆账本。
3. **一个坏条目只丢自己**——`normalizeTaskIntegrations` 注释：「one malformed entry is dropped alone so a
   single bad provider can never take a card — or another provider's data — with it」。
4. **可选面用 `?` 而不是升版本**——`sessions?` 注释：「the API version stays 1, so a provider built
   against this revision probes the face and keeps working against a board that serves none」。
5. **事件回调互相隔离**——「a throw is logged and never interrupts the board's own execution path」。
6. **浏览器半边不 import 宿主包**——`resolveTaskBoardClientFace(ctx)` 按 service 名解析，
   拿不到返回 `undefined` 而不是抛，让 provider 优雅降级。

### 5.5 不可复用、但常被误认为可复用的

| 以为能复用 | 实际 |
|---|---|
| `fs-local` 与 `fs-sandbox` 同时挂 | **不能**，会因重复注册 `ctx.fs` 直接加载失败（`dsh-base` 限制） |
| 用 `engines.dsh` 拦不兼容版本 | 安装器与 loader **不强制**；真正拦的是 `plugin_manager` 的预检 |
| 手动改 cordis.patch 让插件生效 | HMR 或手改引起的 patch 变更**不发** `plugin-manager/changed` 事件 |
| 用 `dsh-plugin-market` 升级插件 | 它只有 `update-available` **状态**，没有升级动作；升级仍是「卸载再装」 |
| 市场索引可签名校验 | 索引**未签名**；`setIndexes` 整表替换（last write wins）；**拒绝重定向** |
| `single` 布局的 storage-json 做多进程写 | **无跨进程写锁**，last-completion wins；Windows 走 `MoveFileExW` 无 write-through |

---

## 6. 问题 4：「agent 执行判断」在插件里怎么落地

### 6.1 三条链路都存在

| 链路 | API | 特点 | 什么时候用 |
|---|---|---|---|
| **直接调模型** | `ctx.llm.stream({provider, model, messages})` | 一次性、无工具、无会话痕迹 | 单点判断（「这颗料是不是替代料？」） |
| **直接调模型（稳）** | `ctx.llm.prepareCall(config)` → `prepared.stream(request)` | 冻结路由与重试策略，一次性派发 | 同上，**推荐** |
| **开子 agent** | `ctx.agents.create({...})` | 有工具、有多轮、有 session | 整张 BOM 的处理流程 |
| **跑斜杠命令** | `ctx.commands.execute(agent, line, [], signal)` | 复用已注册命令 | 用户点了 `/bom xxx` |

### 6.2 为什么推荐 `prepareCall`

`src/host/llm-dispatch.ts`（87 行）的注释记录了一次**真实故障**：

> 第三方插件用 waterfall 签名 `(options, next)` 覆盖了 `llm.stream` 之后，`llm.stream(options)` 调用时
> `next === undefined`，抛 `TypeError: next(...) is not a function or its return value is not async iterable`，
> 导致看板两次裁判请求都失败，并记录「验收异常（裁判请求失败）」。

原因：`llm.stream(options)` 是**普通实例属性**（可被别的插件覆盖），
而 `llm.prepareCall(config)` 返回的是一次性冻结句柄，`prepared.stream(request)` 走**内部 dispatch**，
不经过那个可被覆盖的属性。官方 agent loop 用的是后者。

### 6.3 `ctx.llm` 的契约细节

- chunk 序列：`block-start` → `text-delta` → … → `usage` → `finish`；**每个流恰好一个终结 `finish`**
  （失败 `{kind:'error', failure}`，取消 `{kind:'aborted', failure}`）。
- 失败码（**按 code 路由，绝不按 message 文本**）：
  `NO_ADAPTER` `MISSING_CREDENTIAL` `AUTH` `RATE_LIMIT` `CONTEXT_WINDOW_EXCEEDED` `QUOTA`
  `ACCOUNT_QUOTA` `INVALID_CREDENTIAL` `DUPLICATE_ADAPTER` `INVALID_MODEL_INFO` `IMAGE_OFFLOAD_REQUIRED`。
- 采样只有 `temperature` / `maxTokens` / `stop`——**没有 `tool_choice` / `top_p` / penalty**。
- `ctx.llm` 本身**不重试**，重试归 `@deepseek-ai/dsh-llm-retry`。
- 不变量：**Model-visible ⟺ logged**（每次 provider 请求的模型可见输入必须能从 session log 重建）。
  loop 构造的请求到达时已 deep-frozen，监听者/适配器**只读不改**。
- `resolveModelInfo(provider, model)` → `{contextWindow, outputDefault, reasoning, inputModalities, systemPromptUpdate}`，
  配单场景可以用来判断「这张 BOM 塞不塞得进上下文」。

### 6.4 对「Excel 解析 → agent 判断」这条链路的意义

结论：**这条链路可以完全在插件内闭环，不需要用户手动开新会话。**

```
浏览器半边：拖入 .xlsx → ctx.fileUpload.upload(...) 或 ctx.attachments.saveFile(...)
   ↓
host 半边：bom.py 解析（复用 skill 里的解析器）
   ↓ 逐行循环
   lcsc.py 取候选（带 6h 缓存）
   ↓
   ctx.llm.prepareCall(...).stream(...)  ← 写一句结构化 prompt，要它输出 JSON
   ↓ 带 code 处理失败（RATE_LIMIT 退避、CONTEXT_WINDOW_EXCEEDED 拆行）
汇总 → 前端面板逐行展示 + 人工确认列
```

如果判断逻辑本身要多轮（比如「先查手册再定」），就升级成 `ctx.agents.create()` 开子 agent，
把工具给它（`ctx.tools.register` 已经注册的 `bom_*`），让它自己决定调几次。

---

## 7. 问题 5：BOM 配单插件该自写什么、复用什么都

### 7.1 必须自写（不可替代的护城河）

| 项 | 为什么不能复用 |
|---|---|
| **参数判据引擎** | `spec.py` + `spec-rules.yaml`（32 family）+ `categories.yaml`（26 family、129/238 功能词）是独有资产 |
| **立创取数适配** | `lcsc.py` 里的 6 个静默坑（`$` 分隔符、`pageSize>30`、QPS 1、`catalogIdFilter`、`sortNumber`、代理）都是实测出来的 |
| **替代料推理** | `function_check()` + 黑名单 + 品牌 tier，市场里没有任何东西能做 |
| **渠道策略** | 「少量买淘宝、批量走立创/1688」是业务决策，不是代码 |
| **Excel 解析** | 表头位置不固定、合并单元格、多 sheet——`bom.py` 已处理 |
| **知识库** | 144 品牌 / 438 别名 / 26 品类参数键，只能自己养 |

### 7.2 应该复用（不要重写）

| 需求 | 复用什么 | 怎么接 |
|---|---|---|
| 面板壳、右侧栏、文件预览 | `better-sidebar` | `inject = ['betterSidebar']` → `registerTab()` / `registerFileViewer()` |
| 执行队列、定时、人工复核门 | `task-board` | `ctx.taskBoard.registerExtension({id, apiVersion: 1, start(host){...}})` → 用它的 `tasks.create()` 建卡、`events.onExecutionSettled` 收结果 |
| Excel 预览 | `Melody-max114/dsh-excel-panel` | 只读预览；写回要自己算，别指望它 |
| Office 预览 | `HuanLinOTO/dsh-plugin-better-sidebar-plugin-office` | `.docx/.xlsx/.pptx` 只读 |
| 持久化 | `dsh-storage-json` + `dsh-storage-domain` | 配 `{root}`，`per-record` 布局存每张 BOM |
| 长跑任务 | `dsh-jobs` | 比价跑成 job，`job_output` 拉 |
| 交付物 | `present` 工具 | 报单直接 `present([{path}])` |
| 文件上传 | `dsh-client-file-upload` | 拖拽进来 |
| 模型调用 | `ctx.llm.prepareCall()` | **别用** `ctx.llm.stream` |
| 发布 | `dshmarket` 生态 | 见 §7.4 |

### 7.3 建议分层

```
bom-flow/
├── package.json              ← "main" + "exports[./client]" + "dsh".{bundle.patch, client}
├── cordis.patch.yml          ← 12 行以内，只 insert 自己
├── src/
│   ├── index.ts              ← 只做装配：inject / provide / Config / apply
│   ├── mount-once.ts         ← 抄 task-board
│   ├── core/                 ← 纯逻辑，无 IO，可单测
│   │   ├── bom-parse.ts      ← 包 bom.py
│   │   ├── spec.ts           ← 包 spec.py
│   │   ├── rules.ts          ← 读 spec-rules.yaml / categories.yaml
│   │   └── use-cases/
│   ├── host/                 ← 只有 Node 能做的
│   │   ├── lcsc-client.ts    ← 包 lcsc.py（注意 QPS 1）
│   │   ├── llm-judge.ts      ← prepareCall 封装
│   │   └── agent-tools.ts / routes.ts / store.ts   ← bom_* 工具 / 路由 / 台账
│   └── client/               ← 只有浏览器能做的
│       └── service.ts + host-api.ts + panel/  ← BomTable / RowReview / QuoteExport
└── data/                     ← spec-rules.yaml / categories.yaml / knowledge/*.yaml
```

**关键约束**：`core/` 不许 import `fs` / `http` / `react`——这样 host 与 client 两边都能用同一份解析逻辑。

### 7.4 发布路径

1. **先不发 npm**。`dsh-bom` 名字已被占，别去撞。
2. 走 **GitHub 源安装**（像 `dsh-pcb-parts-search` 那样钉 commit），在 profile 里写 `git+https://...#<commit>`。
3. 想进市场就要过 `plugin_manager` 的预检：`engines.dsh` 要写对（当前实测可用范围 `>=0.2.1-rc.3 <0.3.0-0`）。
4. 提审到 `awesome-dsh-plugin.com`（`dshmarket` 的唯一数据源）或 `dshplugin.net`（另一个评审站，
   `dsh-pcb-parts-search` 就在那）。
5. 注意 `dsh-pcb-parts-search` **带 `prepack` 生命周期脚本**——自己发布时如果不必要就别加，
   市场评审会把它当风险项记。

---

## 8. 附录

### A. 证据路径清单

| 主题 | 路径 |
|---|---|
| DSH 核心 SDK README（40 个包） | `C:\Users\dell\AppData\Local\Temp\dsh_asar_probe\out\dsh\node_modules\@deepseek-ai\<pkg>\README.md` |
| task-board 装配 | `C:\Users\dell\.dsh\profiles\desktop\node_modules\@linxin666\dsh-client-ui-task-board\src\index.ts` |
| task-board 扩展契约 | `...\@linxin666\dsh-client-ui-task-board\lib\types\core\extension.d.ts` |
| task-board LLM 派发 | `...\@linxin666\dsh-client-ui-task-board\src\host\llm-dispatch.ts` |
| task-board patch | `...\@linxin666\dsh-client-ui-task-board\cordis.patch.yml` |
| better-sidebar service | `C:\Users\dell\.dsh\profiles\desktop\node_modules\dsh-better-sidebar\lib\types\client\service.d.ts` |
| better-sidebar 接入范式 | `...\dsh-better-sidebar\README.md:125-137`（生态目录 139-193，安全边界 216-222） |
| dshmarket 清单 | `C:\Users\dell\.dsh\profiles\desktop\node_modules\dshmarket\package.json` |
| dshmarket 索引源 | `...\dshmarket\lib\registry.js` 头注释 |
| dshmarket market service | `...\dshmarket\client\client.js:18502` |
| skill-explorer inject | `...\@linxin666\dsh-client-ui-skill-explorer\lib\index.js:1947` |
| 市场全量索引 | `C:\Users\dell\AppData\Local\Temp\dsh_asar_probe\market-index.json`（4.7 MB / 4,704 条） |
| 关键词命中明细 | `%TEMP%\dsh_asar_probe\bom_hits.txt` / `bom_hits2.txt` |
| service 扫描结果 | `%TEMP%\dsh_asar_probe\services.txt` / `services2.txt` |
| slot 扫描结果 | `%TEMP%\dsh_asar_probe\slots.py` 输出 |
| bom-sourcing skill | `D:\WorkDesigns\3_WorkTools\skills\bom-sourcing\SKILL.md` |
| 立创探针原始数据 | `D:\WorkDesigns\3_WorkTools\Bom_Flow\probe\` |

### B. 复现命令

```powershell
# 1) 解包 @deepseek-ai 的 README
python "$env:TEMP\dsh_asar_probe\asar_extract_pkgs.py"
# 2) 拉全量市场索引
python "$env:TEMP\dsh_asar_probe\dl.py"
# 3) 扫元器件关键词
python "$env:TEMP\dsh_asar_probe\scan2.py"; python "$env:TEMP\dsh_asar_probe\scan3.py"
# 4) 扫插件间 service 与 client slot
python "$env:TEMP\dsh_asar_probe\svc.py"; python "$env:TEMP\dsh_asar_probe\svc2.py"
python "$env:TEMP\dsh_asar_probe\slots.py"
# 5) 查某个名字有没有被占
npm view dsh-bom version description
```

### C. 一句话复述

> 市场里**没有** BOM 配单插件，但**有**完整的「双面插件 + service 契约 + 面板挂载」范式可抄；
> 业务逻辑已经在 `bom-sourcing` skill 里；插件层要写的只是**装配 + 面板 + LLM 判断编排**这三件事。
