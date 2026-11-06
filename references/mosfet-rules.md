# MOSFET 判据速查（含 EAS / SOA / 工艺反推）

> 机读版：`data/knowledge/mosfet.yaml`
> 研究过程：`research/mosfet-selection.md`（900 行，含 5 个测试用例与 10 组实测回放）
> 原始探针：`probe/mosfet/`（22 脚本 + 14 份带时间戳产物）

---

## 0. 一句话结论

立创接口只够做**电气初筛**（Vdss / Id / RDS(on) / 沟道类型 + 封装 + 价格库存）。
**抗冲击（EAS）、SOA、工艺类型、热阻、Tjmax 全部 0% 覆盖，必须查手册。**
所以「pick 命中 N 条」永远不等于「这些都能用」。

---

## 1. 立创能自动判定的部分

| 参数键（`paramLinkedMap` 原文） | 覆盖率 | 解析率 | 坑 |
|---|---|---|---|
| `漏源电压(Vdss)` | 100% | 99.7% | 唯一失败是 `1.5kV` |
| `连续漏极电流(Id)` | 100% | 93.6% | 21 条 `300mA` 类 mA 单位；`32A；17A` 双值取大 |
| `导通电阻(RDS(on))` | 100% | 100% | **100% 带 `@Vgs` 条件**（@10V 72% / @4.5V 20% / @2.5V 5%），跨条件直接比是错的 |
| `数量`（= 沟道类型，如 `1个N沟道`） | 99% | — | 要解析成 N/P 沟道 + 通道数 |
| 封装 | 99.4% 非空 | — | **49 种写法**，需归一表 |
| 价格 / 库存 | — | — | 阶梯价 + 多仓库存 |

## 2. 立创拿不到的部分（必须查手册）

`Pd@Tc=25℃` 0.7% · `Vgs(th)` 0.3% · **Qg / Qgs / Qgd / Ciss / Coss / Crss / Qrr / trr /
Vgs(max) / Rθja / Rθjc / Tjmax / EAS / EAR / SOA 曲线 / 工艺类型 / AEC-Q101 / EOL —— 全部 0%**。
`datasheet` 字段 **0/330**，取手册只有一条路：

```bash
python lcsc.py detail C20917 --pdf          # 拿签名直链
python lcsc.py detail C20917 --download ./pdfs
# 然后交给 read-pdf skill 读第一段（工艺描述）+ SOA 图 + 雪崩表
```

---

## 3. EAS（单脉冲雪崩能量）

### 3.1 标准与公式

- IEC 60747-8:2010+AMD1:2021 §6.2.3.2（非重复雪崩能量）/ Fig.16（感性雪崩开关电路）
- JEDEC JESD24-5（Single Pulse UIS Avalanche Test Method）
- AEC-Q101 Rev E（子文档 -004 含 UIS）

```
E_AS = ½·L_loop·i_AS(0)² · V_DS,peak / (V_DS,peak − V_DD)     # VDD 未断开
E_AS = ½·L·i_AS(0)²                                          # VDD 在雪崩中断开
E_AS = ∫ V_(AV)DSS(t)·i_AS(t) dt                             # 精确式
t_av  = L·I / (V_AV − V_DD)
ΔTj   = E_AS × Z_th(t_av) / t_av
```

**余量要求 2.0×**（`margin_required: 2.0`），`V_AV` 默认取 `1.2 × Vdss`。

### 3.2 自检算例（Infineon 原文）

`L=100µH`、`i_AS(0)=50A`、`V_DS,peak=72V`、`V_DD=12V`：
- 不降额 `0.125 J`
- 带降额 `0.150 J`
- 两者差 20% —— **就是因为 VDD 是否在雪崩中断开**。别只抄一个数。

### 3.3 判定

`E_AS_req ≤ E_AS_rated / 2.0` 才 PASS。缺 EAS 额定值 → 结论只能是 `NEED_DATASHEET`。

---

## 4. SOA（安全工作区）—— 为什么必须查手册

三条理由，任何一条都足以否掉「算出来」的做法：

1. **SOA 是实测曲线**，不是算出来的。Nexperia 明确写 measured 而非 calculated；
   Spirito 能力限（`V_DS·∂I_D/∂T ≤ 1/f_th`）是直接画在图上的。
2. 线性区低于 ZTC 点（`∂I_D/∂T > 0`）时是**正反馈**，热流丝化（current filamentation）
   会让局部温度远超平均温度。**「平均结温 < Tjmax 所以安全」在物理上就是错的。**
3. SOA 成立的前提是：**单元一致性 + die attach 焊层完整（无空洞/倾斜）+ 热阻分布均匀**
   —— 立创字段一条都反映不了。

**硬规则**：`EAS / EAR / SOA / Zth` 四项任一缺失 → verdict 必须是 `NEED_DATASHEET`。
线性区 / 缓启动 / 热插拔三类应用，即使有 SOA 也要提示上述三条前提。

---

## 5. 工艺类型（平面 / 沟槽 / SGT / 超结）

### 5.1 为什么重要

| 工艺 | RDS·Qg | 抗雪崩 | 线性区 SOA | 典型电压 |
|---|---|---|---|---|
| 平面 Planar | 差 | **最强** | **最好** | ≥200V |
| 沟槽 Trench | 好 | 中 | 中 | 30~200V |
| 屏蔽栅 SGT | 最好 | 中偏差 | 差 | 25~150V |
| 超结 SuperJunction | 极好 | 差 | 差 | ≥500V |

**选错工艺的后果**：缓启动/热插拔用了 SGT，线性区会烧；高压场合用平面，损耗下不来。

### 5.2 怎么判定（标注：检索事实 vs 推论）

| 手段 | 等级 | 说明 |
|---|---|---|
| 手册首页工艺描述（Planar / Trench / SGT / Superjunction / CoolMOS / MDmesh） | **fact** | 最可靠，`lcsc.py detail --pdf` 后读第一段 |
| 原厂官网产品页的技术分类 | **fact** | 如 Infineon CoolMOS、ST MDmesh、onsemi SuperFET |
| 型号家族名（OptiMOS / Trench / SJ / P7） | **inference** | 只在已知家族内可靠，跨厂商不通用 |
| 型号命名规律（IRF=平面、IRL=逻辑电平沟槽、…P7=CoolMOS 超结） | **inference** | 需品牌白名单，跨厂商会错 |
| `Vdss≥500V` 且 RDS 显著低于同压平面管 | **inference** | 横向对比推断，需同封装同测试条件 |
| 同封装下 RDS 明显更低 | **inference** | 同上 |
| 封装统计（TO-247 多高压平面/超结；DFN5x6 多低压 SGT） | **inference** | 330 条样本的统计规律，有反例 |
| 品牌档位 | **inference** | 由品牌产品线推断 |

**硬规则**：应用 ∈ {linear, soft_start, hot_swap} 时，工艺类型必须来自手册或官网（fact 级）；
只有型号名推断时，结论措辞必须是「**疑似 <工艺>，需查手册确认**」，不得直接给可用。

### 5.3 网络检索查证（m03347 要求）

工艺类型不是「猜」出来的，标准动作是**两个来源交叉**：

```bash
# 1) 手册（fact）
python lcsc.py detail C20917 --pdf

# 2) 原厂官网 / 分销商页面（fact 或 inference，按来源分级）
python distributor.py search "AO3400A" --site mouser      # 描述里常带 Trench/Planar
python origin.py search "TPA7836B" --vendor 3peak
```

搜索结果里凡是「二手论坛说它是沟槽」这类，只能记 `inference` 并注明「来自社区，未核实」。

---

## 6. 应用语义（9 类）

| 应用 | 关键判据 | 常见错误 |
|---|---|---|
| 负载开关 | 工作电压区间覆盖、最大连续电流、导通电阻、软启动 | 只看 Vdss/Id，忽略 SOA |
| 缓启动 / 热插拔 | **SOA + Zth**（必须手册） | 用 Rdson 算功耗就当够 |
| 线性 / LDO 旁路 | **SOA 线性区**、热阻 | 忽略 ZTC 点以下的正反馈 |
| ORing / 理想二极管 | 反向漏电、Vf、快速关断 | 忽略反向恢复 |
| 电机驱动 | 雪崩、体二极管、热循环 | 忽略堵转电流 |
| 开关电源主开关 | Qg、Coss、RDS·Qg、开关损耗 | 忽略 @Vgs 条件 |
| 电池保护 | 低 RDS、ESD、封装热 | 忽略双 N 每通道比价 |
| 抗冲击 / 浪涌 | **EAS / EAR**（必须手册） | 用平均电流算 |
| 汽车 / 工业 | AEC-Q101、PPAP、EOL/PCN | 只看温度等级 |

---

## 7. 已知缺陷（pick.py 侧，已修 / 待修）

已修（提交 `68084b7`）：

- `parse_ohm` 漏 `m/µ/u/n/p` 单位 → `48mΩ` 当 `48Ω`（买错 500 倍）
- `match_family` 单字母子串误判 → `N` 命中 `inductor`、`P` 命中 `mpu`
- `parse_intent` 负压丢失 → `-30V` 读成 `30V`；P/N 沟道不生成约束

待修 / 边界：

- 候选池默认只扫 2 页（60 条），「0 命中」≠ 市场没有 → `--pages` 调大
- `totalCount` 服务端硬上限 1500，无法全量枚举
- 关键词里的数字是**精确等于**不是 `≥`（`30V 5A` 只返 Vdss=30 且 Id=5）
- 参数区间**无服务端筛选**，只能客户端过滤
- 双 N 封装未按每通道比价；封装 49 种写法未完全归一

---

## 8. 参考

- IEC 60747-8:2010+AMD1:2021 §6.2.3.2、Fig.16 / Fig.18
- JEDEC JESD24-5（Single Pulse UIS Avalanche Test Method）
- AEC-Q101 Rev E（-004 UIS）
- Spirito, P. (2005) — 热丝化判据 `V_DS·∂I_D/∂T ≤ 1/f_th`
- Nexperia AN90003 / Infineon AN 应用笔记（SOA 与雪崩测试口径）
