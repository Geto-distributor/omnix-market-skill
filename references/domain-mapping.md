# OmniX Market 领域映射

## 顺序

1. Company 与 CompanyRole/LegalEntity identity；先 `companies:resolve`。把 CommercialAccount 作为 Company 在该市场的商业账户信息保存。
2. Product、Project/Opportunity；Project 先 `projects:resolve`。把 Opportunity 作为 Project 的商业机会信息保存。
3. ProjectParticipant、ProjectProduct、Relationship。
4. Assessment 与 AssessmentDimension。
5. Source、Claim、ClaimSourceLink。
6. Contact、CustomsEvidence、FinancialRecord。
7. 使用对象 list + `contentStatus=Draft` 回读当前用户的稳定 draft/resource keys。
8. 执行批量草稿校验，再对同一 subject 的 draft keys 做显式 submit。

实际 endpoint、method、query 和 DTO 始终从当前 OpenAPI 读取；此顺序不授权调用缺失接口。

## 自然键

- Company：优先主域名，其次注册号、规范名称/法定名称；别名和多法定主体一并保存。
- Project：优先 researchCode，其次规范项目名 + 城市；地区、国家代码、金额/币种、状态和时间窗口作为结构化字段保存。
- Relationship：sourceCompanyKey + targetCompanyKey + relationshipType + project/product/time discriminator。
- Source：canonical URL + retrieved/content discriminator；同一页面不重复创建。
- Claim：target type/key + claimType + stable discriminator。
- Contact：companyKey + normalized name/email/phone identity。
- Financial：company/legalEntity + period + currency + report type。
- Customs：subject + provider/query boundary + period + commodity/HS discriminator。

Relationship 的 `relationshipType` 只表达关系边，不得填 customer、competitor、project 等实体角色；合作方式和对手方角色分别写 `cooperationMode`、`counterpartyRoleCode`。采购方、实际使用方和付款方不可混成一个字段。填写 GETO 建议的 `cooperationMode` 或 `entryPoint` 时必须附带 status=available 且含 contentHash 的 `capabilityFoundationRef`；客观关系本身可在能力底座不可用时保存。

Contact、Customs、Financial 的 provider observation 写 `provider`、`sourceKeys`、`queryBoundary`、`retrievedOn`。外部 provider 的内部任务 ID 或凭据不进入 Market draft。

## 状态

研究状态 `normalized|claim_only|not_queried|not_found|conflicting|not_applicable|stale` 与发布状态 `private_draft|pending_approval|published|changes_requested` 分开。Provider 的 unavailable 不能映射为 not_found。

Assessment、ClaimSourceLink、ProjectProduct 和 Source 的 draft 必须能由 owner-scoped 对象 list 找回，并返回足以继续 update/submit 的稳定 draftKey/resourceKey；只有内部 revision/modifiedOn 可作为审计元数据，不要求 Agent 做版本协商。
