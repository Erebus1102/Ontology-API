"""SHACL 正负向用例：V3.0 Agreement/FeedbackRecord/Product Shape。"""
from pathlib import Path
from rdflib import Graph, Dataset, Namespace
from rdflib.namespace import SH
from pyshacl import validate

ROOT = Path(__file__).resolve().parents[1]
TKOS = Namespace("https://ontology.tokenking.ai/tkos#")
SHAPES = ROOT / "ontology/shapes/tkos-validation-shapes.jsonld"
ONTOLOGY = ROOT / "ontology/schema/tkos-ontology.jsonld"
CASES = {
    "agr-positive": (True, 0),
    "agr-negative-no-status": (False, 1),
    "agr-negative-score-out-of-range": (False, 1),
    "agr-negative-feedback-no-score": (False, 1),
    "agr-negative-product-dup-id": (False, 1),
    "agr-negative-two-go-on-same-issue": (False, 2),
}

def merged(dataset: Dataset, case_name: str) -> Graph:
    g = Graph()
    for gn in (TKOS["test-baseline"], TKOS[case_name]):
        for t in dataset.graph(gn):
            g.add(t)
    return g

def main() -> None:
    shapes = Graph().parse(SHAPES, format="json-ld")
    ontology = Graph().parse(ONTOLOGY, format="json-ld")
    dataset = Dataset().parse(ROOT / "tests/v2.x-agreement-cases.trig", format="trig")
    failures = []
    for case_name, (exp_conforms, exp_count) in CASES.items():
        conforms, results_graph, _ = validate(
            data_graph=merged(dataset, case_name), shacl_graph=shapes, ont_graph=ontology,
            inference="rdfs", advanced=True)
        count = len(set(results_graph.subjects(SH.resultSeverity, None)))
        ok = conforms == exp_conforms and count == exp_count
        print(f"{case_name}: conforms={conforms}, results={count}, expected={exp_conforms}/{exp_count}")
        if not ok:
            failures.append(case_name)
    if failures:
        raise SystemExit("Unexpected SHACL outcome: " + ", ".join(failures))
    print("v2.x-agreement: all cases pass")

if __name__ == "__main__":
    main()
