"""Validate the V2.3 acceptance rule through Openllet's RDF/XML SWRL adapter.

Openllet's CLI does not accept JSON-LD, and its RDF/XML reader is order-sensitive
for swrl:head/body. This runner emits canonical RDF/XML (head before body), then
checks the four business-rule cases by entailment.
"""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

from rdflib import Dataset, Graph, Namespace, RDF
from rdflib.collection import Collection

ROOT = Path(__file__).resolve().parents[1]
TKOS = Namespace("https://ontology.tokenking.ai/tkos#")
CASES = {
    "swrl-complete": True,
    "swrl-missing-evidence": False,
    "swrl-missing-review": False,
    "swrl-missing-confirmation": False,
}

RULE = """
  <swrl:Variable rdf:about="#varMission"/><swrl:Variable rdf:about="#varEvidence"/><swrl:Variable rdf:about="#varReview"/><swrl:Variable rdf:about="#varConclusion"/><swrl:Variable rdf:about="#varConfirmation"/>
  <swrl:Imp rdf:about="#Rule_MissionReadyForAcceptance">
    <swrl:head rdf:parseType="Collection"><swrl:ClassAtom><swrl:classPredicate rdf:resource="#MissionReadyForAcceptance"/><swrl:argument1 rdf:resource="#varMission"/></swrl:ClassAtom></swrl:head>
    <swrl:body rdf:parseType="Collection">
      <swrl:ClassAtom><swrl:classPredicate rdf:resource="#Mission"/><swrl:argument1 rdf:resource="#varMission"/></swrl:ClassAtom>
      <swrl:IndividualPropertyAtom><swrl:propertyPredicate rdf:resource="#supportedByEvidence"/><swrl:argument1 rdf:resource="#varMission"/><swrl:argument2 rdf:resource="#varEvidence"/></swrl:IndividualPropertyAtom>
      <swrl:ClassAtom><swrl:classPredicate rdf:resource="#Evidence"/><swrl:argument1 rdf:resource="#varEvidence"/></swrl:ClassAtom>
      <swrl:IndividualPropertyAtom><swrl:propertyPredicate rdf:resource="#isReviewedBy"/><swrl:argument1 rdf:resource="#varMission"/><swrl:argument2 rdf:resource="#varReview"/></swrl:IndividualPropertyAtom>
      <swrl:IndividualPropertyAtom><swrl:propertyPredicate rdf:resource="#hasReviewConclusion"/><swrl:argument1 rdf:resource="#varReview"/><swrl:argument2 rdf:resource="#varConclusion"/></swrl:IndividualPropertyAtom>
      <swrl:ClassAtom><swrl:classPredicate rdf:resource="#ReviewConclusion"/><swrl:argument1 rdf:resource="#varConclusion"/></swrl:ClassAtom>
      <swrl:IndividualPropertyAtom><swrl:propertyPredicate rdf:resource="#confirmedBy"/><swrl:argument1 rdf:resource="#varMission"/><swrl:argument2 rdf:resource="#varConfirmation"/></swrl:IndividualPropertyAtom>
      <swrl:ClassAtom><swrl:classPredicate rdf:resource="#ConfirmationEvent"/><swrl:argument1 rdf:resource="#varConfirmation"/></swrl:ClassAtom>
    </swrl:body>
  </swrl:Imp>
"""


def data_document(evidence: bool, review: bool, confirmation: bool) -> str:
    mission_properties = ""
    individuals = ""
    if evidence:
        mission_properties += '<supportedByEvidence rdf:resource="#evidence"/>'
        individuals += '<owl:NamedIndividual rdf:about="#evidence"><rdf:type rdf:resource="#Evidence"/></owl:NamedIndividual>'
    if review:
        mission_properties += '<isReviewedBy rdf:resource="#review"/>'
        individuals += '<owl:NamedIndividual rdf:about="#review"><rdf:type rdf:resource="#MissionReview"/><hasReviewConclusion rdf:resource="#continue"/></owl:NamedIndividual><owl:NamedIndividual rdf:about="#continue"><rdf:type rdf:resource="#ReviewConclusion"/></owl:NamedIndividual>'
    if confirmation:
        mission_properties += '<confirmedBy rdf:resource="#confirmation"/>'
        individuals += '<owl:NamedIndividual rdf:about="#confirmation"><rdf:type rdf:resource="#ConfirmationEvent"/></owl:NamedIndividual>'
    return f'''<?xml version="1.0"?>
<rdf:RDF xmlns="https://ontology.tokenking.ai/tkos#" xml:base="https://ontology.tokenking.ai/tkos#" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:owl="http://www.w3.org/2002/07/owl#" xmlns:swrl="http://www.w3.org/2003/11/swrl#">
  <owl:Ontology rdf:about=""/>
  <owl:Class rdf:about="#Mission"/><owl:Class rdf:about="#Evidence"/><owl:Class rdf:about="#MissionReview"/><owl:Class rdf:about="#ReviewConclusion"/><owl:Class rdf:about="#ConfirmationEvent"/><owl:Class rdf:about="#MissionReadyForAcceptance"/>
  <owl:ObjectProperty rdf:about="#supportedByEvidence"/><owl:ObjectProperty rdf:about="#isReviewedBy"/><owl:ObjectProperty rdf:about="#hasReviewConclusion"/><owl:ObjectProperty rdf:about="#confirmedBy"/>
{RULE}
  <owl:NamedIndividual rdf:about="#mission"><rdf:type rdf:resource="#Mission"/>{mission_properties}</owl:NamedIndividual>{individuals}
</rdf:RDF>'''


def expected_document() -> str:
    return '''<?xml version="1.0"?>
<rdf:RDF xmlns="https://ontology.tokenking.ai/tkos#" xml:base="https://ontology.tokenking.ai/tkos#" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Class rdf:about="#MissionReadyForAcceptance"/>
  <owl:NamedIndividual rdf:about="#mission"><rdf:type rdf:resource="#MissionReadyForAcceptance"/></owl:NamedIndividual>
</rdf:RDF>'''


def case_conditions(dataset: Dataset, case_name: str) -> tuple[bool, bool, bool]:
    graph = dataset.graph(TKOS[case_name])
    mission = next(graph.subjects(RDF.type, TKOS.Mission), None)
    if mission is None:
        raise ValueError(f"{case_name} does not declare a Mission")
    evidence = any((item, RDF.type, TKOS.Evidence) in graph for item in graph.objects(mission, TKOS.supportedByEvidence))
    # Continue is typed as ReviewConclusion by the V2.3 ontology enum; the case
    # fixture deliberately carries only the business assertion itself.
    review = any(
        True
        for item in graph.objects(mission, TKOS.isReviewedBy)
        for _ in graph.objects(item, TKOS.hasReviewConclusion)
    )
    confirmation = any((item, RDF.type, TKOS.ConfirmationEvent) in graph for item in graph.objects(mission, TKOS.confirmedBy))
    return evidence, review, confirmation


def assert_source_rule(ontology: Graph) -> None:
    swrl = Namespace("http://www.w3.org/2003/11/swrl#")
    rule = TKOS.Rule_MissionReadyForAcceptance
    body_node = next(ontology.objects(rule, swrl.body), None)
    head_node = next(ontology.objects(rule, swrl.head), None)
    if body_node is None or head_node is None:
        raise ValueError("V2.3 source rule lacks swrl:body or swrl:head")
    body = list(Collection(ontology, body_node))
    head = list(Collection(ontology, head_node))
    if len(body) != 8 or len(head) != 1:
        raise ValueError(f"Unexpected acceptance rule shape: body={len(body)}, head={len(head)}")
    if (head[0], swrl.classPredicate, TKOS.MissionReadyForAcceptance) not in ontology:
        raise ValueError("Acceptance rule head no longer derives MissionReadyForAcceptance")


def entails(openllet: Path, data_file: Path, expected_file: Path) -> bool:
    result = subprocess.run(
        [str(openllet), "entail", "--all", "-e", expected_file.as_uri(), data_file.as_uri()],
        text=True, capture_output=True, check=False, cwd=openllet.parent,
    )
    output = result.stdout + result.stderr
    if "All axioms are entailed." in output:
        return True
    if "Not entailed:" in output or "Non-entailments" in output:
        return False
    raise RuntimeError(f"Openllet returned an unrecognised result:\n{output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openllet", type=Path, default=ROOT / "openllet" / "openllet.sh")
    args = parser.parse_args()
    openllet = args.openllet.resolve()
    if not openllet.is_file():
        raise SystemExit(f"Openllet CLI not found: {openllet}")
    ontology = Graph().parse(ROOT / "ontology" / "schema" / "tkos-ontology.jsonld", format="json-ld")
    assert_source_rule(ontology)
    dataset = Dataset().parse(ROOT / "tests" / "v2.3-swrl-acceptance-cases.trig", format="trig")
    failures = []
    with tempfile.TemporaryDirectory(prefix="tkos-swrl-") as temporary:
        directory = Path(temporary)
        expected_file = directory / "expected.rdf"
        expected_file.write_text(expected_document(), encoding="utf-8")
        for name, expected in CASES.items():
            evidence, review, confirmation = case_conditions(dataset, name)
            data_file = directory / f"{name}.rdf"
            data_file.write_text(data_document(evidence, review, confirmation), encoding="utf-8")
            actual = entails(openllet, data_file, expected_file)
            print(f"{name}: entailed={actual}, expected={expected}")
            if actual != expected:
                failures.append(name)
    if failures:
        raise SystemExit("Unexpected SWRL entailment: " + ", ".join(failures))


if __name__ == "__main__":
    main()
