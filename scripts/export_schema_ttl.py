"""Export the canonical Turtle form of the TKOS ontology.

The JSON-LD file is the human-edited source (compact @context, multilingual
labels). Turtle is the reasoner/tool-canonical form: Openllet, Protégé and most
OWL tooling consume it directly without the JSON-LD parsing or SWRL ordering
workarounds. This script regenerates the Turtle from the JSON-LD so the two stay
in sync; ``tests/run_schema_isomorphism.py`` guards that sync.

Unlike ``export_protege_view.py`` this keeps ``owl:imports`` — a reasoner loading
the canonical schema needs the imports closure.

Note: rdflib does not guarantee a stable ordering of anonymous blank nodes
(e.g. ``owl:Restriction`` under ``subClassOf``), so re-running this script can
produce a cosmetically different file. Such diffs are harmless —
``tests/run_schema_isomorphism.py`` checks structural equivalence, which is
order-insensitive.
"""
from pathlib import Path

from rdflib import Graph


ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "ontology" / "schema" / "tkos-ontology.jsonld"
target = ROOT / "ontology" / "schema" / "tkos-ontology.ttl"

graph = Graph().parse(source, format="json-ld")
graph.serialize(destination=target, format="turtle")
print(f"Wrote {target.name}: {len(graph)} triples")
