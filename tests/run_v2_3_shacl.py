"""Run each V2.3 SHACL case as: shared baseline graph + one named case graph."""
from pathlib import Path

from pyshacl import validate
from rdflib import Dataset, Graph, Namespace
from rdflib.namespace import SH


ROOT = Path(__file__).resolve().parents[1]
TKOS = Namespace("https://ontology.tokenking.ai/tkos#")
CASES = {
    "test-positive": (True, 0),
    "test-negative-role": (False, 1),
    "test-negative-early-end": (False, 1),
    "test-negative-open-mission-finite-assignment": (False, 1),
    "test-negative-interval-start": (False, 1),
    "test-negative-interval-end": (False, 1),
}


def merged_graph(dataset: Dataset, case_name: str) -> Graph:
    graph = Graph()
    for graph_name in (TKOS["test-baseline"], TKOS[case_name]):
        for triple in dataset.graph(graph_name):
            graph.add(triple)
    return graph


def main() -> None:
    dataset = Dataset()
    dataset.parse(ROOT / "tests" / "v2.3-role-assignment-cases.trig", format="trig")
    ontology = Graph().parse(ROOT / "ontology" / "schema" / "tkos-ontology.jsonld", format="json-ld")
    shapes = Graph().parse(ROOT / "ontology" / "shapes" / "tkos-validation-shapes.jsonld", format="json-ld")

    failures = []
    for case_name, (expected_conforms, expected_results) in CASES.items():
        conforms, results_graph, _ = validate(
            data_graph=merged_graph(dataset, case_name),
            shacl_graph=shapes,
            ont_graph=ontology,
            inference="rdfs",
            advanced=True,
        )
        # Only sh:ValidationResult resources count; graph metadata is excluded.
        result_count = len(set(results_graph.subjects(SH.resultSeverity, None)))
        passed = conforms == expected_conforms and result_count == expected_results
        print(f"{case_name}: conforms={conforms}, results={result_count}, expected={expected_conforms}/{expected_results}")
        if not passed:
            failures.append(case_name)
    if failures:
        raise SystemExit("Unexpected SHACL outcome: " + ", ".join(failures))


if __name__ == "__main__":
    main()
