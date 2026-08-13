# src/tkos_runtime/domain/query_plan.py
"""BFS 查询计划单一来源（Retriever 与 scripts/resolve_issue_context.py 共享）。"""
TKOS = "https://ontology.tokenking.ai/tkos#"
MAX_DEPTH = 2
QUERY_PLAN_VERSION = "bfs-2gram/p0-v1"
TRAVERSAL = [TKOS + p for p in (
    "informedBy","researchedBy","hasContextGap","hasRisk","contributesTo","belongsTo",
    "hasOutcome","hasPortfolio","inPortfolio","expects","hasResponsibleAssignment",
    "assignmentHolder","assignmentRole","assignmentScope","dependsOn","hasMilestone",
    "hasProgressSnapshot","hasCriterion","hasRationale","hasScope","hasKeyPath",
    "supportedByEvidence","sourcedFrom","confirmedBy","challengingEvidence","challengesClaim",
    "isReviewedBy","delivers","supports","isDeliveredBy","hasSuccessCriterion","contains","confirmsEntity",
    "hasProductModule",
)]
