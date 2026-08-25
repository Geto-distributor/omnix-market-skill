# Company Aggregate 映射

## 本地输入

上传源是已验证的 `company.json`。本地 ResearchBundle 保存研究事实、查询日志、来源索引和报告；Company Aggregate 保存允许平台内共享的业务投影。用户在上传时选择 visibility，服务端根据认证 principal 和强身份解析聚合管理字段。

## Resolve

优先法定注册号，其次已确认稳定官网域名。private 与 public 都要求强身份。名称相似、地址相同、集团关系或共同项目不得自动合并。entityKind 从本地 company.entityType 映射。

## 完整聚合

上传 company、aliases、registrations、capitalRecords、websites、addresses、marketPresence、socialChannels、researchClassifications、companyRoles、productsAndServices、projects、relationships、contacts、licensesAndCertifications、financialRecords、newsAndSocialMedia、customsTransactions、lawsuitsAndCompliance、inquiries、risks、assessment、competitorCustomerPortfolio、missingInformation、recommendedActions、additionalInformation、researchStatus、lastResearchedOn 和所有内嵌 Evidence。

projects[] 使用 participants[]；relationships[] 使用 limitations[] 与 exclusivity 状态对象。assessment 可包含 capabilityContext。Evidence 只保存来源元数据。

投影器按 API 字段显式转换：aliasType→type、legalName→registeredName、websiteType→type、startedOn→startOn、targetCompanyRole→companyRole、counterpartyName→relatedPartyName、reviewDecision→customerQualificationStatus、cooperationModeCode/cooperationDepthCode→cooperationMode/cooperationDepth。项目规模字段汇入 scale 对象，长期价值 dimension 的 finalDimensionScore 映射为 score。

inquiryAssessment、researchQueries、reportFiles、report.md、Sources/sources.md、progress.md 和本地路径保存在 ResearchBundle。

同一 Company 可同时含 lead 与 competitor 分类，不使用 both。installer/service_contractor-only 不得上传为 confirmed competitor；自有品牌/系统即使 outsourced 仍可；distributor/reseller/rental_provider 可为渠道竞对。

完整聚合根统一控制 private/public 和软删除。public Aggregate 整体展示联系人、项目、关系、Evidence、财务、海关、诉讼和询盘。

## 市场与范围

- marketCode 使用单公司研究所在市场的 ISO 3166-1 alpha-2 大写代码；跨国研究可明确使用 GLOBAL，跨国经营事实写入 marketPresence[]。
- scopeCode 使用 construction_formwork，对应“建筑模架与相关制造生态”。

## 评分投影

competitorCustomerPortfolio 上传已核实客户数、已评分客户数、覆盖率、客户价值平均分和逐客摘要。逐客分来自其完成的 GETO_LEAD_VALUE cohort assessment；缺分客户保留 null，不进入平均分分母。关系 0–5 切入分保存在 relationships[].entryAssessment。

执行竞对客户组合分析时，competitorCustomerPortfolio 与 relationships[].customerQualificationStatus=verified_customer 的去重集合保持一致；未执行组合分析时 portfolio 可为 not_requested 或不进入投影。confirmed competitor 的公司级投影不依赖组合完整度。active lead 要求已完成六维 cohort assessment；assessment.evidence 聚合维度 Evidence，capabilityContext 保存本次评分使用的能力上下文。

包含 lead 的投影由客户端读取平台 scoring-criteria hash。company.json 与用户输入不承担 hash 管理。
