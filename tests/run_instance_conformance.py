"""SHACL conformance gate over real instance data and visibility into test fixtures.

This runner complements ``run_v2_3_shacl.py`` (which validates engineered
positive/negative cases). It answers two production-shaped questions:

1. *Hard gate* — when every real instance file in ``data/instances/`` is loaded
   together the way the runtime would materialise the current view, does the
   result conform to the SHACL shapes? This is the architecturally correct place
   to validate: SHACL runs in Layer 4 over the materialised Layer 2 graphs, not
   over individual source fragments. Cross-file references (an object defined in
   one batch and referenced in another) only resolve once the fragments are
   merged, so per-fragment validation produces spurious "missing field" results.

2. *Soft report* — per test-fixture violation counts are printed so that fixture
   debt (nodes that deliberately omit shape-required fields, or that quietly
   violate a shape because no test runs SHACL on them) stays visible. These are
   informational only: some fixtures are intentionally minimal (e.g. the SWRL
   acceptance fixture documents that it does not carry Mission Card completeness).
"""
from pathlib import Path

from pyshacl import validate
from rdflib import Dataset, Graph
from rdflib.namespace import SH


ROOT = Path(__file__).resolve().parents[1]
SHAPES = ROOT / "ontology" / "shapes" / "tkos-validation-shapes.jsonld"
ONTOLOGY = ROOT / "ontology" / "schema" / "tkos-ontology.jsonld"

# Fixtures whose violations are expected, with the reason. The soft report labels
# them so a reader is not misled into treating them as accidental debt.
#   by-design  — engineered negatives or deliberately minimal entailment fixtures.
#   read-side  — exercises the read-side ContextResolver filter; the write-gate
#                shapes (ConfirmedAssetShape, AttributedAssertionShape, ...) live
#                on the Layer 4 write path and are not this fixture's concern.
#   legacy     — superseded and unreferenced by any runner; retained for history.
EXPECTED_VIOLATION_FIXTURES = {
    "v2.3-swrl-acceptance-cases.trig": ("by-design", "SWRL atoms only, no Mission completeness"),
    "v2.3-role-assignment-cases.trig": ("by-design", "baseline + 5 engineered negative cases"),
    "v2.x-agreement-cases.trig": ("by-design", "6 engineered negative cases for V3.0 Agreement/FeedbackRecord/Product shapes"),
    "v2.3-context-pack-runtime.trig": ("read-side", "read-side resolver filter; write-gate shapes out of scope"),
    "v2.1-role-and-acceptance-fixtures.trig": ("legacy", "superseded by v2.3-role-assignment-cases.trig; unreferenced"),
}


def load_union(path: Path) -> Graph:
    dataset = Dataset()
    dataset.parse(path, format="trig")
    graph = Graph()
    for named in dataset.graphs():
        for triple in named:
            graph.add(triple)
    return graph


def violation_count(results_graph: Graph) -> int:
    return len(set(results_graph.subjects(SH.resultSeverity, None)))


def validate_graph(graph: Graph, ontology: Graph, shapes: Graph):
    conforms, results_graph, _ = validate(
        data_graph=graph,
        shacl_graph=shapes,
        ont_graph=ontology,
        inference="rdfs",
        advanced=True,
    )
    return conforms, violation_count(results_graph)


def main() -> None:
    ontology = Graph().parse(ONTOLOGY, format="json-ld")
    shapes = Graph().parse(SHAPES, format="json-ld")

    # --- Hard gate: all real instance files merged as the runtime would load. ---
    merged = Graph()
    instance_files = sorted((ROOT / "data" / "instances").glob("*.trig"))
    for path in instance_files:
        for triple in load_union(path):
            merged.add(triple)
    conforms, count = validate_graph(merged, ontology, shapes)
    print(f"real-instances-merged ({len(instance_files)} files): conforms={conforms}, violations={count}")
    if not conforms:
        raise SystemExit(f"FAIL: real instance data violates SHACL ({count} violations)")

    # --- Soft report: per-fixture visibility, informational only. ---
    print("\nfixture visibility (informational, not asserted):")
    for path in sorted((ROOT / "tests").glob("*.trig")):
        conforms, count = validate_graph(load_union(path), ontology, shapes)
        entry = EXPECTED_VIOLATION_FIXTURES.get(path.name)
        if entry:
            category, reason = entry
            note = f"  [{category}: {reason}]"
        elif not conforms:
            note = "  [review: possible fixture debt]"
        else:
            note = ""
        print(f"  {path.name:<46} conforms={conforms}, violations={count}{note}")


if __name__ == "__main__":
    main()
