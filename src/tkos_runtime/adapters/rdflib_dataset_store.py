# src/tkos_runtime/adapters/rdflib_dataset_store.py
from __future__ import annotations
import hashlib
from pathlib import Path, PurePosixPath
from rdflib import Dataset, Graph, URIRef, RDF
from rdflib.namespace import OWL
from tkos_runtime.domain.models import GraphStatement
from tkos_runtime.domain.policies import AdmissionPolicy

TKOS = "https://ontology.tokenking.ai/tkos#"
PARTITION_CLASS = TKOS + "KnowledgeGraphPartition"
REGISTRY = TKOS + "graph-registry"
SENSITIVE = "graph-sensitive-persona"


def _frag(u: str) -> str:
    return str(u).rsplit("#", 1)[-1]


class RdfDatasetStore:
    def __init__(self, schema_path: Path, dataset_path: Path, instance_paths: list[Path], release_root: Path | None = None):
        self._ds = Dataset()
        self._ds.parse(schema_path, format="json-ld")
        self._ds.parse(dataset_path, format="trig")
        for p in instance_paths:
            self._ds.parse(p, format="trig")
        self._policy = AdmissionPolicy()
        self.registered_partition_ids = self._read_registered()
        self.restricted_partition_ids = {SENSITIVE}
        self.restricted_node_ids = self._compute_restricted()
        self.ontology_release_id = self._version(schema_path)
        # release_root 默认上溯至仓库根（file ← datasets ← ontology ← 根，即 parents[2]）
        self._release_root = (release_root or dataset_path.resolve().parents[2])
        self.dataset_revision = self._revision(dataset_path, instance_paths)

    def _read_registered(self) -> set[str]:
        out = set()
        for s, _, _ in self._ds.graph(URIRef(REGISTRY)).triples((None, RDF.type, URIRef(PARTITION_CLASS))):
            out.add(_frag(s))
        return out

    def _compute_restricted(self) -> set[str]:
        ids = set()
        for g in self._ds.graphs():
            if _frag(g.identifier) == SENSITIVE:
                for s, _, _ in g:
                    if isinstance(s, URIRef):
                        ids.add(str(s))
        return ids

    def _version(self, schema_path: Path) -> str:
        for o in Graph().parse(schema_path, format="json-ld").objects(URIRef(TKOS), OWL.versionInfo):
            return str(o)
        return "unknown"

    def _posix_rel(self, p: Path) -> str:
        return PurePosixPath(*p.resolve().relative_to(self._release_root.resolve()).parts).as_posix()

    def _revision(self, dataset_path: Path, instance_paths: list[Path]) -> str:
        h = hashlib.sha256()
        for p in sorted([dataset_path, *instance_paths]):
            rel, data = self._posix_rel(p), p.read_bytes()
            rb, db = rel.encode(), data
            h.update(len(rb).to_bytes(8, "big")); h.update(rb)
            h.update(len(db).to_bytes(8, "big")); h.update(db)
        return h.hexdigest()

    # —— 单参 GraphPolicy 端口（应用层使用）——
    def allowed_graphs(self, purpose: str, principal_scopes: set[str] | None = None) -> list[str]:
        return self._policy.allowed_graphs(
            purpose, self.registered_partition_ids, self.restricted_partition_ids, principal_scopes)

    def _uris(self, graph_ids: list[str]) -> list[str]:
        return [TKOS + f for f in graph_ids if f in self.registered_partition_ids]

    def _ok(self, s: str, o: str) -> bool:
        return s not in self.restricted_node_ids and o not in self.restricted_node_ids

    def _stmt(self, s, p, o, g) -> GraphStatement:
        return GraphStatement(str(s), str(p), str(o), _frag(g))

    def statements_in(self, graph_ids: list[str]) -> list[GraphStatement]:
        out = []
        for guid in self._uris(graph_ids):
            g = self._ds.graph(URIRef(guid))
            for s, p, o in g:
                if self._ok(str(s), str(o)):
                    out.append(self._stmt(s, p, o, guid))
        return sorted(out, key=lambda x: (x.subject, x.predicate, x.object, x.source_graph))

    def neighbors(self, node: str, predicates: list[str], graph_ids: list[str]) -> list[tuple[str, GraphStatement]]:
        n = URIRef(node)
        out = []
        for guid in self._uris(graph_ids):
            g = self._ds.graph(URIRef(guid))
            for p in [URIRef(p0) for p0 in predicates]:
                for o in g.objects(n, p):
                    if isinstance(o, URIRef) and self._ok(node, str(o)):
                        out.append((str(o), GraphStatement(str(n), str(p), str(o), _frag(guid))))
                for s in g.subjects(p, n):
                    if isinstance(s, URIRef) and self._ok(str(s), node):
                        out.append((str(s), GraphStatement(str(s), str(p), str(n), _frag(guid))))
        seen, ded = set(), []
        for nb, st in sorted(out, key=lambda x: (x[0], x[1].predicate, x[1].object, x[1].source_graph)):
            k = (nb, st.predicate, st.object, st.source_graph)
            if k not in seen:
                seen.add(k); ded.append((nb, st))
        return ded

    def member_statements(self, subject: str, graph_ids: list[str]) -> list[GraphStatement]:
        """双向 incident（BFS/proof/关系）。"""
        n = URIRef(subject)
        out = []
        for guid in self._uris(graph_ids):
            g = self._ds.graph(URIRef(guid))
            for s, p, o in g:
                if (s == n or o == n) and self._ok(str(s), str(o)):
                    out.append(self._stmt(s, p, o, guid))
        return sorted(out, key=lambda x: (x.predicate, x.subject, x.object, x.source_graph))

    def subject_statements(self, subject: str, graph_ids: list[str]) -> list[GraphStatement]:
        """仅 subject==成员（字段/准入），避免入向污染。"""
        n = URIRef(subject)
        out = []
        for guid in self._uris(graph_ids):
            g = self._ds.graph(URIRef(guid))
            for s, p, o in g:
                if s == n and self._ok(str(s), str(o)):
                    out.append(self._stmt(s, p, o, guid))
        return sorted(out, key=lambda x: (x.predicate, x.object, x.source_graph))

    def object_value(self, subject: str, predicate: str, graph_ids: list[str]) -> str | None:
        # 端口信任边界：subject 或 object 命中 restricted_node_ids 则不返回
        if subject in self.restricted_node_ids:
            return None
        n, p = URIRef(subject), URIRef(predicate)
        values = []
        for guid in self._uris(graph_ids):
            for o in self._ds.graph(URIRef(guid)).objects(n, p):
                if self._ok(subject, str(o)):
                    values.append((guid, str(o)))  # 按 (图, 对象) 稳定排序取第一个，保证可复现
        if not values:
            return None
        values.sort(key=lambda x: (_frag(x[0]), x[1]))
        return values[0][1]
