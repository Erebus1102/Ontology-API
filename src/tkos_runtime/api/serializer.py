# src/tkos_runtime/api/serializer.py
"""Serialize a Phase-A ``ContextPack`` to / from a JSON-safe dict.

Thin transport concern: the resolver/domain never sees this code. We rely on
``dataclasses.asdict`` to recurse through the nested dataclasses
(``ScopeResolution``, ``ContextPackMember``, ``AdmissionDecision``,
``GraphStatement``, ``Omission``). List fields of plain dicts
(``alternative_matches``, ``proof``, ``conflicts``) are recursed into by
``asdict`` as well; their values are already JSON primitives (str/int), so no
``URIRef``/``datetime`` leaks. The input pack is not mutated.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from tkos_runtime.domain.models import (
    AdmissionDecision,
    ContextPack,
    ContextPackMember,
    GraphStatement,
    Omission,
    ScopeResolution,
)


def pack_to_dict(pack: ContextPack) -> dict[str, Any]:
    """Return a JSON-serializable dict view of ``pack`` (no mutation)."""
    return dataclasses.asdict(pack)


def dict_to_pack(d: dict[str, Any]) -> ContextPack:
    """Reconstruct a ``ContextPack`` from a dict (e.g. JSON from a prior /resolve call).

    Only the fields consumed by the deterministic renderer are reconstructed;
    optional nested objects are built with safe defaults.
    """
    def _member(m: dict) -> ContextPackMember:
        stmts = [GraphStatement(**s) for s in m.get("statements", [])]
        adm = m.get("admission", {})
        return ContextPackMember(
            id=m.get("id", ""),
            display_name=m.get("display_name", ""),
            scope=m.get("scope"),
            partition=m.get("partition", ""),
            statements=stmts,
            source_graphs=m.get("source_graphs", []),
            confirmation_status=m.get("confirmation_status"),
            lifecycle=m.get("lifecycle"),
            valid_from=m.get("valid_from"),
            valid_until=m.get("valid_until"),
            sources=m.get("sources", []),
            admission=AdmissionDecision(
                accept=adm.get("accept", True),
                partition=adm.get("partition", ""),
                stage=adm.get("stage"),
                reason=adm.get("reason"),
            ),
        )

    scope = d.get("scope_resolution", {})
    omissions = [
        Omission(**o) for o in d.get("omissions", [])
        if isinstance(o, dict)
    ]

    return ContextPack(
        pack_id=d.get("pack_id", ""),
        schema_version=d.get("schema_version", ""),
        as_of=d.get("as_of", ""),
        query=d.get("query", ""),
        purpose=d.get("purpose", ""),
        matched_root=d.get("matched_root", ""),
        alternative_matches=d.get("alternative_matches", []),
        scope_resolution=ScopeResolution(
            requested_scope=scope.get("requested_scope", []),
            resolved_scope=scope.get("resolved_scope", []),
            enforcement=scope.get("enforcement", ""),
            reason=scope.get("reason", ""),
        ),
        current_facts=[_member(m) for m in d.get("current_facts", [])],
        candidate_context=[_member(m) for m in d.get("candidate_context", [])],
        provenance_context=[_member(m) for m in d.get("provenance_context", [])],
        proof=d.get("proof", []),
        derived_claims=[_member(m) for m in d.get("derived_claims", [])],
        reasoning_status=d.get("reasoning_status", "not_available"),
        context_gaps=[_member(m) for m in d.get("context_gaps", [])],
        conflicts=d.get("conflicts", []),
        omissions=omissions,
        contributing_graphs=d.get("contributing_graphs", []),
        admission_policy=d.get("admission_policy", ""),
        ontology_release_id=d.get("ontology_release_id", ""),
        dataset_revision=d.get("dataset_revision", ""),
        policy_version=d.get("policy_version", ""),
        query_plan_version=d.get("query_plan_version", ""),
    )
