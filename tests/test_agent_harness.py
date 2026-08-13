# tests/test_agent_harness.py
"""Phase C — agent integration harness (联调) acceptance test.

This is the acceptance gate for the user's primary goal: "首要目标是完成和
agent的联调". Agent code is not accessible, so this test simulates the agent
consuming the Phase-B read API in-process and asserts the returned Context Pack
is correct and agent-usable.

It uses ``fastapi.testclient.TestClient(create_app())`` so no external server
is required. The harness script (``scripts/agent_harness.py``) is the
live-server counterpart of the same contract.

The assertions here are STRICTER than ``tests/test_runtime_api.py`` — they
encode what an agent actually needs (provenance citation, epistemic honesty,
traceable proof) rather than just HTTP-level happy-path behavior. They must
fail loudly if the Pack is not agent-usable.
"""
from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tkos_runtime.api.server import create_app

TKOS = "https://ontology.tokenking.ai/tkos#"
ISSUE = TKOS + "issue-product1-lighthouse-synchronous-delivery"

FE_REQ = {
    "enterprise_id": "tokenking",
    "organization_scope": [],
    "purpose": "decision_preparation",
    "query": "是否在本季度同时完成产品 1.0 上线和灯塔项目交付",
    "as_of": "2026-08-11T23:59:59+08:00",
    "actor_id": "agent-harness",
}


def _member_ids(members: list[dict[str, Any]]) -> set[str]:
    return {m["id"] for m in members}


def test_pack_is_agent_usable_for_fe_issue(monkeypatch):
    """Acceptance: the Pack the agent receives for the FE issue is usable."""
    monkeypatch.setenv("TKOS_API_KEY", "test-key")
    client = TestClient(create_app())
    resp = client.post("/v1/context-packs:resolve", json=FE_REQ,
                       headers={"Authorization": "Bearer test-key"})
    assert resp.status_code == 200, resp.text
    pack = resp.json()

    # 1. matched_root exact issue IRI (agent has a stable anchor).
    assert pack["matched_root"] == ISSUE, pack["matched_root"]

    # 2. Graph-attribution: every member across current/candidate/provenance
    #    has non-empty source_graphs, and every statement a source_graph — so
    #    the agent can cite provenance for anything it surfaces.
    for bucket in ("current_facts", "candidate_context", "provenance_context"):
        for m in pack[bucket]:
            assert m.get("source_graphs"), (
                f"{bucket}/{m.get('id')} has empty source_graphs")
            for s in m.get("statements", []):
                assert s.get("source_graph"), (
                    f"statement in {bucket}/{m.get('id')} missing source_graph")

    # 3. Epistemic honesty: tagged candidates carry confirmation_status and are
    #    NOT in current_facts — the agent will not treat candidates as fact.
    current_ids = _member_ids(pack["current_facts"])
    for m in pack["candidate_context"]:
        status = m.get("confirmation_status")
        if status in ("Candidate", "PreliminarilyConfirmed"):
            assert status in ("Candidate", "PreliminarilyConfirmed"), status
            assert m["id"] not in current_ids, (
                f"candidate {m['id']} leaked into current_facts")
    # At least one tagged candidate must exist (the FE issue is disputed).
    tagged = [m for m in pack["candidate_context"]
              if m.get("confirmation_status") in
              ("Candidate", "PreliminarilyConfirmed")]
    assert tagged, "no tagged candidate members — FE issue is disputed"

    # 4. context_gaps non-empty — agent knows what's unknown.
    assert pack["context_gaps"], "context_gaps empty — agent cannot show unknowns"

    # 5. reasoning_status present (not_available for P0).
    assert pack["reasoning_status"], "reasoning_status missing"
    assert pack["reasoning_status"] == "not_available", pack["reasoning_status"]

    # 6. scope_resolution.enforcement == "not_enforced" for decision_preparation;
    #    sensitive graph must not contribute.
    scope = pack["scope_resolution"]
    assert scope["enforcement"] == "not_enforced", scope
    assert "graph-sensitive-persona" not in pack["contributing_graphs"], (
        "sensitive graph leaked into contributing_graphs")

    # 7. Proof contains the confirmsEntity edge — agent can trace a candidate
    #    back to its confirmation card.
    confirms_edges = [
        {k: e[k] for k in ("from", "predicate", "to")}
        for e in pack["proof"] if e.get("predicate") == "confirmsEntity"
    ]
    assert confirms_edges, "proof has no confirmsEntity edges"
    # The specific FE-M2 confirmation card is part of the canonical contract.
    expected = {
        "from": "confirmation-mission-fe-m2-card",
        "predicate": "confirmsEntity",
        "to": "mission-fe-m2-lighthouse-context-loop",
    }
    assert expected in confirms_edges, (
        f"expected confirmsEntity edge missing; saw {confirms_edges[:3]}")

    # 8. Version metadata present — agent can record what it reasoned against.
    assert pack["ontology_release_id"] == "2.4.1", pack["ontology_release_id"]
    assert len(pack["dataset_revision"]) == 64, (
        f"dataset_revision len={len(pack['dataset_revision'])}, expected 64")
    assert pack["policy_version"], "policy_version missing"
    assert pack["query_plan_version"], "query_plan_version missing"
    assert pack["schema_version"], "schema_version missing"


def test_degraded_path_fe_issue_yields_usable_pack(monkeypatch):
    """Degraded path: the real FE issue yields current_facts==[] but a
    non-empty candidate_context + context_gaps — the agent gets a usable
    degraded Pack, not an error or empty 200."""
    monkeypatch.setenv("TKOS_API_KEY", "test-key")
    client = TestClient(create_app())
    resp = client.post("/v1/context-packs:resolve", json=FE_REQ,
                       headers={"Authorization": "Bearer test-key"})
    assert resp.status_code == 200, resp.text
    pack = resp.json()

    # Real-world state: nothing confirmed yet on this issue.
    assert pack["current_facts"] == [], (
        f"expected empty current_facts for the FE issue, got "
        f"{[m['id'] for m in pack['current_facts']]}")

    # But the agent still has something to act on.
    assert pack["candidate_context"], (
        "candidate_context empty — degraded Pack is not usable")
    assert pack["context_gaps"], (
        "context_gaps empty — degraded Pack does not surface unknowns")

    # And it is still graph-attributed (degraded does not mean unattributed).
    for m in pack["candidate_context"]:
        assert m.get("source_graphs"), (
            f"degraded candidate {m['id']} has empty source_graphs")
