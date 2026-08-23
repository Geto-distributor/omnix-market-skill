# Company Aggregate 交付验证

## 四层一致性

每次创建、更新或批量刷新后，依次验证：

1. 本地源：`company.json` 通过 validator，active lead/competitor、assessment、relationships、portfolio 和 Evidence 符合本地合同。
2. 上传投影：`prepare-upload` 输出的 identity、visibility、marketCode、scopeCode、content 和 scoringCriteriaHash 符合运行时 OpenAPI；本地专用字段不进入请求。
3. 详情回读：GET Aggregate 返回目标 Company Key，identity、visibility、marketCode、scopeCode 和业务切片与投影一致。
4. 列表回读：使用产品实际采用的 lead/competitor 过滤请求验证列表成员。`status=rejected` 不得进入对应列表，`possible` 保留状态标签，confirmed competitor 不因另一条 lead 缺少 assessment 而改写。

任一层不一致时，记录具体字段、请求路径、Company Key 和实际响应，停止宣告交付完成。详情正确不能替代列表正确；列表容器名称不能替代 `researchClassifications` 原始字段。

## active 分类

- lead active set：`classification=lead` 且 `status=confirmed|possible`；
- competitor active set：`classification=competitor` 且 `status=confirmed|possible`；
- rejected 分类保留在 Aggregate 详情作为研究反证，但服务端分类索引与业务列表排除 rejected；
- 双分类 Company 分别出现在两个 active set，且两条状态独立展示。

## 列表请求

列表请求从运行时 OpenAPI 和实际产品调用路径取得。至少保留 marketCode、visibility、view、pageNumber、pageSize 和 researchClassification 查询边界；分页时验证所有页或明确本次覆盖范围。

前端直接把接口 items 作为数据源时，真实列表响应就是展示层数据证据。需要浏览器验收时使用现有登录会话；没有登录会话时报告浏览器边界，不伪造页面截图，并保留同一路径 API 响应和前端数据绑定证据。

## 批量结果

批量交付逐家公司记录：

- `uploaded_private|uploaded_public|updated_private|updated_public|blocked_public_duplicate|failed`；
- Company Key、detailRoute、HTTP 状态；
- 详情回读状态；
- lead/competitor 列表成员状态；
- 阻断或差异原因。

临时凭据只存在于受限本地环境；任务结束时撤销临时 Key、删除临时文件，回传仅保留 Key 标识、末四位和撤销状态。
