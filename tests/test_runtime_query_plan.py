# tests/test_runtime_query_plan.py
from tkos_runtime.domain import query_plan

def test_traversal_and_constants():
    p = set(query_plan.TRAVERSAL)
    for need in ["hasProgressSnapshot","confirmsEntity","supportedByEvidence","hasContextGap","hasCriterion","informedBy"]:
        assert ("https://ontology.tokenking.ai/tkos#"+need) in p
    assert query_plan.MAX_DEPTH == 2 and query_plan.QUERY_PLAN_VERSION == "bfs-2gram/p0-v1"
