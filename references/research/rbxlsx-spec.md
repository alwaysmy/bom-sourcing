# 红黑榜 Excel 解析规格（rbxlsx v2）

> 状态：设计规格（含参考实现与实测证据），未落地到 `skills/bom-sourcing`
> 适用范围：把「元器件 供应商 / 品牌 / 型号」的白名单-黑名单 Excel 导入为 `blacklist.yaml` v2
> 标记约定：`[标准]` 来自外部规范/官方文档 · `[手册]` 来自库手册 · `[经验]` 工程惯例 · `[实测]` 本机跑过、有日志
> 复放：`python probe\rbxlsx\make_samples.py && python probe\rbxlsx\rbxlsx_proto.py`
> 日志：`probe\rbxlsx\_run_20261106.txt`

---

## 0. 摘要

### 0.1 三个核心决策

| # | 决策 | 理由 |
|---|------|------|
| D1 | **列按「角色」识别，不按列名精确匹配**：10 个角色（kind/name/verdict/reason/scope/added/expires/authorized/aliases/id），每角色一张别名正则表，`re.search` 忽略大小写，按表头从左到右先到先得 | 现场表头有几十种写法（`厂商名称`/`Manufacturer_Name`/`品牌`/`供应商`），精确匹配必然漏 [实测 sample_03/04] |
| D2 | **`verdict` 只三态 `allow / deny / restricted`**，白/黑/灰一一对应；等级词先精确后子串，子串按别名长度降序 | 「不合格」包含「合格」，不排序会把黑名单读成白名单 [实测 22 词全表] |
| D3 | **冲突取严重度最大：`deny > restricted > allow`，且必须进 `conflicts` 报警**；过期条目不参与判定但保留在库 | 顺序无关（不依赖文件遍历/行序），审计留痕；「同一牌子既白又黑」是数据事故，不能静默 [实测 sample_03] |

### 0.2 两个最容易踩的坑

| # | 坑 | 现象 | 对策 |
|---|----|------|------|
| P1 | **合并单元格只有左上角有值**，其余格读出来是 `None` | 等级列 `D7:D8` 合并成「灰」，第 8 行等级读成空 → 被当成「无等级」放行 | 遍历 `ws.merged_cells.ranges` 取 `group.bounds` 的左上值**下填/右填** [手册][实测 merged_filled=8] |
| P2 | **表头不在第 1 行**，且第 1 行常是合并的大标题 | 直接拿第 1 行当表头 → 全部列识别失败，整表 0 条 | 前 10 行逐行打分，取「命中角色数最多且 distinct 值最多」的行 [实测 sample_02 选中第 4 行] |

> 附加坑（P3，属实现细节）：用 `{id: entry}` 去重会退化成「最后写入者胜」，结果依赖 `glob` 遍历顺序 —— 实测同一批 7 个文件两次跑出的 `Faketron` 判定在 `allow`/`deny` 间漂移。必须用 `merge_into()` + 严重度合并，禁止裸字典覆盖。

---

## 1. 业界「红黑榜 / AVL」的真实形态

### 1.1 五类真实来源

调研覆盖了工业模板、SaaS 导出、中文台账、电商配单四种语境 [标准]：

| 来源 | 语言 | 特征 |
|------|------|------|
| BSH（博西家电）供应商 AVL Template | 英 | 每列有严格的字典校验，`Manufacturer_ID` ≤10 字符纯大写 |
| Aurora Solar 设备 AVL 导出 | 英 | 单 sheet、表头第 1 行、列名带 `_string` 后缀 |
| 上市公司原材料库台账（PDF） | 中 | 状态三态：`正常 / 限用 / 注销` |
| 供应商管理十本台账（模板） | 中 | 黑名单是**第 9 本子台账**，不是独立文件 |
| 立创商城 BOM 智能配单 | 中 | 三色匹配态（绿/黄/红），**不是名单等级** |

### 1.2 五个样例表头

**S1 — BSH AVL（工业强校验型）**

| Material_Number | Manufacturer_ID | Manufacturer_Name | BOM_Pos_Number | Status |
|---|---|---|---|---|
| 1000123456 | MURATA | Murata Manufacturing | 0010 | Active |

要点：`Manufacturer_ID` 与 `Manufacturer_Name` **都不能为空**，且必须是主数据里已存在的码；`BOM_Pos_Number` 4 位递增（0010/0020），**同号 = 替代料** [标准]。
→ 对规格的启示：**ID 与 Name 双列并存时，以 ID 为准、Name 只做展示**；但现场中文表往往只有 Name，所以两者都要能当 `name` 角色。

**S2 — Aurora Solar AVL（SaaS 导出型）**

| Name_string | OEM_Manufacturer_string | whitelabel_manufacturer_string | PanelSize_string | PanelType_string | UAT_panelId |
|---|---|---|---|---|---|

要点：单 sheet、表头第 1 行、无「等级」列（白名单即全部）、以 UUID 兜底唯一性 [标准]。
→ 启示：**没有 verdict 列是合法输入**，此时全表按 `allow` 处理（见 §2.6 规则 R5），不要报错。

**S3 — 中文原材料台账（ERP 型）**

| 物料编码 | 制造商 | 型号 | 封装 | 描述 | 状态 |
|---|---|---|---|---|---|
| C990001 | 新纪元微 | NEVM3400A | SOT-23 | N-MOS | 限用 |

要点：`状态 ∈ {正常, 限用, 注销}`；「注销」等价于删除，应转成 `deny` + `reason=注销` [标准]。
→ 启示：等级词表必须覆盖 ERP 三态（§2.8.4）。

**S4 — 供应商红黑榜（管理型，最接近本需求）**

| 序号 | 供应商编码 | 供应商名称 | 类型 | 等级 | 原因 | 品类 | 生效日期 | 失效日期 | 责任人 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | SUP-0007 | 深圳叁和电子商行 | 店铺 | 黑 | 翻新料 | LDO | 2026-01-01 | 2027-01-01 | 张工 |

要点：**等级 + 原因 + 生效/失效 + 责任人**四件套是管理型台账的标配；供应商评价体系里「不合格(<60 分) → 观察期 ≤6 个月 → 复评仍不合格 → 进黑名单」，所以 `expires` 是真实字段而不是可选项 [标准]。
→ 启示：`reason` 与 `expires` 进 schema 一等公民；`责任人` 不做判定，只随 `source` 存档。

**S5 — 立创三色配单（易混概念）**

| 位号 | 型号 | 匹配状态 | 商品编号 | 品牌 |
|---|---|---|---|---|
| R1 | 0402WGF1002TCE | 绿色-完全匹配 | C990002 | 风华 |

⚠️ **警告**：这里的「绿/黄/红」是**单行匹配结果**，不是名单等级。若把红色当成 `deny`，会把「本行没配到货」误写成「该品牌被拉黑」[标准]。
→ 规格里由 §2.3 的角色表把 `匹配状态/配单状态` 排除在 `verdict` 别名之外（只认名单语义词）。

### 1.3 从形态归纳的 9 条硬约束

1. 一个文件可能**多个 sheet**，且常按对象分表（`品牌` / `店铺` / `料号` / `说明`）[实测 sample_04]。
2. 表头**不一定第 1 行**：标题、填表说明、空行都可能占前几行 [实测 sample_02]。
3. 表格**常带示例行**（「第 6 行为示例行，正式使用前应删除」）—— 不识别就会把 `某某公司` 导进真实名单 [标准]。
4. 表格**常带合计/小计/备注行**，且备注行横跨整行 [实测 sample_02/03]。
5. 等级列常**纵向合并**表示「这几行同一等级」[实测]。
6. 同一对象可能**既白又黑**（不同部门各维护一份后合并）[实测 sample_03]。
7. 品牌名常带**中文别名括号**：`Tokmas(托克马斯)` / `Nihonix（日能士）` [实测]。
8. 料号大小写、前导 `C`、Excel 把数字料号存成 `float`（`12345678.0`）[实测]。
9. 店铺名带**营销后缀**：`专营店` / `旗舰店` / `官方店` / `企业店` [实测]。

---

## 2. `parse_rbxlsx(path)` 接口规格

### 2.1 签名与返回

```python
def parse_rbxlsx(path, *, 
                 sheet: str | None = None,      # 只解析指定 sheet（默认全部）
                 today: str | None = None,      # 注入"今天"，便于测试与回放
                 scan_rows: int = 10,           # 表头搜索窗口
                 ) -> dict:
    """返回 {entries, warnings, errors, meta}"""
```

返回结构（JSON 可序列化，不含 openpyxl 对象）：

```python
{
  "entries": [                       # 已归一化、已合并冲突、按 id 唯一
    {
      "id": "brand:faketron",        # 稳定主键 = f"{kind}:{normalized_name}"
      "kind": "brand",               # brand|shop|code
      "name": "Faketron",            # 归一化后的展示名
      "aliases": ["法科创"],          # 归一化后的别名
      "verdict": "allow",            # allow|deny|restricted|None
      "reason": "合格供方",
      "scope": {"family": ["MOS"], "package": []},
      "added": "2026-01-05",
      "source": "sample_02_merged.xlsx#红黑榜!5",
      "authorized": False,
      "expires": None,               # 或 "2027-01-31"
      "expired": False,              # 派生：expires < today
      "raw": {"name": "Faketron(法科创)"},   # 原始值，仅用于报错定位
    }
  ],
  "warnings": [{"code": "W_NOTE_ROW", "sheet": "红黑榜", "row": 10, "msg": "..."}],
  "errors":   [{"code": "E_NO_HEADER", "sheet": "Sheet5", "msg": "..."}],
  "meta": {"path": "...", "sheets": [...], "rows_total": 10, "rows_used": 4},
}
```

**契约**：`errors` 非空时 `entries` 仍可用（部分成功），调用方按 §4.5 决定是否放行；`warnings` 幂等（同一文件两次解析逐字相同，因为 `source` 里带行号、`today` 可注入）。

### 2.2 处理流水线（7 阶段）

```
① 打开   openpyxl.load_workbook(data_only=True, read_only=False)
② 取格   for ws in wb.worksheets: grid = [[cell_str(c) for c in row] for row in ws.iter_rows()]
③ 填合并 遍历 ws.merged_cells.ranges → 左上值下填/右填（P1）
④ 定表头 前 scan_rows 行逐行打分 → (hrow, cols)
⑤ 逐行   分类（数据/空/备注/合计/重复表头/示例）→ 抽字段 → 归一化 → 组条目
⑥ 归并   merge_into 同 id → 严重度合并 → 产出 conflicts
⑦ 过期   标记 expired（不删）
```

`read_only=False` 是**必须**的：`read_only=True` 时 worksheet 对象**根本没有** `merged_cells` 属性（[实测] `getattr(ws, "merged_cells", "NO_ATTR")` → `NO_ATTR`，同一文件 `read_only=False` → 2 个 range），合并单元格下填无从做起。

### 2.3 列识别：角色表

`detect_columns(grid, scan_rows=10)` 返回 `(hrow, cols, evidence)`，`cols: {role: col_index}`。

| 角色 | 别名正则（`re.search`，忽略大小写） | 必需 |
|---|---|---|
| `name` | `名称\|名字\|品牌\|厂商\|厂家\|供应商\|制造商\|店铺\|商家\|型号\|料号\|物料\|part\s*no\|mpn\|manufacturer\|vendor\|supplier\|name\|model` | ✅ |
| `kind` | `类型\|种类\|对象\|分类\|type\|category` | |
| `verdict` | `等级\|级别\|状态\|名单\|黑白\|红黑\|判定\|结论\|verdict\|status\|level\|grade\|state` | |
| `reason` | `原因\|理由\|备注说明\|说明\|reason\|comment\|remark\|note` | |
| `scope` | `适用范围\|适用品类\|品类\|范围\|项目\|封装\|scope\|family\|package\|project` | |
| `added` | `登记日期\|录入日期\|加入日期\|创建日期\|新增日期\|added\|created\|date` | |
| `expires` | `失效日期\|有效期至\|有效期\|到期\|截止\|expires\|expiry\|valid\s*until\|until` | |
| `authorized` | `审批\|授权\|审核\|批准\|authorized\|approved` | |
| `aliases` | `别名\|曾用名\|英文名\|其它名称\|alias` | |
| `id` | `序号\|编号\|编码\|no\.?\|id` | |

**优先级陷阱（必须写死）**：

- `expires` 必须在 `added` **之前**匹配：`有效期至` 同时含 `效`/`期`，若先跑 `added` 的 `date` 会抢走（按角色表顺序匹配 + 每列只归一个角色即可，但 `added` 的正则要收紧到 `登记日期|录入日期|加入日期|创建日期|新增日期|added|created`，**不要**放裸 `date`）。
- `reason` 与 `scope` 都可能含「说明」，靠**列位置从左到右**先到先得；`scope` 先匹配更具体的 `适用品类|适用范围|封装|项目`。
- `name` 是最宽的（含 `型号`），所以 `name` 必须**最后**匹配，否则会把 `型号` 列抢成名称列。实现上：按 §2.3 表**自上而下**匹配，每列一旦归入角色即标记已用。

### 2.4 表头定位（不假设第 1 行）

```python
def detect_columns(grid, scan_rows=10):
    best = (-1, None, None)
    for i, row in enumerate(grid[:scan_rows]):
        vals = [v for v in row if v]
        distinct = len(set(vals))
        if distinct <= 1:            # 合并标题行填满同值 → 直接排除
            continue
        cols = {}                    # 按 §2.3 顺序匹配
        for v in vals: ...
        score = len(cols) * 10 + min(distinct, 20)   # 角色命中数为主，distinct 为辅
        if score > best[0]:
            best = (score, i, cols)
    return best[1], best[2], {...}
```

[实测] sample_02 的 A1:H1 合并标题填充后 8 格同值（`distinct=1`）被跳过，说明行只命中 0 个角色，最终正确选中第 4 行。
若前 10 行**一列都没命中 `name`** → `E_NO_HEADER`，整页跳过（但若该页只有 ≤1 行有内容，只报 `W_EMPTY_SHEET`，不报 error —— 空表是数据问题不是格式问题）。

### 2.5 合并单元格下填（P1）

```python
for rng in ws.merged_cells.ranges:
    top, left, bottom, right = rng.bounds      # 1-based, 含端点
    v = ws.cell(top, left).value
    for r in range(top, bottom + 1):
        for c in range(left, right + 1):
            if (r, c) != (top, left) and grid[r-1][c-1] in (None, ""):
                grid[r-1][c-1] = v             # 只填空格，不覆盖已有值
```

规则：
- **只填空格**。若合并区里非左上格已有值（openpyxl 写入时通常已被清空，但 CSV 转换来的表可能有），保持原值并报 `W_MERGED_CONFLICT`。
- 横向合并（`A1:H1` 标题）填出来会导致 8 列同值 —— 由 §2.4 的 `distinct <= 1` 过滤掉，**不需要**特判。
- `merged_filled` 计数进 `meta`，用于回归（sample_02 期望 8）。

### 2.6 行级判定

对每个数据行，**按顺序**判：

| 规则 | 条件 | 动作 |
|---|---|---|
| R1 | 整行全空 | 静默跳过（不报） |
| R2 | 命中 `NOTE_RE = ^(注|备注|说明|提示|注意|注：)` | `W_NOTE_ROW`，跳过 |
| R3 | 命中 `TOTAL_RE = ^(合计|小计|总计|共计|总额)` | `W_TOTAL_ROW`，跳过 |
| R4 | 该行与表头**归一化后相同**（≥3 列相等） | `W_REPEAT_HEADER`，跳过（分页打印的表会在中途重复表头） |
| R5 | 无 `verdict` 列，或该格为空 | `verdict=None` → 解析期按 `allow` 落库，但每行报 `W_NO_VERDICT`；**若整表都没有 verdict 列，只报一次 `I_NO_VERDICT_COL`**（信息级，不算 warning 噪音） |
| R6 | 命中 `EXAMPLE_RE = 示例|样例|example|sample|某某|XX公司` 且该行是表头后第一行 | `W_EXAMPLE_ROW`，跳过 |
| R7 | `name` 为空 | 跳过，静默（多为合并/缩进残留） |
| R8 | 其余 | 正常抽取 |

[实测] sample_02 的 10 行数据净得 4 条，四类噪音各命中一次；sample_03 的备注行被 R2 拦下。

### 2.7 `kind` 推断

顺序（先显式、后形态）：

1. **显式列**：`kind` 列的值 → `品牌/厂商/制造商/brand` → `brand`；`店铺/商家/供应商/shop` → `shop`；`料号/型号/MPN/code` → `code`。
2. **名称形态**：
   - `^C\d{4,}$` 或 `[A-Z]{2,}\d{3,}[A-Z0-9-]*` → `code`
   - 含 `店|商行|商城|电子|科技|贸易|实业` → `shop`
   - 含 `半导体|微电子|Ltd|Inc|Corp|GmbH|Co\.` → `brand`
3. 都不中 → **按 `brand` 处理并报 `W_KIND_GUESSED`**（不跳过：猜错比丢掉强，且能被人看见）。

[实测] sample_05 只有「型号」一列时，`kind` 正确推断为 `code`；sample_04 每个 sheet 靠 sheet 名（`品牌`/`店铺`/`料号`）也能定 kind。

### 2.8 归一化

全部归一化**幂等**（`f(f(x)) == f(x)`），且归一化结果进 `id`，保证重复导入不产生新条目。

#### 2.8.1 通用

```python
def to_halfwidth(s):   # 全角 → 半角（ＡＢＣ１２３ → ABC123，( ) → ( )）
def norm_key(s):       # 小写 + 去所有空白 + 去 ()（）【】[] 及其中内容
```

`norm_key` 与现有 `blacklist.norm()` **语义一致**（`Tokmas(托克马斯)` → `tokmas托克马斯`），但 v2 额外把括号内容**抽成 alias** 后再算 key，见 2.8.2。

#### 2.8.2 品牌

```python
def norm_brand(raw):
    # "Nihonix（日能士）"        → ("Nihonix",   ["日能士"])
    # "Tokmas(托克马斯)"         → ("Tokmas",    ["托克马斯"])
    # "新纪元微(NEVM)"           → ("新纪元微",   ["NEVM"])
    base, inner = split_alias(raw)      # 括号内/外的部分
    return base or inner, [x for x in (inner, raw) if x and x != base]
```

规则：括号外为主名，括号内（含全角）进别名；括号**内为空**时取括号外；`raw` 原名永远保留为别名之一（便于原样命中）。

#### 2.8.3 店铺

```python
SHOP_SUFFIX  = ("专营店","旗舰店","官方旗舰店","官方店","企业店","专卖店","直营店","工厂店")
SHOP_PLATFORM= ("淘宝","天猫","京东","1688","阿里巴巴","拼多多","立创商城","华强北")
def norm_shop(raw):
    # "东莞立信电子专营店" → ("东莞立信电子", ["东莞立信电子专营店"])
    # "淘宝-深圳叁和电子商行" → ("深圳叁和电子", ["淘宝-深圳叁和电子商行","深圳叁和电子商行"])
```

去后缀、去平台前缀，**原名进别名** —— 因为 `find()` 是子串匹配，别名能让原写法仍然命中。

#### 2.8.4 等级词（`norm_verdict`）

```python
VERDICT_ALIASES = {
  "deny":       ("黑","黑名单","禁用","禁入","拉黑","淘汰","冻结","注销","不合格","停用",
                 "banned","blacklist","blocked","forbidden","rejected"),
  "restricted": ("灰","灰名单","限用","限制","观察","观察期","待定","条件使用","降级",
                 "restricted","watch","conditional","limited"),
  "allow":      ("白","白名单","优选","合格","正常","可用","准入","推荐","approved",
                 "whitelist","allowed","preferred","active"),
}
_VERDICT_EXACT = {k: v for ...}                     # 全词精确
_VERDICT_SUB   = sorted(..., key=len, reverse=True) # 子串，长别名优先
```

匹配顺序：**去空白 → 全角转半角 → 精确命中 → 子串命中（长别名优先）→ None**。

[实测] 22 个词全部命中正确，含两个关键陷阱：
- `不合格` → `deny`（若先跑子串 `合格` 会读成白名单 —— **顺序即正确性**）
- `半黑半白` → `deny`（无精确命中，子串 `黑` 兜底；`restricted` 的 `灰` 不参与，因为 `deny` 组优先）

`待定` 归 `restricted` 而不是 `None`：现场 `待定` 表示「暂缓采购」，按灰处理最安全；若业务要求「待定=未定」，改一行别名即可，但**必须在文档里写死**，不能两处各写一半。

#### 2.8.5 料号

```python
def norm_code(raw):
    s = str(raw).strip()
    if re.fullmatch(r"\d+\.0+", s): s = s.split(".")[0]   # 12345678.0 → 12345678
    s = to_halfwidth(s).replace(" ", "").replace("-", "").upper()  # 保留连字符？见下
    return s
```

决策：**连字符保留**（`FKT1117-3.3` 与 `FKT11173.3` 是不同料），只做 `upper()` + 去空白 + 去 `float` 尾巴 + 全角转半角。
`C 号` 统一大写（`c990001` → `C990001`）。不补零、不删连字符 —— 这两条会改变料号语义。

#### 2.8.6 日期

```python
def norm_date(v):   # → "YYYY-MM-DD" | None
    # 支持 datetime/date、Excel 序列号(int/float)、"2026/1/5"、"2026-01-05"、"20260105"、"2026年1月5日"
```

Excel 序列号（如 `46027`）用 `openpyxl.utils.datetime.from_excel` 转，不要手写 1900 闰年 bug [手册]。

### 2.9 冲突与过期

**冲突（必报）**：同一 `id` 出现多个不同 `verdict`。

```python
SEVERITY = {"deny": 3, "restricted": 2, "allow": 1, None: 0}
resolved = max(verdicts, key=lambda v: SEVERITY[v])
```

- `resolved` 写进条目，`conflicts` 记 `{id, verdicts:[...], resolved, sources:[...]}`。
- 同时报 `W_VERDICT_CONFLICT`（**warning 不是 error**：文件能导入，但人要去看）。
- 结果**与行序/文件序无关**（`max` 满足交换律），这是 D3 的直接收益 [实测：`['allow','deny'] → deny`]。
- 同 `id` 同 `verdict` 只合并 `aliases`/`scope`/`reason`，报 `unchanged`，不算冲突。

**过期**：`expires < today` → `expired=True`。

- 条目**保留**在 `entries`（审计价值：知道曾经黑过谁），`decide()` 时**不参与判定**。
- 解析期不报 warning（批量导入时几百条过期会淹没输出），改由 `blacklist.py list --expired` 主动查。
- `expires == today` 视为**仍有效**（当天到期当天生效到 23:59，避免跨时区歧义）。

### 2.10 幂等

| 层面 | 保证 | 实现 |
|---|---|---|
| 解析 | 同文件两次解析结果**逐字相同** | 不写 `today` 到条目（`added` 取文件里的日期，缺省才用 `today`）；`source` 用 `文件名!sheet:行`，不用绝对路径 |
| 落库 | 重复导入 `added=0 updated=0 unchanged=N` | `id` 由归一化名生成；`merge_into` 只在**内容变化**时置 `updated` |
| 时间戳 | `updated` 只在内容变化时改 | v1 的 `save()` 无条件写 `updated=today` 是**已知缺陷**，v2 改为「有 diff 才写」 |

[实测] 首次 `added=5`，重复导入 `added=0 updated=0 unchanged=5 total=5`。

`merge_into(existing, parsed)` 的返回（原型真实结构）：

```python
{"entries": [...],        # 合并后的全量条目（**必须返回**，否则调用方拿不到新增项）
 "added": [id...], "updated": [id...], "unchanged": [id...],
 "conflicts": [{"id","name","verdicts":[...],"resolved"}], "total": int}
```

两条**容易写错**的合并规则（都在原型上真踩到过）：

1. **`verdict` 取严重度最大，禁止后写覆盖前写。** 若按「新文件优先」直接 `cur.update(...)`，先导黑名单再导白名单会把黑名单**洗白**（[实测] 早期版本就是这样，`Faketron` 在两次 `glob` 遍历里 verdict 漂移）。现在 `verdict` 走 `rank` 比较，`updated` 记 diff，`conflicts` 记原委。
2. **`expired` 是派生字段，每次合并都要按 `(expires, today)` 重算。** 从旧条目继承会出两种错：给条目「续期」（改 `expires` 到未来）后仍被判过期；或新设的 `expires` 不生效。原型最初漏了重算，[实测] 现在 `shop:东莞立信电子` 正确 `expired=True` → `decide()` 返回 `None`。

同理，**`id` 用可读主键 `{kind}:{norm_key(name)}`**（如 `brand:faketron`），不要用 `sha1[:8]` 哈希 —— 哈希在 `blacklist.yaml` 里不可 grep、冲突日志里无法定位到人（[实测] 早期哈希版报冲突只能看到 `260151d7`）。

`reason`/`scope` 的差异也算内容变化；仅 `raw` 里的原始写法不同（`Tokmas` vs `Tokmas(托克马斯)`）**不算**（否则改名别名会造成假更新）。

### 2.11 多 sheet 策略

| sheet 名 | 处理 |
|---|---|
| 含 `说明/help/readme/说明页/目录/cover` | `W_SKIP_SHEET` 跳过（[实测] sample_04 的 `说明`） |
| 空表 / 只有 1 行 | `W_EMPTY_SHEET`，跳过（不报 error） |
| 其余 | 全部解析，`entries` 汇总后统一归并 |

- 不假设「第一个 sheet 就是数据表」，也不假设「每个 sheet 同一套列」——每个 sheet 独立跑 `detect_columns`。
- 同一对象在多个 sheet 出现 → 走 §2.9 的归并（`id` 相同即合并），`source` 记第一个来源，其余进 `aliases` 的 `sources`。
- `--sheet 名称` 可只导一个 sheet（CI 场景：先导 `品牌` 再导 `料号`，避免一次改太多）。
### 2.12 告警与错误码

| 码 | 级别 | 含义 | 可恢复 |
|---|---|---|---|
| `E_NO_HEADER` | error | 前 10 行找不到 `name` 角色 | 整页跳过 |
| `E_BAD_FILE` | error | 打不开/不是表格/依赖缺失 | 整体失败 |
| `E_BAD_ROW` | error | 行内字段类型异常（如日期列是「待定」） | 跳过该行 |
| `W_EMPTY_SHEET` | warn | 空表 | 是 |
| `W_SKIP_SHEET` | warn | 说明页 | 是 |
| `W_NOTE_ROW` / `W_TOTAL_ROW` / `W_REPEAT_HEADER` / `W_EXAMPLE_ROW` | warn | 噪音行 | 是 |
| `W_NO_VERDICT` | warn | 该行无等级，按 allow 落库 | 是 |
| `W_VERDICT_CONFLICT` | warn | 同 id 多等级，已按严重度取值 | 是 |
| `W_KIND_GUESSED` | warn | kind 靠猜 | 是 |
| `W_MERGED_CONFLICT` | warn | 合并区非左上格有值 | 是 |
| `W_UNKNOWN_VERDICT` | warn | 等级词不在词表，按 None 处理 | 是 |
| `I_NO_VERDICT_COL` | info | 整表无等级列（白名单语义） | 是 |

### 2.13 骨架（40 行内，仅供评审，勿落盘到 skill 目录）

```python
def parse_rbxlsx(path, *, today=None, sheet=None, scan_rows=10):
    out = {"entries": [], "warnings": [], "errors": [], "meta": {}}
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception as e:
        out["errors"].append({"code": "E_BAD_FILE", "msg": str(e)})
        return out
    for ws in wb.worksheets:
        if sheet and ws.title != sheet:            continue
        if _SKIP_RE.search(ws.title):              warn(out,"W_SKIP_SHEET",ws);   continue
        grid = [[_cell(c) for c in row] for row in ws.iter_rows()]
        _fill_merged(ws, grid)                                  # P1：只填空格
        if sum(1 for r in grid if any(r)) <= 1:  warn(out,"W_EMPTY_SHEET",ws);   continue
        hrow, cols = detect_columns(grid, scan_rows)             # P2：不假设第 1 行
        if "name" not in cols:
            err(out,"E_NO_HEADER",ws);             continue
        for i, row in enumerate(grid[hrow+1:], start=hrow+2):
            raw = _get(row, cols, "name")
            if not raw:                                             continue
            if _NOTE_RE.match(raw):  warn(out,"W_NOTE_ROW",ws,i,raw);  continue
            if _TOTAL_RE.match(raw): warn(out,"W_TOTAL_ROW",ws,i,raw); continue
            if _is_repeat(raw,row,cols,grid,hrow): warn(out,"W_REPEAT_HEADER",ws,i,raw); continue
            kind = _kind(raw, _get(row, cols, "kind"))
            name, aliases = _NORM[kind](raw)
            v, how = norm_verdict(_get(row, cols, "verdict"))
            out["entries"].append({
                "id": f"{kind}:{norm_key(name)}", "kind": kind,
                "name": name, "aliases": aliases, "verdict": v,
                "reason": _get(row, cols, "reason"),
                "scope": _scope(row, cols),
                "added": norm_date(_get(row, cols, "added")) or today,
                "source": f"{Path(path).name}#{ws.title}!{i}",
                "authorized": False,
                "expires": norm_date(_get(row, cols, "expires")),
            })
    out["entries"], conflicts, _ = resolve(out["entries"])      # 冲突取 max + 过期标记
    out["warnings"] += [{"code": "W_VERDICT_CONFLICT", **c} for c in conflicts]
    return out
```

> 说明：`resolve(parsed) -> (entries, conflicts, expired)` 是原型的真实签名（[实测]），骨架按它写；冲突不在这里直接写 warning 列表，是为了让 `resolve` 保持纯函数、可单测。

---

## 3. 落库 schema：`blacklist.yaml` v2

### 3.1 完整结构

```yaml
schema: bom-sourcing/knowledge/blacklist
version: 2
updated: "2026-11-06"          # 内容有变化才更新（幂等）
# ---- 兼容段：v1 的三组，仅迁移期保留，新代码不读 ----
brands: []
shops: []
codes: []
# ---- v2 主体 ----
entries:
  - id: "brand:faketron"
    kind: brand                 # brand | shop | code
    name: "Faketron"
    aliases: ["法科创", "Faketron(法科创)"]
    verdict: allow              # allow | deny | restricted
    reason: "合格供方，2026 年度评审通过"
    scope:                      # 可选；空 = 全局
      family: ["MOS", "LDO"]    # 品类（spec.detect_family 的 key）
      package: ["SOT-23"]       # 封装（spec.norm_pkg 的 key）
      project: []               # 项目/客户代号
    added: "2026-01-05"
    source: "sample_02_merged.xlsx#红黑榜!5"
    authorized: true            # 是否走过授权写流程
    expires: "2027-01-01"       # 可选；空 = 永久

  - id: "shop:shenzhen叁和电子"
    kind: shop
    name: "深圳叁和电子"
    aliases: ["深圳叁和电子商行", "深圳叁和电子旗舰店", "淘宝-深圳叁和电子商行"]
    verdict: deny
    reason: "翻新料、拆机料"
    scope: {}
    added: "2026-01-05"
    source: "sample_04_multisheet.xlsx#店铺!2"
    authorized: true
    expires: null

  - id: "code:c990001"
    kind: code
    name: "C990001"
    aliases: []
    verdict: deny
    reason: "停产且无替代"
    scope:
      family: ["连接器"]
    added: "2026-03-01"
    source: "sample_03_dirty.xlsx#Sheet1!5"
    authorized: true
    expires: "2025-12-31"       # 过期条目：保留但判定时跳过

  - id: "brand:nihonix"
    kind: brand
    name: "Nihonix"
    aliases: ["日能士", "Nihonix（日能士）"]
    verdict: restricted
    reason: "仅限打样，量产需评审"
    scope:
      family: ["LDO"]
    added: "2026-01-05"
    source: "sample_03_dirty.xlsx#Sheet1!3"
    authorized: true
    expires: null
```

### 3.2 字段表

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | str | ✅ | `{kind}:{norm_key(name)}`，库内唯一，导入时用它做 upsert 键 |
| `kind` | enum | ✅ | `brand` / `shop` / `code`（`family` 为预留值，见 §4.2，默认不启用）；对应 v1 的 `brands`/`shops`/`codes` |
| `name` | str | ✅ | 归一化后的主名（展示用） |
| `aliases` | str[] | | 归一化后的别名（含原名）；`find()` 子串匹配用 |
| `verdict` | enum | ✅ | `allow`(白) / `deny`(黑) / `restricted`(灰) |
| `reason` | str | | 人话原因；写操作必备（无原因的黑名单无法复核） |
| `scope` | obj | | `{family:[], package:[], project:[]}`；**空 dict 或缺失 = 全局** |
| `added` | date | ✅ | 首次入库日；导入时取文件值，缺省用 `today`（**不覆盖已有值**） |
| `source` | str | | `文件名#sheet!行`，相对路径，便于追溯；同 id 多来源时用竖线连接 |
| `authorized` | bool | ✅ | 是否经授权流程写入；`false` 的条目 `decide()` 仍生效但 `list` 会标红 |
| `expires` | date\|null | | 失效日；`null` = 永久 |
| `expired` | bool | 派生 | `expires < today`；**不进 YAML**，解析时算、序列化前剔除；**每次合并/落库必须重算**（§2.10 规则 2） |
| `exempt` | bool | | 预留：料号级豁免（§4.2 唯一豁免通道），默认 `false`，`true` 时必须同时给 `reason` |

### 3.3 `verdict` 与 `scope` 语义

- `allow`：优选/合格供方。**不强制**，只在候选排序里加分（对应 `vendors.md` 的 `SCORE_BONUS`）。
- `deny`：**硬拦截**，等价于现有 `filter_records` 的 dropped。
- `restricted`：**条件放行**——只在 `scope` 命中时拦截；`scope` 为空时拦截（保守：灰名单没写范围就按黑处理，并报 `W_RESTRICTED_NO_SCOPE`）。
- `scope` 具体化优先：`brand:X + family:["LDO"]` 命中 LDO 时，比全局 `deny` 的同样品牌**更具体**；但严重度仍是 `deny > restricted > allow`（D3 不变），scope 只用于「同严重度」时的取舍与文案。

### 3.4 v1 → v2 迁移

一次性、幂等、可回滚：

```python
def migrate_v1_to_v2(data):
    if data.get("version", 1) >= 2:        return data          # 幂等
    entries = []
    for kind, key in (("brand","brands"), ("shop","shops"), ("code","codes")):
        for it in data.get(key) or []:
            name, aliases = _NORM[kind](it["name"])
            entries.append({
                "id": f"{kind}:{norm_key(name)}", "kind": kind,
                "name": name, "aliases": sorted(set(aliases + it.get("aliases", []))),
                "verdict": "deny",                          # v1 语义 = 黑名单
                "reason": it.get("reason", ""), "scope": {},
                "added": it.get("added") or data.get("updated") or today,
                "source": it.get("source", "v1-migrated"),
                "authorized": True,                         # v1 能写进去就已授权
                "expires": None,
            })
    data.update(version=2, entries=merge_into([], entries)["entries"],
                brands=[], shops=[], codes=[])              # 保留空键，老代码不炸
    return data
```

要点：
1. **v1 全是 `deny`**（v1 只有黑名单语义），不要臆测成 `allow`。
2. 保留空的 `brands/shops/codes` 键 —— 老版本 `blacklist.py` 读到 v2 文件时至少不会 `KeyError`（但会读到空名单，**这是可接受的降级**：宁可不拦，不可误拦）。
3. 迁移前自动备份 `blacklist.yaml.bak.<时间戳>`。
4. 迁移是纯函数，`--dry-run` 输出 diff。

### 3.5 写门禁（沿用 v1）

- 任何写操作（import/add/remove）必须 `--authorized`，否则 `PermissionError`（v1 的 `_require_auth` 语义不变）。
- 导入的条目 `authorized` 默认 `False`；`--authorized` 时置 `True`，并记 `source`。
- `--dry-run` 只算 diff 不写盘（含 `updated` 不变）。

---

## 4. 判定接口 `decide(item, context)`

### 4.1 签名

```python
def decide(item: dict, context: dict | None = None, library: list[dict] | None = None) -> dict:
    """
    item    : {"brand": "...", "model": "...", "code": "...", "shop": "...", "family": "..."}
    context : {"stage": "prototype|small_batch|mass_production|...", "project": "...",
               "family": "...", "package": "..."}
    library : entries[]（v2 的 entries）；None/[] 视为不可用
    返回    : {"verdict": "allow|deny|restricted|None",
               "reasons": [entry 子集],   # 命中的条目，去重；见下
               "fallback": bool,          # True = 名单未生效，本次放行
               "conflicts": [...]}        # 透传 resolve() 的冲突（可选）
    """
```

`reasons` 的元素是**条目子集**（不是裸字符串），字段固定为
`{id, kind, name, alias, verdict, reason, scope, expires}`：

- `alias` = 实际命中的那个别名（L3 子串命中时），名称精确命中时为 `null`；
- 这样 `filter_records` 的 `hits`（v1 的 `{kind,name,alias,reason,added,source}`）可以直接由它映射，字段不新增、不丢。

[实测] 原型当前把 `reasons` 落成条目子集（无 `alias` 字段），`fallback` 实现为 `not has_allow`。
**落地时按本规格收紧**：`fallback = library 为空 or 解析失败`；`not has_allow` 的弱化版在「库全是 deny」时会误报 `fallback=True`（样本里恰好没触发，属未覆盖路径）。

### 4.2 匹配算法（三级，从精确到模糊）

| 级 | 对象 | 匹配方式 | 说明 |
|---|---|---|---|
| L1 | `code` | `norm_code` 精确相等（`item.code` 或 `item.model`） | 料号是强标识，命中即算 |
| L2 | `brand` / `shop` | `norm_key` 精确相等 | 收集 |
| L3 | `brand` / `shop` | 别名**子串**包含（沿用 v1 `find()` 语义） | 收集（`东莞立信电子` 能命中 `东莞立信电子专营店`） |
| L4 | `family` | `norm_key` 精确相等 | 可选扩展，见下 |

**合并规则：所有命中条目按 `SEVERITY = {deny:3, restricted:2, allow:1}` 取 max，不短路。**

> ⚠️ 这里有一个容易设计错的点：立创商城写「品牌偏好：系统优先匹配您设定的品牌，**有确切型号和商品编号时品牌偏好不生效**」[标准]，容易被读成「料号白名单可以覆盖品牌黑名单」。**不能**这么做 —— 品牌进黑名单的典型原因是假货/翻新/无授权渠道，这与「这个型号恰好被标成优选」不冲突。所以：
> - **不设短路**：`{"brand":"Nihonix","code":"FKT1117-3.3"}` 若品牌 deny、料号 allow → 结果 `deny`（[实测] 输出 `reasons=['Nihonix','FKT1117-3.3']`）。
> - 立创那条原则只作用于**排序/推荐**（`pick.py` 的候选排序），不作用于**拦截**。
> - 真要开例外，用条目字段 `exempt: true`（v2 预留，默认 `false`，且必须写 `reason`），并且**只能是料号级**。这是唯一豁免通道，禁止用「白名单整体优先」。

**scope 过滤**（在命中之后、取 max 之前）：

| 条目 scope | context 有该键 | 行为 |
|---|---|---|
| `family` 非空 | 有 | `context.family` 不在 scope 里 → 本条**不适用** |
| `family` 非空 | 无 | 保守**生效**（无法判断就不放过） |
| `package` 非空 | 有 | 同上，`spec.norm_pkg` 归一后比较 |
| `project` 非空 | 有 | 同上 |
| `{}` / 缺失 | — | 全局生效 |

[实测] `Faketron` 的 `family:["MOS"]` 在 `context.family="mosfet"` 时不命中 —— 避免了「MOS 的黑名单误拦 LDO」；`Nihonix` 的 `family:["LDO"]` 在 `family=ldo` 时命中 → `deny`。

**过期**：`expired=True` 的条目**不参与**；若**只**命中过期条目 → `verdict=None`，`reasons` 里带一条 `{id, expired: true}`（人能看到「曾黑过」但不再拦）。

**可选扩展 `kind: family`**：原型已支持（品类级名单，如「整个品类禁用某封装」）。v2 默认不启用，因为 `blacklist.py` 的 `KINDS` 只有三值；启用需同步改 `KINDS` 与 `_KIND_KEY`，属破坏性变更（Q5）。

### 4.3 与现有代码的兼容点

| 现有 | 兼容方式 |
|---|---|
| `blacklist.filter_records(records, data, kind="brand")` | 内部改调 `decide()`：`verdict in (deny, restricted 且 scope 命中)` → 进 `dropped`；`hits` 字段名保持 `{kind,name,alias,reason,added,source}` 不变 |
| `blacklist.find(text, kind, data)` | 保留，改为在 `entries` 上跑；`data` 传 v1 结构时先 `migrate_v1_to_v2` |
| `blacklist.check_record(rec)` | 保留；`rec` 的 brand/model/code 映射到 `item` |
| `bom._blacklist_filter(cands)` | 不改；它已包了异常兜底 `return list(cands), []` |
| `pick.py --no-blacklist` | 不改；`decide` 增加 `--no-blacklist` 时直接 `verdict=None, fallback=True` |
| `pick.py` 的 `shop_blacklisted` / `bl_hits` 输出 | `decide()` 的 `hits` 直接喂给 `bl_hits` |
| `bom.parse_bom` 跳 `合计/小计` | 与 §2.6 R3 同源，复用 `TOTAL_RE` |

### 4.4 失败降级（必须保留）

```python
try:
    ...
except Exception as e:
    return {"verdict": None, "reasons": [f"blacklist error: {e}"], "fallback": True, "hits": []}
```

「黑名单坏了不能拖垮配单」是现有 `_blacklist_filter` 的既有行为，v2 不得回退成抛异常。`fallback=True` 时 `pick.py` 的提示文案要显式加一行 `⚠ 黑名单不可用，本次未拦截`。

### 4.5 判定样例（[实测] 输出）

| item | context | verdict | reasons（`name`） |
|---|---|---|---|
| `{"brand":"Faketron(法科创)"}` | `{"family":"mosfet"}` | `allow` | `['Faketron']` |
| `{"brand":"Nihonix"}` | `{"family":"ldo"}` | `deny` | `['Nihonix']` |
| `{"code":"c990002"}` | `{"stage":"prototype"}` | `restricted` | `['C990002']` |
| `{"brand":"Nihonix","code":"FKT1117-3.3"}` | `{"family":"ldo"}` | `deny` | `['Nihonix','FKT1117-3.3']` |
| `{"shop":"深圳叁和电子商行"}` | `None` | `deny` | `['深圳叁和电子商行']` |
| `{"brand":"从未出现过的牌子"}` | `None` | `None` | `[]` |

第 1 行说明 scope 生效（`Faketron` 的 scope 是 `MOS`，`mosfet` 不匹配 → 该条目被过滤，最终由 sample_03 的全域 `allow` 条目给出结论）；第 4 行说明**不短路**（料号 allow 没有覆盖品牌 deny）；第 6 行是「未命中」——`verdict=None` 由调用方按「无记录」处理，不是「放行」也不是「拦截」。

---

## 5. 测试用例

样例由 `probe\rbxlsx\make_samples.py` 生成（**全部自造数据**，品牌 `Faketron/Nihonix/新纪元微`、店铺 `深圳叁和电子商行` 均为虚构）。

| # | 文件 / 构造 | 输入要点 | 期望 | 覆盖 |
|---|---|---|---|---|
| T01 | `sample_01_standard.xlsx` | 英文 AVL 表头 `Kind/Name/Verdict/Reason/Scope/Added/Expires` | 5 条；`brand:Faketron`=allow、`code:C990002`=restricted | 基线、英文列名 |
| T02 | `sample_02_merged.xlsx` | A1:H1 合并标题 + 说明行 + 空行 → 表头在第 4 行；`D7:D8` 合并「灰」 | 表头行=4；`merged_filled=8`；第 8 行（华强北）等级=restricted | **合并单元格**、表头不在第 1 行 |
| T03 | `sample_03_dirty.xlsx` | 中文别名表头 `厂商名称/供应商类型/物料状态/禁用原因/适用品类/登记日期/有效期至/责任人` | 7 条；`东莞立信电子`（去 `专营店`）+ 别名；`expired=True` | **表头别名**、店铺后缀、过期 |
| T04 | `sample_03_dirty.xlsx` | 同 id 出现「白」和「黑」 | `resolved=deny` + `W_VERDICT_CONFLICT` | **白黑冲突**、顺序无关 |
| T05 | `sample_03_dirty.xlsx` | `c990001`（小写）、`12345678.0`（float）、`fkt3400a` | `C990001` / `12345678` / `FKT3400A` | **大小写**、float 料号 |
| T06 | `sample_03_dirty.xlsx` | `Nihonix（日能士）` 全角括号 | name=`Nihonix`，aliases 含 `日能士` | **中文全角括号** |
| T07 | `sample_05_minimal.xlsx` | 只有「型号」一列 | 3 条，kind=`code`，每行 `W_NO_VERDICT` | **只有型号没有品牌** |
| T08 | `sample_06_empty.xlsx` | 只有 A1:D1 合并标题 | 0 条，仅 `W_EMPTY_SHEET`（**不报** `E_NO_HEADER`） | **空 sheet** |
| T09 | `sample_04_multisheet.xlsx` | 5 个 sheet：品牌/店铺/料号/说明/空表 | 5 条；`说明`→`W_SKIP_SHEET`；`Sheet5`→`W_EMPTY_SHEET` | 多 sheet |
| T10 | `sample_02_merged.xlsx` | 备注行、`合计 4 条`、末尾重复表头 | 分别 `W_NOTE_ROW`/`W_TOTAL_ROW`/`W_REPEAT_HEADER` | 噪音行 |
| T11 | `sample_07_gb18030.csv` | GB18030 编码 CSV | 3 条正常（不抛 UnicodeDecodeError） | **CSV 兜底** |
| T12 | 任意 | 同一文件连续导入两次 | 第二次 `added=0 updated=0 unchanged=N` | **幂等** |
| T13 | 任意 | 等级词表 22 词 | `不合格`→deny、`合格`→allow、`半黑半白`→deny、`待定`→restricted | 子串陷阱 |
| T14 | v1 文件（`probe\rbxlsx\check_migrate.py`） | `version: 1` + `brands/shops/codes` 各 1 条 | 转成 3 条 `deny`；`brands/shops/codes` 清空但键保留；再跑一次 `entries` 不变 | **v1→v2 迁移**、迁移幂等 |
| T15 | 构造 | 库文件损坏（非法 YAML） | `decide` 返回 `fallback=True`，`filter_records` 放行全部 | 失败降级 |
| T16 | `check_migrate.py` | v1 库 + sample_01 + sample_03 连续 merge | `added=5 → added=3 updated=4`；`conflicts=['brand:faketron','brand:nihonix']`，`faketron` 的 `resolved=deny` | **跨文件合并**、不洗白 |
| T17 | `check_migrate.py` | 条目 `expires` 改为过去日期后再 merge | 合并后 `expired=True` → `decide()` 返回 `None` | **派生字段重算** |

断言写法建议：直接比对 `entries` 的 `(id, verdict, aliases, expired)` 四元组集合，避免比 `raw`/`source` 造成脆弱测试。

---

## 6. 实现建议

### 6.1 纯标准库 vs openpyxl

| 维度 | 标准库（zipfile + xml.etree） | openpyxl |
|---|---|---|
| 依赖 | 0 | 已有（`bom.py` 在用）[实测 3.1.5] |
| 合并单元格 | 要自己解析 `mergeCell` 并算 `bounds` | `ws.merged_cells.ranges` 现成 |
| 日期 | 要自己处理 1900 闰年与 `numFmt` | `from_excel` 现成 |
| 共享字符串 | 要自己维护 `sharedStrings` 索引 | 透明 |

**结论：用 openpyxl**。理由：合并单元格 + 日期是两个最容易写错的地方，而 `bom.py` 已经把 openpyxl 变成既有依赖，不新增成本。仅当出现「Excel 文件大到内存扛不住」（>10 万行）时才考虑 `read_only=True` + 自己解析 XML，届时另立规格。

### 6.2 CSV 兜底

要。理由 [实测 T11]：现场常见「Excel 另存为 CSV」，且中文 Windows 默认 **GB18030**。

- 编码探测顺序 `utf-8-sig → utf-8 → gb18030 → latin-1`（沿用 `bom.read_table`）；定界符 `tab`/`,`/`;` 按首行列数取最大。
- 若 `.xls`（旧二进制格式）→ `E_BAD_FILE`，文案提示「另存为 .xlsx 或 .csv」。

### 6.3 文件放置与命名

```
skills/bom-sourcing/
  scripts/
    rbxlsx.py            # 新：解析 + 迁移 + decide（本规格主体）
    blacklist.py         # 改：list/add/remove 走 v2；filter_records 转调 decide
    bom.py               # 不改（_blacklist_filter 已兜底）
  references/
    rbxlsx-schema.md     # 新：字段表 + 等级词表（给人和 LLM 看）
  data/knowledge/
    blacklist.yaml       # 升 v2（先 .bak 备份）
```

- 解析器**独立成 `rbxlsx.py`**，不要塞进 `blacklist.py`（后者已 422 行，且解析与写门禁是两件事）。
- CLI 入口挂在 `blacklist.py import-xlsx <path> --authorized [--dry-run] [--sheet 名称]`，与现有 `import` 子命令并列。
- 临时/调试产物一律落 `Bom_Flow\probe\rbxlsx\`，**不要**写进 skill 目录。

### 6.4 性能与体量

常规红黑榜（100–2000 行）< 0.5 s；1 万行约 1–2 s（openpyxl 正常内存模式）；> 5 万行改走 CSV。
`decide()` 每次 `dict` 线性扫数百条无压力；超过 5000 条再建 `norm_key → entry` 索引（预留 `library["_index"]` 惰性缓存，序列化时剔除）。

### 6.5 落地路线（4 步，每步可回滚）

1. **加 `rbxlsx.py`**（只读，不接线）→ 用 §5 的 17 条用例回归，`probe/` 里跑。
2. **加 `migrate_v1_to_v2` + `--dry-run`** → 对现有 `blacklist.yaml` 跑 diff，人工确认条目数一致。
3. **改 `blacklist.py` 的 `filter_records` 转调 `decide`** → 跑一遍现有配单（`pick.py`）对比输出，`bl_hits` 必须逐字相同。这是唯一可能改变现有行为的步骤，必须**前后对比同一份 BOM 的输出 diff** 才算通过（[经验]「脚本没报错」不构成验证）。
4. **切数据文件**（备份后写 v2）→ 再跑一次配单，确认无新增拦截。

---

## 附录 A 等级词全表（[实测] 22 词）

| 输入 | 归一化 | 命中方式 |
|---|---|---|
| 白 / 白名单 / 优选 / 合格 / 正常 / 可用 | allow | exact |
| Approved | allow | exact（小写后） |
| 黑 / 黑名单 / 禁用 / 拉黑 / 注销 | deny | exact |
| 不合格 | deny | exact（**先于**子串 `合格`） |
| Banned | deny | exact |
| 灰 / 灰名单 / 限用 / 限制 / 观察 / 待定 | restricted | exact |
| Restricted / Conditional | restricted | exact |
| 半黑半白 | deny | substr `黑` |
| （空） | None | empty |
| 其它 | None | `W_UNKNOWN_VERDICT` |

## 附录 B 复放命令

```powershell
cd D:\WorkDesigns\3_WorkTools\Bom_Flow
$env:PYTHONUTF8="1"
python probe\rbxlsx\make_samples.py
python probe\rbxlsx\rbxlsx_proto.py *> probe\rbxlsx\_run_$(Get-Date -f yyyyMMdd).txt
```

## 附录 C 未决问题

| # | 问题 | 当前取向 | 需谁定 |
|---|---|---|---|
| Q1 | `待定` 归 `restricted` 还是 `None` | 归 restricted（保守拦截） | 采购 |
| Q2 | `restricted` 且 `scope` 为空时是否按 `deny` 处理 | 是（无范围=最严） | 采购 |
| Q3 | v2 是否还保留 v1 的空 `brands/shops/codes` 键 | 保留一个版本周期 | 维护者 |
| Q4 | `authorized: false` 的条目是否参与判定 | 参与（`list` 标红提醒） | 安全 |
| Q5 | 是否支持「项目级」独立名单文件 | 暂不，先靠 `scope.project` | 产品 |
