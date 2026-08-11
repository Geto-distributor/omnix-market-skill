# GETO 客户价值六维评分

先从 `reference-data.currentAssessmentModels` 选择 `modelCode=GETO_LEAD_VALUE` 的当前 `modelVersion`，不得自行猜版本。只有公司背调达到可评分条件时写分；证据不足且无有效 peer prior 的维度标为未评分，不能用 0 代替未知。

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

若有有效 peer prior：

`finalDimensionScore = observedScore × evidenceWeight + peerPriorScore × (1 - evidenceWeight)`

若没有有效 prior，按当前评分合同决定是否允许 observed score 直接成为 final；无法满足前置条件时不评分。总分只汇总六个已合法计算的 `finalDimensionScore`，所有维度完整前不得伪造完整总分或等级。

Assessment 使用 `assessmentType=lead_value`、`modelCode=GETO_LEAD_VALUE`、服务端当前 `modelVersion`，并写 `diligenceStatus`、`asOf`、`levelCode`、`scoreRationale`、`conclusion` 和 `capabilityFoundation`。存在未评分维度时省略 `levelCode`。服务端会拒绝维度缺失、重复、maxScore 不符、公式不一致、能力底座或证据引用不完整的 payload。
