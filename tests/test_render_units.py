from tkos_runtime.domain.render_units import (
    RenderedFactUnit, RenderBudgetTooSmall, DECISION_INCIDENT_PREDICATES,
    NON_DECISION_INCIDENT_PREDICATES,
)
from tkos_runtime.domain.query_plan import TKOS

def test_rendered_fact_unit_view_key_derived():
    u = RenderedFactUnit(
        member_id="m1", partition="graph-candidate-and-dispute",
        source_graphs=("graph-candidate-and-dispute",),
        canonical_claim="x", expected_section="risks",
    )
    assert u.view_key == ("m1", "graph-candidate-and-dispute")

def test_incident_predicates_exclude_governance():
    excluded = {TKOS+p for p in (
        "sourcedFrom","confirmedBy","confirmsEntity","hasResponsibleAssignment",
        "assignmentHolder","assignmentRole","assignmentScope")}
    assert excluded == NON_DECISION_INCIDENT_PREDICATES
    assert excluded.isdisjoint(DECISION_INCIDENT_PREDICATES)
    assert (TKOS+"hasOutcome") in DECISION_INCIDENT_PREDICATES

def test_render_budget_exception_carries_fields():
    exc = RenderBudgetTooSmall(500, 1378)
    assert exc.requested_max_chars == 500
    assert exc.minimum_required_chars == 1378
