# 2026-08-13 方法论、产品基础设施与 Persona 缺口蒸馏记录

## 蒸馏结论

本轮从三份飞书快照（2026-08-13 抓取）针对**当前部署的 V2.4.1 本体**重新蒸馏：

1. **TKOS Glossary 与战略议题时序图**（wiki `UjVpwuxX…`，rev 25）
2. **TKOS 企业事项与个人决策本体方案**（docx `QRSLdn85…`，rev 517；替代早期 r508 来源）
3. **1号位 Agent 产品说明**（wiki `K0mMwTRQ…`，rev 778）

候选实例写入 [2026-08-13-methodology-product-distillation.trig](../../data/instances/2026-08-13-methodology-product-distillation.trig) 的 `tkos:graph-candidate-and-dispute`。本轮不向 `tkos:graph-confirmed-enterprise` 写入任何三元组。

## 本体增量（V2.4.0 → V2.4.1）

- 新增类 `ProductModule`（产品模块）⊆ `CompanyCapability` + `ContextAsset`：构成公司产品平台的基础设施模块，可被业务域运营、被 Mission 交付、被 Context Pack 引用。
- 新增对象属性 `hasProductModule`（Domain → ProductModule），并加入查询计划 `TRAVERSAL`，使产品模块可从 Domain 经 BFS 抵达。

## 蒸馏策略：不重复、只增量

早期批次（`2026-08-12-methodology`、`-strategy`、`-business-model-fde`）已蒸馏过产品模块（`capability-*`）、Method Layer 1/2/3（`capability-sico/omd/moer-method`）、商业模式、战略问题研究 / CEO 经营会议等 Work Pattern。本轮据此采取：

- **重分类而非重建**：5 个既有 `capability-*`（CEO Agent、管理者 Agent 矩阵、Agent Ontology/权限、数字员工、TokenHub 运行底座）以附加 `a tkos:ProductModule` 类型归入新子类（原实例文件不变，附加类型写在本批次的候选图）。
- **新增未覆盖模块**：仅 Method / Engine / Foundry 三个 Glossary 基础设施模块此前无实例，本轮新建为 `ProductModule`。TokenHub 与 Ontology 已由重分类实例承载。
- **Domain → 模块运营关系**：Method 域→Method/Foundry；TokenHub 域→TokenHub 运行底座；Agents 域→CEO Agent/管理者 Agent 矩阵；FE 域→Engine/Agent Ontology（按各域既有职责推断）。

## 新增候选实例（均为 Candidate）

| 类 | 对象 | 来源 |
|---|---|---|
| `ProductModule`（新） | Method / Engine / Foundry | Glossary rev25 |
| `OperatingPrinciple`（新） | ACT 经营闭环框架、推理不替代经营判断 | Glossary / 方案 r517 |
| `CompanyPolicy`（新） | 本体内容纪律（防三种误用） | 方案 r517 |
| `WorkPattern`（新） | 一号位 Agent 专家团讨论、任务跟进、上下文更新与学习 | 产品说明 rev778 / 方案 r517 |
| `ContextGap`（新） | Agreement 落盘类缺失、Persona 本体未建模、persona_context 编译未实现、submissions/lineage 写路径未实现、DigitalLabor 类缺失 | Glossary / 方案 r517 |

> **未重建的内容**：Method Layer 1/2/3、商业模式（一主一副）、会议督导 / 战略问题研究 Work Pattern 已在早期批次覆盖，不重复造实例。一号位 Agent（No1Agent）作为产品由既有 `capability-ceo-agent`（本轮重分类为 ProductModule）承载；新增独立 Actor 实例会与它在“CEO Agent / 一号位”查询上 409 冲突，故不另建。

## 认知诚实：V3.0-only 概念记为缺口

方案与 Glossary 使用的 V3.0 词汇（`Agreement`、个人决策本体整套、persona_context 编译、写入/可追溯接口、Digital Labor）在部署的 V2.4.1 本体中**无对应类或未实现**。这些一律记为 `ContextGap`，绝不塞进不存在的类。详见上表 5 条 ContextGap。

## 机器校验

- `run_instance_conformance.py`：`real-instances-merged (10 files): conforms=True, violations=0`。
- `make test-fast`：183 项全绿（含 SHACL、context-pack、实例一致性、schema 同构、全量 runtime pytest）。
- 战略闭环首个端到端场景（产品 1.0 + 灯塔同步交付）的 `resolve`/`render` 与 `agent_harness`、`dcc_e2e` 验收保持通过，未被新候选污染。
