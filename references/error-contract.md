# OmniX Market 错误与恢复

| HTTP/状态 | 含义 | 处理 |
|---|---|---|
| 401 | Key 缺失、无效、撤销或过期 | `unauthenticated`，停止写入 |
| 403 | 当前接口不允许该 principal | `forbidden`，不尝试其他身份路径 |
| 404 | 实体或 endpoint 不存在 | 区分 resolve miss 与 capability miss |
| 409 | 自然键、状态或发布冲突 | 重新 resolve，人工仲裁冲突 |
| 422 | DTO/证据/业务验证失败 | 保留错误，回到 ResearchDelta 修正 |
| 429 | 速率限制 | `rate_limited`，遵守 Retry-After |
| 5xx | 服务暂不可用 | `upstream_unavailable`，保留 checkpoint |

重试只适用于幂等读请求和带稳定 Idempotency-Key 的 create。update 超时后先 resolve 并回读稳定 draft/resource key，再判断服务端状态；不得自动重试 DELETE、submit 或任何审批操作。

新国家返回 `MARKET_SCOPE_NOT_FOUND` 时不是“该国没有客户”，而是 `initialization_required`。管理员通过 Web session 初始化后再继续；Skill 不使用 API Key 绕过初始化/发布边界。
