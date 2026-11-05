# 厂商 / 品牌可信度（vendors）

> 目标是回答：**同一个料号，这家品牌能不能用、用在什么场合、什么场合绝对不能省这个钱。**
> 机读版：`data/knowledge/vendors.yaml`；实测采集记录：`Bom_Flow/research/vendors.md`。
> 品牌名一律原样取自立创 `productGradePlateName`（含中文括号），2026-11 快照。

## 1. 这份表解决什么问题

同一个型号在立创上常挂着十几个品牌的 C 号，价差是真实存在的：

| 型号 | 品牌数 | 最低价 | 最高价 | 价差 |
| --- | --- | --- | --- | --- |
| S8050 | 17 | ¥0.0393（FOSAN 富捷/富信） | ¥0.1004（BORN 伯恩） | 2.6× |
| SS34 | 13 | ¥0.1356（Zhengxin 正芯） | ¥3.1000（onsemi 安森美） | 22.9× |
| AMS1117-3.3 | 13 | ¥0.2308（国芯佳品） | ¥1.2589（Advanced Monolithic Systems） | 5.5× |
| AO3400A | 10 | ¥0.1772（baocheng 宝乘） | ¥0.5430（AOS 原厂） | 3.1× |
| PC817C | 6 | ¥0.1389（AOTE 奥特） | ¥0.5416（Slkor 萨科微） | 3.9× |

只按价格排序，会稳定地选出最便宜的贸易商品牌。打样时这没问题，量产时意味着批次一致性、
参数一致性、可追溯性都没有保障，**返修成本远高于料价差**。

所以这份表的态度是：**不是黑名单，是「按场合选择信任层级」的映射。**
贸易商在打样阶段是合理选择，原厂在认证场合是唯一选择。

## 2. 五档定义与判据

| tier | 中文 | 定义 | 价格指数（相对原厂） | 典型例子 |
| --- | --- | --- | --- | --- |
| `original_idm` | 原厂 IDM | 自有晶圆/封测产线的原厂，或自有品牌的全流程制造商（含阻容感、连接器、继电器等无源件龙头） | 1.0 | TI(德州仪器)、ST(意法半导体)、muRata(村田)、YAGEO(国巨)、FH(风华)、松乐 |
| `original_fabless` | 原厂 Fabless | 无自有晶圆厂但**自有设计、自有型号与品牌** | 0.9 | WCH(南京沁恒)、GigaDevice(兆易创新)、3PEAK(思瑞浦)、西安航天民芯、AOS |
| `domestic_second` | 国产二线 / 替代品牌 | 有自有型号体系与官网的二线/替代品牌，多为 pin-to-pin 兼容件 | 0.3 | UMW(友台半导体)、HGSEMI(华冠)、MDD(辰达)、HRE(芯声)、HKT(合科泰) |
| `trader` | 贸易商 / 贴牌散货 | 无自有产线、无自有型号体系的贴牌/散货品牌 | 0.15 | JSMSEMI(杰盛微)、GOODWORK(固得沃克)、R+O(宏嘉诚)、FOSAN(富捷/富信)、国芯佳品 |
| `unknown` | 未判定 / 无牌 | 无官网、无中文名，或资料不足以判定 | — | 脚本自动回填 |

价格指数是**同一型号内**的相对比值，不是绝对价格。

字段（`vendors.yaml` 每个品牌）：`name` / `aka` / `tier` / `type` / `country` / `evidence` /
`confidence` / `risk_note` / `observed`（实测频次与最低价）/ `typical_parts`（实测见到的型号 + C 号）/ `sources`。

`evidence` 四档：`official`（官网/授权名录，可作硬约束）、`measured`（本仓 `probe/vendors/` 实测，
可作硬约束）、`secondary`（第三方转述，只作提示）、`experience`（行业经验，可被推翻）。

## 3. tier 如何影响推荐（可执行规则）

`pick.py` / `bom.py` 的调用顺序是固定的：**先指标核对，再品牌分层，最后价格排序**。
品牌层不能反向放宽指标约束。

### 3.1 硬过滤（按使用场合）

```python
ALLOWED = {
    "prototype":       {"original_idm", "original_fabless", "domestic_second", "trader"},
    "small_batch":     {"original_idm", "original_fabless", "domestic_second"},
    "mass_production": {"original_idm", "original_fabless"},
    "certified":       {"original_idm", "original_fabless"},   # 且必须能拿到官方 datasheet
}

def brand_gate(tier: str, stage: str) -> tuple[bool, str | None]:
    if stage in ("mass_production", "certified") and tier in ("trader", "unknown"):
        return False, f"量产/认证场合不接受 {tier} 品牌，请换原厂或二线料号"
    if stage == "certified" and tier == "domestic_second":
        return False, "认证场合不接受二线替代品牌"
    if stage == "prototype" and tier == "trader":
        return True, "贸易商品牌，量产需换原厂/二线料号"
    return True, None
```

### 3.2 加分（同等规格下的排序）

```python
SCORE_BONUS = {          # 权重 15%，与 spec-rules.yaml 的 brand_score 对齐
    "original_idm": 1.00,
    "original_fabless": 0.90,
    "domestic_second": 0.45,
    "trader": 0.10,
    "unknown": 0.00,
}
score += 0.15 * SCORE_BONUS[tier]
```

### 3.3 三条不可协商的规则

1. **`tier` 只用于同规格候选排序，不得因为 tier 高而放宽 `spec-rules.yaml` 的硬约束** —— 原厂的错料依然是错料。
2. **`unknown` 在量产/认证场合直接剔除**（`no_unknown_in_mass`），不管价格。
3. **同 MPN 多个 C 号时先按 C 号去重、取有货者，再比 tier** —— 同型号不同 C 号库存完全独立
   （W25Q64JVSSIQ 的 C179171 有货 1383，C83140 库存 0）。

### 3.4 输出约定

- 推荐结果里每个候选必须带 `tier` 与 `evidence` 字段，报关/量产评审时要能自证。
- 命中 `trader` 但被放行的，必须附 `warning` 文案（见 3.1），不允许静默通过。
- 采购单只写 `name`（完整 `productGradePlateName`）而不写简称，详见第 6 节。

## 4. 怎么判定一个新品牌属于哪一档

### 4.1 四个机械判据（先跑脚本，别先凭印象）

| 判据 | 阈值 | 含义 |
| --- | --- | --- |
| **品类横跨度** | 同一品牌出现在 **≥5 个不相关品类** | 原厂只在自家品类出现；横跨二极管、MOS、LDO、运放、555、光耦的一定是贸易商/贴牌 |
| **价格档位** | 同型号中位价的 **<20%** | 低于原厂 5 倍以上的，基本可判定为贴牌散货 |
| **型号后缀** | MPN 带 `-HXY` / `-JSM` / `-XBLW` / `-MS` / `-ED` 等品牌缩写后缀 | 贴牌代工的机械特征；同名但后缀不同，**不能当作原厂料号** |
| **可查性** | 官网 / 官方 datasheet 拿不到 | 无 datasheet 的一律 `unknown`，不管价格多低 |

实测例子（本次 645 条记录）：JSMSEMI 横跨 10 个品类、GOODWORK 9 个、FOSAN 8 个、R+O 7 个 ——
全部判为 `trader`；而 TI 32 条记录只落在 4 个相关品类（LM2596/LM358/NE555/TL431），YXC 22 条只在晶振。

### 4.2 人工查证清单（新增品牌必做）

1. **官网**：是否有独立官网、产品线是否自洽（做 LDO 的通常不做光耦）。
2. **型号体系**：厂商前缀是否稳定（如 `AMS1117` 是 Advanced Monolithic Systems 的原型号，
   其它品牌叫 `AMS1117-3.3` 是兼容件；而 `TCC0603X7R104K500CT` 这种带厂商前缀的才是自有型号）。
3. **公司实体**：企查查/官网「关于我们」是否写明自有产线（IDM）还是 fabless。
4. **授权**：是否出现在原厂授权代理名录里（决定能不能开原厂 COC）。
5. **实测取样**：至少买 1 批做关键参数抽测（Rds(on) 的测试条件、CTR 分档、温漂）。

### 4.3 证据等级怎么填

- 官网明写 → `official` + `confidence: high`
- 本仓脚本实测到频次/价格 → `measured` + `confidence: medium`（价格是快照）
- 只有论坛/媒体转述 → `secondary`，**不得用于硬过滤**
- 凭行业常识 → `experience`，必须写清可被推翻的条件

## 5. 维护流程（新增与复核）

### 5.1 新增一个品牌

```powershell
cd D:\WorkDesigns\3_WorkTools\Bom_Flow\probe\vendors
# 1) 把新关键词加进 collect.py 的 KEYWORDS，重跑采集
python collect.py
# 2) 看频次与同型号多品牌分组
python stats.py; python by_keyword.py
# 3) 在 gen_vendors.py 的 CATALOG 里登记（tier / type / country / aka / risk_note）
#    未登记的会被自动回填成 unknown —— 这是有意设计，宁可 unknown 也不要瞎猜
python gen_vendors.py
python report.py
```

登记时三个硬要求：

1. `name` **原样复制**立创 `productGradePlateName`，不改写、不翻译、不补空格。
2. `tier` 必须有第 4 节的机械判据或人工查证支撑，否则填 `unknown`。
3. `risk_note` 写「能用在什么场合、什么场合禁用」，不写「质量差」这种不可执行的话。

### 5.2 复核周期

| 触发条件 | 动作 |
| --- | --- |
| 每 **6 个月** | 全表复核一次（品牌被并购、改名、停产） |
| 每 **3 个月** | 抽查 `trader` / `unknown` 两档（这两档最容易变化） |
| 采到 **新品类的关键词** | 只复核该品类相关品牌，不整表重跑 |
| 发现某品牌被爆**翻新/涂标/参数虚标** | 立刻降级（见 5.3），并在 `risk_note` 写清事件 |
| 某品牌**拿到原厂授权/自建产线** | 可升级，但必须有 `official` 证据 |

### 5.3 降级与失效条件

| 现象 | 处理 |
| --- | --- |
| 同品牌同型号出现「涂标」「散新」「批次」备注 | 直接降到 `trader`，`risk_note` 标注事件 |
| 实测参数与标称不符（如 Rds(on) 只在最优条件测得） | 降一档 + `risk_note` 写明测试条件差异 |
| 品牌被并购/改名 | 旧名进 `aka`，新名作 `name`，不删旧记录 |
| 连续两次复核都查不到官网 | 降到 `unknown` |
| 出现 EOL/停售 | 不进 tier 调整，走「库存 0 剔除」（`dedup_rule`） |

降级是**单向保守**的：没有 `official` 证据不得升回 `original_*`。

## 6. 命名与重名坑（真实踩过）

| 立创品牌名 | 容易混淆的对象 | 风险 |
| --- | --- | --- |
| `FOSAN(富捷/富信)` | `FOJAN(富捷)` | 两个不同实体，中文名都含「富捷」 |
| `ST(先科)` | `ST(意法半导体)` | **完全不同**：先科是国产二极管品牌，意法是原厂 |
| `RS(容硕)` | RS Components | 前者国产，后者国际分销商 |
| `HUAWEI(华威集团)` | 华为 | 国产连接器/元件品牌，与华为无关 |
| `JBL(金比莱)` | JBL 音响 | 国产连接器品牌 |

结论：采购单和 BOM 里**只写完整 `productGradePlateName`**，禁止写「ST」「富捷」这类简称。
`name_collision_check` 是硬规则，不是建议。

## 7. 已知局限

- **价格是瞬时快照**（2026-11-05），只用于量级比较；阶梯档不同品牌的起订量不同，不可直接比单价。
- **`unknown` 档 12 个品牌不是「坏品牌」**，是「本次采集资料不足」——需要人工补证，不是黑名单。
- 立创的 `productGradePlateName` 会随品牌入驻/改名变化，本表按快照记录，**以页面为准**。
- 同一品牌不同产线/不同封装可能品质不一致（尤其 `domestic_second`），tier 是品牌级判断，不替代批次抽检。
- 本表不做「好/坏」评价，只做「场合匹配」。
