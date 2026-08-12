# tests/test_runtime_retriever.py
from pathlib import Path
from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
from tkos_runtime.adapters.rdflib_graph_retriever import RdfGraphRetriever

ROOT = Path(__file__).resolve().parents[1]
SCHEMA, DATASET = ROOT/"ontology/schema/tkos-ontology.jsonld", ROOT/"ontology/datasets/tkos-runtime-dataset.trig"
MG = "https://ontology.tokenking.ai/tkos#mission-growth"

def test_mission_growth_dual_slice_and_subject_incident_split():
    s = RdfDatasetStore(SCHEMA, DATASET, [ROOT/"tests/v2.3-context-pack-runtime.trig"], release_root=ROOT)
    mg = {m.subject: m for m in RdfGraphRetriever(s).retrieve(MG,
        ["graph-confirmed-enterprise","graph-candidate-and-dispute","graph-decision-provenance"])}[MG]
    assert "graph-confirmed-enterprise" in mg.subject_by_partition
    assert "graph-candidate-and-dispute" in mg.incident_by_partition
    assert any(st.predicate.endswith("supportedByEvidence") for st in mg.incident_by_partition["graph-candidate-and-dispute"])
    assert not any(st.predicate.endswith("hasConfirmationStatus")
                   for st in mg.subject_by_partition.get("graph-candidate-and-dispute", []))
