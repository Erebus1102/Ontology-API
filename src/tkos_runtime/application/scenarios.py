"""场景注册表（权威：docs/mvp/01 §5）。本轮：枚举校验 + purpose 映射。"""

from __future__ import annotations
SCENARIOS = {
    "meeting_supervision": "decision_preparation",
    "strategic_research": "decision_preparation",
    "expert_panel": "decision_preparation",
    "task_followup": "mission_review",   # 非 execution_support；映射既有 mission_review（Reconciliation #7）
}


def resolve_purpose(scenario: str | None, principal_default: str | None) -> str:
    sid = scenario or principal_default
    if sid is None:
        return "decision_preparation"
    if sid not in SCENARIOS:
        raise ValueError(f"unknown scenario: {sid!r}")
    return SCENARIOS[sid]
