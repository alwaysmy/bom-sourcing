# 按意图找料（pick.py）实现说明

> 用途：只有一句话需求、还没定型号时，从立创商城品类里筛出候选。
> 全部结论来自 2026-11 实测（立创中文站免登录接口，人民币含税价）。

## 1. 为什么不能"直接搜一句需求"

`POST so.szlcsc.com/query/product` 的 `keyword` 是**站内搜索词**，不是自然语言理解：
`"3.3V 1A 的 LDO"` 丢进去会命中标题里的数字，结果是一锅粥。可行的做法是把需求拆成两层：

| 层 | 用什么表达 | 服务端支持 |
|---|---|---|
| 品类 | `catalogIdFilter` | ✅ 真正收敛（`keyword` 必须非空） |
| 参数 | 无 | ❌ `parmeterValueList` 恒空，只能客户端过滤 `paramLinkedMap` |

## 2. 品类解析：关键词 → `catalogId`

1. 用**裸品类词**检索一次（`keyword=LDO` / `稳压` / `电阻`），**不看结果行、只看 facet**：
   `result.searchResult.catalogGroup[] = [{label:"线性稳压器(LDO)", value:"387", count:65167}, ...]`
2. `value` 就是 `catalogIdFilter` 的取值，同时等于结果的 `productVO.productTypeCode`。
3. 再查一次：`keyword=<品类名> & catalogIdFilter=<value>` —— 品类被真正钉住。
   反证：`keyword=电阻 & catalogIdFilter=387` 只返回 28 条 LDO（不匹配组合被强约束，不会退化成空）。

`data/categories.yaml` 预先存好 25 个常见 family 的 `label_cn` / `catalog_id` / `param_keys`，
所以日常不需要现场解析；表里没有的品类才走上面的动态路径（`pick.py resolve <关键词>` 可直接看品类树）。
`data/categories.json` 是它的 JSON 缓存，运行时**不依赖 PyYAML**。

## 3. 参数约束：动态聚键 + 别名映射

参数键**随类目变化**，不能硬编码：

| 品类 | `paramLinkedMap` 实际键 |
|---|---|
| 线性稳压器(LDO) | 输出极性、工作电压、输出电压、输出电流 |
| DC-DC电源芯片 | 功能类型、工作电压、输出电流、输出电压、开关频率 |
| 场效应管(MOSFET) | 数量、漏源电压(Vdss)、连续漏极电流(Id)、导通电阻(RDS(on)) |
| 单片机(MCU) | CPU内核、CPU最大主频、CPU位数、程序存储容量 |
| 运算放大器 | 输入失调电压(Vos)、放大器数、增益带宽积(GBW)、轨到轨 |
| 贴片电容(MLCC) | 容值、精度、额定电压、温度系数 |
| 贴片电阻 | 电阻类型、阻值、精度、功率 |
| 静电和浪涌保护(TVS/ESD) | 反向工作电压(Vrwm)、钳位电压、极性、峰值脉冲电流(Ipp) |
| 无源晶振 | 晶振类型、频率、常温频差、负载电容 |
| NOR FLASH | 接口类型、存储容量、时钟频率(fc)、工作电压 |

`pick.py` 内置别名表（`ALIASES`）：物理量 → 中文/英文键名片段 + 单位类别 + 极性。

| 物理量 | 匹配键名 | 极性 |
|---|---|---|
| `vout` | 输出电压 / Vout | 相等（2% 相对误差） |
| `vin` | 工作电压 / 输入电压 | 区间包含 |
| `iout` | 输出电流 / 连续漏极电流(Id) | 越大越好 |
| `vdss` / `vrwm` / `vmax` | 漏源电压 / 反向工作电压 / 额定电压·耐压 | 越大越好 |
| `rds` / `iq` | 导通电阻 / 静态电流 | 越小越好 |
| `freq` | 频率 / 开关频率 / 时钟频率 / 增益带宽积 | 越大越好 |
| `flash` / `bits` | 存储容量 / CPU位数 | 越大越好 |
| `tol` | 精度 / 容差 | 越小越好 |
| `iface` / `polarity` / `count_type` | 接口类型 / 极性 / 数量（沟道） | 文本包含 |

取值解析能处理：`3.3V`、`500mA`、`10uF`、`10kΩ`、`±1%`、`128KB`、`5.5V~36V`（区间取上限）、
`47mΩ@10V`（`@` 后面的测试条件先剥掉）；`；` 分隔的多条件只取第一段。

## 4. 约束语法

```bash
python scripts/pick.py "找 3.3V 1A 的 LDO" --qty 100      # 自然语言：无单位数字按品类落到物理量
python scripts/pick.py pick --family ldo \
       --param "输出电压=3.3V" --param "输出电流>=1A" --package SOT-23
python scripts/pick.py pick --cat "贴片电容(MLCC)" --param "容值=10uF" --param "额定电压>=25V"
```

自然语言里无单位数字的落位规则（`FAMILY_VOLT_ROLE` / `FAMILY_AMP_ROLE`）：
LDO/DC-DC 的 `3.3V` → 输出电压；MOS 的 `30V` → 漏源电压；TVS 的 `5V` → 反向工作电压；
电容的 `25V` → 额定电压；LED 的 `2V` → 正向压降；`1A` 在 LDO/MOS 上 → 输出电流。

**比较语义由物理量的极性决定，不是由数字决定**：

| 物理量极性 | 语义 | 例子 |
|---|---|---|
| `eq`（等值，2% 容差） | 必须是这个值 | 输出电压 `3.3V`、容值 `10uF`、阻值 `10k` |
| `ge`（不低于） | 满足下限即可 | 额定电压 `25V`（50V 的料合格）、Vdss `30V`、输出电流 `1A` |
| `le`（不高于） | 满足上限即可 | 导通电阻、静态电流、钳位电压 |

例外：**晶振/有源晶振的频率按等值**（要 `8MHz` 就不能给 `25MHz`），其它品类的 `频率` 仍按"不低于"
（`开关频率 500kHz` 允许更高）。写 `--param` 显式给算子时以你写的为准。

**这条规则是"猜"**：写了 `--param` 就以显式约束为准，自然语言推断只在没写时补位。

## 5. 排序与"缺参数"策略

- 排序：`--sort sales`（默认，销量降序）/ `price`（单价升序，无价与无货沉底）/ `stock`。
- 同型号去重：同一 MPN 多个 C 号保留**库存最多**的那条。
- **缺参数当不满足**：该料没有约束对应的参数字段时默认排除（`--allow-unknown` 放行）。
  理由：立创参数是卖家填的，缺字段不代表满足；把它当"通过"会选到 3.0V 冒充 3.3V 的料。
- 输出末尾给"落选主因"（`3.3V→输出电压=5V ×11`），用来判断该放宽哪一项。

## 6. 渠道倾向与可选比价（`--taobao N`）

输出末尾按 `--qty` 给一句渠道倾向（口径与 `bom.py` 一致）：≤10 少量走淘宝样品、11–100 中小批量看立创阶梯、
≥100 批量走立创 + 1688 询盘。

再加 `--taobao N` 会拿前 N 个候选型号去跑 `taobao.py`，取淘宝「单只价」与立创阶梯价比：

- 淘宝价格 tab 点击实测无效 → 销量 tab 可用（`_coefp` → `_sale`）；1688 用 `sortType=va_sales360&descendOrder=true`
- 标题里的「100个/包」这类包装要归一成单只价；`芯片包 / 套装 / 混装 / 样品盒` 是**混装**，
  单只价没有可比性 → 直接剔除；`N-M片` 是数量区间不是包装 → 不做归一（表里显示「区间价」）
- 结论口径：小批量（<10）淘宝通常更省；批量看立创阶梯 + 免运费门槛；核心件（MCU/电源/晶振/连接器）立创优先

## 7. 边界（用前先看）

- **采样边界**：默认 2 页 ×30 = 60 条候选。立创把"精准匹配组"钉最前、`pageSize` 上限 30，
  所以"最便宜的料"可能没进候选；要更全用 `--pages 4`（注意 QPS ≤ 1）。
- **`totalCount` 被服务端截到 1500**：品类真实规模看 `catalogGroup[].count`（贴片电阻 100 万+），
  不要用 `totalCount` 判断"这个品类有多少料"。
- **参数区间筛选无服务端支持**：候选之外的料即使满足参数也不会被看到（见 `references/lcsc-api.md` §3）。
- **`paramLinkedMap` 在 `productRecordList[i]` 这一层**，不在 `productVO` 里：取错层级会拿到空参数表。
- `key_constraints`（`data/categories.yaml`）只决定表格展示哪几个参数，**不影响过滤**；过滤看 `--param`。
- 文本类约束是"包含"匹配，比较宽松：`数量=N沟道` 会同时命中 `1个N沟道`，但 `N+P` 复合沟道件需人工看。
- 品类共 25 个 family（`pick.py cats` 可列）：`ldo/dcdc/mosfet/bjt/mcu/opamp/comparator/vref/eeprom/
  norflash/crystal/oscillator/isolator/optocoupler/relay/connector/resistor/mlcc/inductor/bead/led/
  diode/schottky/tvs/esd`。**TVS 与 ESD 在立创是同一个 catalog（526）**，靠关键词区分，候选池高度重叠。
