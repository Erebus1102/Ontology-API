# ADR-0002 本体序列化的规范源与派生形式

状态：已确认

日期：2026-08-11

## 背景

同一份 TKOS 本体存在多种序列化形式：人工编辑的 JSON-LD、供推理器使用的 Turtle，以及供 Protégé 浏览的去 imports 视图。V2.4 审计发现手写维护的 `tkos-ontology-protege.ttl` 停留在 2.3.0，与规范的 2.4.0 schema 在子类公理上发散（`BusinessModel`、`KnowledgeGraphPartition` 的父类不一致）。这暴露了一个治理缺口：多份并存的人写副本必然漂移。

需要决定：哪一份是规范源（source of truth），其余如何派生与保持一致。

## 决策

1. **JSON-LD（`ontology/schema/tkos-ontology.jsonld`）为人工编辑源**。它拥有紧凑的 `@context`、`@vocab` 和多语言 label，是可读性最高、团队投入维护成本最多的形式。
2. **Turtle（`ontology/schema/tkos-ontology.ttl`）为推理器规范派生形式**，由 `scripts/export_schema_ttl.py` 从 JSON-LD 生成，**保留 `owl:imports`**，供 Openllet、Protégé 等 OWL 工具直接消费（对应 V2.3 暴露的痛点：推理器无法直接读 JSON-LD，需要人肉 RDF/XML 适配器）。
3. **Protégé 视图（`ontology/views/tkos-ontology-protege-view.ttl`）为去 imports 的浏览派生形式**，由 `scripts/export_protege_view.py` 生成。
4. **同构由 `tests/run_schema_isomorphism.py` 强制**：按图同构（`rdflib.compare.isomorphic`，对空白节点顺序不敏感）断言 JSON-LD ⇔ Turtle、JSON-LD（去 imports）⇔ Protégé 视图一致。该测试纳入 CI 必过门禁。
5. **删除手写发散的 `tkos-ontology-protege.ttl`（2.3.0）**。仓库不再保留任何手写副本序列化，只保留生成形式。

## 理由

选择 JSON-LD 而非 Turtle 作为编辑源，是因为在本项目中 JSON-LD 是**更高质量的人写形式**；若反过来以 Turtle 为源、由 rdflib 反生 JSON-LD，会丢失紧凑 `@context` 与可读排版，损害最常被阅读的产物，却换不来额外的一致性——同构守卫已经保证正确性。Turtle 承担推理器消费职责，正好消除 V2.3 暴露的 JSON-LD 不可直读问题。

因此"JSON-LD 完全派生化"这一曾列为待定的选项**不予采纳**：派生化会降低编辑源质量，且无收益。

## 结果

- 编辑本体的流程：修改 JSON-LD → `make generate` 重生成 Turtle 与 Protégé 视图 → 提交三者。CI 拒绝任何不一致。
- rdflib 对匿名空白节点（如 `owl:Restriction`）的序列化顺序不保证稳定，重生成可能产生表面 diff；此类 diff 无害，同构守卫按结构比对、对顺序不敏感。
- 未来若引入新的序列化形式（如 OWL/XM、推理器专用 RDF/XML），应一律由构建步骤生成并纳入同构守卫，不新增手写副本。
