# DSH 插件架构：怎样安全地写一个插件

> **性质**：只读逆向 + 官方 README 交叉验证的技术报告，供后续实现评估。
> **本次研究遵守的禁令**：未修改任何 DSH 安装文件、未启用/禁用任何插件、未执行 npm publish。
> **日期**：2026-11-06

## 0. 环境基线（先纠正三处错误事实）

**路径别名**：`$DSH` = `C:\Users\dell\AppData\Local\pi-node\current\node_modules\@deepseek-ai\dsh`；`$PKG` = `$DSH\node_modules\@deepseek-ai`；`$HOME` = `C:\Users\dell\.dsh`。

**任务书的检出路径不存在**。`...\resources\app.asar\dsh\` 在 asar 归档内部，不是解包目录。实际可读的树只有两处：

1. `...\app.asar.unpacked\dsh\node_modules\@deepseek-ai\` —— 只有原生模块（koffi / node-pty / sharp / sherpa-onnx），**无插件源码**。
2. **`$DSH`** —— npm 安装的 `@deepseek-ai/dsh@0.2.1-rc.2`，约 300 个 `@deepseek-ai/*` 包在 `$PKG\<pkg>`。**这才是真源码**（`lib/bin.js`、`lib/plugin-BiveYA7h.js`、`lib/profile-boot*.js`、`lib/dump-config*.js`）。注意外层 `pi-node\current\node_modules\@deepseek-ai` **不存在**，只有 `dsh` 一个包。

**任务书的插件清单位置也错了**。`~/.dsh/profiles/web/node_modules` 实际只有 `.bin` `.pnpm` `@deepseek-ai` `@standard-schema` `dsh-cost-meter` `dsh-effort-slider` `dsh-lan-access` `nowledge-mem-deepseek-harness` `zod`。`dshmarket`/`dsh-better-sidebar`/`@linxin666/*`/`@openviking/*` 全在 **desktop profile**（`~/.dsh/profiles/desktop/node_modules/`）。**关键认知：一个 DSH 安装可以有多个 profile，每个有独立 `node_modules`，查插件必须逐 profile 找。**

**版本**：Node v24.19.0；pnpm 12.4.1；`dsh` = `pi-node\current\dsh.ps1` → `lib/bin.js`。
**证据规则**：没在代码里看到的注册点一律写"未找到证据"；所有 API 名/事件名/配置键都可用 `file:line` 复核。

---

## 1. 结论速览

| 问题 | 结论 |
|---|---|
| 基本形态 | **ESM 包，导出 4 个具名绑定** `{ name, inject, Config, apply }`；不是 `export default` |
| 必需字段 | `name`/`version` 必填；`dsh.bundle.patch` 指 patch 文件；`dsh.client` 声明浏览器半 |
| 模块格式 | 源码 ESM（`"type": "module"`）；**客户端 bundle 被 tsdown 打成 CJS 工厂**（`return module.exports;`） |
| UI 怎么挂 | `ctx.slots.inject(座位名, () => ctx.slots.register({...}, Component))`，两层 |
| 数据怎么存 | `ctx.storageDomain.open(defineDomain({...}))`，同步读 + 异步写 |
| HTTP | `ctx.webServer.register({ kind, path, handler })`，handler 完全拥有 response（SSE 直接持有） |
| 本地装 | `dsh plugin --profile <p> add link:<绝对路径>` |
| 热重载 | 服务端配置靠 `dsh-hmr`；**客户端代码必须 `pnpm run dev:web`** |
| 最危险 | 替换型 patch 条目（整段 `config` 被替换，不合并） |
| 回滚 | `sanitizeProfile()` 把 patch 改名 `.bak-<时间戳>`；或删 `insert` 段 |

---

## 2. Q1 — 插件基本形态

### 2.1 最小骨架

**证据**：`$PKG\dsh-tool-todo\lib\index.js`

```js
import z from "@deepseek-ai/schemastery";        // 配置 schema
import { defineTool } from "@deepseek-ai/dsh-tools";

const name = "tool-todo";                         // Loader 条目 id 断言
const inject = ["tools", "sessionProjections"];   // 依赖的 Cordis 服务
const Config = z.object({ allowParallelInProgress: z.boolean().required() });

function apply(ctx, config) {                     // 插件体，可 async
  ctx.tools.register(defineTool({
    name: "todo_write",
    description: describe(config.allowParallelInProgress),
    parameters: { todos: { type: "array", required: true } },
    output: { schema: { /* ... */ }, render: (_a, v) => [{ type: "text", text: "..." }] },
    execute(args, exec) {
      if (!exec.agent) throw new Error("todo_write requires an owning agent session");
      exec.agent.session.append("todo/write", { todos: args.todos });
      return Promise.resolve({ todos: args.todos });
    },
  }));
}

export { Config, apply, inject, name };           // ← 就是这四个名字
```

四个要点：**①** 没有 `export default`，cordis 用具名绑定约定。**②** `name` 是 Loader 条目 id 的断言（patch 写 `id: tool-todo`，插件也必须 `name = "tool-todo"`，否则 name mismatch）。**③** `inject` 是**服务名数组**（不是 npm 依赖），DSH 等到这些服务在 scope 可见才调 `apply()`。**④** `Config` 是 **Schemastery** schema（不是 zod / JSON Schema），同时承担默认值、类型、**设置页表单**（见 §4.4）。

### 2.2 服务型插件 = `Service` 子类

**证据**：`$PKG\dsh-jobs\lib\index.js`

```js
var JobRegistry = class JobRegistry extends Service {
  constructor(ctx) {
    if (new.target === JobRegistry) throw new Error("...abstract job registry seam; load @deepseek-ai/dsh-jobs-local instead");
    super(ctx, "jobs");                    // ← 注册成 ctx.jobs
  }
};
export { JobId, JobRegistry, JobRegistry as default };
```

官方大量使用「抽象 seam + 具体实现」两段式：`dsh-jobs`/`dsh-jobs-local`、`dsh-fs`/`dsh-fs-local`、`dsh-storage`/`dsh-storage-json`。`super(ctx, "jobs")` 第二参数即服务名；**同名重复注册抛错**。给别的插件用的服务**不需要 manifest 声明**。

### 2.3 `package.json` 需要哪些字段

**证据**：`$PKG\dsh-package-manifest\lib\types\types.d.ts`

```ts
interface DshPackageManifest {                  // :7-26
  name: string; version: string;                // 必填
  description?: string; icon?: string;          // icon ≤256 KiB，相对 manifest 目录
  private?: boolean;
  dependencies?: Record<string, string>;
  peerDependencies?: Record<string, string>;
  engines?: DshEnginesManifest;
  dsh?: DshManifest;
}
interface DshManifest {                         // :28-37
  manifestVersion?: 1;
  bundle?: DshBundleManifest;                   // 服务端半
  profile?: DshProfileManifest;                 // 只在 profile 包里
  client?: DshClientManifest;                   // 浏览器半
}
interface DshEnginesManifest  { dsh?: string; node?: string; npm?: string; [e: string]: string | undefined }  // :55-64
interface DshBundleManifest   { patch: string | string[] }       // :66-69，相对包根
interface DshProfileManifest  { bundles?: string[] }             // :71-74，有序
interface DshClientManifest   {                                  // :76-89
  platform: string;                        // Web 消费者选 'web'
  inject?: string[];                       // 信息性包名依赖，**不是**服务注入
  immediately?: boolean;                   // 启动第一阶段注册栅栏
  external?: string[];                     // 基础模块表之外的精确请求
}
```

`README.md:46`：一个 `patch` 可以是单路径或**有序列表**，按序应用为一个 bundle 层。

标准 bundle 包范例（`$PKG\dsh-base\package.json`）——注意 `dsh-base\lib\index.js` **只有 11 字节**（空 re-export），**bundle 包的运行时代码可以为空**，价值全在 patch 上：

```json
{
  "type": "module", "main": "lib/index.js", "types": "lib/types/index.d.ts",
  "exports": { ".": { "types": "./lib/types/index.d.ts", "default": "./lib/index.js" },
               "./cordis.patch.yml": "./cordis.patch.yml" },
  "files": ["lib/index.js", "cordis.patch.yml", "lib/types/**/*.d.ts"],
  "dsh": { "bundle": { "patch": "./cordis.patch.yml" } },
  "peerDependencies": { "@deepseek-ai/cordis": "~4.0.5" }
}
```

### 2.4 ESM 还是 CJS（分三层，别混）

| 层 | 格式 | 证据 |
|---|---|---|
| 插件源码 | **ESM** | `dsh-tool-todo\package.json` 有 `"type": "module"` |
| 服务端入口 `lib/index.js` | **ESM** | `import` / `export { }` |
| 浏览器入口 `lib/client.js` | **CJS 工厂** | 文件尾部 `return module.exports;` |

`@linxin666/dsh-client-ui-task-board\lib\client.js` 末尾：

```js
        exports.apply = apply;
        exports.inject = inject;
        return module.exports;
```

`$PKG\dsh-client-modules\README.md:72` 解释：

> Executing a plugin bundle only registers its factory; every module-body side effect (CSS injection included) lives in the factory closure and runs at materialization.

**含义**：客户端 bundle 求值时什么都不执行，只登记工厂；模块体（含 CSS 注入）要等 materialize。**别在 `lib/client.js` 顶层假定 DOM 就绪。**

### 2.5 双面插件（host + client 同包）

**证据**：`$PKG\dsh-client-ui-jobs\package.json`

```json
{
  "exports": {
    ".":        { "types": "./lib/types/index.d.ts",        "default": "./lib/index.js" },
    "./client": { "types": "./lib/types/client/index.d.ts", "default": "./lib/client.js" }
  },
  "dsh": { "client": {
      "inject": ["@deepseek-ai/dsh-api-job-controller", "@deepseek-ai/dsh-client-locale",
                 "@deepseek-ai/dsh-client-ui-conversation", "@deepseek-ai/dsh-client-ui-primitives"],
      "platform": "web" } },
  "scripts": { "bundle": "tsdown", "watch": "tsdown --watch" }
}
```

服务端半 `lib/index.js` 是**故意的空实现**（注释：这个入口存在只是让包在 Loader 里作为普通条目出现）：`function apply() {}` / `export { apply };`。
真正逻辑在 `lib/client.js:611-643`：

```js
const inject = ["jobs", "slots", "locale"];

function apply(ctx) {
  ctx.effect(() => ctx.locale.register("job", { zh, en }), "ui-jobs: dictionaries");
  ctx.slots.inject("conversation.session.header.actions", () => ctx.slots.register({
    name: "conversation.session.header.actions",
    id: "job-list", order: 20, locale: "job",
    inject: () => ({
      hooks:    { jobs: ctx.jobs.state },
      watchRows: (sessionId) => ctx.jobs.watchRows(sessionId),
      observe:   (sessionId, id) => ctx.jobs.observe(sessionId, id),
      killJob:   async (sessionId, jobId) => (await ctx.jobs.kill(sessionId, jobId)).ok,
    }),
  }, JobListAction));
}
exports.apply = apply; exports.inject = inject;
```

**三个易混点**：**①** 客户端 `apply` 的 `inject` 是 **Cordis 服务名**（`"jobs"`），与 manifest 的 `dsh.client.inject`（**包名**）是两个同名不同义的字段。**②** `ctx.effect(fn, label)` = 带 dispose 的副作用。**③** `ctx.provide(name, svc)` / `ctx.get(name)` 是**客户端侧**的服务注册/查找。

### 2.6 最小可运行插件（15 行）

`package.json`：

```json
{
  "name": "dsh-plugin-hello", "version": "0.0.1", "type": "module",
  "main": "lib/index.js",
  "exports": { ".": "./lib/index.js", "./cordis.patch.yml": "./cordis.patch.yml" },
  "files": ["lib/index.js", "cordis.patch.yml"],
  "engines": { "node": ">=22" },
  "dsh": { "manifestVersion": 1, "bundle": { "patch": "./cordis.patch.yml" } }
}
```

`cordis.patch.yml`：

```yaml
- insert:
    - id: hello
      name: dsh-plugin-hello
```

`lib/index.js`（10 行）：

```js
const name = "hello";
const inject = [];
function apply(ctx) { ctx.logger.info("[hello] mounted"); }
export { apply, inject, name };
```

**没有 `Config` 是合法的**（可选）。但一旦 patch 里给了 `config:` 键，就必须有 `Config` schema，否则配置校验失败（见 §6.2）。

---

## 3. Q2 — `ctx` 能做什么

| 能力 | 服务 | 证据 | 有实测范例 |
|---|---|---|---|
| 注册模型工具 | `ctx.tools` | `$PKG\dsh-tools\README.md` | 是（`dsh-tool-todo`） |
| 注册斜杠命令 | `ctx.commands` | `$PKG\dsh-commands\README.md` | 是（task-board） |
| 系统提示段 | `ctx.systemPrompt` | `$PKG\dsh-system-prompt\lib\types\index.d.ts:237,250` | 是 |
| UI 座位 | `ctx.slots` | `$PKG\dsh-client-ui-jobs\lib\client.js:611` | 是 |
| 设置页 | `Config`（Schemastery） | task-board `lib/index.js` | 是 |
| 服务给别的插件 | `Service` / `ctx.provide` | `$PKG\dsh-jobs\lib\index.js` | 是 |
| 持久化 | `ctx.storageDomain` | `$PKG\dsh-storage-domain\README.md` | 仅 README 示例 |
| HTTP 路由 | `ctx.webServer` | `$PKG\dsh-host-webserver\lib\types\index.d.ts` | 是（task-board） |
| 后台任务 | `ctx.jobs` | `$PKG\dsh-jobs\README.md` | 是 |
| 子 agent 会话 | `ctx.subagent` | 见 §3.7 | **未找到直接范例** |
| 事件总线 | `ctx.on` / `ctx.emit` | `$PKG\dsh-jobs\lib\index.js` | 是 |
| 日志 | `ctx.logger` | 同上 | 是 |

### 3.1 `ctx.tools` — 模型工具

**证据**：`$PKG\dsh-tools\README.md`

> Mount `dsh-tools` wherever agents call tools: it provides `ctx.tools`, the registry every tool plugin registers into and the loop dispatches through. **Registering a tool is enough to make it visible** — the registry feeds its schemas into the system-prompt assembly automatically.

```ts
import { defineTool } from '@deepseek-ai/dsh-tools'

ctx.tools.register(defineTool({
  name: 'read_file', description: 'Read a file from disk.',
  parameters: {
    path:   { type: 'string',  required: true, description: 'Absolute file path' },
    offset: { type: 'number' }, limit: { type: 'number' },
  },
  output: { schema: { type: 'string' }, render: (_a, v) => [{ type: 'text', text: v }] },
  async execute(args, exec) {
    return readFile(args.path, { encoding: 'utf8', signal: exec.signal })
  },
}))
```

- **参数 DSL**：`string` / `number` / `integer` / `boolean` / `null` / `array` / `object` / 仅作者可用 `json` / 精确一选 `oneOf`。`InferValue` 在 16 层容器内保精确类型。
- **配置**：`mode`（`native` 默认 | `ptc`）、`maxParallelSubCalls`（默认 10，`1` = 严格串行）。PTC 需组合 `ctx.ptcRuntime`。
- **按 agent 限制**：`restrict(filter)`（掩码取交集，dispose 解除）、`get(name, scope)`、`schemas(scope)`（拿 schema 不拿 `execute`）。
- **流水线（固定顺序）**：`tools/pre-execute` → 已注册单调 guard → `tools/execute` → `tools/post-execute` → 定义自有 `finalizeContent` → `tools/result`（只观测）。`guard()` 是**单调同步** guard，返回原因即拒绝，**后面的监听器无法翻案**；`tools/execute` 是**唯一可替换 required signal 的视图**。
- **反直觉**（README 明写）：`presentCall()` / `presentResult()` 在**内置 Web 客户端里不生效**。它走 `tool.call.toolview` 渲染器 + 从原始调用参数推导卡片。写自定义卡片要注册 toolview。

### 3.2 `ctx.commands` — 斜杠命令

**证据**：`$PKG\dsh-commands\README.md`

```text
ctx.commands.register({
  name: 'plan', description: 'Enter plan mode',
  input: { hint: '<message>' },
  handler: ({ agent, rawInput }) => ({ kind: 'success', text: 'plan mode selected' }),
})
```

命令与结果**都不进模型消息历史**；**同 scope 内同名注册抛错**。语法：`/` 必须在字节 0，名字只能小写字母/数字/`_`/`-`，空白之后全是 `rawInput`；未知名字/非法语法由适配器拒绝，**不会变成模型 prompt**。生命周期：`execute()` 先铸 `commandId` → handler 前 append `command/run` → settle 时 append `command/done`（独立 log-only append，无 turn 包裹）。附件：`input.attachments` 声明图片 + 通用文件，**声明缺失/存储缺失/receipt 未知/图片超限都在 handler 之前报错**。Agent 作用域：挂在 `agent.ctx` 下的命令只对那个 agent 生效并遮蔽全局同名定义（ScopedLayers）。

### 3.3 `ctx.systemPrompt` — 系统提示段

**证据**：`$PKG\dsh-system-prompt\lib\types\index.d.ts`

```ts
export declare class SystemPrompt extends Service {        // :237
  section(section: PromptSection): () => void;            // :250
  getSectionOrder(name: PromptSectionOrderName): number;
}
interface PromptSection {                                  // :47
  name: string;              // 唯一，重复注册抛错
  order: number;
  text: string;
  interpolate?: boolean;     // 默认 true；false 保留字面量
}
```

段按 `order` 升序拼接；**相同 order 按名字 code-unit 序**。

### 3.4 `ctx.storageDomain` — 持久化

**证据**：`$PKG\dsh-storage-domain\README.md`

```text
const workspaceSpec = defineDomain({
  name: 'workspace', version: 1,
  tables: { workspaces: domainTable(workspaceRecordSchema) },
})
const domain = await ctx.storageDomain.open(workspaceSpec)
await domain.table('workspaces').put(id, { path: '/work/demo' })
const record = domain.table('workspaces').get(id)   // 同步，从内存
domain.table('workspaces').update(id, (r) => ({ ...r, path: newPath }))
```

`defineDomain` 在**模块加载时**就失败（名字非法 / version 非负整数 / 全局 schema 接受 `null`）。**读同步**（从校验过的内存）；**写异步，resolve 前已落盘**，然后按写序 emit `domain/changed`。生命周期归调用方：`domain.close()`（通常放自己的 `ctx.effect` disposer）。后端路由 `backend`（必填）+ `routes`（域名 → 后端名），未知后端 open 时 `backend-not-found`。错误码 `already-open` / `facet-unsupported` / `invalid-record`（带表名+键）/ `missing-key` / `closed`；后端 `version-mismatch` 原样透传。**别用它的场景**：数据属于 session 事件日志时——那个面归 session 持久化层。

### 3.5 `ctx.webServer` — HTTP 路由

**证据**：`$PKG\dsh-host-webserver\lib\types\index.d.ts`

```ts
type WebRouteKind = 'exact' | 'prefix';                    // :32
interface WebRoute {                                        // :34-40
  kind: WebRouteKind;
  path: string;                                             // 绝对 pathname，无尾斜杠
  handler: (req: IncomingMessage, res: ServerResponse) => void | Promise<void>;
}
interface WebUpgradeRoute { path: string; handler: (req, socket: Duplex, head: Buffer) => ... }  // :42-47

declare class WebServer {
  get port(); get host(); get protocol(): 'http:' | 'https:'; getOrigin(): string;
  register(route: WebRoute): () => void;                    // 重复 (kind, path) 抛错
  registerUpgrade(route: WebUpgradeRoute): () => void;      // 重复 path 抛错
  registerFallback(handler): () => void;                    // 只能一个 owner
  tapIndex(transform: (html: string) => string): () => void;
}
```

**三条刻意的抛错**（composition 契约）：`register` 重复 `(kind,path)`；`registerUpgrade` 重复 path（"一个 socket 只能有一个协议 owner"）；`registerFallback` 第二个（"两个 fallback 无法组合"）。**handler 完全拥有 response 生命周期**——SSE 直接不返回即可。

**配置**（`:60-88`）：`host` 必须是具体 IP 字面量（**未指定地址在 load 期被拒**）、`port`（0 = OS 分配）、`tls: { certFile, keyFile }`（只读一次，换证书要重启）、`compression: 'none'|'gzip'`、`compressionLevel`、`compressionThresholdBytes`（默认 1024）。

**task-board 用法**（`lib\index.js:12572`）：`for (const route of routes) disposers.push(ctx.webServer.register(route));`
路由：`/state`（`:10721`）、`/action`（`:10733`）、`/events`（`:10775`，SSE）、`/parse`（`:10827`）、`/verification`（`:10887`）、`/attachments/upload`（`:10906`）、`/attachments/image`（`:10958`）。

### 3.6 `ctx.slots` — 客户端座位

**证据**：`@linxin666/dsh-client-ui-task-board\lib\client.js:13025-13052`

```js
function registerTaskBoardPanel(ctx, controller) {
  const slots = ctx.slots;
  const disposers = [];

  disposers.push(slots.inject("sidebar.panellist", () => slots.register({
    name: "sidebar.panellist", id: TASK_BOARD_PANEL_ID, order: PANEL_ORDER,
    label: () => t("entry.label"),
  }, TaskBoardPanelIcon)));

  disposers.push(slots.inject("main", () => slots.register({
    name: "main", key: TASK_BOARD_PANEL_ID,
    children: {
      "task-board.detail.section":  { kind: "list", scope: "root" },
      "task-board.card.decoration": { kind: "list", scope: "root" },
    },
    inject: () => ({ controller }),
  }, TaskBoardPanel)));

  return () => { for (const dispose of disposers.splice(0)) dispose(); };
}
```

**两层**：`slots.inject(座位名, callback)` 等座位被声明 → `slots.register({ name, id/key, order, children, inject }, Component)` 登记内容。

**为什么必须包 `inject`**（源码注释 `:13014-13024`）：

> Both seats are declared by shell plugins this package does not depend on at runtime, so each registration is wrapped in `ctx.slots.inject`: the callback runs only after the owning entry declares the seat, and a shell that never declares it leaves the board simply absent instead of failing boot.

**踩坑**：`ctx.slots.inject()` **只在声明存在时跑回调**。座位名被上游删了，UI 会**静默消失**——无错误、无日志、构建不失败（见 §6.5 的 `C1` 缝）。

### 3.7 未找到证据的注册点

| 能力 | 状态 |
|---|---|
| **发起子 agent 会话** | `$PKG\dsh-subagent*` 存在，但**没找到第三方插件直接 `ctx.subagent.*` 起会话的范例**。task-board 是通过 `task_board_run` **工具**间接驱动。**未找到证据**说明 `ctx.subagent` 的公开注册面。 |
| **`ctx.fs`** | `dsh-fs` / `dsh-fs-local` / `dsh-fs-sandbox` 存在，**未读到服务面类型定义**。**未找到证据**。 |
| **"241 条 plugin 行"精确条数** | `~/.dsh/profiles/web/cordis.patch.yml` 24 757 B，**未做全量行计数**。`dsh-web-app\README.md:101` 只说"one patch layer of five files plus one runtime glue plugin"。 |
| **官方脚手架** | `$PKG` 下**不存在** `guide` / `template` / `scaffold` / `create` / `init` 类包。 |

---

## 4. Q3 — agent-based 插件的既有范式

主案例：`@linxin666/dsh-client-ui-task-board@0.4.15`（host 侧执行 + 前端面板，任务书点名的最复杂形态）。

### 4.1 最小 patch 行（664 B 全文）

```yaml
# dsh-task-board bundle patch: inserts the dual-face plugin row into the web
# profile roster. Applied as a profile bundle layer (the `dsh.bundle.patch`
# manifest field) over dsh-base; activate with
# `dsh plugin --profile <name> add link:~/code/dsh-web-ui/packages/dsh-task-board`.
#
# The row is a bare plugin by package name: the node half (exports ".") runs
# in the host process (the system-prompt announcement section), and the
# `dsh.client` declaration in package.json makes the browser half
# (exports "./client", served at /plugins/<id>/client.js) load in the web GUI.
- insert:
    - id: ui-task-board
      name: '@linxin666/dsh-client-ui-task-board'
```

**就 5 行有效代码**。`id` = Loader 条目 id（也是插件 `name` 断言的来源），`name` = 包名。

### 4.2 宿主半的 `inject` 清单

**证据**：`lib\index.js:12104-12111`

```js
const inject = ["systemPrompt", "typertGateway", "workspaceRegistry", "webServer", "agents", "commands"];
```

实际用到的 `ctx.*`（去重）：`agents`、`attachments`、`commands`、`effect`、`get`、`inject`、`logger`、`on`、`provide`、`systemPrompt`、`typertGateway`、`webServer`、`workspaceRegistry`。

### 4.3 Config 即设置页（最值得抄的范式）

```js
const Config = z.object({
  announceToAgent:           z.boolean().default(false).volatile(),
  enabled:                   ..., preventIdleSleep: ...,
  trustedProxyHosts:         z.array(z.string()).default([]),
  proxyTokenEnv:             z.string().min(1).default(DEFAULT_PROXY_TOKEN_ENV),
  trustForwardedProxy:       ...,
  sessionDefaultPermission:  z.union(TASK_PERMISSIONS),
  maxSubtaskDepth:           z.number().min(1).max(3).default(1).volatile(),
  sessionPollSeconds:        ..., runLaunchWidth: ..., spendBudgetTokens: ...,
  goalRunEnabled:            ..., cardDefaultMode: ..., cardDefaultPermission: ...,
  cardDefaultModel:          ..., cardDefaultReasoningEffort: ..., goalVerification: ...,
});
```

文档注释逐字：

> **This schema IS the board's settings page**: the 0.1.7 Host serves one configuration form per profile entry from the entry's own Config, so the fields the browser card edits are marked volatile — the Loader commits an edit into the running fiber's references without remounting the row (no settings document of the plugin's own exists any more). A field without the marker is refused by the settings write path, which fences writes on volatility.

**四条规则**：**①** 设置页不用单独写——Schemastery `Config` 自动变表单。**②** 可热改字段必须标 `.volatile()`，没标的被设置写入路径拒绝。**③** 读值必须现读，不能捕获；配套 helper `readConfigField(field, fallback)`（注释：Loader 把 volatile 字段作为稳定引用就地提交，所以活值要在使用时读）。**④** Loader emit `'loader/volatile-update'`：

```ts
declare module '@deepseek-ai/cordis' {
  interface Events { 'loader/volatile-update'(paths: readonly (readonly string[])[]): void }
}
```

### 4.4 故意不注入的可选服务

task-board 有一组 resolver，**故意不写进 `inject`**：`resolveConnectionTrust(ctx)`、`resolveToolRegistry(ctx): AgentToolRegistry | undefined`、`resolveHostTimers(ctx): HostTimerFace | undefined`、`resolveProxyAccess(config, env)`。

原因：`inject` 会导致**服务不存在时插件根本挂载不了**。这些是可选的增强能力，用 `ctx.get(name)` 探测，探不到就降级。

```ts
type AgentToolRegistry = {
  register(definition: ToolDefinition): () => void;
  get?(name: string, scope?: unknown): unknown;
};
```

**这是"可独立部署插件"的关键技巧**：核心依赖写 `inject`，锦上添花用 `ctx.get()` 软探测。

### 4.5 客户端半的座位策略（一条极重要的经验）

**证据**：`lib\client.js:15323-15364` 注释 + `:15695-15706` 调用

注释列的座位：`web-ui.plugin.item`（`dsh-web-settings` 组 section 声明的列表座位，本家族自己的"Web UI plugins"节）、`plugins.bundle.config`（官方 plugin manager 页的**键控**座位，按 bundle 包名键控）。

> alpha.2 removed the `settings.plugin.item` keyed seat of the `ui-settings-plugins` tab that this helper used before, so a card keyed by its settings namespace has no seat to land in any more.
>
> **SEAT SELECTION IS NOT A DECLARATION PROBE.** The official plugin surface belongs to the harness bundle and declares its seats before any external plugin's `apply()` runs, so "is the official seat declared?" answers yes even in the deployment whose whole point is the family group. Choosing on that probe sends every family card to the official page and leaves the group's own section permanently empty.

**即：绝不能用"官方座位是否已声明"选座位**——它永远是已声明的。真正的判据是"`dsh-web-settings` 是否加载"（它 `apply()` 时发布 `webUiSettings` 服务）。并且在 `slots/changed` 上重新求值，迁移时**先 dispose 旧的再注册新的**，保证卡片不会同时出现在两个座位。

### 4.6 其它插件对照

| 插件 | 版本 | 形态 | 备注 |
|---|---|---|---|
| `@openviking/dsh-memory-plugin` | 0.5.32 | 只有 bundle，**无 client** | 纯服务端；peer `dsh-llm`/`dsh-mcp-client`/`dsh-skill-filesystem` |
| `dshmarket` | 1.73.9 | bundle + client | 只 peer 一个 `dsh-settings`，范围跨多个 rc 线 |
| `ds-bot` | 0.2.6 | bundle + client | peer 全 `*`（最宽松，等于不设防） |
| `billion-context` | 0.1.212 | bundle + client | 只有一个 `engines.node`，无 dsh 约束 |
| `dsh-better-sidebar` | 0.28.2 | bundle + client | 14 个 peer 全 `^0.2.1-rc.1`（最严格） |
| `@linxin666/*` | 0.4.x | bundle + client | 用**嵌套** `dsh.engines.dsh`（见 §7.2，**别学**） |

**`dsh.engines.dsh` 的发现**：`@linxin666` 家族写 `"dsh": { "engines": { "dsh": ">=0.2.2-rc.1" } }`，但 `DshManifest`（`types.d.ts:28-37`）**只有 `manifestVersion`/`bundle`/`profile`/`client`**，没有 `engines`。官方位置是**顶层** `engines.dsh`。**这个嵌套写法无效**——它能"生效"纯属同包还写了顶层 `peerDependencies["@deepseek-ai/dsh"]`，兼容门走了 peer 分支。**不要照抄。**

---

## 5. Q4 — 开发 / 调试 / 安装

### 5.1 profile 是什么

**证据**：`$PKG\dsh-app-boot\README.md:50`

> A profile lives at `$DSH_HOME/profiles/<name>`, combining installable bundles with its own `cordis.patch.yml`.

本机 profile：`~/.dsh/profiles/{web,desktop,headless,node_modules}`

```
~/.dsh/profiles/web/
├── package.json          ← dsh.profile.bundles[]（有序）
├── cordis.patch.yml      ← 用户覆盖层（24 757 B）
├── cordis.yml            ← 223 B
├── pnpm-lock.yaml / pnpm-workspace.yaml
├── node_modules/
├── .plugin-manager/      ← 运行记录 + 日志
└── *.bak-*               ← 时间戳快照
```

`~/.dsh/profiles/web/package.json` 逐字：

```json
{
  "name": "dsh-profile-web", "private": true,
  "dependencies": {
    "dsh-cost-meter": "^1.8.15",
    "dsh-effort-slider": "link:D:/ChatWorkspace/dsh-effort-slider",
    "dsh-lan-access": "^0.1.3",
    "nowledge-mem-deepseek-harness": "github:nowledge-co/nowledge-mem-deepseek-harness"
  },
  "dsh": { "profile": {
      "bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app", "dsh-lan-access",
                  "nowledge-mem-deepseek-harness", "dsh-cost-meter", "dsh-effort-slider"],
      "patchReload": "live"
  } }
}
```

**三种依赖写法**：`^1.8.15`（普通 npm）｜`link:<绝对路径>`（本地开发）｜`github:owner/repo`（Git）。`patchReload: "live"` = 这个 profile 启用了 HMR。

### 5.2 `cordis.patch.yml` 长什么样

**证据**：`~/.dsh/profiles/web/cordis.patch.yml` 头部注释（逐字）

```yaml
# Your patch layer for this dsh profile, applied after every bundle layer:
# a top-level YAML array of loader patch entries (id-targeted config overrides,
# disables, and insert lists; `!!js` expressions allowed).
```

**只能是最外层 YAML 数组**。三种条目：

```yaml
# ① 替换型
- id: webserver
  config:
    host: 0.0.0.0
    port: !!js ctx.webStartup.port ?? 3080
    compression: gzip
    compressionLevel: 1
    compressionThresholdBytes: 1024

# ② 插入型
- insert:
    - id: mcp-everything-search
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: everything-search
        transport: stdio
        command: C:/Users/dell/.agents/skills/everything-search/bin/everything-search-mcp.exe

# ③ 禁用型
- id: some-plugin
  disabled: true
```

**语法规则**（`app-boot\README.md:61`）：

> A patch replaces the targeted row's whole `config`, so each web row restates every key it owns.

**`config` 是整段替换，不是深度合并**。只改 `port` 也要把 `host`/`compression` 全重写。命名不存在的条目 → **stderr 警告**（不炸）。**空文件或只有注释 → 启动失败**，停用这一层写 `[]`。`!!js` 在启动时求值。路径：双引号标量用正斜杠 `C:/...`；反斜杠用单引号。

本机 patch 的实战注释：

```yaml
# 每个服务器 = 一个 mcp-client 插件实例
# 工具以 `mcp__<serverName>__<tool>` 暴露给模型
# 本文件变更会被 HMR 热加载
# 改完必须重启 DSH，MCP 工具表才会重新握手
#   （HMR 只重载插件配置，不会重启已存在的 MCP 子进程 —— 实测 2026-09-16）
# 回滚：删掉本段即可恢复插件默认
```

### 5.3 本地未发布插件怎么装

**`dsh plugin` 就是 pnpm 透传器**（`dsh plugin --help` 逐字）：

```
manage a profile's plugins by forwarding the remaining arguments to pnpm in the
profile directory

Arguments: args   pnpm arguments, forwarded verbatim (add <pkg>, remove <pkg>, why <pkg>, ...)
Options:   --profile <name>   the profile whose plugins to manage (initialized on first use)
```

所以所有 pnpm 安装形态都可用：

```powershell
dsh plugin --profile web add link:D:/ChatWorkspace/my-plugin        # 本地目录
dsh plugin --profile web add link:../my-plugin                       # 相对路径
dsh plugin --profile web add file:D:/build/my-plugin-0.0.1.tgz      # tarball
dsh plugin --profile web add github:owner/repo                        # Git
dsh plugin --profile web add my-plugin@0.1.0                          # npm
```

**装完还要两步**：**①** 在 `package.json` 的 `dsh.profile.bundles[]` 追加包名（`plugin_manager` 自动做，手写 `pnpm add` **不会**）。**②** 在 `cordis.patch.yml` 加 insert 行（**除非包自带 `dsh.bundle.patch`**）。

`plugin_manager\README.md:40`：

> A bundle toggle changes `package.json`'s ordered `dsh.profile.bundles` list. Disabling retains the dependency; enabling appends the bundle at the end (can change precedence).

**`plugin_manager install_bundle` 能装本地目录吗？能。** `README.md:44` 说 `source` 是 "a spec `pnpm add` accepts (git address/URL, `file:`/`link:` made absolute, registry range/tag/alias)"；`README.md:50` 补 "Source Web and development Desktop offer `link:<absolute workspace package directory>`"。**前置条件**：`pnpm install` + `pnpm run build`；"Linked packages use that checkout's dependencies and peers; rebuilding and restarting remain necessary after code changes."

### 5.4 热重载（两套独立 HMR，别混）

| 层 | 包 | 管什么 | 怎么开 |
|---|---|---|---|
| 宿主 | `dsh-hmr` | profile manifest + 两个 patch 文件 | profile 的 `dsh.profile.patchReload: "live"` |
| 客户端 | `dsh-client-hmr` | 浏览器 bundle 重载 | `pnpm run dev:web` |

**宿主限制**（`app-boot\README.md:63`）：`dsh-hmr` 监视 profile manifest 和两个用户 patch 文件，重读有序 bundle 层，应用重载失败策略。**Launcher 不装 HMR 也不装 watcher**；没有 HMR 就要重启。

**客户端机制**（`$PKG\dsh-client-hmr\README.md`）：

> `dsh-client-hmr` keeps open Web pages in sync with the Host plugin graph and reloads rebuilt browser bundles. Ordinary plugin enable/disable changes take effect without reloading the page or restarting the Host. Code rebuilds replace the affected plugin with fresh component state.
>
> Run `pnpm run dev:web`, which starts the host and the rebuild watchers together… rebuilt plugins are then swapped into the running browser automatically, one at a time.
>
> **React state inside the reloaded plugin is lost, while session, workspace, and connection state survives.**

**回答任务书**："热重载对插件生效吗（客户端插件是否要 `pnpm run dev:web`）？"
**是。客户端插件的代码改动必须 `pnpm run dev:web`。** 只改配置不需要——那是 `dsh-hmr` 的活。实现：宿主半监视每个包的 stamped entry artifact，通过 `/plugins/events` 发 SSE（`graph`/`rebuilt` 帧）；浏览器半用 `__DSH_TRANSPORT__.fetch`（若 shell 提供）或 `EventSource`。`pollIntervalMs` 默认 500。

**客户端 bundle 构建链**（`$PKG\dsh-client-modules\README.md`）：`:54` "The host serves built client bundles, so `pnpm run build` must have produced each `lib/client.js` before launch; a missing bundle fails activation loudly with one build instruction and a package/path list."；`:78` 组合路由 `/plugins/??...&rev=...`，每个 phase 在 URL 超 3 KiB 前分区，revision 由 `mtimeMs`/`ctimeMs`/size 推导（**不做内容哈希**）；`:76` "**Distinct active Loader sources resolving to one package name are rejected.**"；`:134-140` 限制：metadata 型 revision、扁平模块图（设计如此）、**"Source launch has no build step for the Host half"**、替换 bootstrap 需刷新页面。

### 5.5 调试手段

| 手段 | 用途 | 出处 |
|---|---|---|
| `dsh --profile web --dump-config` | **打印精确的组合条目树**，`!!js` 原样保留，按源文件分组并标注哪些 patch 层改过。**排查"插件到底加载了没"的第一工具** | `app-boot\README.md:71` |
| `--dump-config-schema` | 打印每个组合条目的 JSON Schema。**会 import 每个模块**——只在信任的 profile 上跑 | `:79` |
| `--dump-default-config` | 打印不含用户层的 profile 树，区分"bundle 带的" vs "我加的" | `dsh --help` |
| `--patch <path>`（可重复） | 额外叠一层 patch，**不写进 profile**，适合试错 | `dsh --help` |
| `--from-default-profile <template>` | 用官方模板重建 profile。**最干净的回滚**——建新名字，不动原来的 | `:50` |
| `plugin_manager list_plugins` / `list_bundles` | 只读，不改任何东西 | — |

shipped 模板（`app-boot\README.md:50`）：`web`、`headless`、`acp`、`sdk`、`sdk-minimal`；本机实际 `web`、`desktop`、`headless`。**只有 `web` 模板用 live reload**，其它只在启动时应用 patch。

---

## 6. Q5 — 风险面

### 6.1 会把 DSH 改炸的操作（按危险程度）

**① 替换型 patch 忘重写字段（最高频）** —— 例如只写 `- id: webserver` + `config: { port: 3081 }`，则 `host`/`compression`/`tls` 全丢。正确做法：改前先 `--dump-default-config` 看清原值，全部重写。

**② 空 patch 文件** → **启动失败**（只有注释也不行）。停用写 `[]`。

**③ 改 `agent-instructions` 行（本机已踩过）**。`~/.dsh/AGENTS.md` 记录逐字：

> 该入口在本 deployment 内改不动：web 组合把 host 层的 `agent-instructions` 行禁用了（`dsh-web-app/cordis.patch.yml:464`），真正生效的那一行由 **agent preset** 承载（`dsh-agent-presets/presets/<id>/agent.cordis.yml`）→ 从 profile / home patch 覆盖无效（按该思路写过一版并重启验证，入口仍未切换，已撤并在 patch 里留注释）。

**教训**：`agent-instructions` 入口由 **agent preset** 决定，profile patch 改不动。要改只能做自定义 preset，而那会一并改变 agent 平面的工具与 persona。

**④ 动 agent preset 的 composition** —— `plugin_manager\README.md:140-144` 明确禁止：manager "cannot disable its own management components, change another profile, or edit an agent preset's composition"。

**⑤ 改 `engines.dsh` 的 peer band**。`P1` 缝（逐字）：

> `P1` is a blocker. Never collapse the peer range to `>=0.1.2-rc.1 <0.2.0`: under npm semver's prerelease-tuple rule it rejects `0.1.5-rc.1` (measured `false` on semver 7.8.5).

`D1` 缝：

> The host compares the runtime version to your declared `engines.dsh` / dsh peer ranges and refuses the install or restart when it does not match. A band that still ends at `<0.2.0` is not "old but working": it cannot be installed on the 0.2.x host at all.

**⑥ 在 detached async 里抛异常** —— 直接打死整个 app，见 §6.2。

### 6.2 失败矩阵

**证据**：`$PKG\dsh-app-boot\README.md:92-113`

| 失败点 | 可选条目 | 必需条目 |
|---|---|---|
| 模块 import 失败 | warn + 继续 | 停止启动 |
| config schema 校验失败 | warn + 继续 | 停止启动 |
| `!!js` 求值抛错 | warn + 继续 | 停止启动 |
| `disabled: !!js` 求值抛错 | warn + 继续 | 停止启动 |
| 同步 `apply()` 抛错 | warn + 继续 | 停止启动 |
| 异步 `apply()` 抛错 | warn + 继续 | 停止启动 |
| 注入的服务不可用 | warn + 继续 | 停止启动 |
| HTTP 端口绑定失败 | warn + 继续 | 停止启动 |
| **detached async 未捕获 rejection** | **FATAL** | **FATAL** |
| **同步回调里抛错**（stream `'data'`、timer） | **FATAL** | **FATAL** |

**"FATAL" = dispose 整个 app 并非零退出，跟条目 id 无关。**
必需条目（`:92-113`）：`agent-loop`、`webserver`、`web-runtime`、`modules`、`connection`、`headless-runner`、`acp`、`sdk-jsonrpc-server`。
兜底（`:43`）：`installFailLoud('dsh')` 写一条带标签的 `util.inspect` 诊断，等 release hook（固定超时），退出 1。

**这条最坑**：`setTimeout` 回调里忘了 `try/catch`，整个 Web GUI 就没了，报错信息还跟你改的插件毫无关系。

### 6.3 兼容性门（唯一"官方会拦你"的地方）

**证据**：`$PKG\dsh-app-boot\lib\index.js:252-336`

```js
function satisfies(runtimeVersion, range) {
  return range.trim() !== "" && semver.satisfies(runtimeVersion, range, { includePrerelease: true });
}

function unmetRequirements(fields, runtimeVersion) {
  const engines = Object.hasOwn(fields, "engines") ? objectOf$1(fields.engines, "Plugin manifest engines") : {};
  if (Object.hasOwn(engines, "dsh")) {
    const range = engines.dsh;
    if (typeof range !== "string") throw new Error("Plugin manifest engines.dsh must be a string");
    return satisfies(runtimeVersion, range) ? {} : { "engines.dsh": range };     // ← 提前返回
  }
  if (!Object.hasOwn(fields, "peerDependencies")) return {};
  const dependencies = objectOf$1(fields.peerDependencies, "Plugin manifest peerDependencies");
  const unmet = {};
  for (const [name, range] of Object.entries(dependencies)) {
    if (typeof range !== "string") throw new Error(`Plugin manifest peerDependencies[${JSON.stringify(name)}] must be a string`);
    if (name !== "@deepseek-ai/dsh" && !name.startsWith("@deepseek-ai/dsh-")) continue;
    if (!satisfies(runtimeVersion, ["workspace:^","workspace:~","workspace:*"].includes(range) ? runtimeVersion : range)) unmet[name] = range;
  }
  return unmet;
}
```

**四条硬规则**：**①** **`engines.dsh` 一旦存在，`peerDependencies` 完全被忽略**（`:281-285` 提前返回）。**②** 没有 `engines.dsh` 时，**每一个** `@deepseek-ai/dsh` 或 `@deepseek-ai/dsh-*` peer 都必须满足。**③** `workspace:^` / `workspace:~` / `workspace:*` **只在 peer 里合法**；写在 `engines.dsh` 里就是无效 range（必然不满足）。**④** **预发布参与 range 匹配**（`includePrerelease: true`）——`>=0.2.0` **匹配不了** `0.2.1-rc.2`。

`getDshRuntimeVersion()`（`:271-275`）读的是 **app-boot 自己的 `package.json`**，不是 `dsh` CLI 的。拒绝文案（`:333-336`，逐字）：

```
Plugin ${key} is incompatible with dsh ${issue.runtimeVersion}: requirements ${JSON.stringify(issue.requirements)}.
Running it may cause crashes or data loss. Update the plugin or install a plugin version compatible
with this dsh runtime. To accept this risk explicitly, grant the exact-version exemption for ${key}
on dsh ${issue.runtimeVersion} with `dsh plugin allow-version` or the plugin manager, then retry the
installation or restart dsh. Exact-version exemption: ${issue.exempted ? "active" : "not active"}.
```

**两个执行点**：bundle 加载（`loadProfileDirectory` → 不兼容 bundle 被 skip，列进 `skippedBundles`）；安装/重启（`pluginManager.installBundle` → 拒绝码 `incompatible-version`）。

**免责声明**（`app-boot\README.md:52` 逐字）："These checks are not a sandbox against malicious package code."
**兼容性门只防"版本对不上"，不防恶意代码。** 插件在宿主进程内、workspace sandbox 之外执行（`plugin_manager\README.md:31`）。

### 6.4 版本豁免（"我知道有风险，让我装"）

**证据**：`plugin_manager\README.md:56, 71`

存在于 profile 自己的 **`compatibility.json`**（**不是** `package.json`），结构是精确 `package-name@version` → 精确 DSH 运行时版本列表。**插件升级和 DSH 升级都不继承权限**；文件缺失 = 无豁免；**格式坏掉不阻止启动**（能接受的记录照常生效，被拒记录报 stderr，然后文件变只读）。

```text
plugin_manager: list_version_exemptions → set_version_exemption { target, runtimeVersion, enabled }
```

授予还需 `acceptRisk: true`，且必须先警告可能崩溃或丢数据并拿到**该精确版本对**的明确许可。

```powershell
dsh plugin --profile web version-exemptions
dsh plugin --profile web allow-version <package@version> --dsh-version <runtime> --accept-risk
dsh plugin --profile web revoke-version <package@version> --dsh-version <runtime>
```

### 6.5 回滚机制

**① `sanitizeProfile()`**（`app-boot\README.md:69`）：

> filesystem recovery without loading plugins: renames `cordis.patch.yml` to unique `.bak-<timestamp>` sibling and restores the supplied bundle list, preserving installed packages and other manifest fields.

签名 `sanitizeProfile(binName, profileDir, bundles): string | undefined`。时间戳 = Unix 毫秒，碰撞追加 `-1`/`-2`；返回备份路径或 `undefined`；profile 初始化会在下次启动重建空 patch；**home 层 patch 不动**；**非法 profile JSON 在任何改动之前就失败**。这解释了 `~/.dsh/profiles/web/` 里那些 `.bak-*` 的来历。

**② 手动回滚** —— 删掉 patch 的 `insert` 段（本机 patch 注释原话："回滚：删掉本段即可恢复插件默认"）。

**③ 安装失败自动回滚**（`plugin_manager\README.md:52, 104, 162`）："Installation failure restores the profile manifest and lockfile." / "A failed/cancelled package run or failed bundle validation restores manifest + lockfile snapshotted before pnpm ran." / "Restoration rewrites only those two files; user-authored patch config, application data, diagnostic logs, downloaded files remain untouched."
**注意**：只恢复 `package.json` + `pnpm-lock.yaml`。**你手写的 patch 配置不会回滚。**

**④ 社区升级走廊**（`dsh-plugin-upgrade@2.2.0`，非官方）把"跨版本迁移"固化成可执行扫描器：三条封闭走廊 `legAB`（20 缝）/ `legC`（5 缝）/ `legD`（5 缝 + 建议段）；路由器 `lib/route.mjs` 从仓库声明的 band 自动选走廊（`--span legAB|legC|legD` 覆盖）；扫描器 `scripts/scan-0.1.5.mjs` → `lib/scan.mjs` / `lib/scan-0.1.6.mjs` / `lib/scan-0.2.mjs`；零依赖，`file:line` 输出，error 级命中退出码 1。

**它点出的两类"绿灯也能过"的失败（最值钱的经验）**：**stale-type false green**（本地门编译的是旧类型线——`tsconfig` 的 `paths` 别名指向不存在的目录，TypeScript 静默回退到已发布类型）、**silent non-mount**（宿主丢掉某个贡献，**无错误、无日志、构建不失败**）。

**退出标准**（逐字）：

> Real-host smoke is the exit criterion. Temp `DSH_HOME` (mkdtemp) + target CLI + `dsh plugin --profile web add <tarball>` + `--dump-config`. **Never touch the user's real `~/.dsh`.**

### 6.6 官方推荐的隔离做法

| 场景 | 做法 | 出处 |
|---|---|---|
| 试用新插件 | 建**新 profile** 名，不动生产 profile | `app-boot\README.md:50` |
| 试一层配置 | `--patch ./extra.yml`（不写 profile） | `dsh --help` |
| 跑未知插件前 | `--dump-config-schema` 会 import 代码，**只在信任的 profile 上跑** | `app-boot\README.md:79` |
| 真实宿主 smoke | 临时 `DSH_HOME`（mkdtemp） | `plugin-upgrade\SKILL.md` §2.9 |
| 插件权限 | 需 `danger-full-access` 或逐次批准；**批准不改变 session 权限模式** | `plugin_manager\README.md:31` |
| 依赖构建脚本 | 单独审批（与插件安装分开） | 同上 |

**最重要的一条**（`plugin_manager\README.md:31` 逐字）：**"installed Host code executes in-process outside the workspace sandbox."**
**插件不是沙箱化执行的。装一个插件 = 给它宿主进程的完整权限。**

---

## 7. Q6 — 打包发布

### 7.1 npm 包名规范

17 个第三方插件的实测形态：

| 形态 | 例子 |
|---|---|
| 无 scope + `dsh-` 前缀 | `dsh-better-sidebar`、`dsh-context`、`dsh-plugin-upgrade`、`dsh-rewind-plugin`、`dsh-market-peek` |
| 无 scope 无前缀 | `dshmarket`、`billion-context`、`ds-bot` |
| scope + `dsh-` | `@linxin666/dsh-client-ui-task-board`、`@openviking/dsh-memory-plugin`、`@model-arena/dsh-better-sidebar`、`@xmanrui/dsh-im`、`@tt-a1i/archify-dsh` |
| scope 无 dsh | `@liustack/modsearch` |

**没有强制规则**——`billion-context`/`ds-bot`/`@liustack/modsearch` 都不含 `dsh`。但 `dsh-` 前缀是事实标准，且 official 包全是 `@deepseek-ai/dsh-*`。
**推荐起步**：`@<scope>/dsh-plugin-<名字>` 或 `dsh-plugin-<名字>`；**双面包惯例** `dsh-client-ui-<名字>`（镜像官方 `dsh-client-ui-*`）。

### 7.2 `engines.dsh` 版本约束（最容易搞错）

**正确**（顶层 `engines`）：

```json
{
  "engines": { "node": "^22.19.0 || >=24.0.0", "dsh": ">=0.2.1-rc.2 <0.3.0-0" },
  "peerDependencies": {
    "@deepseek-ai/dsh-tools": "^0.2.1-rc.2",
    "@deepseek-ai/cordis": "~4.0.5"
  }
}
```

**错误**（`@linxin666` 家族的做法，别学）：`{ "dsh": { "engines": { "dsh": ">=0.2.2-rc.1" } } }`。`DshManifest`（`types.d.ts:28-37`）只有 `manifestVersion`/`bundle`/`profile`/`client`，**没有 `engines`**，兼容门读不到它。

**三条实测经验**：**①** **预发布要显式写**——`>=0.2.0` 不匹配 `0.2.1-rc.2`。**②** **别写 `*`**——`ds-bot` 用 `*` 等于完全不设防。**③** **锁上界**——`dsh-plugin-upgrade` 写 `>=0.2.1-0 <0.3.0`，`dsh-rewind-plugin` 写 `>=0.2.1-rc.1 <0.3.0-0`；**上界是必须的**，否则 0.3 破坏性变更会静默装进来。

**只有 `@deepseek-ai/dsh` 和 `@deepseek-ai/dsh-*` 会被检查**（`:291`）：`if (name !== "@deepseek-ai/dsh" && !name.startsWith("@deepseek-ai/dsh-")) continue;`。把 `react` 写进 peer 完全不影响兼容门。

### 7.3 是否必须 official 才能出现在 marketplace

**不是。但默认什么都不会出现。** `$PKG\dsh-plugin-market\README.md`：

> Config: `indexes` (default `[]` — **no index source is configured by default, so the Host sends no market request until a user adds one**)

**official 是 DSH 安装侧的属性，不是包声明**——17 个 manifest 里全都没有 `official` 字段。由两处决定：随 DSH 一起 ship 的 bundle，或 `OFFICIAL_ON_DEMAND_CATALOG` 里内嵌的按需包（`app-boot\README.md:89`：`ON_DEMAND_BUNDLES` 列出只按需安装的 public Official 包，`pnpm gen-official-bundle-catalog` 更新、`verify-official-bundle-catalog` 校验）。

**安装状态值域**：`not-installed`（按需目录里有但 profile 没装也是这个）｜`installed`｜`update-available`｜`different-version`｜`provided`（"for a bundle the DSH installation ships"）。

**市场索引格式**（`$PKG\dsh-plugin-market-index\README.md`）：format 1 JSON；导出 `parseMarketIndex`、`marketInstallTarget`、`MarketIndexError`（带 `path`+`reason`）、`MAX_INLINE_ICON_BYTES` = 32 KiB。安装目标：npm → `name@version`；Git → `git+<url>.git#<commit>`（+ `&path:/<path>`）。验证器不管什么（逐字）："**Generator obligations are unchecked** — the validator cannot verify that `name`, `version`, `publishTimestamp`, `engines.dsh`, or display fields match the package they describe, or that the package declares a bundle."
**即：市场索引里的元数据可以全是假的。** 安装时会去 npm 拉真包，但索引本身不校验一致性。

### 7.4 本地私有插件怎么给用户装

按侵入性从低到高：

```powershell
# ① tarball（最简单，无需 registry）
pnpm pack                                                             # 你这边
dsh plugin --profile web add file:D:/path/dsh-plugin-hello-0.0.1.tgz  # 用户那边

# ② Git 仓库（可私有）
dsh plugin --profile web add github:your-org/dsh-plugin-hello
dsh plugin --profile web add git+https://gitee.com/your-org/dsh-plugin-hello.git#v0.0.1

# ③ 本地目录链接（开发期）
dsh plugin --profile web add link:D:/ChatWorkspace/dsh-plugin-hello
```

`plugin_manager` 会先 `git ls-remote`（`README.md:54`，超时 `githubConnectionTimeoutMs` 默认 5000 ms，失败报 `failedAt: 'spec-host'`）。**registry 包、路径、tarball 和其它 Git 宿主跳过此检查**。

**④ 私有 npm registry**（`plugin_manager\README.md:56` 逐字）：

> Registry order: `options.registry` → configured `registry` (`null` = the one pnpm names) → `fallbackRegistries` (default `['https://registry.npmmirror.com/']`). A registry outside the configured set is asked alone (**private registry never falls through to public**).

**⑤ 自建市场索引** —— 写符合 format 1 的 JSON，让用户把 URL 加进 `indexes` 配置（`pluginMarket.setIndexes()` 通过 `settings.update` 写入）。

**给用户的安装说明必须含四步**（缺一不可）：`dsh plugin add <spec>` → 在 `dsh.profile.bundles[]` 追加包名（`pnpm add` **不会**自动做）→ 在 `cordis.patch.yml` 加 insert 行（**除非包自带 `dsh.bundle.patch`**）→ 重启 DSH（**除非 profile 开了 `patchReload: "live"` 且只改了配置**）。

---

## 8. 最小插件骨架 + 三条最容易踩的坑

### 8.1 最小插件骨架（可直接复制）

```
dsh-plugin-hello/
├── package.json
├── cordis.patch.yml
└── lib/index.js
```

**`package.json`**：

```json
{
  "name": "dsh-plugin-hello",
  "version": "0.0.1",
  "description": "Minimal DSH plugin",
  "type": "module",
  "main": "lib/index.js",
  "exports": {
    ".": "./lib/index.js",
    "./cordis.patch.yml": "./cordis.patch.yml"
  },
  "files": ["lib/index.js", "cordis.patch.yml"],
  "engines": { "node": "^22.19.0 || >=24.0.0", "dsh": ">=0.2.1-rc.2 <0.3.0-0" },
  "dsh": { "manifestVersion": 1, "bundle": { "patch": "./cordis.patch.yml" } }
}
```

**`cordis.patch.yml`**：

```yaml
# 顶层必须是 YAML 数组。空文件会让 DSH 启动失败 —— 停用请写 []
- insert:
    - id: hello
      name: dsh-plugin-hello
```

**`lib/index.js`**：

```js
const name = "hello";                 // 必须与 patch 的 id 一致
const inject = ["systemPrompt"];       // 依赖的 Cordis 服务

function apply(ctx) {
  ctx.logger.info("[hello] mounted");
  const dispose = ctx.systemPrompt.section({
    name: "hello", order: 500,
    text: "When the user greets you, reply with a haiku.",
  });
  ctx.effect(() => dispose, "hello: system prompt section");
}

export { apply, inject, name };
```

**安装**：

```powershell
dsh plugin --profile web add link:D:/ChatWorkspace/dsh-plugin-hello
# 再在 ~/.dsh/profiles/web/package.json 的 dsh.profile.bundles[] 追加 "dsh-plugin-hello"
dsh --profile web --dump-config | Select-String hello     # 验证
```

### 8.2 三条最容易踩的坑

**坑 1：`export default` 而不是具名导出。**
cordis 要的是**具名绑定** `{ name, inject, Config, apply }`。写 `export default { apply }` **不报错**——插件只是**永远不激活**：`--dump-config` 里能看到条目，但 `apply()` 从不被调用，没有任何日志。
**自查**：`grep -n "^export" lib/index.js` 应看到 `export { apply, inject, name };`。

**坑 2：客户端座位名被上游删了 → UI 静默消失。**
`ctx.slots.inject()` **只在座位声明存在时才跑回调**。座位名拼错或被上游删掉（例如 alpha.2 删了 `settings.plugin.item`），结果是：无错误、无日志、构建不失败、**UI 就是不见了**。
**自查**：改完必须在**真实浏览器**里确认 UI 出现。干净的 scanner + 绿的 `typecheck` **都不是证据**（`plugin-upgrade\SKILL.md` 硬规则 7 逐字）。**并且**：不要用"官方座位是否已声明"选座位——它永远是已声明的；要用"某个服务是否发布"判断部署形态（§4.5）。

**坑 3：detached async 里抛异常 → 整个 app 挂掉。**
失败矩阵里，**未捕获 rejection 和同步回调抛错是 FATAL，跟条目 id 无关**（`app-boot\README.md:92-113`）。

```js
// 千万别这样
setTimeout(() => { doSomethingRisky(); }, 1000);          // 抛了 → 整个 DSH 退出
emitter.on("data", () => { throw new Error("oops"); });   // 抛了 → 整个 DSH 退出

// 应该这样
setTimeout(() => { try { doSomethingRisky(); } catch (e) { ctx.logger.error(e); } }, 1000);
emitter.on("data", () => { void handleData().catch((e) => ctx.logger.error(e)); });
```

**为什么最坑**：报错堆栈指向 `installFailLoud`，跟你改的插件**毫无关系**，你会以为 DSH 坏了。

---

## 9. 附录

### 9.1 证据索引

| 主题 | 文件 | 关键行 |
|---|---|---|
| 插件最小形态 | `$PKG\dsh-tool-todo\lib\index.js` | 全文 |
| manifest 字段 | `$PKG\dsh-package-manifest\lib\types\types.d.ts` | 7-26, 28-37, 55-64, 66-69, 76-89 |
| bundle 包范例 | `$PKG\dsh-base\package.json` | 全文 |
| 服务注册 | `$PKG\dsh-jobs\lib\index.js` | 全文 |
| 客户端座位 | `$PKG\dsh-client-ui-jobs\lib\client.js` | 611-643 |
| 双面包 manifest | `$PKG\dsh-client-ui-jobs\package.json` | 全文 |
| 客户端加载 | `$PKG\dsh-client-modules\README.md` | 12, 34, 46, 50, 54, 68, 72, 76, 78, 84, 134-140 |
| 客户端 HMR | `$PKG\dsh-client-hmr\README.md` | 全文 |
| 工具注册 | `$PKG\dsh-tools\README.md` | 全文 |
| 命令注册 | `$PKG\dsh-commands\README.md` | 全文 |
| 存储 | `$PKG\dsh-storage-domain\README.md` | 全文 |
| 系统提示 | `$PKG\dsh-system-prompt\lib\types\index.d.ts` | 47, 85, 237, 250 |
| HTTP 路由 | `$PKG\dsh-host-webserver\lib\types\index.d.ts` | 1-8, 16-19, 20-29, 32, 34-47, 60-88 |
| profile / patch | `$PKG\dsh-app-boot\README.md` | 32, 43, 50, 52, 54, 56, 60-61, 63, 65, 67, 69, 71-79, 87, 89, 92-113 |
| 兼容性门实现 | `$PKG\dsh-app-boot\lib\index.js` | 252-336 |
| 插件管理器 | `$PKG\dsh-plugin-manager\README.md` | 14, 31, 36-38, 40, 44, 48, 50, 52, 54, 56, 58, 71, 79-88, 102-104, 140-144, 162 |
| 市场 | `$PKG\dsh-plugin-market\README.md` | 全文 |
| 市场索引格式 | `$PKG\dsh-plugin-market-index\README.md` | 全文 |
| 插件清单 | `$PKG\dsh-host-plugin-inventory\README.md` | 全文 |
| web 组合 | `$PKG\dsh-web-app\README.md` | 91, 101, 105, 170 |
| **双面插件完整案例** | `~/.dsh/profiles/desktop/node_modules/@linxin666/dsh-client-ui-task-board/` | `cordis.patch.yml`、`package.json`、`lib/index.js:12104,12572`、`lib/client.js:13025-13052,15323-15364,15695-15706` |
| 升级走廊 | `~/.dsh/profiles/desktop/node_modules/dsh-plugin-upgrade/skills/plugin-upgrade/SKILL.md` | 全文 |
| 本机 profile | `~/.dsh/profiles/web/package.json` | 全文 |
| 本机 patch | `~/.dsh/profiles/web/cordis.patch.yml` | 1-120 |

### 9.2 明确"未找到证据"的项目

1. **`ctx.subagent` 的注册面** —— 包存在（`dsh-subagent*`），但没找到第三方插件直接调用的范例
2. **`ctx.fs` 的服务类型定义** —— 包存在（`dsh-fs*`），未读到服务面 `.d.ts`
3. **"241 条 plugin 行"的精确条数** —— 未做全量行计数
4. **`.plugin-manager/run.json` 的完整 schema** —— 只有 README 描述
5. **官方是否有插件脚手架** —— `$PKG` 下无 `guide`/`template`/`scaffold`/`create`/`init` 类包

### 9.3 一句话总结

> DSH 插件 = **一个 ESM 包 + 一个 YAML 数组 + 四个具名导出**。
> 危险不来自 API 复杂度（API 面很薄），而来自**三处静默失败**：具名导出写错（不激活）、座位名写错（UI 消失）、detached async 抛错（整个 app 挂掉）。
> 三者都不会在 `typecheck` 里现形，**唯一可靠的验证是临时 `DSH_HOME` 里的真实宿主 smoke + 真实浏览器断言**。
