# TKOS Runtime API 契约草案 V1

## 1. 生成 Context Pack

`POST /v1/context-packs:resolve`

```json
{
  "enterprise_id": "lighthouse-group",
  "organization_scope": ["group", "fangdongdong", "aidc", "tokenking"],
  "include_descendants": true,
  "include_projects": ["lighthouse"],
  "actor_id": "person-123",
  "purpose": "decision_preparation",
  "query": "是否在本季度同时完成产品 1.0 上线和灯塔项目交付",
  "intent_hint": null,
  "as_of": "2026-08-11T10:00:00+08:00",
  "confirmation_policy": "confirmed_with_labeled_candidates",
  "context_budget": 12000,
  "render": "llm"
}
```

响应必须包含：

- `pack_id`
- `ontology_release_id`
- `matched_root` 与 `alternative_matches`
- `scope_resolution`
- `current_facts`
- `candidate_context`
- `derived_claims`
- `conflicts`
- `context_gaps`
- `omissions`
- `proof`
- `rendering`

`rendering` 可以缺失。结构化 Pack 始终返回。

## 2. 创建文档蒸馏任务

`POST /v1/distillation-jobs`

```json
{
  "enterprise_id": "lighthouse-group",
  "organization_scope": ["fangdongdong"],
  "source": {
    "uri": "lark://docx/example",
    "content_hash": "sha256:..."
  },
  "profile": "decision_case_bootstrap",
  "ontology_release_id": "tkos-2.4",
  "submitted_by": "person-123"
}
```

同步返回 `202 Accepted` 和 `job_id`。Worker 产出：

- `SourceSnapshot`
- `ExtractionRun`
- `CandidateAssertionBatch`
- 原文定位
- SHACL 报告
- 重复、冲突和 ContextGap 报告

## 3. 查询断言溯源

`GET /v1/assertions/{assertion_id}/lineage`

响应包括：

- 断言当前版本与状态
- 来源文档和原文定位
- 生成 Activity 与 Agent
- 支持和挑战 Evidence
- 关联 DecisionCase
- 使用的规则、Profile 和 Release
- ConfirmationEvent
- RevisionEvent、supersedes、refutedBy 和 expiredAt

## 4. 提交与确认

`POST /v1/submissions`

```json
{
  "idempotency_key": "client-generated-key",
  "enterprise_id": "lighthouse-group",
  "organization_scope": ["tokenking"],
  "type": "Evidence",
  "target_ids": ["mission-fe-m2-lighthouse-context-loop"],
  "payload": {},
  "source": {},
  "submitted_by": "person-123",
  "submitted_reason": "补充本周真实使用记录",
  "valid_time": {}
}
```

初次提交只能生成 Candidate。后续 Action：

- `POST /v1/submissions/{id}:confirm`
- `POST /v1/submissions/{id}:reject`
- `POST /v1/submissions/{id}:supersede`

确认事务完成以下动作：

1. 校验确认主体与范围。
2. 写入不可变 ConfirmationEvent。
3. 关闭或替代冲突版本。
4. 物化新的当前有效视图。
5. 重算受影响派生图。
6. 生成新的 Release 与审计回执。

## 通用错误

- `400` 请求结构错误
- `401` 身份缺失
- `403` 组织或用途不允许
- `404` 对象或 Release 不存在
- `409` 幂等冲突、版本冲突或待处理争议
- `422` SHACL 或业务门禁失败
- `503` 推理、存储或 LLM 依赖暂不可用

所有错误返回 `request_id`、稳定错误码和可追溯的失败阶段。
