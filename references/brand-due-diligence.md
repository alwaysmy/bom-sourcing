# 品牌背调（Brand Due Diligence）

> 回答一个问题：**这个牌子能不能用、能不能追溯**。
> 不回答：这颗料的参数够不够（那是 `spec-rules.yaml` + `pick.py` 的事）。

机器可读：`scripts/brand_dossier.py` + `data/knowledge/brands.dossier/*.yaml`
分层用法：`data/knowledge/vendors.yaml`（`tier` 字段）→ `pick.py` / `bom.py` 排序时使用

---

## 0. 为什么不能只靠立创料号反推

早期 `vendors.yaml` 的分层是从立创检索结果里归纳的：看这个品牌卖什么料、卖多贵、横跨多少不相关品类。
这条路子有一个硬缺陷：

> **只在立创上卖冷门料的品牌，永远进不了采样集合。**

真实案例：Tokmas(托克马斯) 在立创只有 322 条料号，采样时用的是「稳压 / 电阻 / SS34 / AMS1117」
这类关键词，它的型号（ULN2803CDW、MC1496DR2G、CP2102-GMR）一个都没被检索到 → 144 个品牌的
知识库里没有它 → 被当成「不存在」。

而实际上，站点外能查到的东西非常多：

| 能查到什么 | 在哪查 | 说明 |
|---|---|---|
| 工商主体 | 国家企业信用信息公示系统 / 企查查 / 天眼查 / 爱企查 | 公司全称、注册资本、成立日期、经营异常 |
| 是否自有产线 | 品牌官网「关于我们 / 工厂 / 认证」 | 决定 IDM 还是 fabless |
| 商标归属 | 中国商标网 / CIPO / USPTO | 品牌名是否在自有实体名下 |
| 授权代理 | 代理商官网的签约公告 | 有官方授权 = 有正规渠道 |
| 官网产品线 | 品牌官网 | 产品线宽度是否与自述一致 |
| 社区口碑 | 知乎 / 贴吧 / B站 / CSDN / 立创社区 / EEVblog | 翻新、假货、批次一致性投诉 |
| 通用料号痕迹 | 立创/分销商页面 | 型号是不是别人的通用料号贴自家品牌 |

---

## 1. 取证渠道与可信度顺序

`brand_dossier.py` 的 `CHANNELS` 按可信度排序，**同一个结论有多个渠道时取排前的**：

| 渠道 key | 名称 | 能给 fact 吗 |
|---|---|---|
| `official_site` | 品牌官网 | ✅ |
| `official_doc` | 官方文档 / 认证证书（RoHS/REACH/AEC-Q/UL） | ✅ |
| `trademark` | 商标注册公告 | ✅ |
| `business_registry` | 工商登记 | ✅ |
| `authorized_dist` | 授权代理公告 | ✅ |
| `qcc_ic` | IC 资料站（114ic / icpdf / 立创品牌页） | ✅ |
| `lcsc_brand_page` | 立创商城品牌页 | ✅ |
| `distributor_page` | 分销商商品页 | ✅（仅限商品事实） |
| `community` | 社区口碑 | ❌ 只能 claim |
| `complaint` | 质量投诉 / 翻新料报告 | ✅（若有原始链接） |
| `agent_site` | 代理商/店铺自述（营销文案） | ❌ **只能 claim** |
| `inference` | 本仓推论 | ❌ 只能 inference |

> 代码里 `CLAIM_ONLY = {"agent_site", "community"}` 是硬约束：往这两个渠道写 `--grade fact` 会直接报错。

---

## 2. 三级标注（这是整套东西的核心）

任何一条结论都要能回答：**这是查到的，还是推出来的？**

| 等级 | 含义 | 例子 |
|---|---|---|
| `fact` | 可点开链接复核的客观事实 | 商标注册号 18357895 归属广州托克马斯电子有限公司 |
| `claim` | 对方自己的说法，无第三方佐证 | 「1995 年成立、年销售额超 6 亿美元」 |
| `inference` | 由上面事实推出的结论 | 「自述流片封装均代工 + 有授权代理 → 判为 fabless」 |

**输出规则**：`fact` 与 `inference` 必须分列；**inference 不得单独作为「可用」的判据**，
只能作为「建议进一步查证的方向」。若结论主要靠 inference 撑着，必须写进 `gaps`。

---

## 3. 分层判定规则（`tier_from_evidence`）

只认 `fact` 级证据；`claim` 只降低 confidence，不升 tier。

| tier | 判定条件 |
|---|---|
| `original_idm` | 官网 + 认证证书显示**自有产线**（工厂地址、产线介绍、UL/ISO 证书） |
| `original_fabless` | 自有品牌 + **明确代工模式**（fabless / 流片代工），或官网/商标在自有实体名下 + 有授权代理 |
| `domestic_second` | 有自有品牌资料（官网/商标/工商），但无产线或代工模式证据 |
| `trader` | 只有目录站/分销页，没有独立品牌资料；同型号挂多个不同品牌 |
| `unknown` | 除立创料号外没有任何独立资料 |

人工可覆盖（`meta --tier ... --reason "..."`），但**覆盖必须写理由**，否则报错。

---

## 4. 操作手册

```bash
cd ~/.agents/skills/bom-sourcing/scripts

# 1) 建档（需要授权说明）
python brand_dossier.py new 12489 --name "Tokmas(托克马斯)" \
    --alias 托克马斯 --alias TOKMAS --authorized "傅师傅 2026-11-06 要求品牌核查"

# 2) 逐条追加证据（渠道 + 链接 + 结论 + 等级 + 把握）
python brand_dossier.py add 12489 --channel qcc_ic \
    --url "https://www.114ic.cn/tokmas/" \
    --claim "工商全称：广州托克马斯电子有限公司；官网 tokmas.com；自述流片封装均代工" \
    --grade fact --confidence high --authorized "..."

python brand_dossier.py add 12489 --channel agent_site \
    --url "http://www.olasshop.com/brandDetails/12489" \
    --claim "宣称 1995 年成立、年销售额超 6 亿美元，多站同文" \
    --grade claim --confidence low --authorized "..."

# 3) 主体信息 + 人工覆盖（如需要）
python brand_dossier.py meta 12489 --legal-entity "广州托克马斯电子有限公司" \
    --website "http://www.tokmas.com" --country CN --authorized "..."

# 4) gaps 与结论（各写一个 UTF-8 文本文件）
python brand_dossier.py gaps 12489 --file gaps.txt --authorized "..."
python brand_dossier.py conclusion 12489 --file conclusion.md --authorized "..."

# 5) 重算分层 + 校验 + 出报告
python brand_dossier.py tier 12489 --authorized "..."
python brand_dossier.py validate 12489
python brand_dossier.py render 12489 --out ../../Bom_Flow/research/brand-tokmas.md
python brand_dossier.py list
```

> **写操作门禁**：`new` / `add` / `meta` / `gaps` / `conclusion` / `tier` 全部要求
> `--authorized "<谁/什么时候/为什么>"`。**品牌结论属于知识库写操作，只有用户明确指定的核查才能落库**
> —— 这条和 `blacklist.py` 同一套纪律（起因：把没被授权的店铺名写进黑名单）。

---

## 5. 落地到采购动作

分层不是「好坏评价」，是**场合匹配**：

| 场合 | 允许的 tier | 额外动作 |
|---|---|---|
| 打样 / 验证 | 全部（trader 也行） | 贸易商必须打 warning |
| 小批量试产 | 除 unknown | 要求批次追溯 |
| 量产 | original_* / domestic_second | 关键料号取原厂规格书 + RoHS/REACH |
| 车规 / 工业级 | original_* 且 AEC-Q101 有证书 | 来料验证（雪崩 / SOA / 批次一致性） |

**通用料号贴牌的品牌（tier=fabless）特别提示**：同一品牌下不同品类的实际生产方可能不同，
关键料号只按「料号 + 规格 + 批次一致性」验收，不按品牌整体信任。

---

## 6. 维护约定

1. **新增品牌必须有 ≥2 条 fact 证据**，否则 `confidence` 只能是 low；
2. 证据链接会失效 —— 每条都带 `fetched` 日期，超过 12 个月视为过期，需重取；
3. 结论若发生变化（例如查到工商异常），**保留旧证据并追加新证据**，不要覆盖历史；
4. 与 `vendors.yaml` 的关系：`vendors.yaml` 是「有证据的子集 + 分层 + 排序权重」，
   `brands.dossier/` 是「完整证据链」。`vendors.yaml` 条目的 `dossier` 字段指回档案路径；
5. `brands.index.yaml` 是立创品牌全集（1,296 个，自动重建），**不要手工编辑**。

---

## 7. 已知边界

- **立创品牌页抓不到内容**：`list.szlcsc.com/brand/<id>.html` 走 Firecrawl 只回 "Safety check"，
  必须用真浏览器（`taobao.Bridge`）或改用 `brands.index.yaml` 的 `part_count`；
- **工商信息需要付费/登录**：企查查、天眼查的原始登记页要账号，公开可查的只有部分；
- **社区口碑检索噪声大**：「托克马斯」同时命中杭州托马克机电、江西托克马克科技、加拿大箱包商标
  TOMKAS 等无关实体，**必须区分同名不同实体**；
- **没有第三方质量数据 = 不等于质量好**：只说明公开信息少，必须写进 `gaps`。
