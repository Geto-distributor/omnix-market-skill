# Agent REST 合同成熟度基线

截至 2026-08-13，本文件只用于防止把设计目标误写成已上线事实；每次执行仍以目标环境实时 OpenAPI 为唯一可调用合同。

## 当前服务端 main 已确认能力

- 已发布面为 17 个只读 GET。
- 不据此宣称 draft create/update/delete、resolve、submit 或批量 validate 已上线。
- 未部署测试环境，当前只运行静态合同和 Mock 测试。

## 未合并候选 PR/分支

- 候选 Agent REST 面约 59 个 operation：3 个 reference/resolve、18 个读取、36 个 draft 对象操作、2 个生命周期操作。
- 该数字不是当前 main 的发布事实；只有 endpoint 出现在目标环境 OpenAPI 后才能调用。
- Web UI 专用初始化、审核和发布接口不计入 Agent 合同。

## 本轮建议新增/调整

- 建议新增 `POST /markets/{marketCode}/drafts:validate`，候选总面约 60 个 operation。该接口只做 submit 前批量预校验，不写入、不提交。
- 不新增 Owner Draft List；复用对象 list + `contentStatus=Draft`，并要求 owner 隔离、完整可发现和稳定 draftKey/resourceKey。
- 不新增 CommercialAccount/Opportunity 独立 CRUD；一个市场内 Company→CommercialAccount 一一映射，Project→Opportunity 一一映射，分别内嵌 Company/Project。
- Agent 公共合同取消 ETag、If-Match、412、428 流程。保留 resolve-before-upsert、POST Idempotency-Key、稳定键、数据库唯一约束和内部审计 revision/modifiedOn。
- MCP 完全不纳入设计、实现或测试。

真实 REST 合同测试在测试环境上线并合并对应服务端 PR 前保持 blocked/pending，不产生外部写入或成本。
