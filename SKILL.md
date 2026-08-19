---
name: omnix-market
description: 通过 OmniX 单一无版本 Market Intelligence OpenAPI 解析强身份，并可选创建、读取、更新、切换可见性、软删除或恢复完整 Company Aggregate。用于本地 GETO ResearchBundle 验证完成后由用户明确选择上传 private/public，或管理当前用户有权操作的 Company；不处理研究 Draft/Approval/Submit/Reject、ResearchDelta、ETag 或旧 API fallback。
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

只允许 OpenAPI 实际声明的以下无版本路径：

```text
GET    /api/market-intelligence/companies
GET    /api/market-intelligence/companies/{companyKey}
POST   /api/market-intelligence/companies:resolve
POST   /api/market-intelligence/companies
PUT    /api/market-intelligence/companies/{companyKey}
PATCH  /api/market-intelligence/companies/{companyKey}
DELETE /api/market-intelligence/companies/{companyKey}
POST   /api/market-intelligence/companies/{companyKey}:restore
```

任何 `/api/market-intelligence/v1`、`/v2`、Draft、Approval、Submit、Approve、Reject、redirect、adapter 或 fallback 都必须拒绝。

## 调用

```bash
python scripts/omnix_market.py capabilities
python scripts/omnix_market.py request POST '/api/market-intelligence/companies:resolve' --body identity.json
python scripts/omnix_market.py request POST '/api/market-intelligence/companies' --body upload.json --idempotency-key stable-key
python scripts/omnix_market.py request PUT '/api/market-intelligence/companies/company-key' --body upload.json
python scripts/omnix_market.py request PATCH '/api/market-intelligence/companies/company-key' --body visibility.json
python scripts/omnix_market.py request DELETE '/api/market-intelligence/companies/company-key' --confirm-delete
python scripts/omnix_market.py request POST '/api/market-intelligence/companies/company-key:restore' --body restore.json --confirm-restore
```

示例只说明调用形态；method、path、请求体与枚举必须通过本次 OpenAPI 校验。

## 标准流程

### 1. 本地门禁

确认国家 `progress.md`、公司 `company.json`、`report.md` 和 `Sources/sources.md` 已通过本地验证。ERROR 阻止上传；WARNING 必须显式保留。上传完整 Company Aggregate，不生成或要求本地 Company/Classification ID。

### 2. Capability check

运行 `capabilities`。若新 API 未完整发布，返回 partial/upstream_unavailable 并停止；不得探测或回退旧接口。

### 3. 强身份 resolve

按法定注册号、已确认稳定官网域名等强锚点调用 `companies:resolve`。legal_entity、operating_company、corporate_group 分别解析。ambiguous/identity conflict 时停止自动写入。

### 4. 创建或更新完整聚合

读取 OpenAPI Company Aggregate request schema，把 company.json 业务字段和用户选择的 visibility 映射为完整请求。保留同一 Company 的 lead 与 competitor 两条 researchClassifications；保留 productsAndServices 的 commercialRoles、manufacturingStatus 和内嵌 Evidence。

resolve 匹配当前用户已有 Company 时 update；不存在时 create。已存在其他用户 public 强身份时，将本次保持或上传为 private，并返回 `blocked_public_duplicate`，不能拆分项目、联系人或证据绕过聚合根。

### 5. 回读与记录

校验服务端响应，返回 `uploadStatus=uploaded_private|uploaded_public|blocked_public_duplicate|failed`、服务端 Company Key、visibility 和 detailRoute。只把 uploadStatus 与 detailRoute 写入 progress.md；平台 Key 不回写 company.json。

## 其他 CRUD

- private/public 是普通 PATCH/PUT 更新；public 表示认证且有 Market 读取权限的用户可见，不是匿名互联网公开。
- DELETE 是软删除，必须有用户明确意图并使用 `--confirm-delete`。
- restore 必须有用户明确意图并使用 `--confirm-restore`；服务端重新检查 public 强身份唯一性。
- 普通用户只操作自己拥有的数据；Admin 能力由服务端 principal 决定，客户端不传 ownerUserId。

详细映射见 [company-aggregate.md](references/company-aggregate.md)，错误处理见 [error-contract.md](references/error-contract.md)。
