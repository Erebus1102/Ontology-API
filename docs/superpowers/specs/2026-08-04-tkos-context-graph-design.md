# TKOS 上下文图谱设计（Context Graph Design）

- **日期**：2026-08-04
- **状态**：已确认，待实现
- **范围**：从 Doc/ 下 6 份 TKOS 设计文档中提取业务设计的逻辑关系，构建一个**能被 Agent 直接读取、作为高质量上下文**的结构化图谱。

---

## 1. 目标与约束

### 1.1 目标
构建一个文件化的知识图谱，编码 TKOS 业务设计中的**实体、关系与约束**，使 Agent 在推理（理解问答、一致性校验、经营状态推理、设计与生成辅助）时能获得准确、可追溯、可校验的上下文，从而提升推理准确率。

### 1.2 已确认约束
| 约束 | 取值 |
|---|---|
| 消费方式 | **结构化文件，Agent 直接读取**（无数据库、无检索服务） |
| 推理用途 | 理解问答 + 一致性/约束校验 + 经营状态推理 + 设计/生成辅助（全部覆盖） |
| 项目状态 | 全新（当前目录无代码、非 git 仓库） |
| 语言 | 内容用中文，schema 键名/类型名用英文 |
| 表达形态 | 方案 A：分层文件本体（YAML schema + YAML/JSON 实例 + Markdown 原理模板） |

### 1.3 核心设计判断
图谱的灵魂句（源自文档）：**TKOS 管理的不是人，也不是 Agent，而是企业结果如何由人和 Agent 共同实现。** 图谱围绕"结果（Outcome）—任务（Mission）—责任（DRI）"这条主线建模。

---

## 2. 总体架构（四层，对应四类推理）

```
ontology/
├── schema.yaml            ① 规则层   → 约束校验
├── graph/                 ② 实例层   → 状态推理
│   └── index.json         ③ 遍历层   → Agent 快速跳转/子图提取
└── guides/*.md            ④ 原理模板层 → 理解问答 + 生成
```

每个实例文件同时承载：**类型化关系**（机器可判）+ **rationale（为什么）**+ **source（出处溯源）**。后者落实本体设计文档要求的"来源追溯"。

---

## 3. 实体类型目录（19 类，分 5 组）

### 3.1 A 组 · 经营骨架（Operating Backbone）——图谱核心
| 类型 | 中文 | 关键属性 | 归属层 |
|---|---|---|---|
| `StrategicIntent` | 战略意图 | direction, non_negotiables | company |
| `Outcome` | 结果 | **level**: company\|domain, success_evidence, rolls_up_to | company / domain |
| `Domain` | 经营域 | boundary, scope | domain |
| `Mission` | 任务 | expected_result, deadline, status | domain |
| `Signal` | 信号 | source, credibility | company |
| `Issue` | 战略议题 | decision_owner, urgency | company |

### 3.2 B 组 · 责任与角色（Accountability & Actors）
| 类型 | 中文 | 说明 | 归属层 |
|---|---|---|---|
| `Person` | 个人 | 真实责任人（刘明华、田田…） | company / domain |
| `Role` | 角色 | CEO / DomainDRI / MissionDRI / IC | 跨层 |

### 3.3 C 组 · 上下文资产（Mission Context Assets）
| 类型 | 中文 | 核心价值 | 归属层 |
|---|---|---|---|
| `Decision` | 决策 | 保留判断逻辑 | domain |
| `Evidence` | 证据 | 区分观点与事实，支撑验收 | domain |
| `Artifact` | 产物 | 可复用交付物 | domain |
| `Risk` | 风险/问题 | 帮 Agent 识别偏差 | domain |
| `Lesson` | 经验/洞见 | 使组织不重复犯错 | domain |

### 3.4 D 组 · 系统与产品结构（TKOS System Structure）
| 类型 | 中文 | 实例 | 归属层 |
|---|---|---|---|
| `TKOSComponent` | TKOS 顶层组成 | Method / Agents / Engine&Ontology | company |
| `MethodPattern` | 方法模式 | M1 SICO / M2 OMD / M3 MOER | company（带 `operates_at`） |
| `AgentProduct` | Agent 产品 | A1 一号位 / A2 管理者 / A3 Co-agent / A4 数字劳动力 | company（带 `operates_at`） |
| `OntologyCapability` | 本体能力层 | E&O1 战略本体 / E&O2 经营本体+引擎 / E&O3 执行本体+引擎 | company（带 `operates_at`） |
| `TransformationPhase` | 转型阶段 | T1 认知破局 / T2 组织重构贯通 / T3 共营固化 | company |
| `Infrastructure` | 基础设施 | TokenHub | company |

### 3.5 E 组 · 可复用资产
| 类型 | 中文 | 说明 | 归属层 |
|---|---|---|---|
| `WorkPattern` | 工作模式 | 被反复验证的标准方法 | domain |

---

## 4. 关系类型（带方向与基数 `[min, max]`）

### 4.1 层级与归属（骨架）
| 关系 | 方向 | 基数 | 语义 |
|---|---|---|---|
| `produces` | StrategicIntent → Outcome | `[0,*]` | 战略意图产生结果 |
| `rolls_up_to` | Outcome → Outcome | `[0,1]` | Domain Outcome 汇聚到 Company Outcome |
| `owns_outcome` | Domain → Outcome | `[0,*]` | 域负责的结果 |
| `contains_mission` | Domain → Mission | `[0,*]` | 域包含的任务 |
| `supports` | Mission → Outcome | **`[1,*]`** | 任务支撑结果（必≥1） |
| `has_dri` | Mission → Person | **`[1,1]`** | 唯一直接负责人 |
| `has_domain_dri` | Domain → Person | **`[1,1]`** | 域唯一 DRI |

### 4.2 跨域依赖（状态推理关键）
| 关系 | 方向 | 基数 | 语义 |
|---|---|---|---|
| `depends_on` | Mission → Mission | `[0,*]` | 任务间依赖 |
| `depends_on` | Mission → Domain | `[0,*]` | 任务依赖某域能力 |
| `depends_on` | Domain → Domain | `[0,*]` | 域间依赖（如 05→02/03/04） |

### 4.3 上下文资产
| 关系 | 方向 | 基数 | 语义 |
|---|---|---|---|
| `produces` | Mission → Evidence/Artifact | `[0,*]` | 产出证据/产物 |
| `has_decision` | Mission → Decision | `[0,*]` | 关联决策 |
| `has_risk` | Mission → Risk | `[0,*]` | 关联风险 |
| `yields_lesson` | Mission → Lesson | `[0,*]` | 沉淀经验 |
| `based_on` | Decision → Evidence | `[0,*]` | 决策基于证据 |
| `decided_by` | Decision → Person | `[1,1]` | 谁确认的决策 |
| `promotes_to` | Lesson → Domain/StrategicIntent | `[0,*]` | 经验提升到更高层 |
| `evidence_for` | Evidence → Outcome | `[0,*]` | 证明哪个结果 |

### 4.4 战略流（SICO）与复用
| 关系 | 方向 | 基数 | 语义 |
|---|---|---|---|
| `raises` | Signal → Issue | `[0,*]` | 信号提出议题 |
| `resolved_by` | Issue → Decision/Outcome | `[0,*]` | 议题如何被解决 |
| `instantiates` | Mission → WorkPattern | `[0,*]` | 任务复用了某工作模式 |
| `applies_to` | WorkPattern → 问题类型 | `[0,*]` | 模式适用场景 |

### 4.5 系统结构（3×3 矩阵 + 架构）
| 关系 | 方向 | 语义 |
|---|---|---|
| `comprises` | TKOSComponent → 子能力 | Method/Agents/Engine&Ontology 的组成 |
| `operates_at` | MethodPattern/AgentProduct/OntologyCapability → Level | 还原 3×3 的行（ceo/dri/ic） |
| `pairs_in_cell` | (MethodPattern, AgentProduct, OntologyCapability) | 同一 3×3 格的三件套（如 M2+A2+E&O2） |
| `delivers` | TransformationPhase → TKOSComponent | T1/T2/T3 各交付哪层 |
| `supports_runtime` | Infrastructure → TKOS | TokenHub 支撑运行 |
| `maps_to_steps` | TransformationPhase → 九步法区间 | T1=1–4 / T2=5–7 / T3=8–9 |

---

## 5. 约束规则（三类）

### 5.1 结构约束（声明式基数，机器可判）
- `Mission.has_dri` 必须且仅一个 Person
- `Mission.supports` 必≥1 Outcome
- `Mission.belongs_to` 必=1 Domain
- `Outcome` 若 level=domain，必 `rolls_up_to` 一个 company Outcome
- `Decision.decided_by` 必=1 Person

### 5.2 治理约束（Human accountable, Agent enabled）
- DRI 必须是 `Person`，**Agent 不得成为责任主体**（仅 `AgentProduct` 作为执行能力）
- 关键 Decision / Lesson / Evidence 进入正式上下文前须有 `confirmed_by`（人类确认）
- 权限以 Domain/Mission/角色为基础，最小化授予

### 5.3 边界规则（来自文档"责任拆清"，防混淆）
- Method **不由系统字段倒推经营逻辑**（方法先于工具）
- Agents **不承载企业本体和底层 Runtime**
- Engine & Ontology **不替代 Agents，不提前建大而全平台**
- TokenHub **≠ TKOS Engine**（基础设施，不混用）
- Transformation **不定义通用 Method**
- 执行纪律：任何新增公司级事项，必声明支持哪个 Outcome + 替代哪个既有 Mission + DRI 是谁

---

## 6. 文件结构（按业务层级划分）

```
ontology/
├── README.md                  # 导航 +「Agent 如何消费」指南
├── schema.yaml                # ① 规则层：19 类型 + 关系 + 基数 + 约束
├── graph/
│   ├── company/               # ── 战略层 ──
│   │   ├── intent/            #   战略意图 / 战略宪法
│   │   ├── outcomes/          #   公司级 Outcome
│   │   ├── signals/           #   信号（SICO 输入；8 月基线多为概念性，少量实例）
│   │   ├── issues/            #   战略议题（需判断/选择的问题；少量实例）
│   │   ├── people/            #   刘明华（CEO + Transformation Owner）
│   │   └── system/            #   TKOS 系统结构 IP
│   │       ├── components/    #     Method / Agents / Engine&Ontology
│   │       ├── methods/       #     M1 SICO / M2 OMD / M3 MOER
│   │       ├── agents/        #     A1–A4
│   │       ├── ontology/      #     E&O1–3
│   │       ├── transformation/#     T1–T3 + 九步法映射
│   │       └── infrastructure/#     TokenHub
│   ├── domain/                # ── 业务层 ──
│   │   ├── domains/           #   8 个 Domain（含边界/范围）
│   │   ├── outcomes/          #   各 Domain Outcome
│   │   ├── people/            #   6 位 Domain DRI
│   │   ├── missions/          #   Mission 实例（按归属编号，如 03-3.yaml）
│   │   ├── assets/            #   decisions/evidence/artifacts/risks/lessons
│   │   ├── work-patterns/     #   Work Pattern
│   │   └── dependencies/      #   跨域依赖
│   ├── task/                  # ── 本次不做 ──
│   │   └── README.md          #   Task/Action 细粒度执行层（文档本身不建议建模）；占位说明
│   └── index.json             # 索引 company + domain 全部边（含反向边）
└── guides/
    ├── 01-tkos-overview.md            # TKOS 是什么、四组件、产品灵魂
    ├── 02-method-chain.md             # 方法主链路 SICO/OMD/MOER
    ├── 03-ontology-framework.md       # 本体框架（Domain/Mission/资产/关系/时间）
    ├── 04-domain-boundaries.md        # 五专业域责任拆清
    ├── 05-mission-card-template.md    # Mission Card 模板（task 层启用时使用）
    ├── 06-constraints.md              # 约束规则人类可读版
    └── 07-consumption-guide.md        # 按推理类型给读取路径
```

**切片原则**：骨架与资产**一实体一文件**（Agent 可只读它需要的那一个）；系统结构量少且成组，用分组目录文件。

**3×3 层级用数据字段保留**：`methods/agents/ontology` 下的实体均属 company/system（设计 IP），但每个带 `operates_at: ceo|dri|ic` 字段，保留"M2 对应 DRI 层"等语义，不拆散目录。

---

## 7. ID 与命名约定

- 格式：`<type>:<slug>`，全小写连字符，稳定不变。
- 示例：`domain:03-method`、`mission:03-3`、`outcome:method-2026-08`、`person:tiantian`、`method:m2-omd`、`agent:a1-ceo`、`e&o:e&o2`、`phase:t2`、`infra:tokenhub`、`wp:ceo-operating-meeting`、`decision:d-001`。
- **每个实体带 `source` 字段**指向文档+章节（如 `M2-outcome-mission-v1.1.pdf §03`），落实来源追溯。
- Mission 文件名沿用文档编号（`03-3.yaml`），保证人与文档对得上。

---

## 8. 实例填充范围（诚实边界）

从文档能**确定性提取**的、作为设计已确定的实例：

| 范围 | 内容 | 数量级 | 层 |
|---|---|---|---|
| 战略意图 | 公司方向（AI 原生企业经营 OS；3+2→TKOS） | 1 | company |
| 公司级 Outcome | 8 月公司总 Outcome | 1 | company |
| Domain | 8 域 + 各域 Outcome + Domain DRI | 8 | domain |
| Mission | 8 月纲领全部关键 Mission（结果/DRI/验收证据） | 37 | domain |
| People | 7 位命名 DRI | 7 | company/domain |
| 跨域依赖 | 8 月纲领第十二章依赖表 | ~8 边 | domain |
| 系统结构 | 组件 + M1-3 + A1-4 + E&O1-3 + T1-3 + TokenHub | ~15 | company |
| Work Pattern | 方法论框架第九章候选清单 | 6 | domain |

**资产层（assets/）的诚实处理**：文档是**设计稿**，不是运行记录——大部分资产尚未发生。
- 各 Mission 的"关键验收证据"建模为**目标型 Evidence**（`status: target`，aspirational）。
- Decision / Risk / Lesson 只放**少量示范实例** + schema，其余留空槽，标注"运行中填充"。
- 保证图谱不因编造内容而误导推理。

> 实例层 = **8 月基线"按设计应然"的状态**（已规划 Mission、目标 Outcome、已指派 DRI、目标证据），**不是**已完成工作记录。

---

## 9. Agent 消费路径（README 与 guides/07 详述）

| Agent 想做的事 | 读取路径 |
|---|---|
| 「M2 OMD 是什么？」 | `graph/company/system/methods/` + `guides/02` |
| 「Mission X 合法吗（有唯一 DRI 吗）？」 | 读该 mission 文件 → 对照 `schema.yaml` 基数 |
| 「调整 Mission X 会影响谁？」 | `index.json` 查 `depends_on` 的**反向边** |
| 「为新 Outcome 设计 Mission」 | `guides/05` 模板 + 一个 exemplar mission + 相关 `wp:*` |

---

## 10. 关键建模决策（已与用户确认）

1. **`Outcome` 用单类型 + `level` 字段**，而非拆成 CompanyOutcome/DomainOutcome/MissionResult 三个类型。同概念不同层级，`level` + `rolls_up_to` 即可表达。
2. **`Issue` 单独建模为战略议题**（SICO 的"需判断/选择的问题"），资产层"运营问题"并入 `Risk`。
3. **TKOS 系统结构（D 组）建为实体**：3×3 矩阵、四组件、Transformation→TKOS→TokenHub 架构本身是设计逻辑的一部分。
4. **graph/ 按业务层级（company/domain/task）划分**：Mission 属 domain；task（Mission 之下细粒度执行层）本次不做，与文档"不以 Task 为核心层级"一致。

---

## 11. 范围外 / 延后

- **task 层**：Task / Action / 步骤 / Agent 子任务（Mission 之下的执行细节），本次不建模。
- **运行态资产填充**：Decision/Evidence/Artifact/Risk/Lesson 的真实运行数据，留空槽待运行填充。
- **检索服务 / 图数据库 / MCP 工具层**：本次只产出文件；未来可零迁移包装为检索层或导入图库。

---

## 12. 成功标准

1. schema.yaml 完整定义 19 类实体、全部关系与基数、三类约束，可被脚本校验。
2. graph/ 下 company + domain 实例按 8 月基线填充，每个实体有 `source` 溯源。
3. 任意一个"文档已确定"的事实（如某 Mission 的 DRI、某域的 Outcome、M2 与 DRI 层的对应）都能在图谱中找到且唯一。
4. index.json 含正向 + 反向边，支持"调整 X 影响谁"类查询。
5. guides/ 覆盖理解问答与生成所需的原理、模板、约束人类可读版。
6. README 给出按推理类型的消费路径，Agent 照路径读取即可获得高质量上下文。

---

## 附录 A：实例文件样板（Mission）

```yaml
# graph/domain/missions/03-3.yaml
id: mission:03-3
type: Mission
name: 完成 DRI 协商与承诺
domain: domain:03-method
supports: [outcome:method-2026-08]      # 关系：必≥1
has_dri: person:tiantian                # 唯一 DRI（约束 [1,1]）
status: planned                         # proposed|committed|in_progress|blocked|completed|terminated
expected_result: 确认唯一 DRI、结果、路径、资源、权限和升级规则
deadline: 2026-08-31
depends_on: []                          # 运行中补（反向边进 index.json）
produces: []
has_decision: []
has_risk: []
yields_lesson: []
instantiates: []                        # 可挂 wp:*
source: M2-outcome-mission-v1.1.pdf §03
rationale: |                            # 「为什么」——喂推理
  Mission 非自上而下派单。候选 DRI 须评估定义/资源/时间/权限/风险，必要时
  修改或拒绝承诺。承诺成立最低条件：清楚 Outcome 与成功标准、认可或修订路径、
  获得资源与权限、明确依赖与升级条件、愿意对结果而非动作负责。
```

## 附录 B：schema.yaml 结构示意

```yaml
version: 1
entity_types:
  Mission:
    description: 最小可负责、可承诺、可验收的经营单元
    attributes:
      name: {type: string, required: true}
      expected_result: {type: string, required: true}
      deadline: {type: date, required: true}
      status: {type: enum, values: [proposed, committed, in_progress, blocked, completed, terminated], required: true}
    relations:
      supports: {target: Outcome, cardinality: [1,*], required: true}
      has_dri: {target: Person, cardinality: [1,1], required: true}
      belongs_to: {target: Domain, cardinality: [1,1], required: true}
      depends_on: {target: [Mission, Domain], cardinality: [0,*]}
      produces: {target: [Evidence, Artifact], cardinality: [0,*]}
      has_decision: {target: Decision, cardinality: [0,*]}
      has_risk: {target: Risk, cardinality: [0,*]}
      yields_lesson: {target: Lesson, cardinality: [0,*]}
    constraints:
      - "dri must be a Person, not an Agent (Human accountable, Agent enabled)"
      - "must support at least one Outcome"
  # ... 其余 18 类同结构
global_constraints:   # 跨实体边界规则
  - "TokenHub != TKOS Engine"
  - "Method rules are not derived from system fields"
  - "New company-level item must declare: supports Outcome + replaces Mission + DRI"
```
