"""Compile and verify a de-identified Context Pack runtime scenario."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rdflib import Dataset, Graph, Literal, Namespace, RDF, XSD


ROOT = Path(__file__).resolve().parents[1]
TKOS = Namespace("https://ontology.tokenking.ai/tkos#")
AS_OF = datetime(2026, 8, 11, tzinfo=timezone.utc)
ALWAYS_ALLOWED = {TKOS["graph-confirmed-enterprise"], TKOS["graph-decision-provenance"]}
TRAVERSAL = {
    TKOS.belongsTo, TKOS.expects, TKOS.contributesTo, TKOS.delivers,
    TKOS.hasRationale, TKOS.hasCriterion, TKOS.hasScope, TKOS.hasKeyPath,
    TKOS.supportedByEvidence, TKOS.isReviewedBy, TKOS.informedBy,
    TKOS.sourcedFrom, TKOS.confirmedBy, TKOS.hasReviewConclusion,
}


def parse_time(value: Literal) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


class ContextResolver:
    def __init__(self, dataset: Dataset, purpose: str, allow_sensitive_persona: bool) -> None:
        self.dataset = dataset
        self.purpose = purpose
        self.allow_sensitive_persona = allow_sensitive_persona
        self.allowed_graphs = set(ALWAYS_ALLOWED)
        if purpose == "persona_replay_authorized" and allow_sensitive_persona:
            self.allowed_graphs.add(TKOS["graph-sensitive-persona"])
        self.union = Graph()
        self.node_graphs: dict = {}
        for graph_name in self.allowed_graphs | {TKOS["graph-candidate-and-dispute"]}:
            for subject, predicate, obj in dataset.graph(graph_name):
                self.union.add((subject, predicate, obj))
                if not isinstance(subject, Literal):
                    self.node_graphs.setdefault(subject, set()).add(graph_name)

    def current_and_confirmed(self, node) -> bool:
        graphs = self.node_graphs.get(node, set())
        if not graphs or not graphs.intersection(self.allowed_graphs):
            return False
        statuses = set(self.union.objects(node, TKOS.hasConfirmationStatus))
        if statuses and TKOS.Confirmed not in statuses:
            return False
        starts = list(self.union.objects(node, TKOS.validFrom))
        ends = list(self.union.objects(node, TKOS.validUntil))
        return (not starts or all(parse_time(item) <= AS_OF for item in starts)) and (not ends or all(parse_time(item) >= AS_OF for item in ends))

    def resolve(self, mission) -> set:
        if not self.current_and_confirmed(mission):
            raise ValueError("The requested Mission is not current and confirmed in an allowed graph")
        members, pending = {mission}, [mission]
        while pending:
            subject = pending.pop()
            for predicate in TRAVERSAL:
                for obj in self.union.objects(subject, predicate):
                    if isinstance(obj, Literal) or obj in members or not self.current_and_confirmed(obj):
                        continue
                    members.add(obj)
                    pending.append(obj)
        return members


def labels(graph: Graph, members: set) -> list[str]:
    return sorted(str(next(graph.objects(item, TKOS.objectId), item)).rsplit("#", 1)[-1] for item in members)


def materialize_pack(members: set, purpose: str) -> tuple[Graph, str]:
    identifier = f"context-pack-{purpose}"
    pack = TKOS[identifier]
    source = TKOS["source-context-resolver-v2-3"]
    graph = Graph()
    graph.add((pack, RDF.type, TKOS.ContextPack))
    graph.add((pack, TKOS.objectId, Literal(identifier)))
    graph.add((pack, TKOS.displayName, Literal(f"{purpose} 上下文包")))
    graph.add((pack, TKOS.sourcedFrom, source))
    graph.add((pack, TKOS.hasConfirmationStatus, TKOS.PreliminarilyConfirmed))
    graph.add((pack, TKOS.validFrom, Literal(AS_OF.isoformat(), datatype=XSD.dateTime)))
    graph.add((pack, TKOS.usedAt, Literal(AS_OF.isoformat(), datatype=XSD.dateTime)))
    graph.add((source, RDF.type, TKOS.SourceRecord))
    graph.add((source, TKOS.objectId, Literal("source-context-resolver-v2-3")))
    graph.add((source, TKOS.externalSourceIdentifier, Literal("runtime://context-resolver/v2.3")))
    graph.add((source, TKOS.recordedAt, Literal(AS_OF.isoformat(), datatype=XSD.dateTime)))
    for member in members:
        graph.add((pack, TKOS.hasContextMember, member))
    return graph, identifier


def validate_case(dataset: Dataset, purpose: str, allow_sensitive: bool, must_include: set[str], must_exclude: set[str]) -> dict:
    resolver = ContextResolver(dataset, purpose, allow_sensitive)
    members = resolver.resolve(TKOS["mission-growth"])
    identifiers = set(labels(resolver.union, members))
    if not must_include.issubset(identifiers) or must_exclude.intersection(identifiers):
        raise AssertionError(f"Unexpected Context Pack members: {sorted(identifiers)}")
    materialized, pack_id = materialize_pack(members, purpose)
    pack = TKOS[pack_id]
    if len(set(materialized.objects(pack, TKOS.hasContextMember))) != len(members):
        raise AssertionError("Materialized ContextPack lost context members")
    return {
        "context_pack_id": pack_id,
        "purpose": purpose,
        "allow_sensitive_persona": allow_sensitive,
        "as_of": AS_OF.isoformat(),
        "members": sorted(identifiers),
        "excluded": sorted(must_exclude),
    }


def main() -> None:
    dataset = Dataset().parse(ROOT / "tests" / "v2.3-context-pack-runtime.trig", format="trig")
    base_required = {"mission-growth", "domain-growth", "domain-outcome-growth", "mission-outcome-growth", "evidence-current", "review-growth", "rationale-growth", "learning-growth", "source-review"}
    common_excluded = {"evidence-expired", "evidence-candidate"}
    ordinary = validate_case(dataset, "mission_review", False, base_required, common_excluded | {"assertion-sensitive"})
    authorized = validate_case(dataset, "persona_replay_authorized", True, base_required | {"assertion-sensitive"}, common_excluded)
    print(json.dumps({"mission_review": ordinary, "persona_replay_authorized": authorized}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
