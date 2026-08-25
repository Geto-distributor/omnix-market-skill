# Company Aggregate 投影示例

## 完整参考工件

[company-aggregate-example.json](company-aggregate-example.json) 是可通过当前 OpenAPI request schema 的完整合成请求。每个 Company Content 列表都有至少一个业务 item，项目、关系、联系人和 Evidence 也全部带有实际示例值；同一 Company 同时展示 confirmed lead、confirmed competitor、完成态六维 assessment、Capability Context、verified_customer 关系、0–5 切入分和 competitorCustomerPortfolio。

该 JSON 全部为合成数据，仅用于理解 DTO、枚举、Evidence 嵌套和本地到平台的字段映射。实际上传工件由本次 ResearchBundle 和运行时 OpenAPI 生成。

## 本地输入

本地完整输入读取 `$geto-run-market-research/references/company-json-example.json`。它覆盖 ResearchBundle 主合同的全部顶层资源、三个本地评估对象和所有 Company 子资源字段。

## 生成真实投影

```bash
python scripts/omnix_market.py prepare-upload \
  '<公司目录>/company.json' \
  --visibility private \
  --output '<临时目录>/upload.json'
```

`prepare-upload` 根据本次运行时 OpenAPI 完成 DTO 校验；投影包含 lead 时，从 `GET /api/market-intelligence/scoring-criteria` 取得当前 hash 并写入请求。

维护完整合成示例时可运行：

```bash
python scripts/generate_company_aggregate_example.py \
  '<geto-run-market-research>/references/company-json-example.json' \
  --openapi tests/fixtures/company-aggregate-openapi.json \
  --scoring-criteria-hash '<当前平台 hash>' \
  --output references/company-aggregate-example.json
```

生成器同时检查 OpenAPI schema 和空值；示例中的 hash 对应其标注的 API 合同基线，业务上传仍由 `prepare-upload` 动态取得。

## 主要字段映射

| 本地 company.json | Company Aggregate |
| --- | --- |
| aliases[].aliasType | aliases[].type |
| registrations[].legalName | registrations[].registeredName |
| websites[].websiteType | websites[].type |
| projects[].startedOn | projects[].startOn |
| projects[].targetCompanyRole | projects[].companyRole |
| relationships[].counterpartyName | relationships[].relatedPartyName |
| relationships[].reviewDecision | relationships[].customerQualificationStatus |
| relationships[].cooperationModeCode | relationships[].cooperationMode |
| relationships[].cooperationDepthCode | relationships[].cooperationDepth |
| assessment.dimensions[].finalDimensionScore | assessment.dimensions[].score |

`inquiryAssessment`、`researchQueries`、`reportFiles`、报告、来源索引和进度文件属于本地 ResearchBundle。
