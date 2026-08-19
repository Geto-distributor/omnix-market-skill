# OmniX Company Aggregate 错误与恢复

| HTTP/状态 | 含义 | 处理 |
| --- | --- | --- |
| 401 | Key 缺失、无效、撤销或过期 | unauthenticated，停止 |
| 403 | principal 无权限或无数据归属 | forbidden，不尝试其他身份 |
| 404 | Company 或新 endpoint 不存在 | 区分 resolve miss 与 capability miss；不回退旧接口 |
| 409 public identity conflict | 他人已有有效 public 强身份 | 保持/上传 private，返回 blocked_public_duplicate |
| 409 other | 身份、状态或唯一性冲突 | 重新 resolve，人工仲裁 |
| 422 | OpenAPI/业务验证失败 | 修正本地映射后重试 |
| 429 | 速率限制 | rate_limited，遵守 Retry-After |
| 5xx | 服务暂不可用 | upstream_unavailable，本地研究仍完成 |

只自动重试幂等 GET。带稳定 Idempotency-Key 的 create 网络超时后先 resolve/回读，再决定是否重发。DELETE、restore 和可见性变更不自动重试。
