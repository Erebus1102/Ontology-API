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


def attach_version_block(
    d: dict[str, Any], request_id: str, pack: ContextPack
) -> dict[str, Any]:
    """Attach the unified version block (spec docs/mvp/03 §2) to a response
    dict, returning the same dict.

    Transport keys are assigned: ``api_version``, ``request_id``,
    ``ontology_release{company, persona}`` (persona fixed to None this round).
    The pack-sourced governance keys (``dataset_revision`` / ``policy_version``
    / ``query_plan_version``) use ``setdefault`` so values already present on
    resolve paths (via ``pack_to_dict``) are preserved, while the ``render()``
    dict — which lacks them — is completed to the same six-key block.

    ``d`` is expected to be a fresh dict (``asdict`` result or a ``render()``
    return value), so mutating it in place is safe.
    """
    d["api_version"] = "v1"
    d["request_id"] = request_id
    d["ontology_release"] = {"company": pack.ontology_release_id, "persona": None}
    d.setdefault("dataset_revision", pack.dataset_revision)
    d.setdefault("policy_version", pack.policy_version)
    d.setdefault("query_plan_version", pack.query_plan_version)
    return d


def dict_to_pack(d: dict[str, Any]) -> ContextPack:
    """Reconstruct a ``ContextPack`` from a dict (e.g. JSON from a prior /resolve call).

    Only the fields consumed by the deterministic renderer are reconstructed;
    optional nested objects are built with safe defaults.

    **Security hardening (P1-2):**
      * ``admission.accept`` defaults to False — client must prove provenance.
      * Governance fields (``dataset_revision``, ``ontology_release_id``) must be
        non-empty strings; a forged/minimal pack is rejected with ValueError.
      * Callers must set ``pack_origin=client_supplied`` so the renderer marks
        ``grounding_status: unverified_input``.
    """
    # ── governance field validation ──────────────────────────────────────
    missing: list[str] = []
    ds_rev = d.get("dataset_revision", "")
    ont_rel = d.get("ontology_release_id", "")
    if not ds_rev or not isinstance(ds_rev, str) or not ds_rev.strip():
        missing.append("dataset_revision")
    if not ont_rel or not isinstance(ont_rel, str) or not ont_rel.strip():
        missing.append("ontology_release_id")
    if missing:
        raise ValueError(
            f"client-supplied pack missing required governance fields: {missing}. "
            f"Resolve via /v1/context-packs:resolve first, or include valid "
            f"dataset_revision and ontology_release_id."
        )

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
                accept=adm.get("accept", False),
                partition=adm.get("partition", ""),
                stage=adm.get("stage"),
                reason=adm.get("reason"),
            ),
            rdf_types=m.get("rdf_types", []),
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
        ontology_release_id=ont_rel,
        dataset_revision=ds_rev,
        policy_version=d.get("policy_version", ""),
        query_plan_version=d.get("query_plan_version", ""),
        intent_facets=d.get("intent_facets"),
    )
