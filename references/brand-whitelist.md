# 品牌白名单（品牌 × 品类放行）

> 机读文件：`data/knowledge/whitelist.yaml`　｜　工具：`scripts/whitelist.py`
> 相关：`references/brand-due-diligence.md`（怎么背调）、`references/vendors.md`（厂商分层）、
> `data/knowledge/blacklist.yaml`（黑名单，优先于白名单）

## 1. 为什么白名单是「品牌 × 品类」而不是「品牌」

同一品牌下不同品类的实际生产方、产线、质量体系**可以完全不同**：

- **贴牌/代理型**（如 Tokmas）：在连接器上由自有产线制造，在双极型晶体管上只是给通用料号
  （`ULN2803CDW`、`CP2102-GMR`）贴自家品牌 —— 前者可追溯，后者不可。
- **IDM 型**（如 ST、TI）：多数品类可追溯，但停产/转厂（PCN）后批次差异仍需逐料确认。
- **贸易商型**（`trader`）：任何品类都没有产线证据。

所以「这个品牌能用」这个结论**只对核过的品类成立**。一个品牌在 A 品类背调通过，
不代表它在 B 品类也能用 —— B 品类必须重新取证。

## 2. 规则（用户 m03469）

> 每次引入新品牌的时候，或者已有品牌但进入非同类物料的时候，都要进行背调或者知识库核对。
> 引入的品牌存储在白名单。

拆成三条可执行规则：

1. **新品牌引入**：结果里出现白名单与知识库都没有的品牌 → `unknown` → 必须走 `brand_dossier.py` 取证，
   通过后 `whitelist.py approve` 才能当结论。
2. **已有品牌进入非同类物料**：品牌在别的品类通过了，但本品类没核过 → `approved_other_family`
   → 必须补该品类证据（产线/授权/规格书/来料报告任一）。
3. **知识库核对优先**：`vendors.yaml` 已有分层（tier + 置信度 + 证据）的品牌 → `kb_known`
   → 可以推荐，但输出必须注明「本品类未单独背调」。

## 3. 五态判定

| 状态 | 触发条件 | 能不能推荐 | 输出措辞 |
|---|---|---|---|
| `approved` | 白名单里该品牌 × 本品类通过 | ✅ | 直接给结论 |
| `kb_known` | 白名单没有，但 `vendors.yaml` 有分层 | ✅ 但需注明 | 「知识库已知，本品类未单独背调」 |
| `pending` | 本品类已登记待背调 | ❌ | 「已登记待背调，证据不足」 |
| `approved_other_family` | 品牌只在别的品类通过 | ❌ | 「该品牌只在 A 品类背调过，本品类未核」 |
| `unknown` | 白名单与知识库都没有 | ❌ | 「必须先做品牌背调」 |
| `blacklisted` | 命中黑名单（**优先级最高**） | ❌ | 「已拉黑」 |

`blacklisted` 是为了让两个名单在同一条输出里语义自洽 —— 黑名单命中时不再讨论白名单状态。

## 4. 文件结构

```yaml
schema: bom-sourcing/knowledge/whitelist
version: 2
generated: '2026-11-06'
brands:
  tokmas托克马斯:                      # 归一化后的键（norm()）
    name: Tokmas(托克马斯)
    aka: [托克马斯, TOKMAS, 广州托克马斯电子有限公司]
    brand_id: 12489
    tier: original_fabless
    dossier: data/knowledge/brands.dossier/12489-tokmas.yaml   # 背调档案（证据链在这）
    note: fabless，晶圆流片与封装均代工；代理话术不采信
    authorized: 傅师傅 2026-11-06 指定 Tokmas 进入白名单流程
    approved:
      - family: connector
        label: 连接器/排针
        catalog_id: '644'
        basis: 圣禾堂（深圳）电子科技 2026-08-18 官方授权代理公告：产品线为连接器与开关元器件
        grade: fact
        date: '2026-11-06'
    pending:
      - family: bjt
        label: 双极型晶体管(BJT)
        catalog_id: '326'
        reason: 只见过 C53133678 ULN2803CDW(TOKMAS) 一条通用料号贴牌，无该品类产线/质量证据
```

- **键**用 `norm(name)`（小写去空白去括号），品牌全称/英文名/中文名/品牌 id 都能查到。
- `approved[].grade` 只接受 `fact / claim / inference`（对应背调档案的三级标注），
  且 `claim` / `inference` 级的放行**必须**在 `basis` 里说明为什么可以接受。
- `pending` 不是"黑名单"，是**待办队列**：见过料号、证据不足，等补证据。
- `authorized` 是审计字段：谁、什么时候、为什么授权写入。

## 5. 操作手册

```bash
cd scripts

# 1) 登记新品牌（还没有任何品类通过）
python whitelist.py add "Tokmas(托克马斯)" --brand-id 12489 --aka 托克马斯 TOKMAS \
    --tier original_fabless --dossier data/knowledge/brands.dossier/12489-tokmas.yaml \
    --authorized "傅师傅 2026-11-06 指定进入白名单流程"

# 2) 某品类放行（必须有依据）
python whitelist.py approve "Tokmas(托克马斯)" --family connector --label 连接器/排针 \
    --catalog-id 644 --basis "圣禾堂 2026-08-18 官方授权代理公告" --grade fact \
    --authorized "傅师傅 2026-11-06 按背调结论放行"

# 3) 登记待背调（见过料号但证据不足）
python whitelist.py pending "Tokmas(托克马斯)" --family bjt --catalog-id 326 \
    --reason "只有一条通用料号贴牌" --authorized "傅师傅 2026-11-06 登记待办"

# 4) 查询与体检
python whitelist.py check "Tokmas(托克马斯)" --family bjt
python whitelist.py list
python whitelist.py validate
```

**写入门禁（硬规则）**：`add` / `approve` / `pending` 全部要求
`--authorized "<谁/什么时候/为什么>"`，缺失直接 `exit 2`。**不要手工编辑 `whitelist.yaml`** ——
脚本负责归一化、去重、补 `date` 与审计字段。

## 6. 与 pick.py / bom.py 的集成

两个入口默认都会做白名单核对（`--no-whitelist` 关闭），输出「## 品牌白名单核对」段：

```
- ✅ 已背调（本品类通过）：Tokmas(托克马斯)（2 条）
- 📚 知识库已知（本品类未单独背调）：ST(意法半导体)[original_idm]；UMW(友台半导体)[domestic_second] 等 11 个品牌
- ⚠ **需要先背调/核对 5 个品牌**（未通过前不要当结论）：
  - ❔ 未背调 **RICHTEK(立锜)**（3 条，如 C47773、C15651）—— 白名单与知识库都没有这个品牌
  - 处置：`python brand_dossier.py new/add ...` 取证 → `python whitelist.py approve ...`
```

- **`--strict-brand`**：只保留 `approved` + `kb_known` 的候选（适合"只要能用确定的料"的场景）。
- **`bom.py`** 逐行按 `_family()` 判品类 —— 同一品牌在不同行可能是不同状态，
  这是**正确行为**（Tokmas 连接器料放行、BJT 料待背调）。
- JSON 输出带 `brand_whitelist`（`pick.py`）与逐条 `whitelist_status` 字段。

## 7. 维护约定

- **谁来写**：只有用户在对话里明确指定"这个品牌可以用 / 这个品类核过了"才写；agent 不能自行放行。
- **什么时候复核**：授权代理变更、转厂/PCN、连续来料不良、品牌主体变更（商标转让）→ 重新取证。
- **过期**：`approved[].expires` 可选；到期后自动降级为 `pending`（脚本目前只做提示，不自动删）。
- **不要为了消警告批量放行**：`unknown` 是有意义的信号，它告诉你"这条结论还没有证据"。

## 8. 已知边界

- 白名单只覆盖 `data/categories.yaml` 里的 26 个 family；未归类的料按 `unknown` 处理。
- `kb_known` 只代表 `vendors.yaml` 有分层，**不代表该品类验证过** —— 输出措辞已固定，不要改写成"已核"。
- 品牌名归一化是**子串命中**（`tokmas` 能命中 `Tokmas(托克马斯)`），因此极短的名字（如 `ST`）
  可能误命中（`STMicro`），此时以完整 `productGradePlateName` 为准。
- 白名单不替代来料检验：通过背调只说明"来源可追溯"，不说明"批次一致"。
