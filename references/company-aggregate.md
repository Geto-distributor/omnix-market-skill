# Company Aggregate 映射

## 本地输入

上传源是已验证的 `company.json`。用户在上传时选择 visibility，服务端根据认证 principal 和强身份解析聚合管理字段。

## Resolve

优先法定注册号，其次已确认稳定官网域名。名称相似、地址相同、集团关系或共同项目不得自动合并。entityKind 从本地 company.entityType 映射。

## 完整聚合

上传 company、aliases、registrations、capitalRecords、websites、addresses、marketPresence、socialChannels、researchClassifications、companyRoles、productsAndServices、projects、relationships、contacts、licensesAndCertifications、financialRecords、newsAndSocialMedia、customsTransactions、lawsuitsAndCompliance、inquiries、risks、assessment、missingInformation、recommendedActions、additionalInformation、reportFiles、researchStatus、lastResearchedOn 和所有内嵌 Evidence。

同一 Company 可同时含 lead 与 competitor 分类，不使用 both。installer/service_contractor-only 不得上传为 confirmed competitor；自有品牌/系统即使 outsourced 仍可；distributor/reseller/rental_provider 可为渠道竞对。

完整聚合根统一控制 private/public 和软删除。不得拆分公开联系人、项目、关系、Evidence、财务、海关、诉讼、询盘或报告。
