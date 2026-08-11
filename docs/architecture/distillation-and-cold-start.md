# 文档蒸馏与冷启动方案

## 蒸馏产物

文档蒸馏的首要产物是 `CandidateAssertionBatch`。每项候选断言保存来源、原文位置、组织范围、时间、模型和 Prompt 版本、映射本体版本、置信度与提交原因。

## 分层处理

1. 文件接收、病毒检查、哈希和不可变快照。
2. PDF、DOCX、PPTX、会议文本和结构化数据分别解析。
3. 保留页码、段落、表格、说话人和时间位置。
4. 根据 Profile 提取对象、关系、事件和候选主张。
5. 使用稳定 ID、别名、组织和时间完成实体消歧。
6. 运行 SHACL、重复检测与冲突检测。
7. 生成候选批次、ContextGap 和人工确认任务。
8. 确认后发布新 Release。

## 冷启动 Profile

场景完整度由 Competency Question 与 SHACL Profile 决定。首期 Profile：

- `decision_preparation_minimum`
- `mission_review_minimum`
- `decision_case_bootstrap`
- `decision_learning_minimum`

每个 Profile 将字段分为：

- 必须存在
- 可选增强
- 当前未知
- 不适用
- 相互冲突

未知和冲突通过 ContextGap 或 ConflictSet 表达。系统不创建无来源的占位事实。

## 降级模式

资料不足时 API 1 返回：

- 当前已确认事实
- 明确标记的候选事实
- 可引用的原文片段
- 缺失字段和被阻断推导
- 建议向谁确认什么
- 允许 Agent 继续完成的任务边界

降级 Pack 可以支持材料整理和提问准备，不能支持正式决策确认或 Mission 验收。
