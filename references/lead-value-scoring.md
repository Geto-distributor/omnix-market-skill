# GETO 客户价值六维评分

单公司 Assessment 只能由 `$geto-diligence-company` 在 `assessmentMode=lead_value` 时生产；`$geto-find-leads` 只聚合排序。先从 `reference-data.currentAssessmentModels` 选择 `modelCode=GETO_LEAD_VALUE` 的当前已批准 `modelVersion`，不得自行猜版本。只有公司背调达到可评分条件时写逐维判断；证据不足的维度标为未评分，不能用 0 代替未知。

正式评分还必须传 `capabilityFoundation`：`status` 必须为 `available`，并保存本次实际使用的 `contentHash`、`productCodes`、`scenarioCodes`、`caseKeys`、`sourceKeys`。partial/unavailable 时不写正式评分。

## 当前维度

| dimensionCode | 中文 | maxScore |
|---|---|---:|
| `project_city_value` | 项目城市价值 | 15 |
| `account_scale` | 客户规模 | 20 |
| `future_project_demand` | 未来项目需求 | 20 |
| `reachability` | 触达可行性 | 10 |
| `payment_capacity` | 支付能力 | 15 |
| `multi_product_fit` | 多产品适配度 | 20 |

## Dimension 字段

- `observedScore`：证据直接支持的原始分。
- `maxScore`：必须等于当前模型定义。
- `evidenceGrade` 与 `evidenceWeight`：证据等级及其权重。
- `peerPriorScore` 与 `cohortSnapshotKey`：仅在合同允许且存在有效同群基准时使用。
- `finalDimensionScore`：证据与有效先验合成后的最终维度分。
- `rationale`、`claimKeys`、`sourceKeys`：可解释理由和证据引用。
- `gapCodes`、`capCodes`：信息缺口和封顶原因。

只有 cohort 和模型均已冻结时才允许 peer prior。若有有效 peer prior 且批准模型仍使用该公式：

`finalDimensionScore = observedScore × evidenceWeight + peerPriorScore × (1 - evidenceWeight)`

Agent 提供 observedScore、证据等级、理由和 Claim/Source；finalDimensionScore、总分和等级由批准的确定性 validator/服务端规则计算。无法满足前置条件时不评分。所有维度完整前不得生成总分或等级；等级阈值未出现在批准 reference-data 时不得臆造。

Assessment 使用 `assessmentType=lead_value`、`modelCode=GETO_LEAD_VALUE`、服务端当前 `modelVersion`，并写 `producerSkill=geto-diligence-company`、`diligenceStatus`、`assessmentStatus`、`asOf`、`scoreRationale`、`conclusion` 和 `capabilityFoundation`。仅在服务端返回合法结果时保存 totalScore、levelCode、`scoreCalculatedBy` 和 `ratingScaleVersion`。服务端应拒绝维度缺失、重复、maxScore 不符、公式不一致、能力底座或证据引用不完整的 payload。

`assessmentStatus` 用于区分可恢复断点与可提交结果：

- `pending_diligence`：背调尚未完成、失败或主体冲突；不传 dimensions。
- `pending_capability_foundation`：能力底座尚不可用；不传 dimensions。
- `pending_model`：当前批准模型不可用；不传 dimensions。
- `incomplete_evidence`：背调已完成，但至少一个维度为 `U`；不生成总分或等级。
- `completed`：六个维度均可评分；总分只接受服务端确定性计算结果，等级仍取决于已批准的等级规则。

前三种状态只能作为私人草稿检查点，不能通过提交前校验或进入人工审核。
