# bom-sourcing

配单 / BOM 采购助手（DeepSeek Harness skill）：给**一个 BOM 表**或**一句话需求**，在立创商城（szlcsc）
取价、按器件指标核对、给替代料候选，并按数量给渠道建议（少量淘宝、批量立创/1688）。

数据来自立创中文站免登录 JSON 接口（唯一暴露「销量」的入口）+ 淘宝/1688 登录态浏览器，
价格均为抓取时刻快照、人民币含税。

## 两种入口

| 场景 | 命令 |
|---|---|
| 手上有 BOM 表 | `python scripts/bom.py your_bom.csv --qty 10` |
| 只有一句需求 | `python scripts/pick.py "找 3.3V 1A 的 LDO"` |
| 查单个料 | `python scripts/lcsc.py search "STM32F103C8T6" --sort sales` / `price C8734 --qty 100`（JSON）/ `detail` / `compare` |
| 找替代料 | `python scripts/lcsc.py alternate C8734 --qty 100` |
| 淘宝比价 | `python scripts/taobao.py search "STM32F103C8T6" --sort sales --limit 10` |
| 海外站比价 | `python scripts/distributor.py search "TPS25947" --site both --limit 5` |
| 原厂价/库存 | `python scripts/origin.py search TPA7836B --vendor 3peak` |
| 取数据手册 | `python scripts/lcsc.py detail C8734 --pdf --download ./pdfs` |
| 管黑名单 | `python scripts/blacklist.py list` / `check "Tokmas"` / `import entries.yaml --kind shop --authorized "…"` |

## 能力

- **BOM 配单**：CSV/TSV/XLSX/纯文本 → 列名自动识别 → 型号匹配（精确/前缀/包含，考虑封装、现货、销量）→
  指标核对（`✔`/`✘`/`?`）→ 阶梯价落档 → 备料量与 MOQ → Markdown 报价单 + JSON。
- **按意图找料**：一句话 → 品类（`catalogIdFilter`）→ 候选 60 条 → 从 `paramLinkedMap` 动态聚参数键 →
  约束过滤 → **功能符合性闸门** → 排序（销量/价格/库存）→ 落选主因（含"因功能不符剔除"）。
  已覆盖 26 个 family（阻容感、二极管、MOS、LDO、DC-DC、MCU、运放、比较器、基准、EEPROM、
  NOR FLASH、晶振、隔离器、光耦、继电器、连接器、功率电子开关等）。
- **替代料**：立创 substitute 接口（相似度 + 参数差异 + 国产替代），海外站与同型号兜底。
- **渠道建议**：≤10 套淘宝优先、11–100 立创/淘宝比价、>100 立创批量/1688，实测校正已写进文档。
- **海外分销商**：Mouser 中国 / DigiKey 中国检索（含税人民币价 + 库存），用于"立创没有的型号"比价。
- **原厂官方商城**：19 家注册（3PEAK 免登录含税人民币阶梯价 + 实时库存；TI 美元 1ku 价 + 浏览器取库存），
  用原厂价当"会不会买到翻新/散新"的基线。
- **功能符合性**：立创品类按采购口径分，`功率电子开关` 里混着降压转换器；`pick.py` 用商品名功能词做
  四态判定（ok/mismatch/conflict/unknown），挡掉"参数满足但功能不对"的料。
- **品牌白名单**：按「品牌 × 品类」放行（`whitelist.py`）—— 新品牌/跨品类必须背调后才能当结论；`pick.py` / `bom.py` 输出「品牌白名单核对」段。
- **品牌背调**：`brand_dossier.py` 把"这个牌子能不能用"做成证据链 —— 11 个取证渠道（官网/商标/工商/
  授权代理/资料站/社区/分销页…），每条证据带**事实 / 自述 / 推论**三级标注与把握度，按证据算
  tier 分层，没查到的写进 gaps。写操作需 `--authorized`（与黑名单同一套门禁）。
  **白名单粒度是「品牌 + 物料类别」**：在连接器上核过不代表 MOSFET 也能用（见 `references/brand-whitelist.md`）。
- **判据知识库**：`data/knowledge/mosfet.yaml`（EAS 雪崩能量、SOA 校核、工艺反推的
  fact/inference 分级、9 类应用语义）+ `brands.index.yaml`（1,296 品牌全集）+ `vendors.yaml`（145 品牌 tier）。

## 安装

把本目录放到 skill 根（如 `~/.agents/skills/bom-sourcing`）。脚本仅依赖 Python 标准库；
读 `data/categories.yaml` 需要 PyYAML（没有则退回 `data/categories.json` 缓存或内置关键词表）。
`taobao.py` 需要本机 Kimi WebBridge daemon（`http://127.0.0.1:10086`）与已登录的浏览器。

## 目录

```
SKILL.md              触发词、流程与坑（给 agent 看）
scripts/lcsc.py       立创检索/取价/详情/对比/替代料（带缓存，QPS≤1）
scripts/pick.py       按意图找料
scripts/bom.py        BOM 报价单
scripts/spec.py       参数解析与指标比对
scripts/taobao.py     淘宝/1688 检索（WebBridge 登录态）
scripts/distributor.py  Mouser 中国 / DigiKey 中国检索（WebBridge 登录态）
scripts/blacklist.py     品牌 / 店铺 / 料号黑名单（pick、bom、taobao 默认生效；写操作需 --authorized）
scripts/brands.py        品牌索引（按品类枚举立创品牌 facet，1,296 品牌）
scripts/brand_dossier.py 品牌背调档案（多渠道取证 + 事实/自述/推论三级标注 + 分层判定）
scripts/whitelist.py     品牌白名单（按「品牌 × 品类」放行；写操作需 --authorized）
data/categories.yaml  26 family 的品类 id、参数键与关键约束
data/spec-rules.yaml  32 family 的 critical/relaxable 参数、降额基准、风险备注
data/knowledge/       渠道、风险、降额、工作流、厂商 tier、黑名单、品牌索引、MOSFET 判据、品牌档案
references/           API 事实、指标判据、找料实现、渠道配方、品牌背调方法论、调研证据链
```

## 边界

- 立创**参数区间筛选无服务端支持**，只能取候选后本地过滤；单页上限 30 条，找料默认 2 页（60 条）。
- `totalCount` 被服务端截到 1500，真实规模看 `catalogGroup[].count`。
- 淘宝销量必须点「销量」tab（URL 参数无效）；淘宝「价格」tab 点击无效，价格只能客户端排序。
- 1688 只需 URL 参数即可按销量排序，但阶梯价拿不到 → 走量必须人工询盘。
- 立创商城与嘉立创 SMT 的库存/价格彼此独立，商城料不能随 PCB 寄。
- **品牌背调**：工商原始登记页（企查查/天眼查）需付费登录；立创品牌页走普通抓取只回反爬页，
  需真浏览器；社区检索噪声大（"托克马斯"同时命中杭州托马克机电、江西托克马克、加拿大箱包商标），
  必须区分同名实体；**没有第三方质量数据 ≠ 质量好**，只能记进 gaps。
- **MOSFET 抗冲击**：EAS / SOA / 热阻 / Tjmax 在立创全部 0% 覆盖，只能 `detail --pdf` 取手册后人工判；
  自动判定只能做电气初筛，不能给"通过"结论。

## 环境坑

- `*.lcsc.com` 不能走代理；本机 `no_proxy` 含 `[::1]` 会让 httpx 崩（`InvalidURL: Invalid port ':1]'`）。
- 淘宝页面空白但 params 正常 = 登录态过期（重新登录浏览器）。
- 筛选多值分隔符是 `$`（`"91$842"`），写成逗号会**静默返回 0 条**。
