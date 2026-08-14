# src/tkos_runtime/application/context_compiler.py
from __future__ import annotations
import dataclasses
from datetime import datetime
from tkos_runtime.domain.models import (RetrievedMember, ContextPackMember, ContextPack,
    IntentAssessment, ScopeResolution, Omission, AdmissionDecision)
from tkos_runtime.domain.policies import AdmissionPolicy
from tkos_runtime.domain.query_plan import QUERY_PLAN_VERSION

TKOS = "https://ontology.tokenking.ai/tkos#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
DISPLAY, SCOPE_DESC, SOURCED = TKOS+"displayName", TKOS+"scopeDescription", TKOS+"sourcedFrom"
STATUS, LIFE, VF, VU = TKOS+"hasConfirmationStatus", TKOS+"hasStatus", TKOS+"validFrom", TKOS+"validUntil"
PROOF_PREDS = ("confirmsEntity","supportedClaim","challengesClaim","supersedes",
               "confirmedBy","supportingEvidence","challengingEvidence")


def _frag(u): return str(u).rsplit("#", 1)[-1]


class ContextCompiler:
    def __init__(self, store, policy: AdmissionPolicy):
        self._store, self._policy = store, policy

    def compile(self, members, intent: IntentAssessment, scope: ScopeResolution, metadata: dict,
                as_of: datetime, query: str, purpose: str) -> ContextPack:
        current, candidate, provenance, derived, gaps, omissions = [], [], [], [], [], []
        for m in sorted(members, key=lambda x: x.subject):
            parts = sorted(set(m.subject_by_partition) | set(m.incident_by_partition))
            # Pass 1: decide each partition (Admission-gated). rdf_types are
            # collected ONLY from each partition's OWN accepted subject slice —
            # cross-view type merging is the job of type_index, not the member
            # view (a Candidate type must not leak into the Provenance view, and
            # a type asserted only in a rejected partition must enter no view).
            decisions: dict[str, AdmissionDecision] = {}
            types_by_partition: dict[str, list[str]] = {}
            for part in parts:
                subj = m.subject_by_partition.get(part, [])
                d = self._policy.decide(part, subj, as_of)
                decisions[part] = d
                if d.accept:
                    types_by_partition[part] = sorted(
                        s.object for s in subj if s.predicate == RDF_TYPE
                    )
            # Pass 2: build views, each carrying its OWN admitted types only.
            for part in parts:
                d = decisions[part]
                if not d.accept:
                    omissions.append(Omission(_frag(m.subject), part, d.stage or "unknown", d.reason or ""))
                    continue
                subj = m.subject_by_partition.get(part, [])
                view = self._to_member(
                    m, part, m.incident_by_partition.get(part, subj), subj, d,
                    rdf_types=types_by_partition.get(part, []),
                )
                if part == "graph-confirmed-enterprise": current.append(view)
                elif part == "graph-candidate-and-dispute":
                    candidate.append(view)
                    if self._is_gap(subj): gaps.append(view)
                elif part == "graph-decision-provenance": provenance.append(view)
                elif part == "graph-derived-context": derived.append(view)
        reasoning = "materialized_available" if derived else "not_available"
        contributing = sorted({s.source_graph for b in (current, candidate, provenance, derived) for mem in b for s in mem.statements})
        return ContextPack(
            pack_id=f"context-pack-{purpose}", schema_version="context-pack/1.0-draft", as_of=as_of.isoformat(),
            query=query, purpose=purpose, matched_root=intent.root,
            alternative_matches=[{"score":s,"id":i,"name":n} for s,i,n in intent.alternatives],
            scope_resolution=scope, current_facts=current, candidate_context=candidate,
            provenance_context=provenance, proof=self._proof(provenance),
            derived_claims=derived, reasoning_status=reasoning, context_gaps=gaps, conflicts=[],
            omissions=sorted(omissions, key=lambda o:(o.partition,o.subject,o.stage)),
            contributing_graphs=contributing,
            admission_policy=f"purpose={purpose}; read-admission/p0-v1",
            ontology_release_id=metadata["ontology_release_id"], dataset_revision=metadata["dataset_revision"],
            policy_version="read-admission/p0-v1", query_plan_version=QUERY_PLAN_VERSION,
            intent_facets=(dataclasses.asdict(intent.intent_facets)
                           if intent.intent_facets else None))

    def _is_gap(self, subj_stmts) -> bool:
        # 仅认 rdf:type ContextGap（名称前缀不承担分类）
        return any(s.predicate == RDF_TYPE and s.object.endswith("#ContextGap") for s in subj_stmts)

    def _to_member(self, m, part, incident, subj, decision, rdf_types) -> ContextPackMember:
        def val(pred):
            return next((s.object for s in subj if s.predicate == pred), None)
        scope_v = val(SCOPE_DESC)
        return ContextPackMember(
            id=_frag(m.subject),
            display_name=(val(DISPLAY) or _frag(m.subject)),
            scope=(scope_v if scope_v else None),
            partition=part,
            statements=sorted(incident, key=lambda x:(x.predicate, x.subject, x.object, x.source_graph)),
            source_graphs=sorted({s.source_graph for s in incident}),
            confirmation_status=(_frag(val(STATUS)) if val(STATUS) else None),
            lifecycle=(_frag(val(LIFE)) if val(LIFE) else None),
            valid_from=val(VF), valid_until=val(VU),
            sources=sorted({_frag(s.object) for s in subj if s.predicate == SOURCED}),
            admission=decision,
            rdf_types=rdf_types)

    def _proof(self, provenance) -> list[dict]:
        # 用真实 subject/object，避免 m.id 篡改方向；按四元组去重排序
        edges = {}
        for mem in provenance:
            for s in mem.statements:
                if any(s.predicate.endswith(p) for p in PROOF_PREDS):
                    key = (s.subject, s.predicate, s.object, s.source_graph)
                    edges.setdefault(key, {"from": _frag(s.subject), "predicate": _frag(s.predicate),
                                            "to": _frag(s.object), "source_graph": s.source_graph})
        return [edges[k] for k in sorted(edges)]
