# TKOS 上下文图谱 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从 Doc/ 下 6 份 TKOS 设计文档提取业务逻辑，构建一个文件化、可被 Agent 直接读取的结构化知识图谱（schema + 实例 + 索引 + 原理指南 + 校验器）。

**Architecture:** 四层文件本体——`schema.yaml`（规则层）+ `graph/{company,domain,task}/`（实例层，按业务层级划分）+ `graph/index.json`（遍历层，脚本生成）+ `guides/`（原理模板层）。一个 Python 校验器（stdlib unittest + pyyaml）以 TDD 方式保证实例符合 schema 的基数/引用/类型约束。Mission 归 domain 层；task（Mission 之下细粒度执行层）本次不做。

**Tech Stack:** Python 3.9（stdlib `unittest`）、PyYAML 6.0.3（已安装）、JSON。无数据库、无外部服务。

## Global Constraints

- 项目根：`/Users/renhaoliu/Desktop/Ontology`（当前非 git 仓库，Task 1 执行 `git init`）。
- 内容用中文；schema 键名/类型名/枚举值用英文。
- 每个实例必须含 `id`（`<type_prefix>:<slug>`，全小写连字符）、`type`、`source`（出处溯源，指向 `Doc/<file>.pdf §<章节>`）。
- Mission 文件名沿用文档编号（如 `03-3.yaml`）。
- `OntologyCapability` 的 `id_prefix` 为 `eo`（精简自 spec 的 `e&o`，避免 `&` 在 id/文件名中的歧义）；实例 id 形如 `eo:eo1`、`eo:eo2`、`eo:eo3`。
- 资产层（decisions/evidence/artifacts/risks/lessons）只放少量示范实例 + 目标型 Evidence（`status: target`），其余留空槽；不得编造运行态内容。
- 实例层 = 8 月基线"按设计应然"状态，非已完成工作记录。
- 任务方法 M3 在文档中存在 `MOER`/`MEAR` 命名漂移；本图谱统一用 `MOER`（Mission→Orchestration→Execution→Result），在 `method:m3-moer` 的 `aliases` 字段记录 `MEAR`。
- 提交规范：每个 Task 末尾 `git add` + `git commit`，commit message 中文描述。

---

## 文件结构总览

```
/Users/renhaoliu/Desktop/Ontology/
├── .gitignore
├── ontology/
│   ├── README.md
│   ├── schema.yaml
│   ├── graph/
│   │   ├── company/
│   │   │   ├── intent/strategic-intent.yaml
│   │   │   ├── outcomes/company-2026-08.yaml
│   │   │   ├── signals/(按需，少量)
│   │   │   ├── issues/(按需，少量)
│   │   │   ├── people/liu-minghua.yaml
│   │   │   └── system/
│   │   │       ├── components/{method,agents,engine-ontology}.yaml
│   │   │       ├── methods/{m1-sico,m2-omd,m3-moer}.yaml
│   │   │       ├── agents/{a1-ceo,a2-manager,a3-coagent,a4-digital-worker}.yaml
│   │   │       ├── ontology/{eo1,eo2,eo3}.yaml
│   │   │       ├── transformation/{t1,t2,t3}.yaml
│   │   │       └── infrastructure/tokenhub.yaml
│   │   ├── domain/
│   │   │   ├── domains/{01..08}-*.yaml
│   │   │   ├── outcomes/<domain>-2026-08.yaml (8 个)
│   │   │   ├── people/{tiantian,sunmingze,renhao,zhuoran,mengyi,jujie}.yaml
│   │   │   ├── missions/<NN-M>.yaml (37 个)
│   │   │   ├── assets/{decisions,evidence,artifacts,risks,lessons}/*.yaml (示范)
│   │   │   ├── work-patterns/*.yaml (6 个)
│   │   │   └── dependencies/cross-domain.yaml
│   │   ├── task/README.md
│   │   └── index.json
│   └── guides/{01..07}-*.md
├── tools/
│   ├── __init__.py
│   ├── validate.py
│   ├── build_index.py
│   └── tests/
│       ├── __init__.py
│       └── test_validate.py
└── docs/superpowers/{specs,plans}/...
```

---

## Task 1: 项目脚手架 + git 初始化

**Files:**
- Create: `.gitignore`
- Create: 目录树（空目录用 `.gitkeep` 占位）
- Create: `tools/__init__.py`、`tools/tests/__init__.py`（空文件）

**Interfaces:**
- Produces: 可用的空目录结构，供后续 Task 写入；`tools/` 作为 Python 包可被 import。

- [ ] **Step 1: 初始化 git 与目录**

```bash
cd /Users/renhaoliu/Desktop/Ontology
git init
mkdir -p ontology/graph/company/{intent,outcomes,signals,issues,people,system/{components,methods,agents,ontology,transformation,infrastructure}}
mkdir -p ontology/graph/domain/{domains,outcomes,people,missions,assets/{decisions,evidence,artifacts,risks,lessons},work-patterns,dependencies}
mkdir -p ontology/graph/task ontology/guides
mkdir -p tools/tests
# 占位，保证空目录可被 git 跟踪
touch ontology/graph/task/.gitkeep
touch tools/__init__.py tools/tests/__init__.py
```

- [ ] **Step 2: 写 `.gitignore`**

```gitignore
.DS_Store
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 3: 配置 git user（若未配置）并提交**

```bash
cd /Users/renhaoliu/Desktop/Ontology
git config user.email "dev@tokenking.local" 2>/dev/null; git config user.name "TKOS Dev" 2>/dev/null
git add -A
git commit -m "chore: 初始化 TKOS 上下文图谱项目脚手架"
```

Expected: 首个 commit 成功。

---

## Task 2: 图谱校验器（TDD）

**Files:**
- Create: `tools/validate.py`
- Test: `tools/tests/test_validate.py`

**Interfaces:**
- Consumes: `ontology/schema.yaml`（Task 3 产出）、`ontology/graph/**/*.yaml`
- Produces: 可 import 的函数 `load_schema(path)`、`load_graph(graph_dir) -> {id: {data, file}}`、`validate(schema, graph) -> list[Violation]`；CLI `python3 tools/validate.py [schema] [graph_dir]`，有 error 级违规时退出码 1。
- 约定：关系字段值可为单字符串或字符串列表，校验时统一成列表计数；id 前缀（`<prefix>:`）必须等于该类型 schema 的 `id_prefix`；`has_dri.target: Person` 自动强制"DRI 必须是人"。

- [ ] **Step 1: 写失败测试 `tools/tests/test_validate.py`**

```python
import unittest
from tools.validate import validate

SCHEMA = {
    "entity_types": {
        "Mission": {
            "id_prefix": "mission",
            "attributes": {
                "name": {"type": "string", "required": True},
                "status": {"type": "enum", "values": ["planned", "done"], "required": True},
            },
            "relations": {
                "supports": {"target": "Outcome", "cardinality": [1, "*"]},
                "has_dri": {"target": "Person", "cardinality": [1, 1]},
            },
        },
        "Outcome": {"id_prefix": "outcome"},
        "Person": {"id_prefix": "person"},
    }
}

def _graph(*entities):
    return {e["id"]: {"data": e, "file": "x"} for e in entities}

class TestValidate(unittest.TestCase):
    def test_valid_mission_passes(self):
        g = _graph(
            {"id": "mission:1", "type": "Mission", "name": "x", "status": "planned",
             "supports": ["outcome:o"], "has_dri": "person:p"},
            {"id": "outcome:o", "type": "Outcome"},
            {"id": "person:p", "type": "Person"},
        )
        self.assertEqual(validate(SCHEMA, g), [])

    def test_missing_required_attr_fails(self):
        g = _graph(
            {"id": "mission:1", "type": "Mission", "status": "planned",
             "supports": ["outcome:o"], "has_dri": "person:p"},
            {"id": "outcome:o", "type": "Outcome"}, {"id": "person:p", "type": "Person"})
        self.assertTrue(any(v.field == "name" for v in validate(SCHEMA, g)))

    def test_bad_enum_fails(self):
        g = _graph(
            {"id": "mission:1", "type": "Mission", "name": "x", "status": "weird",
             "supports": ["outcome:o"], "has_dri": "person:p"},
            {"id": "outcome:o", "type": "Outcome"}, {"id": "person:p", "type": "Person"})
        self.assertTrue(any(v.field == "status" for v in validate(SCHEMA, g)))

    def test_supports_cardinality_zero_fails(self):
        g = _graph(
            {"id": "mission:1", "type": "Mission", "name": "x", "status": "planned",
             "supports": [], "has_dri": "person:p"},
            {"id": "person:p", "type": "Person"})
        self.assertTrue(any(v.field == "supports" for v in validate(SCHEMA, g)))

    def test_has_dri_must_be_exactly_one(self):
        g = _graph(
            {"id": "mission:1", "type": "Mission", "name": "x", "status": "planned",
             "supports": ["outcome:o"], "has_dri": ["person:p1", "person:p2"]},
            {"id": "outcome:o", "type": "Outcome"},
            {"id": "person:p1", "type": "Person"}, {"id": "person:p2", "type": "Person"})
        self.assertTrue(any(v.field == "has_dri" for v in validate(SCHEMA, g)))

    def test_dri_must_be_person_not_agent(self):
        g = _graph(
            {"id": "mission:1", "type": "Mission", "name": "x", "status": "planned",
             "supports": ["outcome:o"], "has_dri": "agent:a"},
            {"id": "outcome:o", "type": "Outcome"}, {"id": "agent:a", "type": "Agent"})
        v = validate(SCHEMA, g)
        self.assertTrue(any("mismatch" in msg or "type" in msg for msg in [x.message for x in v]))

    def test_dangling_reference_fails(self):
        g = _graph(
            {"id": "mission:1", "type": "Mission", "name": "x", "status": "planned",
             "supports": ["outcome:missing"], "has_dri": "person:p"},
            {"id": "person:p", "type": "Person"})
        self.assertTrue(any("dangling" in x.message for x in validate(SCHEMA, g)))

    def test_bad_id_prefix_fails(self):
        g = _graph(
            {"id": "mission:1", "type": "Outcome"},  # id 前缀与 type 不符
        )
        self.assertTrue(any(v.field == "id" for v in validate(SCHEMA, g)))

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd /Users/renhaoliu/Desktop/Ontology && python3 -m unittest tools.tests.test_validate -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'tools.validate'`）

- [ ] **Step 3: 实现 `tools/validate.py`**

```python
#!/usr/bin/env python3
"""校验 ontology/graph 实例是否符合 schema.yaml 的类型/基数/引用/前缀约束。"""
import sys
import os
import glob
import yaml


class Violation:
    def __init__(self, entity_id, field, message, severity="error"):
        self.entity_id = entity_id
        self.field = field
        self.message = message
        self.severity = severity

    def __str__(self):
        return f"[{self.severity}] {self.entity_id}.{self.field}: {self.message}"


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_schema(path):
    return load_yaml(path)


def id_prefix_of(schema, type_name):
    spec = schema.get("entity_types", {}).get(type_name, {})
    return spec.get("id_prefix", type_name.lower())


def load_graph(graph_dir):
    entities = {}
    for path in sorted(glob.glob(os.path.join(graph_dir, "**", "*.yaml"), recursive=True)):
        data = load_yaml(path)
        if isinstance(data, dict) and "id" in data:
            entities[data["id"]] = {"data": data, "file": path}
    return entities


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def validate(schema, graph):
    ets = schema.get("entity_types", {})
    violations = []
    id_to_type = {eid: e["data"].get("type") for eid, e in graph.items()}

    for eid, entry in graph.items():
        data = entry["data"]
        t = data.get("type")
        if t not in ets:
            violations.append(Violation(eid, "type", f"未知类型 '{t}'"))
            continue
        spec = ets[t]

        # id 前缀校验
        expected_prefix = id_prefix_of(schema, t)
        if not eid.startswith(expected_prefix + ":"):
            violations.append(Violation(eid, "id", f"id 必须以 '{expected_prefix}:' 开头"))

        # 属性校验
        for attr, aspec in spec.get("attributes", {}).items():
            if aspec.get("required") and attr not in data:
                violations.append(Violation(eid, attr, "缺少必填属性"))
            if attr in data and aspec.get("type") == "enum":
                if data[attr] not in aspec.get("values", []):
                    violations.append(Violation(eid, attr, f"'{data[attr]}' 不在 {aspec['values']} 中"))

        # 关系校验
        for rel, rspec in spec.get("relations", {}).items():
            targets = _as_list(data.get(rel))
            count = len(targets)
            lo, hi = rspec["cardinality"]
            hi = 9999 if hi == "*" else hi
            if count < lo or count > hi:
                violations.append(Violation(eid, rel, f"基数 {rspec['cardinality']} 被违反（实际 {count}）"))
            allowed = rspec["target"]
            allowed = [allowed] if isinstance(allowed, str) else allowed
            allowed_prefixes = {id_prefix_of(schema, at) for at in allowed}
            for tgt in targets:
                if tgt not in id_to_type:
                    violations.append(Violation(eid, rel, f"悬空引用 '{tgt}'"))
                else:
                    tgt_prefix = tgt.split(":", 1)[0]
                    if tgt_prefix not in allowed_prefixes:
                        violations.append(Violation(eid, rel, f"引用 '{tgt}' 类型不匹配（允许前缀 {allowed_prefixes}）"))
    return violations


def main(argv):
    schema_path = argv[1] if len(argv) > 1 else "ontology/schema.yaml"
    graph_dir = argv[2] if len(argv) > 2 else "ontology/graph"
    schema = load_schema(schema_path)
    graph = load_graph(graph_dir)
    v = validate(schema, graph)
    for x in v:
        print(x)
    print(f"\n{len(graph)} 个实体，{len(v)} 处违规")
    return 1 if any(x.severity == "error" for x in v) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: 运行测试，确认全绿**

Run: `cd /Users/renhaoliu/Desktop/Ontology && python3 -m unittest tools.tests.test_validate -v`
Expected: `OK`（8 个测试通过）

- [ ] **Step 5: 提交**

```bash
cd /Users/renhaoliu/Desktop/Ontology
git add tools/
git commit -m "feat: 新增图谱校验器 validate.py（TDD，覆盖基数/枚举/引用/类型/前缀）"
```

---

## Task 3: schema.yaml 规则层（完整 19 类型）

**Files:**
- Create: `ontology/schema.yaml`

**Interfaces:**
- Consumes: 校验器（Task 2）
- Produces: 19 类实体的类型/属性/关系/基数/约束定义；每个类型含 `id_prefix`、`description`。

- [ ] **Step 1: 写 `ontology/schema.yaml`（完整内容）**

```yaml
# TKOS 上下文图谱 · 规则层
# 定义 19 类实体的属性、关系（含基数[min,max]，* 表示无上限）、id 前缀与约束。
version: 1

entity_types:

  # ─── A. 经营骨架 ───
  StrategicIntent:
    id_prefix: intent
    description: 战略意图/战略宪法，上位锚点
    attributes:
      direction: {type: string, required: true}
      non_negotiables: {type: list}
    relations:
      produces: {target: Outcome, cardinality: [0, "*"]}

  Outcome:
    id_prefix: outcome
    description: 阶段结束必须发生的状态变化
    attributes:
      name: {type: string, required: true}
      level: {type: enum, values: [company, domain], required: true}
      success_evidence: {type: list}
      deadline: {type: date}
    relations:
      rolls_up_to: {target: Outcome, cardinality: [0, 1]}

  Domain:
    id_prefix: domain
    description: 稳定经营边界，权限/上下文/能力容器
    attributes:
      name: {type: string, required: true}
      boundary: {type: string, required: true}
      scope: {type: string}
    relations:
      has_domain_dri: {target: Person, cardinality: [1, 1]}
      owns_outcome: {target: Outcome, cardinality: [0, "*"]}
      contains_mission: {target: Mission, cardinality: [0, "*"]}
      depends_on: {target: Domain, cardinality: [0, "*"]}

  Mission:
    id_prefix: mission
    description: 最小可负责、可承诺、可验收的经营单元
    attributes:
      name: {type: string, required: true}
      expected_result: {type: string, required: true}
      deadline: {type: date, required: true}
      status: {type: enum, values: [proposed, committed, in_progress, blocked, completed, terminated], required: true}
    relations:
      belongs_to: {target: Domain, cardinality: [1, 1]}
      supports: {target: Outcome, cardinality: [1, "*"]}
      has_dri: {target: Person, cardinality: [1, 1]}
      depends_on: {target: [Mission, Domain], cardinality: [0, "*"]}
      produces: {target: [Evidence, Artifact], cardinality: [0, "*"]}
      has_decision: {target: Decision, cardinality: [0, "*"]}
      has_risk: {target: Risk, cardinality: [0, "*"]}
      yields_lesson: {target: Lesson, cardinality: [0, "*"]}
      instantiates: {target: WorkPattern, cardinality: [0, "*"]}
    constraints:
      - "DRI 必须是 Person，Agent 不得成为责任主体（Human accountable, Agent enabled）"
      - "必须支撑至少一个 Outcome"

  Signal:
    id_prefix: signal
    description: 来自市场/客户/技术/组织/数据的新变化（SICO 输入）
    attributes:
      content: {type: string, required: true}
      source: {type: string}
      credibility: {type: enum, values: [low, medium, high]}
    relations:
      raises: {target: Issue, cardinality: [0, "*"]}

  Issue:
    id_prefix: issue
    description: 需形成判断或做出选择的战略议题（SICO）
    attributes:
      title: {type: string, required: true}
      urgency: {type: enum, values: [low, medium, high]}
    relations:
      resolved_by: {target: [Decision, Outcome], cardinality: [0, "*"]}

  # ─── B. 责任与角色 ───
  Person:
    id_prefix: person
    description: 真实责任人
    attributes:
      name: {type: string, required: true}
      title: {type: string}
    relations:
      has_role: {target: Role, cardinality: [0, "*"]}

  Role:
    id_prefix: role
    description: 角色（CEO/DomainDRI/MissionDRI/IC）
    attributes:
      name: {type: string, required: true}

  # ─── C. 上下文资产 ───
  Decision:
    id_prefix: decision
    description: 对方向/边界/资源/方案的选择
    attributes:
      summary: {type: string, required: true}
      confirmed_by_human: {type: bool}
    relations:
      decided_by: {target: Person, cardinality: [1, 1]}
      based_on: {target: Evidence, cardinality: [0, "*"]}

  Evidence:
    id_prefix: evidence
    description: 证明进展或结果的事实/数据
    attributes:
      content: {type: string, required: true}
      status: {type: enum, values: [target, verified], required: true}
    relations:
      evidence_for: {target: Outcome, cardinality: [0, "*"]}

  Artifact:
    id_prefix: artifact
    description: 关键方案/报告/原型/合同/交付物
    attributes:
      name: {type: string, required: true}
      kind: {type: string}

  Risk:
    id_prefix: risk
    description: 可能影响结果的问题/运营风险
    attributes:
      description: {type: string, required: true}
      severity: {type: enum, values: [low, medium, high]}

  Lesson:
    id_prefix: lesson
    description: 被验证/证伪的假设、有效方法、失败原因
    attributes:
      content: {type: string, required: true}
    relations:
      promotes_to: {target: [Domain, StrategicIntent], cardinality: [0, "*"]}

  # ─── D. 系统与产品结构 ───
  TKOSComponent:
    id_prefix: component
    description: TKOS 顶层组成（Method/Agents/Engine&Ontology）
    attributes:
      name: {type: string, required: true}
      responsibility: {type: string, required: true}
    relations:
      comprises: {target: [MethodPattern, AgentProduct, OntologyCapability], cardinality: [0, "*"]}

  MethodPattern:
    id_prefix: method
    description: 方法模式（M1 SICO / M2 OMD / M3 MOER）
    attributes:
      name: {type: string, required: true}
      expands: {type: string, required: true}        # 展开式，如 Signal→Issue→Choice→Outcome
      operates_at: {type: enum, values: [ceo, dri, ic], required: true}
      aliases: {type: list}

  AgentProduct:
    id_prefix: agent
    description: Agent 产品（A1–A4）
    attributes:
      name: {type: string, required: true}
      operates_at: {type: enum, values: [ceo, dri, ic], required: true}

  OntologyCapability:
    id_prefix: eo
    description: 本体能力层（E&O1–3）
    attributes:
      name: {type: string, required: true}
      operates_at: {type: enum, values: [ceo, dri, ic], required: true}
    relations:
      pairs_in_cell: {target: [MethodPattern, AgentProduct], cardinality: [0, "*"]}

  TransformationPhase:
    id_prefix: phase
    description: 转型阶段（T1 认知破局 / T2 组织重构贯通 / T3 共营固化）
    attributes:
      name: {type: string, required: true}
      maps_to_steps: {type: string, required: true}   # 如 "AI转型九步法 1–4"
    relations:
      delivers: {target: TKOSComponent, cardinality: [0, "*"]}

  Infrastructure:
    id_prefix: infra
    description: 统一运行基础设施（TokenHub）
    attributes:
      name: {type: string, required: true}
      responsibility: {type: string, required: true}
    relations:
      supports_runtime: {target: TKOSComponent, cardinality: [0, "*"]}

  # ─── E. 可复用资产 ───
  WorkPattern:
    id_prefix: wp
    description: 被反复验证的标准工作方法
    attributes:
      name: {type: string, required: true}
      trigger: {type: string}
      steps: {type: list}
    relations:
      applies_to: {target: Issue, cardinality: [0, "*"]}

# ─── 全局边界规则（人类可读；部分由 target 类型自动校验）───
global_constraints:
  - "TokenHub ≠ TKOS Engine：基础设施不与 Engine 混用"
  - "Method 不由系统字段倒推经营逻辑（方法先于工具）"
  - "Agents 不承载企业本体和底层 Runtime"
  - "Engine & Ontology 不替代 Agents，不提前建大而全平台"
  - "Transformation 不定义通用 Method"
  - "新增公司级事项必声明：支持哪个 Outcome + 替代哪个既有 Mission + DRI 是谁"
```

- [ ] **Step 2: 校验器对空 graph 应通过（无实例时 0 违规）**

Run: `cd /Users/renhaoliu/Desktop/Ontology && python3 tools/validate.py ontology/schema.yaml ontology/graph`
Expected: `0 个实体，0 处违规`，退出码 0。

- [ ] **Step 3: 提交**

```bash
cd /Users/renhaoliu/Desktop/Ontology
git add ontology/schema.yaml
git commit -m "feat: 新增 schema.yaml 规则层（19 类型 + 关系 + 基数 + 约束）"
```

---

## Task 4: company/ 战略层 + 公司级人员

**Files:**
- Create: `ontology/graph/company/intent/strategic-intent.yaml`
- Create: `ontology/graph/company/outcomes/company-2026-08.yaml`
- Create: `ontology/graph/company/people/liu-minghua.yaml`
- Create: `ontology/graph/company/roles/role-ceo.yaml`、`role-domain-dri.yaml`、`role-mission-dri.yaml`（在 `people/` 同级建 `roles/` 目录）

**Interfaces:**
- Produces: `intent:strategic-intent`、`outcome:company-2026-08`（level=company）、`person:liu-minghua`、`role:ceo` 等，供后续引用。

- [ ] **Step 1: 建 roles 目录**

```bash
mkdir -p /Users/renhaoliu/Desktop/Ontology/ontology/graph/company/roles
```

- [ ] **Step 2: 写战略意图 `strategic-intent.yaml`**

```yaml
# ontology/graph/company/intent/strategic-intent.yaml
id: intent:strategic-intent
type: StrategicIntent
direction: 成为 AI 原生企业「人 + Agent 混合经营」操作系统（TKOS）的领先者与第一实践者
non_negotiables:
  - TKOS 管理的是「结果如何由人和 Agent 共同实现」，不是人本身、也不是 Agent 本身
  - Human accountable, Agent enabled：人承担结果责任，Agent 增强能力
  - 以 Outcome 与 Mission 为核心组织经营，不以部门/流程/文件为中心
produces: [outcome:company-2026-08]
source: 0-词元云集_TKOS总体定义_高管讨论稿_v0.2.pdf §二/§九
rationale: |
  战略锚点在上，真正建模从 Domain 开始。战略意图提供「为什么做」的方向，
  压缩为少数阶段 Outcome 后由 Domain 展开。本意图为 8 月公司总 Outcome 的上位锚点。
```

- [ ] **Step 3: 写公司级 Outcome `company-2026-08.yaml`**

```yaml
# ontology/graph/company/outcomes/company-2026-08.yaml
id: outcome:company-2026-08
type: Outcome
name: 8 月底公司第一次成型
level: company
deadline: 2026-08-31
success_evidence:
  - 核心业务由 Transformation 进入灯塔客户真实运行
  - 8 个 Domain 按 Outcome-Mission-DRI 方法运转
  - 一号位与管理者 Agents 形成可用版本
  - Engine & Ontology 建立最小经营 Context 与运行能力
  - TokenHub 稳定承接核心调用
  - 核心团队、激励体系与基础运营条件基本到位
rolls_up_to: null
source: M2-词元云集_2026年8月_Outcome-Mission展开纲领_正式版_v1.1.pdf §二
rationale: |
  Company Outcome 描述阶段结束时的状态变化（非动作），数量有限、可被 Evidence 验收。
  本 Outcome 向下展开为 8 个 Domain Outcome。
```

- [ ] **Step 4: 写 `liu-minghua.yaml` + 3 个 Role 文件**

```yaml
# ontology/graph/company/people/liu-minghua.yaml
id: person:liu-minghua
type: Person
name: 刘明华
title: CEO / 一号位
has_role: [role:ceo, role:domain-dri]
source: M2-词元云集_2026年8月_Outcome-Mission展开纲领_正式版_v1.1.pdf §二
rationale: |
  CEO 从任务搬运中退出，聚焦战略方向、关键取舍、价值判断、重大资源配置、
  关键人才与外部关系。当前兼 Domain 01（方向与经营选择）与 Domain 02（Transformation）DRI。
```

```yaml
# ontology/graph/company/roles/role-ceo.yaml
id: role:ceo
type: Role
name: CEO / 一号位
source: M1-3.词元云集_TKOS方法论框架_正式版_v1.0.pdf §五
```

```yaml
# ontology/graph/company/roles/role-domain-dri.yaml
id: role:domain-dri
type: Role
name: Domain DRI
source: M1-3.词元云集_TKOS方法论框架_正式版_v1.0.pdf §五
```

```yaml
# ontology/graph/company/roles/role-mission-dri.yaml
id: role:mission-dri
type: Role
name: Mission DRI
source: M1-3.词元云集_TKOS方法论框架_正式版_v1.0.pdf §五
```

- [ ] **Step 5: 运行校验器，确认 0 违规**

Run: `cd /Users/renhaoliu/Desktop/Ontology && python3 tools/validate.py`
Expected: `6 个实体，0 处违规`，退出码 0。

- [ ] **Step 6: 提交**

```bash
cd /Users/renhaoliu/Desktop/Ontology
git add ontology/graph/company/
git commit -m "feat: 填充 company 战略层（战略意图/公司Outcome/刘明华/角色）"
```

---

## Task 5: company/system/ TKOS 系统结构

**Files:**
- Create: `ontology/graph/company/system/components/{method,agents,engine-ontology}.yaml`（3）
- Create: `ontology/graph/company/system/methods/{m1-sico,m2-omd,m3-moer}.yaml`（3）
- Create: `ontology/graph/company/system/agents/{a1-ceo,a2-manager,a3-coagent,a4-digital-worker}.yaml`（4）
- Create: `ontology/graph/company/system/ontology/{eo1,eo2,eo3}.yaml`（3）
- Create: `ontology/graph/company/system/transformation/{t1,t2,t3}.yaml`（3）
- Create: `ontology/graph/company/system/infrastructure/tokenhub.yaml`（1）

**Interfaces:**
- Produces: 17 个系统结构实体；methods/agents/ontology 各带 `operates_at`（ceo/dri/ic）还原 3×3；transformation 带 `maps_to_steps`。

- [ ] **Step 1: 写 3 个顶层组件 `components/*.yaml`**

```yaml
# components/method.yaml
id: component:method
type: TKOSComponent
name: Method（管理方法）
responsibility: 定义 Outcome/Mission/DRI/Review/复盘等经营方法与运行规则（组织宪法）
comprises: [method:m1-sico, method:m2-omd, method:m3-moer]
source: 0-词元云集_TKOS总体定义_高管讨论稿_v0.2.pdf §四
```

```yaml
# components/agents.yaml
id: component:agents
type: TKOSComponent
name: Agents（AI 员工）
responsibility: 把管理方法转化为一号位/管理者/员工可直接使用的工作入口
comprises: [agent:a1-ceo, agent:a2-manager, agent:a3-coagent, agent:a4-digital-worker]
source: 0-词元云集_TKOS总体定义_高管讨论稿_v0.2.pdf §四
```

```yaml
# components/engine-ontology.yaml
id: component:engine-ontology
type: TKOSComponent
name: Engine & Ontology（管理引擎及本体）
responsibility: 定义企业对象/关系/状态/权限，成为人和 AI 共同理解与运行的底座
comprises: [eo:eo1, eo:eo2, eo:eo3]
source: 0-词元云集_TKOS总体定义_高管讨论稿_v0.2.pdf §四
```

- [ ] **Step 2: 写 3 个方法模式 `methods/*.yaml`**

```yaml
# methods/m1-sico.yaml
id: method:m1-sico
type: MethodPattern
name: M1 SICO
expands: Signal（信号）→ Issue（议题）→ Choice（选择）→ Outcome（结果）
operates_at: ceo
source: 词元云集_企业AI转型TKOS设计方案_管理层汇报版vf.pdf §3×3矩阵
rationale: CEO 层方法——定义战略如何被触发、形成判断并转化为公司结果。
```

```yaml
# methods/m2-omd.yaml
id: method:m2-omd
type: MethodPattern
name: M2 OMD
expands: Outcome（结果）→ Mission（任务）→ DRI（直接负责人）
operates_at: dri
source: 词元云集_企业AI转型TKOS设计方案_管理层汇报版vf.pdf §3×3矩阵
rationale: DRI 层方法——把结果转成任务与唯一 DRI 承诺，并持续评估与纠偏。
```

```yaml
# methods/m3-moer.yaml
id: method:m3-moer
type: MethodPattern
name: M3 MOER
expands: Mission（任务）→ Orchestration（统筹）→ Execution（执行）→ Result（产出）
operates_at: ic
aliases: [MEAR]
source: 词元云集_企业AI转型TKOS设计方案_管理层汇报版vf.pdf §3×3矩阵
rationale: |
  IC 层方法——定义任务如何通过人和数字劳动力协同完成。
  注：文档中存在 MOER/MEAR 命名漂移，本图谱统一用 MOER，别名记录 MEAR。
```

- [ ] **Step 3: 写 4 个 Agent 产品 `agents/*.yaml`**

```yaml
# agents/a1-ceo.yaml
id: agent:a1-ceo
type: AgentProduct
name: A1 一号位 / CEO Agent
operates_at: ceo
source: 词元云集_企业AI转型TKOS设计方案_管理层汇报版vf.pdf §3×3矩阵
```

```yaml
# agents/a2-manager.yaml
id: agent:a2-manager
type: AgentProduct
name: A2 管理者 Agent
operates_at: dri
source: 词元云集_企业AI转型TKOS设计方案_管理层汇报版vf.pdf §3×3矩阵
```

```yaml
# agents/a3-coagent.yaml
id: agent:a3-coagent
type: AgentProduct
name: A3 Co-agent
operates_at: dri
source: 词元云集_企业AI转型TKOS设计方案_管理层汇报版vf.pdf §3×3矩阵
```

```yaml
# agents/a4-digital-worker.yaml
id: agent:a4-digital-worker
type: AgentProduct
name: A4 数字劳动力
operates_at: ic
source: 词元云集_企业AI转型TKOS设计方案_管理层汇报版vf.pdf §3×3矩阵
```

- [ ] **Step 4: 写 3 个本体能力层 `ontology/*.yaml`**

```yaml
# ontology/eo1.yaml
id: eo:eo1
type: OntologyCapability
name: E&O1 战略本体
operates_at: ceo
pairs_in_cell: [method:m1-sico, agent:a1-ceo]
source: 词元云集_企业AI转型TKOS设计方案_管理层汇报版vf.pdf §3×3矩阵
rationale: 把公司宪法/战略/目标/关键假设与决策历史结构化并持续更新。
```

```yaml
# ontology/eo2.yaml
id: eo:eo2
type: OntologyCapability
name: E&O2 经营本体 + 引擎
operates_at: dri
pairs_in_cell: [method:m2-omd, agent:a2-manager, agent:a3-coagent]
source: 词元云集_企业AI转型TKOS设计方案_管理层汇报版vf.pdf §3×3矩阵
rationale: 表达经营责任/状态/关系/权限，使 Mission 协同可运行、可追踪。
```

```yaml
# ontology/eo3.yaml
id: eo:eo3
type: OntologyCapability
name: E&O3 执行本体 + 引擎
operates_at: ic
pairs_in_cell: [method:m3-moer, agent:a4-digital-worker]
source: 词元云集_企业AI转型TKOS设计方案_管理层汇报版vf.pdf §3×3矩阵
rationale: 让任务/动作/工具调用/结果/反馈能被 Agent 执行、记录和回写。
```

- [ ] **Step 5: 写 3 个转型阶段 `transformation/*.yaml`**

```yaml
# transformation/t1.yaml
id: phase:t1
type: TransformationPhase
name: T1 认知破局
maps_to_steps: AI转型九步法 1–4
delivers: [component:method, component:agents, component:engine-ontology]
source: 词元云集_企业AI转型TKOS设计方案_管理层汇报版vf.pdf §AI转型九步法
rationale: 让一号位看见 AI 转型必要性与目标状态，以真实经营议题启动。
```

```yaml
# transformation/t2.yaml
id: phase:t2
type: TransformationPhase
name: T2 组织重构贯通
maps_to_steps: AI转型九步法 5–7
delivers: [component:method, component:agents, component:engine-ontology]
source: 词元云集_企业AI转型TKOS设计方案_管理层汇报版vf.pdf §AI转型九步法
rationale: 把目标组织、决策机制与管理网络带入真实运行，跑通跨角色 Mission 闭环。
```

```yaml
# transformation/t3.yaml
id: phase:t3
type: TransformationPhase
name: T3 共营固化
maps_to_steps: AI转型九步法 8–9
delivers: [component:method, component:agents, component:engine-ontology]
source: 词元云集_企业AI转型TKOS设计方案_管理层汇报版vf.pdf §AI转型九步法
rationale: 推动数字劳动力进入真实业务执行，重构人与 AI 分工，形成可持续新范式。
```

- [ ] **Step 6: 写 TokenHub `infrastructure/tokenhub.yaml`**

```yaml
# infrastructure/tokenhub.yaml
id: infra:tokenhub
type: Infrastructure
name: TokenHub
responsibility: 统一模型接入/账户/权限/调用/计量/日志/SLA，为 TKOS 每次智能运算提供可治理基础设施
supports_runtime: [component:method, component:agents, component:engine-ontology]
source: 词元云集_企业AI转型TKOS设计方案_管理层汇报版vf.pdf §TokenHub
rationale: |
  TokenHub 是基础设施，≠ TKOS Engine（不混用）。统一模型选择与路由、成本质量优化，
  支撑 TKOS 与 TokenOps 的稳定智能运行。
```

- [ ] **Step 7: 运行校验器，确认 0 违规**

Run: `cd /Users/renhaoliu/Desktop/Ontology && python3 tools/validate.py`
Expected: `23 个实体，0 处违规`（company 6 + system 17），退出码 0。

- [ ] **Step 8: 提交**

```bash
cd /Users/renhaoliu/Desktop/Ontology
git add ontology/graph/company/system/
git commit -m "feat: 填充 company/system TKOS 系统结构（组件/方法/Agent/本体/转型/TokenHub）"
```

---

## Task 6: domain/ 8 个 Domain + Domain Outcome + DRI 人员

**Files:**
- Create: `ontology/graph/domain/domains/01-direction.yaml` … `08-operations.yaml`（8）
- Create: `ontology/graph/domain/outcomes/<domain>-2026-08.yaml`（8）
- Create: `ontology/graph/domain/people/{tiantian,sunmingze,renhao,zhuoran,mengyi,jujie}.yaml`（6）

**Interfaces:**
- Produces: 8 个 `domain:*`（含 `has_domain_dri`）、8 个 `outcome:*`（level=domain，`rolls_up_to: outcome:company-2026-08`）、6 个 `person:*`。

- [ ] **Step 1: 写 6 位 Domain DRI**

每个文件结构相同，下面给出 `tiantian.yaml` 全文，其余 5 个按下表替换 `id/name/title/source`。

```yaml
# domain/people/tiantian.yaml
id: person:tiantian
type: Person
name: 田田
title: Method Domain DRI
has_role: [role:domain-dri]
source: M2-词元云集_2026年8月_Outcome-Mission展开纲领_正式版_v1.1.pdf §二
rationale: 负责「公司是否按 TKOS 方法运行」；方法先于工具，不由系统字段倒推经营逻辑。
```

DRI 人员表（其余 5 人按此替换）：

| 文件 | id | name | title | 责任要点 |
|---|---|---|---|---|
| `sunmingze.yaml` | person:sunmingze | 孙铭泽 | Agents Domain DRI（暂代） | 产品入口责任，不承载本体/Runtime |
| `renhao.yaml` | person:renhao | 人豪 | Engine & Ontology Domain DRI | 统一 Context/状态/权限/回写 |
| `zhuoran.yaml` | person:zhuoran | 卓然 | TokenHub Domain DRI | 模型基础设施，≠ Engine |
| `mengyi.yaml` | person:mengyi | 梦怡 | 人才与组织能力 Domain DRI | 核心团队 + 激励体系 |
| `jujie.yaml` | person:jujie | 巨杰 | 公司运营与保障 Domain DRI | 财务/办公/采购/合规 |

> 所有 5 人 `has_role: [role:domain-dri]`、`source` 同 `§二`。

- [ ] **Step 2: 写 8 个 Domain Outcome**

每个 outcome 文件结构相同。模板（以 method 为例）：

```yaml
# domain/outcomes/method-2026-08.yaml
id: outcome:method-2026-08
type: Outcome
name: Method 域 8 月底结果
level: domain
deadline: 2026-08-31
success_evidence:
  - Outcome-Mission-DRI 与 SICO/OMD/MEAR 方法完成设计并真实运行
  - 8 个 Domain 完成 Mission 分解；关键 Mission 形成唯一 DRI 承诺
  - 至少完成三次真实经营 Review
rolls_up_to: outcome:company-2026-08
source: M2-词元云集_2026年8月_Outcome-Mission展开纲领_正式版_v1.1.pdf §03
```

8 个 Domain Outcome 的 `id` 与核心结果（替换 `success_evidence`）：

| id | 文件 | 核心结果（success_evidence 要点） |
|---|---|---|
| `outcome:direction-2026-08` | direction-2026-08.yaml | 战略、阶段 Outcome 与公司 Mission 组合形成统一牵引 |
| `outcome:transformation-2026-08` | transformation-2026-08.yaml | 灯塔目标 Operating Model、转型路径、采用与价值验证进入真实运行 |
| `outcome:method-2026-08` | method-2026-08.yaml | Outcome-Mission-DRI 与 SICO/OMD/MEAR 完成设计并真实运行 |
| `outcome:agents-2026-08` | agents-2026-08.yaml | 一号位/管理者/数字劳动力与经营工作入口形成可用版本并进入真实使用 |
| `outcome:engine-ontology-2026-08` | engine-ontology-2026-08.yaml | 企业 Context、本体与最小运行能力形成并支撑 Agents |
| `outcome:tokenhub-2026-08` | tokenhub-2026-08.yaml | 统一模型接入、账户、权限、计量、日志与稳定性形成内部可用能力 |
| `outcome:talent-2026-08` | talent-2026-08.yaml | 核心团队到位，期权与激励体系完成 |
| `outcome:operations-2026-08` | operations-2026-08.yaml | 财务、办公、设备、研发环境和必要合规齐备 |

> 全部 `level: domain`、`rolls_up_to: outcome:company-2026-08`、`source` 对应章节（§01–§08）。

- [ ] **Step 3: 写 8 个 Domain**

每个 domain 文件含 `has_domain_dri` 与 `owns_outcome`。模板（以 03-method 为例）：

```yaml
# domain/domains/03-method.yaml
id: domain:03-method
type: Domain
name: 03 Method
boundary: 定义公司/客户如何经营：Outcome/Mission/DRI/Review/Work Pattern 规则
scope: 经营方法与运行规则（组织宪法）
has_domain_dri: person:tiantian
owns_outcome: [outcome:method-2026-08]
contains_mission: []        # Task 7 填充
depends_on: []              # Task 8 填充
source: M2-词元云集_2026年8月_Outcome-Mission展开纲领_正式版_v1.1.pdf §三/§03
rationale: |
  Domain 是稳定经营边界（≠部门），权限/上下文容器。Method 定义规则，
  不由系统字段倒推经营逻辑；向其他 DRI 提供业务规则。
```

8 个 Domain 的 `id / has_domain_dri / owns_outcome`：

| id | name | has_domain_dri | owns_outcome |
|---|---|---|---|
| `domain:01-direction` | 01 方向与经营选择 | person:liu-minghua | outcome:direction-2026-08 |
| `domain:02-transformation` | 02 Transformation | person:liu-minghua | outcome:transformation-2026-08 |
| `domain:03-method` | 03 Method | person:tiantian | outcome:method-2026-08 |
| `domain:04-agents` | 04 Agents | person:sunmingze | outcome:agents-2026-08 |
| `domain:05-engine-ontology` | 05 Engine & Ontology | person:renhao | outcome:engine-ontology-2026-08 |
| `domain:06-tokenhub` | 06 TokenHub | person:zhuoran | outcome:tokenhub-2026-08 |
| `domain:07-talent` | 07 人才与组织能力 | person:mengyi | outcome:talent-2026-08 |
| `domain:08-operations` | 08 公司运营与保障 | person:jujie | outcome:operations-2026-08 |

- [ ] **Step 4: 运行校验器，确认 0 违规**

Run: `cd /Users/renhaoliu/Desktop/Ontology && python3 tools/validate.py`
Expected: `45 个实体，0 处违规`（23 + 8 domain + 8 outcome + 6 person），退出码 0。

> 若出现 `has_domain_dri` 类型不匹配或悬空引用，核对 person/outcome id 拼写。

- [ ] **Step 5: 提交**

```bash
cd /Users/renhaoliu/Desktop/Ontology
git add ontology/graph/domain/
git commit -m "feat: 填充 domain 层 8 Domain + 8 Domain Outcome + 6 DRI"
```

---

## Task 7: domain/missions/ 全部 37 个 Mission

**Files:**
- Create: `ontology/graph/domain/missions/<NN-M>.yaml`（37 个，文件名=文档编号）

**Interfaces:**
- Consumes: `domain:*`、`outcome:*`（domain）、`person:*`
- Produces: 37 个 `mission:*`，每个 `belongs_to` 一个 domain、`supports` 对应 domain outcome、`has_dri` 对应人员。

- [ ] **Step 1: 按下表批量创建 37 个 Mission**

每个 Mission 文件用如下模板（以 `03-3.yaml` 为例），替换 `id/name/belongs_to/has_dri/expected_result/source`：

```yaml
# domain/missions/03-3.yaml
id: mission:03-3
type: Mission
name: 完成 DRI 协商与承诺
belongs_to: domain:03-method
supports: [outcome:method-2026-08]
has_dri: person:tiantian
status: planned
expected_result: 确认唯一 DRI、结果、路径、资源、权限和升级规则
deadline: 2026-08-31
source: M2-词元云集_2026年8月_Outcome-Mission展开纲领_正式版_v1.1.pdf §03
rationale: |
  Mission 非自上而下派单。候选 DRI 须评估定义/资源/时间/权限/风险，必要时修改或拒绝承诺。
```

完整 37 Mission 数据表（`belongs_to` 与 `supports` 由所在 Domain 决定，`has_dri` = 该 Domain DRI；`name`/`expected_result` 摘自 8 月纲领）：

| id | name | belongs_to | supports | has_dri |
|---|---|---|---|---|
| mission:01-1 | 确认 8 月公司级战略 Outcome | domain:01-direction | outcome:direction-2026-08 | person:liu-minghua |
| mission:01-2 | 完成 8 个 Domain 授权 | domain:01-direction | outcome:direction-2026-08 | person:liu-minghua |
| mission:01-3 | 形成公司级 Mission Portfolio | domain:01-direction | outcome:direction-2026-08 | person:liu-minghua |
| mission:01-4 | 形成 9 月后经营判断 | domain:01-direction | outcome:direction-2026-08 | person:liu-minghua |
| mission:02-1 | 完成现状诊断与目标 Operating Model | domain:02-transformation | outcome:transformation-2026-08 | person:liu-minghua |
| mission:02-2 | 锁定转型范围、阶段路径与客户协同 | domain:02-transformation | outcome:transformation-2026-08 | person:liu-minghua |
| mission:02-3 | 推动一号位与关键角色进入真实运行 | domain:02-transformation | outcome:transformation-2026-08 | person:liu-minghua |
| mission:02-4 | 完成首轮价值验证与转型复盘 | domain:02-transformation | outcome:transformation-2026-08 | person:liu-minghua |
| mission:03-1 | 形成 Outcome-Mission 标准方法 | domain:03-method | outcome:method-2026-08 | person:tiantian |
| mission:03-2 | 形成 Mission Card 与质量标准 | domain:03-method | outcome:method-2026-08 | person:tiantian |
| mission:03-3 | 完成 8 个 Domain Mission 分解 | domain:03-method | outcome:method-2026-08 | person:tiantian |
| mission:03-4 | 完成 DRI 协商与承诺 | domain:03-method | outcome:method-2026-08 | person:tiantian |
| mission:03-5 | 建立经营运行节奏 | domain:03-method | outcome:method-2026-08 | person:tiantian |
| mission:03-6 | 识别、设计并验证 Work Pattern 候选 | domain:03-method | outcome:method-2026-08 | person:tiantian |
| mission:04-1 | 明确首批 Agents 组合与边界 | domain:04-agents | outcome:agents-2026-08 | person:sunmingze |
| mission:04-2 | 完成一号位 Application 部署 | domain:04-agents | outcome:agents-2026-08 | person:sunmingze |
| mission:04-3 | 形成管理者 Agents 与数字劳动力首批场景 | domain:04-agents | outcome:agents-2026-08 | person:sunmingze |
| mission:04-4 | 形成 Mission/决策/Review 工作入口 | domain:04-agents | outcome:agents-2026-08 | person:sunmingze |
| mission:04-5 | 建立真实使用与产品迭代闭环 | domain:04-agents | outcome:agents-2026-08 | person:sunmingze |
| mission:05-1 | 定义 Foundry v0.x 对象与关系 | domain:05-engine-ontology | outcome:engine-ontology-2026-08 | person:renhao |
| mission:05-2 | 形成公司与灯塔当前有效 Context | domain:05-engine-ontology | outcome:engine-ontology-2026-08 | person:renhao |
| mission:05-3 | 建立 Context 更新、版本与权限机制 | domain:05-engine-ontology | outcome:engine-ontology-2026-08 | person:renhao |
| mission:05-4 | 形成 Engine 最小运行能力 | domain:05-engine-ontology | outcome:engine-ontology-2026-08 | person:renhao |
| mission:05-5 | 接通 Agents 并验证边界 | domain:05-engine-ontology | outcome:engine-ontology-2026-08 | person:renhao |
| mission:06-1 | 完成 MVP 产品与技术定义 | domain:06-tokenhub | outcome:tokenhub-2026-08 | person:zhuoran |
| mission:06-2 | 完成核心平台开发 | domain:06-tokenhub | outcome:tokenhub-2026-08 | person:zhuoran |
| mission:06-3 | 形成基础运行稳定性 | domain:06-tokenhub | outcome:tokenhub-2026-08 | person:zhuoran |
| mission:06-4 | 接入内部真实场景 | domain:06-tokenhub | outcome:tokenhub-2026-08 | person:zhuoran |
| mission:07-1 | 锁定核心岗位与招聘优先级 | domain:07-talent | outcome:talent-2026-08 | person:mengyi |
| mission:07-2 | 完成核心候选人招募 | domain:07-talent | outcome:talent-2026-08 | person:mengyi |
| mission:07-3 | 完成核心团队到位 | domain:07-talent | outcome:talent-2026-08 | person:mengyi |
| mission:07-4 | 完成期权与长期激励体系 | domain:07-talent | outcome:talent-2026-08 | person:mengyi |
| mission:08-1 | 建立基础财务管理体系 | domain:08-operations | outcome:operations-2026-08 | person:jujie |
| mission:08-2 | 完成办公场地与办公环境建设 | domain:08-operations | outcome:operations-2026-08 | person:jujie |
| mission:08-3 | 完成研发环境与模型资源保障 | domain:08-operations | outcome:operations-2026-08 | person:jujie |
| mission:08-4 | 完成设备设施采购 | domain:08-operations | outcome:operations-2026-08 | person:jujie |
| mission:08-5 | 完成必要合同与合规建设 | domain:08-operations | outcome:operations-2026-08 | person:jujie |

> `expected_result` 取 8 月纲领对应 Mission 的「8 月底核心结果」原文；`source` = `§<域编号>`。

- [ ] **Step 2: 回填 Domain 的 `contains_mission`**

更新 8 个 `domain/domains/*.yaml` 的 `contains_mission` 为该域所有 mission id 列表。例：`domain:03-method` → `contains_mission: [mission:03-1, mission:03-2, mission:03-3, mission:03-4, mission:03-5, mission:03-6]`。

- [ ] **Step 3: 运行校验器，确认 0 违规**

Run: `cd /Users/renhaoliu/Desktop/Ontology && python3 tools/validate.py`
Expected: 0 违规（实体数应为 45 + 37 = 82），退出码 0。

- [ ] **Step 4: 提交**

```bash
cd /Users/renhaoliu/Desktop/Ontology
git add ontology/graph/domain/
git commit -m "feat: 填充 37 个 Mission 并回填 Domain.contains_mission"
```

---

## Task 8: domain/assets/ 示范资产 + work-patterns/ + dependencies/

**Files:**
- Create: `ontology/graph/domain/assets/evidence/<domain>-acceptance-evidence.yaml`（8 个目标型 Evidence，`status: target`）
- Create: `ontology/graph/domain/assets/decisions/d-001.yaml`（1 个示范 Decision）
- Create: `ontology/graph/domain/assets/risks/r-001.yaml`（1 个示范 Risk）
- Create: `ontology/graph/domain/assets/lessons/l-001.yaml`（1 个示范 Lesson）
- Create: `ontology/graph/domain/work-patterns/*.yaml`（6 个）
- Create: `ontology/graph/domain/dependencies/cross-domain.yaml`（声明 Domain 间依赖，并回填 Domain.depends_on）

**Interfaces:**
- Consumes: mission/outcome/domain/person
- Produces: 示范资产（标注「运行中填充」）、6 个 WorkPattern、跨域依赖边。

- [ ] **Step 1: 写 8 个目标型 Evidence（每个 Domain 一个验收证据）**

模板（method 为例）：

```yaml
# assets/evidence/method-acceptance-evidence.yaml
id: evidence:method-acceptance-evidence
type: Evidence
content: 8 个 Domain 完成 Mission 分解；关键 Mission 形成唯一 DRI 承诺；至少完成三次真实经营 Review
status: target
evidence_for: [outcome:method-2026-08]
source: M2-词元云集_2026年8月_Outcome-Mission展开纲领_正式版_v1.1.pdf §03 关键验收证据
rationale: 目标型证据（aspirational）；运行中由 DRI 确认后置为 verified。
```

> 其余 7 个：`id=evidence:<domain>-acceptance-evidence`，`evidence_for` 指向对应 domain outcome，`content` 取该域「关键验收证据」原文，`status: target`。

- [ ] **Step 2: 写 1 个示范 Decision**

```yaml
# assets/decisions/d-001.yaml
id: decision:d-001
type: Decision
summary: TKOS 由 3+2 产品矩阵整体升级而成，作为词元云集核心产品母体
decided_by: person:liu-minghua
confirmed_by_human: true
based_on: []
source: 词元云集_企业AI转型TKOS设计方案_管理层汇报版vf.pdf §战略回顾
rationale: 关键决策保留判断逻辑，避免只剩结论；示范实例，其余运行中填充。
```

- [ ] **Step 3: 写 1 个示范 Risk**

```yaml
# assets/risks/r-001.yaml
id: risk:r-001
type: Risk
description: Mission 泛化——所有工作都被包装为 Mission，弱化对经营结果的关注
severity: high
source: M1-3.词元云集_TKOS方法论框架_正式版_v1.0.pdf §十二 风险
rationale: 只保留战略关键、跨越不确定性的事项；示范实例。
```

- [ ] **Step 4: 写 1 个示范 Lesson**

```yaml
# assets/lessons/l-001.yaml
id: lesson:l-001
type: Lesson
content: 方法先于工具——先跑通真实月度 Mission 机制，再建平台；工具先行会导致底层能力与经营目标脱节
promotes_to: [intent:strategic-intent]
source: M1-3.词元云集_TKOS方法论框架_正式版_v1.0.pdf §十一
rationale: 经验提升到更高层（战略意图），使组织不重复犯错；示范实例。
```

- [ ] **Step 5: 写 6 个 Work Pattern**

每个文件结构相同。模板（`wp:strategic-research` 全文）：

```yaml
# work-patterns/strategic-research.yaml
id: wp:strategic-research
type: WorkPattern
name: 战略问题研究
trigger: 出现需要判断的外部/内部战略变化
steps:
  - 资料检索
  - 假设树构建
  - 证据核验
  - 观点冲突识别
  - 结论草案
applies_to: []
source: M1-3.词元云集_TKOS方法论框架_正式版_v1.0.pdf §九
rationale: 把高质量 Mission 运行方式沉淀为可复用 Work Pattern，是规模化/产品化关键资产。
```

其余 5 个 WorkPattern（替换 `id/name/steps`）：

| id | name | steps |
|---|---|---|
| wp:ceo-operating-meeting | CEO 经营会议 | 会前议题准备, 过程分析, 观点提炼, 决策与 Mission 生成 |
| wp:mission-decomposition | Mission 分解 | Outcome 校验, Mission 候选, DRI 匹配, 依赖和风险检查 |
| wp:candidate-evaluation | 候选人评估 | 岗位画像, 简历证据, 面试问题, 评价标尺, 复盘 |
| wp:product-review | 产品方案评审 | 战略一致性, 用户价值, 路径, 风险, 验证计划 |
| wp:project-retrospective | 客户项目复盘 | 目标-结果差异, 关键假设, 可复用资产, 下一步建议 |

> 全部 `applies_to: []`（运行中挂接到具体 Issue）、`source: §九`。

- [ ] **Step 6: 写跨域依赖并回填 Domain.depends_on**

```yaml
# domain/dependencies/cross-domain.yaml
# 这是依赖声明文件（非实体），仅记录域间依赖，供 build_index 读取与人工查阅。
# 同时把这些依赖回填到各 domain 文件的 depends_on 字段（见下）。
dependencies:
  - {from: domain:01-direction, to: domain:02-transformation}
  - {from: domain:01-direction, to: domain:03-method}
  - {from: domain:01-direction, to: domain:04-agents}
  - {from: domain:01-direction, to: domain:05-engine-ontology}
  - {from: domain:01-direction, to: domain:06-tokenhub}
  - {from: domain:01-direction, to: domain:07-talent}
  - {from: domain:01-direction, to: domain:08-operations}
  - {from: domain:02-transformation, to: domain:03-method}
  - {from: domain:02-transformation, to: domain:04-agents}
  - {from: domain:02-transformation, to: domain:05-engine-ontology}
  - {from: domain:02-transformation, to: domain:06-tokenhub}
  - {from: domain:03-method, to: domain:04-agents}
  - {from: domain:03-method, to: domain:05-engine-ontology}
  - {from: domain:04-agents, to: domain:05-engine-ontology}
  - {from: domain:05-engine-ontology, to: domain:06-tokenhub}
  - {from: domain:07-talent, to: domain:04-agents}
  - {from: domain:07-talent, to: domain:05-engine-ontology}
  - {from: domain:08-operations, to: domain:06-tokenhub}
source: M2-词元云集_2026年8月_Outcome-Mission展开纲领_正式版_v1.1.pdf §十二
```

> 注：`cross-domain.yaml` 不含 `id/type`，校验器（仅加载含 `id` 的实体）会自动跳过它。同时**手工回填**每个 domain 文件的 `depends_on`：
> 01→[02,03,04,05,06,07,08]；02→[03,04,05,06]；03→[04,05]；04→[05]；05→[06]；07→[04,05]；08→[06]。（用完整 id 形式）

- [ ] **Step 7: 运行校验器，确认 0 违规**

Run: `cd /Users/renhaoliu/Desktop/Ontology && python3 tools/validate.py`
Expected: 0 违规（实体数 = 82 + 8 evidence + 1 decision + 1 risk + 1 lesson + 6 wp = 99），退出码 0。

- [ ] **Step 8: 提交**

```bash
cd /Users/renhaoliu/Desktop/Ontology
git add ontology/graph/domain/
git commit -m "feat: 填充示范资产/6 WorkPattern/跨域依赖"
```

---

## Task 9: index.json 生成器（TDD）+ 生成索引

**Files:**
- Create: `tools/build_index.py`
- Modify: `ontology/graph/index.json`（生成产物）

**Interfaces:**
- Consumes: `ontology/schema.yaml`（取关系键名）、`ontology/graph/**/*.yaml`
- Produces: `ontology/graph/index.json`，结构 `{entities:[{id,type,label,file}], edges:[{from,rel,to}], reverse:{to:[{from,rel}]}}`。CLI `python3 tools/build_index.py [graph_dir] [schema] [out]`。

- [ ] **Step 1: 写 `tools/build_index.py`**

```python
#!/usr/bin/env python3
"""扫描 graph/**/*.yaml，生成 index.json（实体清单 + 正向边 + 反向边）。"""
import sys
import os
import glob
import json
import yaml

REL_KEYS = {
    "produces", "rolls_up_to", "owns_outcome", "contains_mission", "supports",
    "has_dri", "has_domain_dri", "belongs_to", "depends_on", "produces",
    "has_decision", "has_risk", "yields_lesson", "instantiates", "based_on",
    "decided_by", "promotes_to", "evidence_for", "raises", "resolved_by",
    "applies_to", "comprises", "pairs_in_cell", "delivers",
    "supports_runtime", "has_role",
}


def load(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build(graph_dir):
    by_id = {}
    entities = []
    for path in sorted(glob.glob(os.path.join(graph_dir, "**", "*.yaml"), recursive=True)):
        d = load(path)
        if not isinstance(d, dict) or "id" not in d:
            continue
        eid = d["id"]
        by_id[eid] = d
        entities.append({
            "id": eid,
            "type": d.get("type"),
            "label": d.get("name") or d.get("title") or eid,
            "file": os.path.relpath(path, graph_dir),
        })
    edges = []
    for eid, d in by_id.items():
        for k, v in d.items():
            if k not in REL_KEYS:
                continue
            for tgt in (v if isinstance(v, list) else [v]):
                if isinstance(tgt, str) and tgt:
                    edges.append({"from": eid, "rel": k, "to": tgt})
    reverse = {}
    for e in edges:
        reverse.setdefault(e["to"], []).append({"from": e["from"], "rel": e["rel"]})
    return {"entities": entities, "edges": edges, "reverse": reverse}


def main(argv):
    graph_dir = argv[1] if len(argv) > 1 else "ontology/graph"
    out = argv[2] if len(argv) > 2 else "ontology/graph/index.json"
    idx = build(graph_dir)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
    print(f"wrote {out}: {len(idx['entities'])} entities, {len(idx['edges'])} edges")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 2: 生成 index.json**

Run: `cd /Users/renhaoliu/Desktop/Ontology && python3 tools/build_index.py`
Expected: 输出 `wrote ontology/graph/index.json: 99 entities, N edges`（N 为所有关系边总数，应 > 100）。

- [ ] **Step 3: 验证反向边可用（抽查）**

Run: `cd /Users/renhaoliu/Desktop/Ontology && python3 -c "import json; d=json.load(open('ontology/graph/index.json')); print(len(d['reverse'].get('person:tiantian',[])), '条反向边指向田田')"`
Expected: 输出 ≥6（03 域 6 个 Mission + domain:03 的 has_domain_dri）。

- [ ] **Step 4: 提交**

```bash
cd /Users/renhaoliu/Desktop/Ontology
git add tools/build_index.py ontology/graph/index.json
git commit -m "feat: 新增 build_index.py 并生成 index.json（正向+反向边）"
```

---

## Task 10: guides/ 原理模板层（7 篇）

**Files:**
- Create: `ontology/guides/01-tkos-overview.md` … `07-consumption-guide.md`

**Interfaces:**
- Consumes: 实例与 schema
- Produces: 面向 Agent 的原理、模板、约束人类可读版、消费路径。内容源自 `Doc/*.pdf`（实现者可对照原文）。

> 写作要求：每篇用二级标题分节，关键判断用列表；所有具体对象/方法名用图谱 id（如 `method:m2-omd`）以便 Agent 跨文件跳转。下面给出 2 篇完整范文与 5 篇结构化大纲（大纲已含真实要点，非占位）。

- [ ] **Step 1: 写 `01-tkos-overview.md`（完整范文）**

```markdown
# TKOS 总览（Agent 指南）

## 一句话定义
TKOS（TokenKing Operating System）是面向「人 + Agent 混合组织」的企业经营操作系统。它管理的是**企业结果如何由人和 Agent 共同实现**，不是人本身、也不是 Agent 本身。

## 四大组成（见 graph/company/system/components/）
- `component:method` Method：经营方法与组织宪法（Outcome/Mission/DRI/Review/复盘）
- `component:agents` Agents：角色化工作入口（一号位/管理者/数字劳动力）
- `component:engine-ontology` Engine & Ontology：企业世界模型 + 运行引擎（状态/权限/事件/回写）
- 三者由 `infra:tokenhub` 提供统一模型与 Token 基础设施支撑运行

## 产品灵魂
- Outcome 与 Mission 为核心，连接战略、责任、决策、执行、Review 与组织学习
- Human accountable, Agent enabled：人承担责任，Agent 增强能力
- 每运行一次 Mission，企业不仅获得结果，也获得更完整上下文与更可复用经验

## TKOS 不是什么
- 不是 ERP/OA/项目管理替代品；可连接它们，但聚焦经营结果与人机协同
- 不是单纯 Agent 开发平台；Agent 编排只是 Engine 一部分
- 不是知识库；Ontology 还表达对象/关系/状态/权限/行动

## 参考实例
- 公司意图：`intent:strategic-intent`
- 8 月公司结果：`outcome:company-2026-08`
- 来源：`Doc/0-词元云集_TKOS总体定义_高管讨论稿_v0.2.pdf`
```

- [ ] **Step 2: 写 `02-method-chain.md`（完整范文）**

```markdown
# 方法主链路（Agent 指南）

## 统一链路
Signal → Issue → 战略自查 → Company Outcome → Domain Outcome → Mission Portfolio 取舍 → DRI 协商与承诺 → 人+Agent 执行 → 异常 Review → 结果验收 → 复盘 → Context 与 Work Pattern 沉淀

## 三层方法（3×3 矩阵的 Method 列）
- `method:m1-sico`（CEO 层）：Signal→Issue→Choice→Outcome，定义战略如何被触发并转化为公司结果
- `method:m2-omd`（DRI 层）：Outcome→Mission→DRI，把结果转成任务与唯一 DRI 承诺
- `method:m3-moer`（IC 层）：Mission→Orchestration→Execution→Result，定义人+数字劳动力协同执行
  - 别名 MEAR（文档命名漂移，本图谱统一 MOER）

## 三个核心概念
1. Outcome：阶段结束必须出现的状态变化（非动作），可被 Evidence 验收。见 `outcome:*`
2. Mission：最小可负责/可承诺/可验收单元，有唯一 DRI、可验收结果、时间边界。见 `mission:*`
3. DRI：对结果（非动作）负最终责任的人，有权异议/协商资源/自主决策

## Review 原则
- 周度 Review 只看偏差、风险、跨域依赖、需 CEO 决策事项；不做流水汇报
- 月度 Portfolio Review 做新增/暂停/调整 Mission 的取舍

## 来源
`Doc/M1-3.词元云集_TKOS方法论框架_正式版_v1.0.pdf`、`Doc/M2.词元云集_AI-Native_Mission工作方法_正式版_v1.1.pdf`
```

- [ ] **Step 3: 写其余 5 篇（按结构化大纲，含真实要点）**

`03-ontology-framework.md`：本体框架——上位锚点（战略宪法/意图/Outcome）→ Domain 划界 → Mission 运行 → 5 类上下文资产（Decision/Evidence/Artifact/Risk/Lesson）→ 关联关系轴 + 时间演化轴；三类数据状态（原始素材→过程产物→当前有效上下文）；治理铁律 Human accountable, Agent enabled。来源 `Doc/E&O1-3...本体建模设计...pdf`。引用 `eo:eo1/eo2/eo3`。

`04-domain-boundaries.md`：五专业域责任拆清——Method 定义规则（不由系统字段倒推）；Agents 做产品入口（不承载本体/Runtime）；Engine&Ontology 承载 Context/状态/权限（不替代 Agents、不建大而全）；TokenHub 基础设施（≠ Engine）；Transformation 应用 Method（不定义通用规则）。来源 `Doc/M2...Outcome-Mission展开纲领...pdf §三`。引用对应 `domain:*`。

`05-mission-card-template.md`：Mission Card 标准字段表（名称/Why/预期 Outcome/成功证据/唯一 DRI/边界/关键路径/里程碑/资源与权限/依赖/人-Agent 分工/风险与升级/复盘沉淀）；标注「task 层启用时使用」。来源 `Doc/M1-3...pdf 附录A`。

`06-constraints.md`：约束人类可读版——结构约束（Mission 唯一 DRI、必支撑 Outcome、Domain Outcome 必 rolls_up_to 公司 Outcome）；治理约束（DRI 必须是人、关键资产须人类确认、权限最小化）；边界规则（TokenHub≠Engine、Method 不由系统字段倒推等 6 条）。与 `schema.yaml` 的 `global_constraints` 一致。

`07-consumption-guide.md`：按推理类型给读取路径（见 spec §9 表格原文）：理解问答读 `system/`+`guides/`；约束校验读 mission 文件对照 `schema.yaml` 基数；状态推理读 `index.json` 反向边；生成读 `guides/05` 模板 + exemplar mission + `wp:*`。

- [ ] **Step 4: 提交**

```bash
cd /Users/renhaoliu/Desktop/Ontology
git add ontology/guides/
git commit -m "docs: 新增 guides 原理模板层（7 篇）"
```

---

## Task 11: task/README + 总 README + 全量校验收尾

**Files:**
- Create: `ontology/graph/task/README.md`
- Create: `ontology/README.md`

**Interfaces:**
- Consumes: 全部产出
- Produces: 导航与消费入口；全量校验通过的证据。

- [ ] **Step 1: 写 `ontology/graph/task/README.md`**

```markdown
# task 层（本次不做）

本层为 **Mission 之下的细粒度执行层**：Task / Action / 步骤 / Agent 子任务。

**为何本次不做**：TKOS 文档明确「不以 Task 为核心层级」——Task 易把系统带向微观清单管理，
弱化对经营结果的关注（见 `Doc/E&O1-3...本体建模设计...pdf §四`）。

**何时启用**：当某个 Mission 的执行步骤需要被 Agent 编排、跟踪、回写时，
在此目录建立 `actions/*.yaml`，复用 `schema.yaml` 的对象约定（建议新增 `Action` 类型）。

**启用顺序**：先在 `schema.yaml` 定义 Action 类型与 Mission→Action 关系 → 选 1 个真实 Mission 试点 → 沉淀为 Work Pattern。
```

- [ ] **Step 2: 写 `ontology/README.md`**

```markdown
# TKOS 上下文图谱

一套从 TKOS 设计文档提取的、可被 Agent 直接读取的结构化知识图谱。

## 结构
- `schema.yaml` — 规则层：19 类实体 + 关系 + 基数 + 约束
- `graph/company/` — 战略层（战略意图、公司 Outcome、TKOS 系统结构）
- `graph/domain/` — 业务层（8 Domain、Domain Outcome、37 Mission、示范资产、6 Work Pattern、跨域依赖）
- `graph/task/` — 本次不做（Mission 之下执行层）
- `graph/index.json` — 遍历层（正向 + 反向边，脚本生成）
- `guides/` — 原理模板层（7 篇 Agent 指南）

## Agent 如何消费（按推理类型）
| 想做的事 | 读什么 |
|---|---|
| 理解/问答（如「M2 OMD 是什么」） | `graph/company/system/methods/m2-omd.yaml` + `guides/02-method-chain.md` |
| 约束校验（「Mission 有唯一 DRI 吗」） | 读该 mission 文件 → 对照 `schema.yaml` 基数 |
| 状态推理（「调整 X 影响谁」） | `graph/index.json` 的 `reverse` 字段查反向边 |
| 设计生成（「为新 Outcome 设计 Mission」） | `guides/05-mission-card-template.md` + 一个 exemplar mission + 相关 `wp:*` |

## 校验
运行 `python3 tools/validate.py` 应输出 `0 处违规`。
重建索引：`python3 tools/build_index.py`。

## 边界
实例层 = 8 月基线「按设计应然」状态，非已完成工作记录。
资产层（decisions/evidence/artifacts/risks/lessons）多为示范 + 目标型（`status: target`），运行中填充。
```

- [ ] **Step 3: 全量校验 + 重建索引**

Run:
```bash
cd /Users/renhaoliu/Desktop/Ontology
python3 tools/validate.py && echo "VALIDATION OK"
python3 tools/build_index.py
python3 -m unittest tools.tests.test_validate -v
```
Expected: validate 输出 `0 处违规` 且 `VALIDATION OK`；index 重建成功；8 个单元测试全绿。

- [ ] **Step 4: 提交**

```bash
cd /Users/renhaoliu/Desktop/Ontology
git add ontology/graph/task/README.md ontology/README.md
git commit -m "docs: 新增 task/README 与总 README，全量校验通过"
```

---

## 自检（Self-Review 结果）

1. **Spec 覆盖**：四层架构（schema/graph/index/guides）→ T2/T3/T9/T10；19 类型 → T3；关系+基数 → T3 schema；三层约束 → T3 schema + T10 guide06；company/domain/task 划分 → T4–T8 + T11；ID 约定 → Global Constraints；诚实资产边界 → T8；Agent 消费路径 → T11 README + T10 guide07。✅ 无遗漏。
2. **占位扫描**：所有步骤含完整代码或完整数据表；5 篇 guide 大纲含真实要点（非 TBD）。✅
3. **类型/命名一致性**：`has_dri`/`supports`/`belongs_to`/`has_domain_dri`/`owns_outcome`/`contains_mission`/`depends_on` 在 schema、实例、index REL_KEYS、依赖回填中一致；`eo:` 前缀全局统一；MOER/MEAR 以别名处理。✅
4. **实体计数**（已校正贯穿全计划）：T4=6 → T5=23（+17 system）→ T6=45（+8 domain/8 outcome/6 person）→ T7=82（+37 mission）→ T8=99（+8 evidence/1 decision/1 risk/1 lesson/6 wp）。各 Task 校验步骤以「0 违规」为准，精确计数由脚本输出。
```
