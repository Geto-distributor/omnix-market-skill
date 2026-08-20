---
name: omnix-market
description: 通过 OmniX Market Intelligence OpenAPI 解析强身份，并可选创建、读取、更新、切换可见性、软删除或恢复完整 Company Aggregate。用于本地 GETO ResearchBundle 验证完成后由用户明确选择上传 private/public，或管理当前用户有权操作的 Company。
---

# OmniX Company Aggregate 客户端

## 作用与安全边界

OmniX 是可选上传、持久化、展示和平台内共享手段，不是研究完成条件。OpenAPI 是唯一接口合同；不猜路径、DTO、枚举或 operation。

在任何上传前先询问用户：

1. 是否上传或更新 OmniX；
2. Base URL 与 API Key 是否已通过本地环境安全配置；
3. 使用 `private` 还是 `public`。

配置：

- `OMNIX_API_BASE_URL`
- `OMNIX_API_KEY`，只从本地环境读取
- 可选 `OMNIX_OPENAPI_URL`，缺省 `${OMNIX_API_BASE_URL}/swagger/v1/swagger.json`

Key 不得进入 company.json、progress.md、报告、日志、来源或命令输出。

## 允许的 API

当前 Company Aggregate 操作面：

```text
GET    /api/market-intelligence/companies
GET    /api/market-intelligence/companies/{companyKey}
GET    /api/market-intelligence/scoring-criteria
POST   /api/market-intelligence/companies:resolve
POST   /api/market-intelligence/companies
PUT    /api/market-intelligence/companies/{companyKey}
PATCH  /api/market-intelligence/companies/{companyKey}
DELETE /api/market-intelligence/companies/{companyKey}
POST   /api/market-intelligence/companies/{companyKey}:restore
```

客户端只执行上表中同时出现在运行时 OpenAPI 的操作。

## 调用

```bash
python scripts/omnix_market.py capabilities
python scripts/omnix_market.py prepare-upload '<公司目录>/company.json' \
  --visibility private --output '<临时目录>/upload.json'
python scripts/omnix_market.py request POST '/api/market-intelligence/companies:resolve' --body identity.json
python scripts/omnix_market.py request POST '/api/market-intelligence/companies' --body upload.json --idempotency-key stable-key
python scripts/omnix_market.py request PUT '/api/market-intelligence/companies/company-key' --body upload.json
python scripts/omnix_market.py request PATCH '/api/market-intelligence/companies/company-key' --body visibility.json
python scripts/omnix_market.py request DELETE '/api/market-intelligence/companies/company-key' --confirm-delete
python scripts/omnix_market.py request POST '/api/market-intelligence/companies/company-key:restore' --body restore.json --confirm-restore
```

投影说明见 [upload-example.md](references/upload-example.md)，全字段 JSON 见 [company-aggregate-example.json](references/company-aggregate-example.json)。method、path、请求体与枚举必须通过本次 OpenAPI 校验。

## 标准流程

### 1. 本地门禁

确认国家 `progress.md`、公司 `company.json`、`report.md` 和 `Sources/sources.md` 已通过本地验证。ERROR 阻止上传；WARNING 必须显式保留。本地 ResearchBundle 是事实主合同，Company Aggregate 是其中可共享业务字段的投影。

### 2. Capability check

运行 `capabilities`。操作面完整时继续；否则返回 `partial|upstream_unavailable` 和缺失操作。

### 3. 强身份 resolve

按法定注册号、已确认稳定官网域名等强锚点调用 `companies:resolve`。legal_entity、operating_company、corporate_group 分别解析。private 与 public 都要求强身份；ambiguous/identity conflict 时停止写入。researchClassifications.status=possible 只表达业务分类状态。

### 4. 创建或更新完整聚合

先运行 `prepare-upload`。它按各资源 DTO 显式映射 company.json：marketCode 使用公司 ISO2 countryCode或用户明确给出的 GLOBAL，scopeCode 使用 construction_formwork；保留同一 Company 的 lead 与 competitor 两条 researchClassifications、项目 participants、关系 exclusivity、competitorCustomerPortfolio、assessment.capabilityContext 和内嵌 Evidence。inquiryAssessment、researchQueries、reportFiles、报告与本地路径留在 ResearchBundle。

lead 在同类型 cohort 完成六维评分后进入投影。confirmed competitor 在竞对客户任务生成 competitorCustomerPortfolio 后进入投影；客户缺分保持 null，覆盖率和平均分由组合合同计算。

投影包含 lead 时，客户端读取 `scoring-criteria` 的平台 hash 并注入请求；用户和 company.json 不维护该字段。平台口径与本地 assessment 不一致时停止上传。

resolve 匹配当前用户已有 Company 时 update；不存在时 create。已存在其他用户 public 强身份时返回 `blocked_public_duplicate`，由用户决定后续处理。聚合根整体包含项目、联系人、关系和 Evidence。

### 5. 回读与记录

校验服务端响应，返回 `uploadStatus=uploaded_private|uploaded_public|blocked_public_duplicate|failed`、服务端 Company Key、visibility 和 detailRoute。创建或更新可把 uploadStatus 与 detailRoute 写入 progress.md；平台 Key 不回写 company.json。

## 其他 CRUD

- private/public 是普通 PATCH/PUT 更新；public 表示认证且有 Market 读取权限的用户可见，不是匿名互联网公开。
- DELETE 是软删除，必须有用户明确意图并使用 `--confirm-delete`；结果只在当前任务回传。
- restore 必须有用户明确意图并使用 `--confirm-restore`；服务端重新检查 public 强身份唯一性，结果只在当前任务回传。
- 普通用户只操作自己拥有的数据；Admin 能力由服务端 principal 决定，客户端不传 ownerUserId。

详细映射见 [company-aggregate.md](references/company-aggregate.md)，错误处理见 [error-contract.md](references/error-contract.md)。
