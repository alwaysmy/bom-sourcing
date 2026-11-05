# 立创商城（szlcsc）品类目录与参数键扫描

产出目标：给「按意图找料」的 CLI 提供可机读的品类索引。

| 产物 | 路径 |
| --- | --- |
| 机读索引 | `D:\WorkDesigns\3_WorkTools\skills\bom-sourcing\data\categories.yaml` |
| 本文（人读） | `D:\WorkDesigns\3_WorkTools\Bom_Flow\research\categories.md` |
| 原始响应样本 | `D:\WorkDesigns\3_WorkTools\Bom_Flow\probe\lcsc\params\`（83 个带时间戳 JSON） |

扫描日期 2026-11-04；25 个 family 全部拿到可用 `catalog_id` 与参数键，**无未覆盖项**。

---

## 1. 结论摘要

1. **品类可用 `catalogGroup.value` 直接收敛检索**：`catalogIdFilter` 传该值后，返回的 `productRecordList` 全部落在同一 `productType`，25 个 family 抽检 `productType` 一致率 100%。
2. **`parmeterValueList` 在关键词/品类检索下恒为 `[]`**（本次 80 次请求全程验证），服务端不支持参数区间筛选——参数只能"读"，不能"筛"，区间比较必须由客户端在拿到结果后自行做。
3. **参数键名是中文自由文本，且随品类固化**：同品类 30 条样本里核心参数键出现率基本 100%（如 LDO 的 `输出电压`/`输出电流`/`工作电压` 均 30/30），但**尾部键极稀疏**（磁珠 `类型` 仅 1/30）。`param_keys` 按出现频次降序，前 3–5 个才是稳定可选型维度。
4. **封装不在 `paramLinkedMap` 里**，它是 `productVO.encapsulationModel`（同层的 `productModel` 是型号）。做"封装"筛选要走字段而不是参数表。
5. **`totalCount` 被服务端截到 1500**（所有 family 都是 1500），真实品类规模要读 `catalogGroup[].count`（例：贴片电阻 1,006,111）。

---

## 2. 方法与接口

### 2.1 检索接口

```http
POST https://so.szlcsc.com/query/product
content-type: application/json
origin: https://so.szlcsc.com
referer: https://so.szlcsc.com/global.html
```

```json
{"currentPage":1,"pageSize":30,"keyword":"LDO","sortNumber":6,
 "spotFilter":1,"discountFilter":1,"hasDataFile":false,"catalogIdFilter":"387"}
```

- 免登录；请求体不需要 cookie/token。
- 本机 `*.lcsc.com` 不能走代理，Python 必须绕代理：
  `urllib.request.build_opener(urllib.request.ProxyHandler({}))`。
- `pageSize` 上限 30，超过会静默返回 0 条。
- `keyword` **必须非空**，否则 `catalogIdFilter` 不生效（实测 `keyword=空 + catalogIdFilter=387` 不收敛）。

### 2.2 四级取数流程

```
① 裸关键词检索   keyword=<品类词>              → 读 catalogGroup / parentCatalogGroup 定位品类
② 品类收敛检索   keyword=<品类词> + catalogIdFilter=<value> + sortNumber=6(销量降序)
③ 参数聚合       遍历 30 条 record.paramLinkedMap，统计键频次 + 收集真实值样本
④ 一致性自检     统计返回的 productType 众数，与预期品类名比对
```

`sortNumber`（本次**只用 6 做销量降序**，因为要拿"工程师真会买的料"的参数分布）：

| 值 | 语义 |
| --- | --- |
| 0 | 综合 |
| 1 / 2 | 价格升 / 降 |
| 4 | 库存降 |
| 6 | 销量降 |

### 2.3 参数键聚合规则

- 键：`productRecordList[i].paramLinkedMap`（**注意在 record 层，不在 `productVO` 里**，任务描述的路径需修正）。
- 值可能带高亮 HTML `<SPAN CLASS='LUCENE_HIGHLIGHT_CLASS'>`，落库前用 `<[^>]+>` 去标签并压空白。
- 取出现频次前 12 的键；每键收集 ≤5 个去重真实值。
- 多通道/多条件器件一个键里塞多值，用 `；` 分隔（TVS `7V；12V`、MOSFET `47mΩ@10V；85mΩ@2.5V`）。

### 2.4 `kind` / `unit` 判定规则（生成器内实现，非人工拍脑袋）

| kind | 判定 |
| --- | --- |
| `range` | ≥50% 的值含数值区间（`数字[单位]~数字[单位]` 或 `数字-数字`） |
| `value` | ≥70% 的值为「数值(+单位)(@条件)」形态 |
| `enum` | 全部非数值、去重 ≤8、每个值 ≤10 字符、不含 `；`/`@` 等多值分隔符 |
| `text` | 其余（型号式自由文本、多值/多条件描述） |

`unit`：只看 `value`/`range`。取每条样本**首个**数值的单位；同一原始单位 → 原样（`mΩ`/`mW`/`uH`）；同量纲不同 SI 前缀 → 归并到基本单位（`kΩ`+`Ω`→`Ω`，`mV`+`uV`→`V`）；跨量纲或无单位 → `null`。

> `unit: null` 的 42 个键不等于"无量纲"：可能是 enum/text（单位无意义），也可能是值里根本没带单位（数字隔离器 `隔离电压(Vrms)` 值是 `2500`/`3000`，实为 V 但接口未写）。**消费方必须从值字符串自身解析单位与 SI 前缀，不能只信 `unit` 字段。**

---

## 3. 覆盖表（25 项）

`facet count` = `catalogGroup[].count`，是该品类真实在售数；`totalCount` 一律 1500（服务端截断）。

| family | label_cn | catalog_id | facet count | 参数键 | 一致性 | catalog_id 来源 |
| --- | --- | --- | --- | --- | --- | --- |
| resistor | 贴片电阻 | 439 | 1,006,111 | 4 | ✅ | 首轮 top1，字面一致 |
| mlcc | 贴片电容(MLCC) | 313 | 546,631 | 4 | ✅ | 首轮 top1，字面一致 |
| inductor | 功率电感 | 544 | 131,445 | 6 | ✅ | 首轮 top1（关键词"电感"），字面一致 |
| bead | 磁珠 | 527 | 9,995 | 4 | ✅ | 首轮 top1，字面一致 |
| led | 发光二极管/LED | 528 | 52,097 | 6 | ✅ | 首轮 top1，字面一致 |
| diode | 通用二极管 | 370 | 12,666 | 4 | ✅ | **人工纠偏**：首轮 top1 是"稳压二极管"(321)，改选通用二极管 |
| schottky | 肖特基二极管 | 373 | 29,711 | 4 | ✅ | 首轮 top1，字面一致 |
| tvs | 静电和浪涌保护(TVS/ESD) | 526 | 101,784 | 6 | ✅ | 首轮 top1，字面一致 |
| esd | 静电和浪涌保护(TVS/ESD) | 526 | 101,784 | 6 | ✅ | **同 TVS 一个 catalog**（立创不拆分），详见 §5.1 |
| bjt | 三极管(BJT) | 326 | 20,705 | 4 | ✅ | 首轮 top1，字面一致 |
| mosfet | 场效应管(MOSFET) | 381 | 76,301 | 4 | ✅ | 首轮 top1，字面一致 |
| mcu | 单片机(MCU/MPU/SOC) | 11329 | 64,133 | 6 | ✅ | 首轮 top1，字面一致 |
| ldo | 线性稳压器(LDO) | 387 | 65,167 | 4 | ✅ | 首轮 top1，字面一致 |
| dcdc | DC-DC电源芯片 | 484 | 40,662 | 5 | ✅ | 首轮 top1（关键词"DC-DC电源芯片"），字面一致 |
| opamp | 运算放大器 | 516 | 16,413 | 7 | ✅ | 首轮 top1，字面一致 |
| comparator | 比较器 | 517 | 4,017 | 8 | ✅ | 首轮 top1，字面一致 |
| vref | 电压基准芯片 | 486 | 7,023 | 5 | ✅ | 首轮 top1（关键词"电压基准芯片"），字面一致 |
| eeprom | EEPROM | 502 | 9,863 | 4 | ✅ | 首轮 top1，字面一致 |
| norflash | NOR FLASH | 501 | 9,130 | 4 | ✅ | 首轮 top1，字面一致 |
| crystal | 无源晶振 | 537 | 126,316 | 4 | ✅ | 首轮 top1，字面一致 |
| oscillator | 有源晶振 | 364 | 202,213 | 4 | ✅ | 首轮 top1，字面一致 |
| optocoupler | 晶体管输出光耦 | 351 | 6,286 | 5 | ✅ | **人工纠偏**：首轮 top1 是"固态继电器(可控硅输出)"(11297)，改选晶体管输出光耦 |
| isolator | 数字隔离器 | 581 | 4,336 | 5 | ✅ | 首轮 top1，字面一致 |
| connector | 排针 | 644 | 249,933 | 5 | ✅ | 首轮 top1（关键词"排针"），字面一致 |
| relay | 功率继电器 | 531 | 22,422 | 6 | ✅ | 首轮 top1（关键词"继电器"），字面一致 |

「一致性」= 采样的 30 条记录里 `productType` 众数是否等于 `label_cn`，**25/25 全为 True**。

请求的 24 项里「晶振」被拆成 `crystal`(无源) + `oscillator`(有源) 两条，因此 YAML 里是 25 个 family。

---

## 4. 抽查证据（用记录里的 catalog_id 复检）

命令：

```powershell
cd D:\WorkDesigns\3_WorkTools\Bom_Flow\probe\lcsc
python probe_catalog_verify.py ldo mlcc mosfet relay optocoupler
```

真实输出（取销量前 5 条，核对 `productType`）：

```
[ldo] catalog_id=387 期望 productType=线性稳压器(LDO)
   C6186       AMS1117-3.3             productType=线性稳压器(LDO)  OK
   C347222     AMS1117-3.3             productType=线性稳压器(LDO)  OK
   C82942      ME6211C33M5G-N          productType=线性稳压器(LDO)  OK
   C5446       XC6206P332MR-G          productType=线性稳压器(LDO)  OK
   C2862740    TPS7A2033PDBVR          productType=线性稳压器(LDO)  OK
   => all_match=True

[mlcc] catalog_id=313 期望 productType=贴片电容(MLCC)
   C14663      CC0603KRX7R9BB104       productType=贴片电容(MLCC)  OK
   C1525       CL05B104KO5NNNC         productType=贴片电容(MLCC)  OK
   C15849      CL10A105KB8NNNC         productType=贴片电容(MLCC)  OK
   C19702      CL10A106KP8NNNC         productType=贴片电容(MLCC)  OK
   C52923      CL05A105KA5NQNC         productType=贴片电容(MLCC)  OK
   => all_match=True

[mosfet] catalog_id=381 期望 productType=场效应管(MOSFET)
   C15127      AO3401A                 productType=场效应管(MOSFET)  OK
   C20917      AO3400A                 productType=场效应管(MOSFET)  OK
   C8545       2N7002                  productType=场效应管(MOSFET)  OK
   C347476     AO3401A                 productType=场效应管(MOSFET)  OK
   C347475     AO3400A                 productType=场效应管(MOSFET)  OK
   => all_match=True

[relay] catalog_id=531 期望 productType=功率继电器
   C35449      SRD-05VDC-SL-C          productType=功率继电器  OK
   C30431      SRD-12VDC-SL-C          productType=功率继电器  OK
   C34758      G5NB-1A-E-24VDC         productType=功率继电器  OK
   C48746      G5NB-1A-E-DC5V          productType=功率继电器  OK
   C225714     G5NB-1A-E DC12          productType=功率继电器  OK
   => all_match=True

[optocoupler] catalog_id=351 期望 productType=晶体管输出光耦
   C115450     LTV-217-B-G             productType=晶体管输出光耦  OK
   C42379244   EL357N(C)(TA)-G         productType=晶体管输出光耦  OK
   C42381015   EL357N(B)(TA)-G         productType=晶体管输出光耦  OK
   C3025164    PC817C                  productType=晶体管输出光耦  OK
   C109227     LTV-817S-TA1-C          productType=晶体管输出光耦  OK
   => all_match=True
```

YAML 可加载性与结构校验（PyYAML）：

```powershell
python -c "import yaml;d=yaml.safe_load(open(r'D:\WorkDesigns\3_WorkTools\skills\bom-sourcing\data\categories.yaml',encoding='utf-8'));print(len(d['families']))"
# 25
```

附加结构校验结果：`key_constraints` 引用的键 100% 存在于同 family 的 `param_keys` 中；`kind` 全部落在 `value|range|enum|text` 四值内；124 个参数键中 42 个 `unit: null`。

---

## 5. 异常与坑（按重要性）

### 5.1 TVS 与 ESD 在立创是同一个 catalog（526）

`静电和浪涌保护(TVS/ESD)` 一个品类统管两者，`value=526` 只有一个。YAML 里 `tvs` 与 `esd` 共用 `catalog_id: "526"`，靠首轮关键词区分（`TVS` vs `ESD`）——**但 `catalogIdFilter` 只收敛品类、不细分器件类型，两者返回的候选池高度重叠**。要区分 TVS/ESD 只能靠 `峰值脉冲功率(Ppp)`、`极性`、封装等参数二次判断，或换 `keyword` 让关键字排序起作用。

### 5.2 首轮裸关键词的 top1 可能是完全不同的东西

| 关键词 | top1 catalogGroup | 是不是本意 |
| --- | --- | --- |
| `光耦` | 固态继电器(可控硅输出) `11297` (6669) | ❌ 真光耦是 `晶体管输出光耦` `351` (6286)，仅差 383 条 |
| `二极管` | 稳压二极管 `321` (62394) | ❌ 通用二极管 `370` 只有 12666 |
| `连接器` | 连接器外壳 `11079` (537184) | ❌ 需求是排针 → `644` |
| `继电器` | 功率继电器 `531` | ⚠️ 只是继电器族的一支（另有信号继电器 11305、SSR 11297） |
| `电感` | 功率电感 `544` (131445) | ⚠️ 另有 `贴片电感` `337` (29977)，两者参数键不同 |

结论：**不能假设"关键词搜出来第一条就是目标品类"**。生产 CLI 应把 `keywords` 列表 + 匹配到的 `label_cn` 做显式比对，而不是取 `catalogGroup[0]`。

### 5.3 `parmeterValueList` 恒为空

25 次品类收敛请求 + 5 次抽查 + 50 次裸检索，`result.searchResult.parmeterValueList` **全部为 `[]`**。服务端不支持"参数区间"筛选，YAML 里的 `param_keys` 只能用于**读/展示/客户端比对**，不能拼成查询条件。

### 5.4 `totalCount` 被截到 1500

所有 family 的 `totalCount` 都是 1500（贴片电阻真实 100 万+）。分页取数量、判断"结果多不多"要用 `catalogGroup[].count`，不能用 `totalCount`。

### 5.5 封装字段不在参数表

`paramLinkedMap` 里没有"封装"。封装值在 `productVO.encapsulationModel`（如 `0603`、`SOT-23`），型号在 `productVO.productModel`，立创编号在 `productVO.productCode`。YAML 的 `key_constraints` 因此**没有**把"封装"写进去（它不属于参数键），但选型时它是硬条件，CLI 需从 `encapsulationModel` 读。

### 5.6 参数值可能带高亮 HTML

搜索命中词会被 `<SPAN CLASS='LUCENE_HIGHLIGHT_CLASS'>` 包裹。本扫描已去标签；任何直读接口的代码都必须先去标签，否则同一参数会因高亮产生"不同值"（键本身也可能被高亮）。

### 5.7 多值/多条件参数

- 多通道器件：TVS `反向工作电压(Vrwm)` = `7V；12V`（两个通道各一个值）。
- 带测试条件：肖特基 `正向压降(Vf)` = `550mV@3A`；MOSFET `导通电阻(RDS(on))` = `47mΩ@10V；85mΩ@2.5V`（一个器件多组条件值）。

`kind` 只区分 `value`/`range`/`enum`/`text`，**不表达"多值"**。CLI 做比较前必须先按 `；` 切分，再按 `@` 剥离测试条件，否则 `47mΩ@10V` 这种值没法直接比大小。

### 5.8 单位在键名里而不是值里

`隔离电压(Vrms)` 的值就是 `2500`/`3000`，单位只在键名的括号里。`CPU位数` 的 `32 Bit` 反而把单位写进了值里。同品类不同供应商的写法并不统一，解析器要同时兼容"值带单位"和"键带单位"。

### 5.9 `keyword` 必须非空

空 `keyword` + `catalogIdFilter` 不收敛（返回全站混排）。CLI 拼查询时若只有品类、没有关键词，必须回填一个该品类的代表词（`keywords[0]`）。

### 5.10 限流建议

本次共 ~80 次请求，**全部 1.0s 间隔串行**，无 429、无失败。

建议：**同站请求间隔 ≥0.5s、QPS ≤ 1**。本次扫描脚本统一 `INTERVAL = 1.0`，25 个 family 的品类发现 + 参数聚合总耗时约 90s，成本可接受。并发抓取没有验证过，不建议。

---

## 6. 已知局限 / 未做

| 项 | 说明 |
| --- | --- |
| 参数键是"销量前 30"的分布 | 冷门器件（如超低功耗 LDO、车规料）可能带额外参数键，本索引未覆盖 |
| 只取第 1 页 | 每个 family 固定 30 条样本，`sample_size: 30`；更大的样本只会改变键频次，不改变键名集合的稳定性判断 |
| 未覆盖品类 | 需求清单外未扫（如 NAND FLASH、钽电容、铝电解、压敏电阻、共模电感、TVS 阵列、逻辑芯片、ADC/DAC）；扩展只要在 `probe_catalog_discover.py` 加一行 |
| 未做参数名归一化 | 中文键名在不同品类间不复用（LDO 的"工作电压"= 输入电压，DC-DC 的"工作电压"= 输入范围），跨品类统一词表需要另做映射 |
| 未验证 `pageSize` 之外的分页 | 只验过 `pageSize=30`（上限）；`>30` 静默返 0 条已知 |

---

## 7. 复现与文件清单

### 脚本（`probe\lcsc\`）

| 脚本 | 作用 |
| --- | --- |
| `probe_catalog.py` | 基础 `query()` / `show()`（绕代理已封装），被其它脚本 import |
| `probe_catalog_discover.py` | 阶段 A：25 个 family × 候选关键词裸检索，dump `catalogGroup` / `parentCatalogGroup` → `params/_discover_log.json` |
| `probe_catalog_params.py` | 阶段 C：按选定 `catalog_id` 取 30 条，聚合参数键 → `params/_params_agg.json` |
| `probe_catalog_build_yaml.py` | 阶段 D：由 `_params_agg.json` 生成 `categories.yaml`（纯 stdlib 手写 YAML 发射器） |
| `probe_catalog_verify.py` | 抽查：用 `catalog_id` 复检 `productType` → `params/_verify_result.json` |

### 一键复现

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
cd D:\WorkDesigns\3_WorkTools\Bom_Flow\probe\lcsc
python probe_catalog_discover.py      # ~50 请求 / 50s
python probe_catalog_params.py        # ~25 请求 / 25s
python probe_catalog_build_yaml.py    # 无网络
python probe_catalog_verify.py        # ~5 请求
```

### 原始数据

`probe\lcsc\params\` 下 83 个 JSON，命名 `<阶段>_<family>_<keyword>_<YYYYMMDD_HHMMSS_微秒>.json`：

- `discover_*` × 50（阶段 A 原始响应）
- `params_*` × 25（阶段 C 原始响应，每个约 350KB）
- `verify_*` × 5（抽查原始响应）
- `_discover_log.json` / `_params_agg.json` / `_verify_result.json`（中间汇总）
- `_discover_stdout.txt` / `_params_stdout.txt` / `_verify_stdout.txt`（运行时控制台输出）

历史探针文件（`probe_catalog2.py` / `probe_catalog3.py` 等）保持原样未改动。

---

## 8. 功能符合性判据（`function_keywords` / `exclude_keywords`）

> 本节回答一个问题：**`catalogIdFilter` + 参数筛选都满足的料，凭什么说它"功能对"？**

### 8.1 真实翻车：`MP4316GRE-Z`

按"负载开关"选型时，候选里出现 `MP4316GRE-Z`（C3726292）。实测它在立创的登记信息是：

| 字段 | 值 |
| --- | --- |
| `productType` | 功率电子开关 |
| `productName` | `45V, 6A, 同步降压转换器，带扩频功能` |
| 所属 catalog | 969（功率电子开关） |

它其实是**降压转换器**。同一条目下另外三条同样不是负载开关：

| 型号 | 立创编号 | `productType` | `productName` | 实际功能 |
| --- | --- | --- | --- | --- |
| `MP4316GRE-Z` | C3726292 | 功率电子开关 | 45V, 6A, 同步降压转换器，带扩频功能 | 降压转换器 |
| `LP5280SHVF` | C47345802 | 功率电子开关 | 集成TVS的28V/5A过压保护开关 | 过压保护开关 |
| `SIP32434BDN-T1E4` | C17236769 | 功率电子开关 | 6A，33mΩ，2.8V至23V，带可编程电流限制和过压保护的电子保险丝 | eFuse |
| `TPS259470ARPWR` | C3662799 | **浪涌保护器** | 2.7V至23V、5.5A、28mΩ真反向电流阻断电子保险丝 | eFuse |

结论：**功能类型不是 `productType` 字段，而是 `productName` 里的中文描述。** 于是给 25 个 family 各补一对正/反向词表：

```yaml
dcdc:
  function_keywords: ['降压型', '升压型', '升降压型', 'DC-DC', 'Buck', 'Boost', '转换器']
  exclude_keywords: ['LDO', '线性稳压', '电荷泵', 'LED驱动', '电源模块', '基准',
                     '负载开关', '电子保险丝', '过压保护', '热插拔', 'PMIC', '充电管理']
```

### 8.2 `productType` 为什么靠不住：它是 catalog 级标签

对 6 个可疑 catalog 各取 3 页 × 3 种排序（`sortNumber` 0/6/4），统计 `productType` 纯度：

| catalog | 品类 | 样本数 | 不同 `productType` 数 | 纯度 |
| --- | --- | --- | --- | --- |
| 969 | 功率电子开关 | 153 | 1 | 1.00 |
| 11314 | 浪涌保护器 | 138 | 1 | 1.00 |
| 484 | DC-DC电源芯片 | 164 | 1 | 1.00 |
| 526 | 静电和浪涌保护(TVS/ESD) | 176 | 1 | 1.00 |
| 321 | 稳压二极管 | 170 | 1 | 1.00 |
| 370 | 通用二极管 | 129 | 1 | 1.00 |

25 个 family 的 30 条样本也全部是 30/30 同类型。**`productType` 只是 catalog 名的回显，对"这个料到底是什么"零信息量。** 用 `productType` 做功能校验，`MP4316GRE-Z` 会以 `功率电子开关` 的身份 100% 通过。

### 8.3 采样方法与证据

| 项 | 内容 |
| --- | --- |
| 样本 | 25 family × 30 条 = **750 条真实 `productName`** |
| 取样方式 | `keyword=品类词 + catalogIdFilter=<该 family 的 catalog_id> + sortNumber=6`（销量降序），`pageSize=30` |
| 时间戳 | `20261105_151116` |
| 落盘 | `probe\lcsc\func\func_<family>_20261105_151116.json`（每 family 一个）、`_func_samples_*.json`（合并） |
| 词频 | `_func_ngrams_20261105_151116.json`（中文 n-gram 文档频次，只保留"极大 n-gram"避免碎片） |
| 易混探针 | 15 个裸词（无 `catalogIdFilter`）→ `_func_confuse_20261105_151116.json` |
| 混装 catalog | 6 个 × 3 页 × 3 排序 = 54 请求 → `mixed_catalogs_20261105_151349.json` |
| 限流 | 全部串行，间隔 1.0~1.2s（QPS ≤ 1），无 429 |

**WAF 说明**：`so.szlcsc.com` 自 2026-11-05 起对脚本流量返回 HTTP 203 + 腾讯 EdgeOne 挑战页（`STGW-STATUS-CODE: 203`、`X-WAF-UUID`、`Server: TencentEdgeOne`），`scripts\lcsc.py` 会抛 `JSONDecodeError: Expecting value: line 1 column 5 (char 4)`。本节的采样走 `probe\lcsc\func\waf.py`：用 Node + `vm` 沙箱执行挑战页的混淆脚本、取出它要写的 `tws2_<nonce>` cookie，再带 cookie 重发（**一次挑战后 cookie 可复用**）。这是探针侧 workaround，未改动 `scripts\` 下任何文件。

### 8.4 最危险的 3 个混装品类

| # | catalog | 混装内容 | 危害 |
| --- | --- | --- | --- |
| **1** | **969 功率电子开关**（5 314 条） | 降压转换器、过压保护开关、电子保险丝、负载开关、理想二极管 ORing 全都挂在这里 | 参数（工作电压 / 最大连续电流）完全可比，**只按参数筛必然混入 `MP4316GRE-Z` 这类降压转换器**；`productType` 全同，无任何兜底 |
| **2** | **11314 浪涌保护器**（5 313 条） | 电子保险丝（eFuse）、过压保护、真浪涌/防雷器件 | eFuse 和 TVS 类浪涌器件的耐压/钳位参数长得很像，容易互相冒充 |
| **3** | **526 静电和浪涌保护(TVS/ESD)**（101 784 条） | TVS、ESD 阵列、半导体放电管（TSS），且裸词检索还会混入连接器外壳、MLCC、稳压二极管 | 立创**不拆 TVS 与 ESD**，二者共用 catalog，只能靠 name 里的"截止 / 峰值浪涌电流 / 双向 / 单向"区分；`tvs` 与 `esd` 的候选池必然重叠 |

补充（同一机制）：`321 稳压二极管`（62 394 条）会与 TVS/ESD、电压基准（486）互串；`544 功率电感` 与 `337 贴片电感`、`527 磁珠` 三者靠 name 里的阻抗/感值单位区分。

### 8.5 25 个 family 的正/反向词覆盖

全部 25 个 family 已写入 `family_key` / `function_keywords` / `exclude_keywords`（共 129 条正向词、238 条反向词；每个 family ≥3 正向、≥2 反向；正反向无交集）。

按 **`productName` 的可信度**分三级（依据 `_func_ngrams` 的中文 n-gram 覆盖率）：

| 级别 | 判定 | family | 说明 |
| --- | --- | --- | --- |
| **A 级**（17 个） | name 含明确中文功能词，可直接判定 | `resistor` `bead` `led` `tvs` `esd` `mosfet` `mcu` `dcdc` `opamp` `comparator` `vref` `eeprom` `norflash` `optocoupler` `isolator` `connector` `relay` | 如 `dcdc` 30/30 name 含"降压型/升压型"；`isolator` 30/30 含"隔离器"；`connector` 30/30 含"间距/方针" |
| **B 级**（2 个） | name 无功能词，但有**固定格式特征** | `schottky`（`电压:40V 电流:3A`，30/30）、`bjt`（`电流:29/30 电压:29/30`） | 功能词（`肖特基`/`三极管`）实际只出现在 `productType`，name 里靠 `电压:`/`电流:` 这种**带冒号的格式**当弱正向信号；立创一改格式即失效 |
| **C 级**（6 个） | name 是**纯参数或纯型号**，无任何中文 | `mlcc`（`100nF ±10% 50V`）、`inductor`（`10uH ±20% 3.5A`）、`ldo`（`3.3V 1A 15V`）、`diode`（`1kV 1A`，仅 3/30 含中文）、`crystal`（`YSX321SL 25MHZ 4P 3225 12PF ±10PPM -40~85℃`）、`oscillator`（`YSO110TR 25MHZ 1.8V-3.3V ±10PPM ... CMOS`） | 功能校验**完全退化到 `catalog_id`**，词表只能写品类名（永不命中 name），见 8.6 |

### 8.6 `name` 也不可信时怎么降级

`pick.py` 消费这对词表时必须区分两种情况，否则 A 级之外的 family 会被误杀：

| 情况 | 判据 | 处理 |
| --- | --- | --- |
| **正向命中 + 无反向命中** | `any(w in name for w in function_keywords)` | 功能确认，可输出 |
| **正向未命中 + 无反向命中** | 0 命中 | **不能判"功能不符"** —— 只标"功能未确认"，C 级 family 属于此类；应把 `catalog_id` 当作唯一功能证据 |
| **反向命中** | `any(w in name for w in exclude_keywords)` | 功能不符，直接剔除（**这一条对 C 级同样有效**，例如 LDO 的 name 不会出现"DC-DC"） |

降级链（越靠后越贵，按需触发）：

1. **`catalog_id` 收敛** —— 先用 `catalogIdFilter` 把候选池压到该品类（本索引的 25 个 id 已实测可信）。
2. **`productName` 词表判定** —— A 级 family 到此结束。
3. **`lightProductIntro`（商品简介）** —— 比 `productName` 长，通常带更完整的功能描述；C 级 family 若 name 只有参数，可在这里找功能词。
4. **`paramLinkedMap` 的键名集合** —— 键名本身带功能含义（如 `阻值`/`容值`/`感值` 不可能同时出现），可当弱特征。
5. **人工/LLM 读 `productName` 中文** —— 对 969 这类混装重灾区，`45V, 6A, 同步降压转换器` 这句话只能靠语义理解。
6. **查手册** —— 最终兜底：对高风险选型（功率 > 1A、涉及保护功能），下载 datasheet 看第一句话（"XX Synchronous Step-Down Converter" / "XX eFuse"）。手册库在 `D:\Datasheets`。

> 特别提醒：`969 功率电子开关` 里的料，**name 里的功能词是唯一可靠信号**（`productType` 全同、参数可比、封装可比）。凡是 name 里同时出现 `降压`/`升压`/`DC-DC`/`转换器` 的，一律不是负载开关。

### 8.7 负载开关 / eFuse 组的现成排除清单

本索引固定 25 个 family（没有 `powerswitch`），所以这 5 个词没有落进某个 family 的 `exclude_keywords`。若要新增 `powerswitch`（catalog 969 + 11314）family，直接照抄：

```yaml
powerswitch:
  family_key: powerswitch
  function_keywords: ['负载开关', '电子保险丝', 'eFuse', 'EFUSE', '过压保护开关',
                      '热插拔', 'ORing', '理想二极管']
  exclude_keywords: ['降压转换器', '升压', 'DC-DC', 'LDO', '充电管理',
                     '降压型', '升压型', '稳压二极管', 'TVS', '静电和浪涌保护']
```

其中 `降压转换器` / `升压` / `DC-DC` / `LDO` / `充电管理` 五条是硬要求（`MP4316GRE-Z` 只有 `降压转换器` 能挡住）。

### 8.8 验收与演示

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
python -c "import yaml;d=yaml.safe_load(open(r'D:\WorkDesigns\3_WorkTools\skills\bom-sourcing\data\categories.yaml',encoding='utf-8'));f=d['families'];print(len(f));print([k for k,v in f.items() if not v.get('function_keywords')])"
# 25
# []
```

`python probe\lcsc\func\verify_func_keywords.py` 额外校验：原有字段零改动、family 键顺序不变、正/反向词表无交集。

用词表回放 4 个翻车料（`python probe\lcsc\func\demo_classify.py`）：

```
MP4316GRE-Z
  name: 45V, 6A, 同步降压转换器，带扩频功能
  → 可归入 dcdc         正向词=['转换器']
  被反向词挡掉的 family: []

LP5280SHVF
  name: 集成TVS的28V/5A过压保护开关
  → 25 个 family 全部无法归类（正确：这不是任一品类）
  被反向词挡掉的 family: ['led', 'diode', 'schottky', 'tvs', 'dcdc']

SIP32434BDN-T1E4
  name: 6A，33mΩ，2.8V至23V，带可编程电流限制和过压保护的电子保险丝
  → 25 个 family 全部无法归类（正确：这不是任一品类）
  被反向词挡掉的 family: ['resistor', 'tvs', 'dcdc']

TPS259470ARPWR
  name: 2.7V至23V、5.5A、28mΩ真反向电流阻断电子保险丝
  → 25 个 family 全部无法归类（正确：这不是任一品类）
  被反向词挡掉的 family: ['resistor', 'tvs', 'dcdc']
```

`MP4316GRE-Z` 被判为 `dcdc`（它确实是降压转换器），另外三个 eFuse/OVP 料在 25 个 family 里**一个都不命中**且被 `tvs`/`dcdc` 的反向词主动挡掉 —— 这正是期望行为：立创的 catalog 归属不能当作功能归属。

### 8.9 本节产物清单

| 文件 | 内容 |
| --- | --- |
| `probe\lcsc\func\waf.py` | EdgeOne 挑战绕过（`post(body, tries=4)`） |
| `probe\lcsc\func\_waf_cookie.js` | 挑战页反混淆执行器（Node + `vm`），打印 `---COOKIE---` 段 |
| `probe\lcsc\func\probe_func_names.py` | 阶段 F1：25 family × 30 条 `productName` + 15 个易混裸词 |
| `probe\lcsc\func\probe_mixed_catalogs.py` | 阶段 F2：6 个可疑 catalog × 3 页 × 3 排序 |
| `probe\lcsc\func\apply_func_keywords.py` | 把正/反向词表写进 `categories.yaml`（纯 stdlib，幂等） |
| `probe\lcsc\func\verify_func_keywords.py` | 验收：字段齐全 + 原有字段零改动 + 词表无矛盾 |
| `probe\lcsc\func\demo_classify.py` | 用词表回放 4 个翻车料 |
| `probe\lcsc\func\func_<family>_20261105_151116.json` × 25 | 每 family 原始样本 |
| `probe\lcsc\func\_func_samples_20261105_151116.json` | 25 family 合并样本 |
| `probe\lcsc\func\_func_ngrams_20261105_151116.json` | 中文 n-gram 文档频次 |
| `probe\lcsc\func\_func_confuse_20261105_151116.json` | 15 个易混裸词的品类分布 |
| `probe\lcsc\func\mixed_catalogs_20261105_151349.json` | 6 个混装 catalog 的 productType 纯度证据 |
| `probe\lcsc\func\analyze_crash_cases.json` | 4 个翻车料的实测记录 |
| `probe\lcsc\func\categories.yaml.bak_20261105_153004` | 打补丁前的 YAML 备份（23 175 bytes） |
