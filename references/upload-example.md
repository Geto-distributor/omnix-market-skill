# Company Aggregate 投影示例

## 本地输入

使用已通过 GETO workspace validator 的 `company.json`。其中至少包含：

```json
{
  "company": {
    "companyName": "Example Build Systems Ltd.",
    "entityType": "operating_company",
    "country": "Australia",
    "countryCode": "AU"
  },
  "registrations": [{
    "registrationNumber": "123456789",
    "jurisdiction": "AU",
    "status": "active",
    "verificationStatus": "verified",
    "evidence": []
  }],
  "projects": [{
    "projectName": "Harbour Residence",
    "participants": [{
      "name": "Example Developments Pty Ltd.",
      "role": "developer",
      "identity": {"primaryDomain": "example-developments.test"},
      "status": "confirmed",
      "lastVerifiedOn": "2026-08-20",
      "evidence": []
    }],
    "evidence": []
  }],
  "relationships": [{
    "counterpartyName": "Example Developments Pty Ltd.",
    "relationshipType": "customer",
    "limitations": ["Buyer and payer remain unverified."],
    "exclusivity": {
      "status": "unknown",
      "scope": null,
      "description": null,
      "lastVerifiedOn": null,
      "evidence": []
    },
    "evidence": []
  }],
  "assessment": {
    "status": "completed",
    "capabilityContext": {"foundationKey": "geto:capability-foundation"}
  },
  "competitorCustomerPortfolio": {"status": "not_requested"},
  "inquiryAssessment": {"status": "not_requested"},
  "researchQueries": [],
  "reportFiles": [],
  "researchStatus": "completed_with_gaps",
  "lastResearchedOn": "2026-08-20"
}
```

实际业务 item 使用完整 Evidence。上面的空 Evidence 只用于突出投影字段位置。

## 生成投影

```bash
python scripts/omnix_market.py prepare-upload \
  '<公司目录>/company.json' \
  --visibility private \
  --output '<临时目录>/upload.json'
```

生成结果包含：

```json
{
  "identity": {
    "entityKind": "operating_company",
    "jurisdiction": "AU",
    "registrationNumber": "123456789"
  },
  "visibility": "private",
  "marketCode": "AU",
  "scopeCode": "construction_formwork",
  "asOf": "2026-08-20",
  "lastVerifiedOn": "2026-08-20",
  "content": {
    "company": {},
    "projects": [],
    "relationships": [],
    "assessment": {},
    "competitorCustomerPortfolio": {},
    "researchStatus": "completed_with_gaps",
    "lastResearchedOn": "2026-08-20"
  }
}
```

inquiryAssessment、researchQueries 和 reportFiles 留在本地。投影包含 lead 时，客户端从 scoring-criteria 读取并注入 scoringCriteriaHash。

常见本地字段在生成结果中使用 API 名称：

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
