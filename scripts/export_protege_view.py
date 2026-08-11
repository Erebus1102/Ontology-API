"""Create the import-free Turtle release used for human browsing in Protégé."""
from pathlib import Path

from rdflib import Graph, OWL


ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "ontology" / "schema" / "tkos-ontology.jsonld"
target = ROOT / "ontology" / "views" / "tkos-ontology-protege-view.ttl"

graph = Graph().parse(source, format="json-ld")
for subject, obj in list(graph.subject_objects(OWL.imports)):
    graph.remove((subject, OWL.imports, obj))
graph.serialize(destination=target, format="turtle")
print(f"Wrote {target.name}: {len(graph)} triples")
