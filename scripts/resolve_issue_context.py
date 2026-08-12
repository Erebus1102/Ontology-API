"""Resolve a decision-preparation Context Pack from the current TKOS dataset.

This is a local, read-only service prototype.  It deliberately keeps candidate
material visible for decision preparation, while preserving every member's
confirmation status and provenance.  An application must never present a
Candidate member as a confirmed enterprise fact.
"""
from __future__ import annotations

import argparse
import json
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from rdflib import Dataset, Graph, Literal, Namespace, RDF, URIRef

from tkos_runtime.domain.query_plan import TRAVERSAL


ROOT = Path(__file__).resolve().parents[1]
TKOS = Namespace("https://ontology.tokenking.ai/tkos#")


def fragment(value: URIRef) -> str:
    return str(value).rsplit("#", 1)[-1]


def load_union() -> Graph:
    dataset = Dataset()
    dataset.parse(ROOT / "ontology" / "schema" / "tkos-ontology.jsonld", format="json-ld")
    for path in sorted((ROOT / "data" / "instances").glob("*.trig")):
        dataset.parse(path, format="trig")
    union = Graph()
    for graph in dataset.graphs():
        for triple in graph:
            union.add(triple)
    return union


def text(graph: Graph, node: URIRef) -> str:
    fields = [TKOS.displayName, TKOS.scopeDescription, TKOS.objectId]
    return " ".join(str(value) for field in fields for value in graph.objects(node, field)).lower()


def score(query: str, haystack: str) -> int:
    query = query.lower().strip()
    if query in haystack:
        return 100 + len(query)
    # Chinese inputs often have no whitespace.  Two-character overlap makes
    # matching transparent while avoiding an opaque embedding dependency.
    grams = {query[i:i + 2] for i in range(len(query) - 1)}
    return sum(1 for gram in grams if gram in haystack)


def matching_seeds(graph: Graph, query: str) -> list[tuple[int, URIRef]]:
    candidates = {
        subject for subject in graph.subjects(TKOS.displayName, None)
        if isinstance(subject, URIRef)
    }
    ranked = [(score(query, text(graph, node)), node) for node in candidates]
    return sorted((item for item in ranked if item[0] > 0), key=lambda item: (-item[0], str(item[1])))[:5]


def is_expired(graph: Graph, node: URIRef, as_of: datetime) -> bool:
    if TKOS.Archived in set(graph.objects(node, TKOS.hasConfirmationStatus)):
        return True
    values = list(graph.objects(node, TKOS.validUntil))
    if not values:
        return False
    return all(datetime.fromisoformat(str(value).replace("Z", "+00:00")) < as_of for value in values)


def expand(graph: Graph, seeds: list[URIRef], as_of: datetime, depth: int = 2) -> set[URIRef]:
    members: set[URIRef] = set(seeds)
    queue = deque((node, 0) for node in seeds)
    while queue:
        node, current_depth = queue.popleft()
        if current_depth >= depth:
            continue
        neighbours: set[URIRef] = set()
        for predicate in TRAVERSAL:
            neighbours.update(item for item in graph.objects(node, predicate) if isinstance(item, URIRef))
            neighbours.update(item for item in graph.subjects(predicate, node) if isinstance(item, URIRef))
        for item in neighbours:
            if item not in members and not is_expired(graph, item, as_of):
                members.add(item)
                queue.append((item, current_depth + 1))
    return members


def name(graph: Graph, node: URIRef) -> str:
    return str(next(graph.objects(node, TKOS.displayName), fragment(node)))


def state(graph: Graph, node: URIRef) -> dict[str, Any]:
    return {
        "confirmation": [fragment(value) for value in graph.objects(node, TKOS.hasConfirmationStatus)],
        "lifecycle": [fragment(value) for value in graph.objects(node, TKOS.hasStatus)],
        "sources": [name(graph, value) for value in graph.objects(node, TKOS.sourcedFrom)],
    }


def node_record(graph: Graph, node: URIRef) -> dict[str, Any]:
    return {
        "id": str(next(graph.objects(node, TKOS.objectId), fragment(node))),
        "name": name(graph, node),
        "types": sorted(fragment(value) for value in graph.objects(node, RDF.type) if str(value).startswith(str(TKOS))),
        "scope": str(next(graph.objects(node, TKOS.scopeDescription), "")),
        **state(graph, node),
    }


def rule_results(graph: Graph, members: set[URIRef]) -> dict[str, Any]:
    missions = [node for node in members if (node, RDF.type, TKOS.Mission) in graph]
    review_required = []
    acceptance_pending = []
    for mission in missions:
        risks = list(graph.objects(mission, TKOS.hasRisk))
        high_risks = [risk for risk in risks if (risk, RDF.type, TKOS.HighRisk) in graph]
        if high_risks:
            review_required.append({"mission": name(graph, mission), "high_risks": [name(graph, risk) for risk in high_risks]})
        has_evidence = any(graph.objects(mission, TKOS.supportedByEvidence))
        has_review = any(graph.objects(mission, TKOS.isReviewedBy))
        has_confirmation = any(graph.objects(mission, TKOS.confirmedBy))
        if not (has_evidence and has_review and has_confirmation):
            acceptance_pending.append({
                "mission": name(graph, mission),
                "missing": [label for label, present in (("Evidence", has_evidence), ("MissionReview", has_review), ("Confirmation", has_confirmation)) if not present],
            })
    return {
        "high_risk_review_rule": review_required,
        "mission_acceptance": {
            "ready": [],
            "pending": acceptance_pending,
            "rule": "Mission 同时具备 Evidence、MissionReview 和 Confirmation 后，才可推导为 MissionReadyForAcceptance。",
        },
    }


def compact(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Produce the small, prompt-ready view while retaining raw members."""
    groups = {
        "missions": {"Mission"},
        "outcomes": {"Outcome", "CompanyOutcome", "DomainOutcome", "MissionOutcome"},
        "candidate_decisions": {"StrategicDecision", "StrategicChoice", "Decision"},
        "issues": {"StrategicIssue"},
        "risks": {"Risk", "HighRisk"},
        "context_gaps": {"ContextGap"},
        "evidence_and_challenges": {"Evidence", "EvidenceChallenge", "EvidenceSupport"},
        "research": {"StrategicResearch"},
        "sources": {"SourceRecord"},
    }
    return {
        group: [record for record in records if set(record["types"]).intersection(types)]
        for group, types in groups.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True, help="议题或关键词")
    parser.add_argument("--purpose", default="decision_preparation")
    parser.add_argument("--as-of", default="2026-08-11T23:59:59+08:00")
    args = parser.parse_args()
    as_of = datetime.fromisoformat(args.as_of)
    graph = load_union()
    ranked = matching_seeds(graph, args.query)
    if not ranked:
        raise SystemExit("未匹配到对象。请换用议题名称、Outcome、Mission 或关键词。")
    # One exact or highest-ranked item is the sole traversal root.  Nearby
    # matches remain visible as suggestions but must not silently broaden the
    # decision context.
    seeds = [ranked[0][1]]
    members = expand(graph, seeds, as_of)
    records = [node_record(graph, node) for node in members]
    records.sort(key=lambda item: (item["confirmation"] != ["Confirmed"], item["types"], item["name"]))
    output = {
        "context_pack": {
            "id": "context-pack-decision-preparation-2026-08-11-demo",
            "purpose": args.purpose,
            "as_of": args.as_of,
            "query": args.query,
            "admission_policy": "决策准备可读取当前有效的初步确认与候选材料；每个成员保留确认状态，Candidate 只能作为待核验上下文。",
        },
        "matching": [{"score": score_value, "id": fragment(node), "name": name(graph, node)} for score_value, node in ranked],
        "reasoning": rule_results(graph, members),
        "prompt_context": compact(records),
        "members": records,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
