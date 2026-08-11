---
name: omnix-market
description: 通过 OmniX Agent REST API 查询市场情报实体、解析自然键，并创建或更新当前用户私有的 Market drafts；依据实时 OpenAPI 和 reference-data 校验路径、请求体、枚举、幂等键和 ETag，并可在用户明确要求时提交人工审核。用于 GETO Skills 的 Company、Role、Project、Product、Relationship、Assessment、Claim/Source、Contact、Customs 和 Financial 交付；不执行市场初始化/发布或 Approve/Reject。
---

# OmniX Market Agent REST

## 作用与安全边界

这是 OmniX Market 的薄客户端 Skill。OpenAPI 是唯一接口合同；每次调用前先读取服务端 OpenAPI，不猜路径、参数、operation 或 DTO。

配置：

- `OMNIX_API_BASE_URL`：OmniX API 根地址。
- `OMNIX_API_KEY`：当前用户的 `omx_test_*` 或 `omx_live_*` Key，只从本地环境读取。
- 可选 `OMNIX_OPENAPI_URL`：未设置时使用 `${OMNIX_API_BASE_URL}/swagger/v1/swagger.json`。

不得输出、持久化或转发 Key 到 OmniX 以外的目标。不要把 Key 写入 ResearchDelta、日志或工作文件。

## 调用工具

使用 `scripts/omnix_market.py`：

~~~bash
python scripts/omnix_market.py capabilities
python scripts/omnix_market.py request GET '/api/market-intelligence/v1/reference-data'
python scripts/omnix_market.py request POST '/api/market-intelligence/v1/markets/AU/companies:resolve?scopeCode=construction_formwork' --body company-identity.json
python scripts/omnix_market.py request GET '/api/market-intelligence/v1/markets/AU/companies/company-key?scopeCode=construction_formwork'
python scripts/omnix_market.py request POST '/api/market-intelligence/v1/markets/AU/drafts/companies?scopeCode=construction_formwork' --body company.json --idempotency-key stable-key
python scripts/omnix_market.py request PUT '/api/market-intelligence/v1/markets/AU/drafts/companies/company-key?scopeCode=construction_formwork' --body company.json --if-match 'server-etag'
~~~

脚本只允许 OpenAPI 中实际存在的 Market 读取和 draft 操作；审批路径和 `:approve`/`:reject` 永久拒绝。DELETE 需要 `--confirm-delete`，submit 需要 `--confirm-submit`。

## 标准流程

### 1. capability check

运行 `capabilities`，再读取 `reference-data` 获取产品、当前评分模型/维度、角色、关系类型和服务端能力。OpenAPI 不可访问、接口未发布或本地 Key 未配置时，返回明确 provider status，不要回退为猜测调用。

真正的新国家若返回 `MARKET_SCOPE_NOT_FOUND`，停止写入并报告 `initialization_required`。市场初始化和最终发布只允许 Web session，API Key Skill 不代替管理员执行。

### 2. resolve-before-upsert

Company/Project 先调用各自的 `:resolve`，再用 read endpoints 查询：

- Company 名称、别名、官网域名、法定主体与多角色。
- Project/Opportunity 的名称、地点、参与公司和时间窗口。
- Relationship、Product、Assessment、Claim、Source 与子资源。

`matched` 时 update/link，`not_found` 时采用服务端 `suggestedResourceKey` 创建，`ambiguous` 时保存 identity conflict 并停止该主体写入，不创建重复 Company/Project。

### 3. 构造 draft

读取 OpenAPI 中对应 request schema，逐字段映射 ResearchDelta。先保存 Company，再保存 Project、Relationship、Assessment 和证据子资源。禁止丢弃 API 尚未消费的稳定领域字段；可将其保留在 ResearchDelta gaps/pending payload 中等待合同支持，但不能塞入任意长文本冒充结构化写入。

POST create 必须使用可重算的 `Idempotency-Key`。PUT/DELETE 必须先读取 owner draft 的 ETag，再使用 `If-Match`；遇 412/428 重新读取并合并，不盲重试。

### 4. 校验服务端响应

保存 draftKey、resourceKey、schemaCode、validationStatus、warnings、contentHash、ETag 和 detail URL。服务端 409/412/422/428 属业务冲突，必须回到 resolve/validation，不改写成成功。

### 5. 提交审核

默认只创建/更新私人草稿。仅当用户明确表达“提交审核”时，使用 OpenAPI 中的 draft submit operation，并传精确 draftKeys；submit 不是发布。

Approve、Reject、审批队列和审核详情属于 Web UI，会被本 Skill 与脚本拒绝。

## 领域映射

读取 [country-onboarding.md](references/country-onboarding.md) 编排完整新国家流程，读取 [domain-mapping.md](references/domain-mapping.md) 处理模块对象，读取 [lead-value-scoring.md](references/lead-value-scoring.md) 写入当前 GETO 六维客户价值评分，读取 [error-contract.md](references/error-contract.md) 处理状态和恢复。

## 不变量

- 所有草稿归属由服务端当前 API Key principal 决定，客户端不得传 owner。
- 不使用数据库 ID、SQL patch 或 Excel 行号作为自然键。
- Claim/Source/ClaimSourceLink 保持可追溯；observed Claim 至少有一个 supports Source。
- 先保存 parent，再保存 child/link；批次提交必须属于同一可审核 subject。
- 不创建或写入 ResearchRun；研究检查点留在上层 GETO 编排合同中。
- 不调用未出现在当前 OpenAPI 的接口。
