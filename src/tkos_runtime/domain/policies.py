# src/tkos_runtime/domain/policies.py
from __future__ import annotations
from datetime import datetime
from tkos_runtime.domain.models import GraphStatement, AdmissionDecision

_DEFAULT_PURPOSE_ALLOWED = {
    "decision_preparation": ["graph-confirmed-enterprise","graph-decision-provenance","graph-candidate-and-dispute","graph-derived-context"],
    "mission_review": ["graph-confirmed-enterprise","graph-decision-provenance","graph-derived-context"],
}


class AdmissionPolicy:
    """纯策略。Store 以 registered/restricted 调用；不直接作应用层端口。"""
    def __init__(self, purpose_allowed: dict[str, list[str]] | None = None):
        self.purpose_allowed = purpose_allowed or _DEFAULT_PURPOSE_ALLOWED

    def allowed_graphs(self, purpose: str, registered: set[str], restricted: set[str],
                       principal_scopes: set[str] | None = None) -> list[str]:
        if purpose not in self.purpose_allowed:
            raise ValueError(f"unknown purpose: {purpose!r}")
        base = [g for g in self.purpose_allowed[purpose] if g in registered and g not in restricted]
        # C3: Principal.allowed_scopes narrows visible graphs. None = unlimited
        # (cxo / single-key backward-compat); an empty set = fully blocked
        # (cross-tenant → intent finds nothing → 404, no existence leak).
        if principal_scopes is not None:
            base = [g for g in base if g in principal_scopes]
        return sorted(base)

    def decide(self, partition: str, subject_statements: list[GraphStatement], as_of: datetime) -> AdmissionDecision:
        if partition in ("graph-decision-provenance", "graph-derived-context"):
            return AdmissionDecision(True, partition)
        if partition == "graph-confirmed-enterprise":
            return self._confirmed(partition, subject_statements, as_of)
        if partition == "graph-candidate-and-dispute":
            return self._candidate(partition, subject_statements, as_of)
        return AdmissionDecision(False, partition, "graph_policy", "partition_not_allowed")

    def _status(self, stmts):
        for s in stmts:
            if s.predicate.endswith("hasConfirmationStatus"):
                return s.object.rsplit("#", 1)[-1]
        return None

    def _valid(self, partition, stmts, as_of):
        vf = [s.object for s in stmts if s.predicate.endswith("validFrom")]
        vu = [s.object for s in stmts if s.predicate.endswith("validUntil")]
        if vf and any(_parse(t) > as_of for t in vf):
            return AdmissionDecision(False, partition, "valid_time", "not_yet_valid")
        if vu and all(_parse(t) < as_of for t in vu):
            return AdmissionDecision(False, partition, "valid_time", "expired")
        return None

    def _confirmed(self, partition, stmts, as_of):
        st = self._status(stmts)
        if st != "Confirmed":
            return AdmissionDecision(False, partition, "confirmation", f"status={st}")
        return self._valid(partition, stmts, as_of) or AdmissionDecision(True, partition)

    def _candidate(self, partition, stmts, as_of):
        st = self._status(stmts)
        if st == "Archived":
            return AdmissionDecision(False, partition, "confirmation", "archived")
        if st is None:
            st = "CandidateByPartition"
        if st not in {"Candidate", "PreliminarilyConfirmed", "CandidateByPartition"}:
            return AdmissionDecision(False, partition, "confirmation", f"status={st}")
        return self._valid(partition, stmts, as_of) or AdmissionDecision(True, partition)


def _parse(t: str) -> datetime:
    return datetime.fromisoformat(t.replace("Z", "+00:00"))
