# 新国家拓客写入流程

## 入口检查

1. 运行 `capabilities` 并读取 `GET /api/market-intelligence/v1/reference-data`。
2. 从 reference-data 读取当前产品、评分模型和枚举，不使用本地硬编码替代服务端合同。
3. 读取目标市场。若 resolve/read 返回 `MARKET_SCOPE_NOT_FOUND`，报告 `initialization_required` 并停止写入。

市场初始化 `POST /api/market-intelligence/v1/markets:initialize` 和最终发布 `POST /api/market-intelligence/v1/markets/{marketCode}:publish` 都是 Web session 能力。Agent API Key 不调用；管理员初始化后，Skill 可以在 Unpublished release 上建立和读取当前用户草稿。发布至少需要一条已经审核通过并物化的 Company。

## 一次完整交付

1. 读取 reference-data，锁定 `scopeCode`、产品代码和当前 `GETO_LEAD_VALUE` modelVersion。
2. 对每个候选 Company 调用 `companies:resolve`。matched 走更新，not_found 用 suggestedResourceKey 创建，ambiguous 停止并保留 identity conflict。
3. 先写 Company identity：规范名称、别名、法定主体、注册号、官网/主域名、总部、角色、商业账户和核验日期。
4. 对每个 Project/Opportunity 调用 `projects:resolve`，再写 Project、Participant、Product 和 Relationship。关系分别记录合作方式、对手方角色、采购方、实际使用方、付款方、地点和时间窗口。
5. 写 Source、Claim、ClaimSourceLink；再写 Contact、CustomsEvidence、FinancialRecord。Provider 数据必须带 sourceKeys、queryBoundary、retrievedOn，不把 provider unavailable 当作 not_found。
6. 公司背调完成后，按 [lead-value-scoring.md](lead-value-scoring.md) 写 Assessment 与六个 Dimension。
7. 使用各对象 list + `contentStatus=Draft` 回读当前用户草稿，校验 resourceKey、draftKey、warnings 和关系闭包。
8. 调用 OpenAPI 中的批量草稿校验 operation；不可用时停在私人草稿并报告能力缺口。
9. 默认停在私人草稿。只有用户明确要求“提交审核”时才调用 `drafts:submit`。Approve/Reject 和发布由 Web UI 完成。

不写 ResearchRun。研究范围、检查点和 ResearchDelta 由上层 GETO Skills 维护，OmniX Market 只接收稳定业务实体与证据。

## 完成判定

一次完整交付包括：主体去重、公司与项目、参与方/产品/关系、证据链、联系人/海关/财务、六维评分、私人草稿回读、批量预校验和显式提交。初始化、人工审核和发布由 Web 治理流程完成。
