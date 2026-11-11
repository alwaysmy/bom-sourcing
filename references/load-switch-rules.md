# 功率电子开关的功能判据（反向电流阻断 / 防倒灌 / 理想二极管）

> 适用：负载开关、eFuse、过压保护（OVP）开关、理想二极管、ORing 控制器、热插拔控制器、电源多路。
> 配套：`data/knowledge/load-switch.yaml`（数据）、`scripts/loadswitch.py`（查询/登记）、
> `scripts/pick.py`（使用者：说了要筛，没说只标注）。

## 1. 为什么单独立这一篇

立创 `paramLinkedMap` 对「功率电子开关（catalogIdFilter=969）」只给六个键：
`类型` / `工作电压` / `通道数` / 输入控制逻辑` / `最大连续电流` / `导通电阻(RDS(on))`。
**「反向电流阻断」根本没有这个字段**，也不可能从品类或商品名推出来。

而这一项决定板子会不会倒灌：`V(OUT) > V(IN)` 时电流反向流回输入，轻则掉电复位，重则烧输入级。
所以只能在查过手册之后，把结论**登记进知识库**，之后才有「筛选」可言。

## 2. 三种器件的默认行为（默认 ≠ 结论）

| 器件类别 | 默认反向阻断 | 原因 |
|---|---|---|
| 负载开关（单管） | ❌ 不阻断 | 一只 MOS，关断时体二极管从 OUT 导通回 IN |
| 负载开关（背对背 FET / True Reverse Blocking） | ✅ 阻断 | 两只 MOS 背对背，体二极管互相反向 |
| eFuse / 电子保险丝 | ⚠ 视型号 | 主流（TPS25947）集成背对背 FET 并写明 True Reverse Current Blocking；也有只做正向限流的 |
| 过压保护开关（OVP） | ❌ 多不阻断 | 多为单管 + 快速 OVP；部分型号（LP5280）**设计上就支持 OTG 反向供电** |
| 理想二极管（Ideal Diode） | ✅ 默认阻断 | 名字本义就是单向导电 |
| ORing 控制器 / 电源多路 | ⚠ 视型号 | 取决于外部 MOS 接法与时序 |
| 热插拔控制器 | ⚠ 视型号 | 主职是限流与斜坡，阻断常需外接背对背 MOS |

## 3. 理想二极管为什么也要单独核

「理想二极管」听起来天然阻断，实际有三层差异，必须看手册：

1. **控制器 + 外部 MOS 架构**：阻断靠比较器快速关断，`t_rev` 窗口内仍有反向电流；
   只有外部**双管**才是硬阻断。集成单管的理想二极管同理（体二极管方向决定成败）。
2. **带 reverse polarity protection 的型号 ≠ 普通 ORing 型号**：前者保护的是"输入接反"，
   后者保护的是"另一路电压更高"，两种场景的能力边界不同。
3. **少数只优化正向 VF 的器件**：名字叫 ideal diode，反向仍靠体二极管 → 特性表才是判据。

因此 `loadswitch.py infer` 只给类别提示，**不给结论**；结论必须 `--grade fact` 且写 `basis`。

## 4. 判定口径（写进知识库的规矩）

| 字段 | 取值 | 含义 |
|---|---|---|
| `reverse_block` | `yes` / `no` / `unknown` | 有没有阻断 |
| `grade` | `fact` / `claim` / `inference` | 证据强度；**只有 fact 能用于筛选** |
| `basis` | 自由文本 | 手册哪一节、原文怎么说 |
| `class` | 见 `device_classes` | 器件类别，决定"默认行为"的起点 |

- `grade=fact` 必须写 `basis`，否则 `validate` 报错。
- 不确定就 `unknown` —— **猜错的代价是倒灌烧板，unknown 的代价只是多查一次手册**。
- `claim`（分销页/卖家标题）与 `inference`（由类别推断）只能**标注**，不能筛选。

## 5. 「说了就筛，没说就标」

| 用户怎么说 | pick.py 行为 |
|---|---|
| 句子里有「防倒灌 / 防反灌 / 反向电流阻断 / 不许倒流 / ORing / 理想二极管」 | **筛选**：只留 `reverse_block=yes` 且 `grade=fact`；不达标/未登记的进「反向电流阻断筛选」段并说明原因 |
| `--require-reverse-block` | 同筛选（显式开关） |
| 没说，但品类是功率电子开关 | **只标注**：表格多一列「反向阻断」，值 ✅有 / ❌无 / ❔未核，不据此淘汰 |
| 说了但只想看标注 | `--no-reverse-block`（把要求降级为标注） |

其它品类（LDO/MOSFET…）只有当候选里真有登记过的料时才出这一列，避免整列 `❔未核` 的噪音。

## 6. 操作手册

```bash
cd scripts
python loadswitch.py list                    # 已登记料号（含证据等级与依据）
python loadswitch.py classes                 # 器件类别默认能力表
python loadswitch.py check C47345802         # 查一颗（C 号或型号都可）
python loadswitch.py infer "LM66100 理想二极管"  # 按名称猜类别（只给提示 + caveat）
python loadswitch.py validate                # 校验知识库

# 登记（写操作要授权串）
python loadswitch.py add C47345802 --model LP5280SHVF --class ovp_switch \
  --reverse-block no --grade fact \
  --basis "Rev1.5 §USB On-The-Go Operation：OUT 供电时 IN 经体二极管拉起至 VOUT-0.7V" \
  --authorized "傅师傅 2026-11-11 指定补反向阻断判据"

# 选型时用
python pick.py "找 3.3V~21V 5A 防倒灌的负载开关"     # 筛选
python pick.py "找 3.3V~21V 5A 的负载开关"           # 只标注
```

## 7. 已登记实例（2026-11-11）

| C 号 | 型号 | 类别 | 反向阻断 | 依据 |
|---|---|---|---|---|
| C47345802 | LP5280SHVF | ovp_switch | ❌ 不阻断 | 手册 Rev1.5 §USB On-The-Go Operation：ENB 拉低/悬空且 OUT 被 OTG 源供 5V 时，**IN 经 MOSFET 体二极管被拉起**至约 VOUT−0.7V，待 IN > UVLO 持续 15ms 后主 MOS 才导通 —— 反向是导通不是阻断 |
| C3662799 | TPS259470ARPWR | efuse | ✅ 阻断 | TI SLVSFC9C 特性：**True Reverse Current Blocking** + 集成背对背 FET + ideal diode operation |
| C3662789 | TPS259472ARPWR | efuse | ✅ 阻断 | 同 TPS25947xx 系列 |

**教训**：LP5280 的商品名只写「集成 TVS 的 28V/5A 过压保护开关」，参数也只给电压/电流，
按"负载开关 + 参数满足"选它出来是对的；但它**不阻断反向**，要防倒灌就必须换件。

## 8. 已知边界

- **立创查不到**：`parmeterValueList` 恒空、无服务端参数区间筛选，反向阻断更不在参数表里 → 只能手册 + 登记。
- **候选池采样**：`pick.py` 默认只取前 N 页（每页 30），按销量排序时高库存的真·eFuse 可能没进候选；
  已知料号时用 `--cat "TPS25947"` 之类收窄再选。
- **BOM 流程未接**：`bom.py` 目前不出这一列；BOM 行如果要防倒灌，需要人工把要求写进描述列。
- **同型号多封装**：知识库按 C 号登记，同型号不同 C 号要分别登记（型号前缀唯一时 `check` 可命中）。
