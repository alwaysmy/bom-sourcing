# 验收记录：配单 / BOM 采购能力（2026-11-04）

技能真源：`D:\WorkDesigns\3_WorkTools\skills\bom-sourcing`（`C:\Users\dell\.agents\skills\bom-sourcing` 为 junction）
远端：<https://github.com/alwaysmy/bom-sourcing>（public，main，30 个受版本控制文件，约 598 KB）

## 需求 → 证据

| 需求 | 实现 | 验证 |
|---|---|---|
| 立创商城检索/比价 | `scripts/lcsc.py`（`search/price/detail/compare/alternate`） | `search "0.1uF 0603 50V" --sort sales` 返回 1500 条、销量降序；`alternate C25804` 得 6 条同品牌替代（相似度 91–99） |
| 按指标范围筛选 | `scripts/spec.py` + `scripts/pick.py` 约束 | `pick "3.3V 1A 的 LDO"` 扫 53 条命中 3 条；落选主因 `3.3V→输出电压=5V ×11`、`1A→输出电流=500mA ×10` |
| 按意图找料（无型号反查） | `pick.py`：品类 facet → `catalogIdFilter` → 候选 → 动态参数键 | `8MHz 5032 无源晶振`、`30V 5A N沟道 MOS`、`10uF 25V 0805 电容`、`--family norflash --param "存储容量>=64Mbit"` 四组均命中 |
| 按销量/热度反向选型 | `pick.py` 默认 `--sort sales`（立创唯一销量字段 `recentlySalesCount`） | C6186 AMS1117-3.3 销量 29060 排首；C15850 三星 MLCC 销量 52513 排首 |
| 少量 vs 批量渠道推荐 | `bom.py::channel_advice` + `pick.py::channel_hint` + `references/channels.md` | `--qty 5` → 「少量：淘宝样品…」；`--qty 500` → 「批量：立创阶梯 + 1688 询盘」；BOM 整体「立创批量/1688」 |
| 淘宝/1688 检索 | `scripts/taobao.py`（Kimi WebBridge 登录态） | `check` 全绿（logged_in=True nick=你要记卓）；销量 tab 生效；混装包/区间价不参与单价归一 |
| BOM 表格配单 | `scripts/bom.py`（CSV/TSV/XLSX/纯文本） | 16 行示例全部匹配，合计 ¥28.84，1 行需人工确认；`--alternate` 只对风险行取替代 |
| 不造轮子 | `references/research/github-tools.md`（16 个现成轮子实测） | 复用 jlcparts 数据托管 / `jlcpcb` PyPI / `easyeda2kicad`；自建仅"BOM 行→候选→核对→落档"中间层 |

## 原始输出

- `probe\verify_20261104_170618.txt`：六段验收命令的真实输出（lcsc help/search、pick、bom、taobao check、alternate）
- `probe\bom\报价单_sample.md`、`probe\bom\报价单_sample_alt.md`、`probe\bom\result_sample.json`
- `probe\lcsc\`（110 文件）、`probe\lcsc\params\`（86 文件）、`probe\taobao\`、`probe\market\`、`probe\github\`
- 远端一致性：`probe\repo-verify\bom-sourcing-clone` 为 GitHub 直接克隆，跑 `pick.py cats`（25 family）与 `pick.py "3.3V 1A 的 LDO"` 均正常

## 未覆盖（明确边界）

- 立创参数区间筛选无服务端支持；单页上限 30，找料只看采样到的 60 条候选
- 京东只做过探测（以开发板套件为主、字段不同），未做成脚本
- 立创 BOM 一键配单接口需登录 Cookie，未内置
- 1688 阶梯价不公开，走量必须人工询盘
