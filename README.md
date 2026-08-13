# OmniX Market Agent Skill

面向 OmniX Market Agent REST API 的 Agent Skill 与 Python 安全客户端。它依据运行时 OpenAPI 查询市场情报实体、解析 Company/Project 自然键，并创建或更新当前 API Key principal 的私人草稿。

## 能力

- 读取 Market reference-data 和已发布市场实体。
- Company、Project 自然键解析，避免重复主体。
- 创建、更新和删除当前用户的私人草稿。
- 写入 Company、Project、Relationship、Assessment、Claim/Source、Contact、Customs 和 Financial 等稳定业务实体。
- 用户明确要求时提交指定草稿进入人工审核。

本仓库不执行市场初始化、最终发布、Approve、Reject、审批队列或 ResearchRun；这些仍由 OmniX Web 治理流程或上层研究编排负责。

集成只使用 Agent REST，不包含 MCP。当前服务端 main、未合并候选 PR 与建议新增能力的区分见 [合同成熟度基线](references/contract-status.md)；测试环境未上线前不声称真实写入测试已通过。

## 安装

~~~bash
git clone https://github.com/Geto-distributor/omnix-market-skill.git ~/.codex/skills/omnix-market
~~~

也可以将仓库克隆到其他支持 `SKILL.md` 的 Agent 运行时的 Skill 搜索目录。

## 配置

~~~bash
export OMNIX_API_BASE_URL="https://<your-omnix-host>"
export OMNIX_API_KEY="omx_live_xxx"
# 可选；默认使用 $OMNIX_API_BASE_URL/swagger/v1/swagger.json
export OMNIX_OPENAPI_URL="https://<your-omnix-host>/swagger/v1/swagger.json"
~~~

API Key 必须由 OmniX 部署方签发。不要把真实 Key 写入仓库、Prompt、日志或 ResearchDelta。

## 使用

~~~bash
python3 scripts/omnix_market.py --help
python3 scripts/omnix_market.py capabilities
python3 scripts/omnix_market.py request GET '/api/market-intelligence/v1/reference-data'
python3 -m unittest discover -s tests -v
~~~

先阅读 [SKILL.md](SKILL.md)。实际 endpoint、method、DTO、枚举和评分版本始终以当前 OmniX OpenAPI 与 reference-data 为准。

## 许可证

Apache-2.0，见 [LICENSE](LICENSE)。
