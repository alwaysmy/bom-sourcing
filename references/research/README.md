# 配单 BOM 调研工作区

## 目录
- `BOM-配单-调研报告.md` —— 汇总报告（Lead 最终产出）
- `architecture.md` —— 能力架构草案
- `lead-findings.md` —— Lead 实测的立创接口事实（原始记录）
- `github-tools.md` —— 现成开源工具/MCP/库盘点（gh-research）
- `lcsc-probe.md` —— 立创商城接口逆向清单（lcsc-probe）
- `market-probe.md` —— 淘宝/1688/京东 检索与销量排序验证（market-probe）
- `cn-knowledge.md` —— B站/知乎/CSDN/立创社区 方法论与可用工具（cn-knowledge）
- `spec-rules.md` / `spec-rules.yaml` —— 指标对比与替代规则（spec-rules）
- `probe/` —— 原始抓包、脚本、样本（按渠道分目录）

## 规则
1. 每份报告写"事实 / 证据 / 结论"三层，可复放命令必须附上。
2. 失败路径也要记（哪个接口 403/验证码），避免后人重踩。
3. 样本 JSON 落 `probe/<渠道>/`，报告里引用相对路径。
