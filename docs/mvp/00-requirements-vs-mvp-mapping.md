# 核心文档〇：改进需求与 MVP 对照

状态：v1（2026-08-13，由根目录草稿《改进需求.md》整理而来）
定位：把一号位的原始改进需求逐条与权威设计 `docs/mvp/01-04` 对照，确认"哪些已被覆盖、落在哪里、哪些仍是 gap"。本文件与 `docs/mvp/01-04` 冲突时以上游为准。
来源：三份飞书源材料已于 2026-08-13 拍板蒸馏为 `docs/mvp/01-03`（见 `docs/architecture/2026-08-13-mvp-requirements-clarification.md`）。**源链接已脱敏**，仅保留材料名称，不含任何登录凭据。

---

## 1. 三份源材料 → MVP 文档映射

| 源材料（飞书） | 草稿评注 | 蒸馏落点 |
|---|---|---|
| 本体 MVP 时序图 & Glossary | Glossary 尚不完善标准 | `docs/mvp/01`（统一语言 + 闭环时序图）—— 术语表已消解三分裂 |
| 本体设计方案 | 整体逻辑健全；类/属性/关系不清晰 | `docs/mvp/02`（本体 V3.0：核心集 ~47 类、关系最简、存留判据） |
| 产品场景介绍 + 蒸馏所需材料 | 场景待完善、所需材料不够明确 | `docs/mvp/01 §5`（四场景）+ `docs/mvp/03 §1`（蒸馏）—— **场景材料清单仍是 gap，见 §5** |

> 拍板结论已生效：三份源材料与 `docs/mvp` 冲突时以 `docs/mvp` 为准并回改源材料。

---

## 2. 草稿需求逐条对照

### 2.1 本体结构理解（业务人视角）

| 草稿要点 | MVP 覆盖 | 落点 |
|---|---|---|
| 个人本体 / 公司本体两套 | ✅ 已定 | `docs/mvp/02 §1`：TKOS 领域层 = 企业事项包（Company）＋ 个人决策本体包（Persona），双 Ontology IRI |
| 公司本体分层：战略域/业务域 → 公司宪法/公司现实 → 公司愿景/组织架构/战略内容 | ✅ 已定 | `docs/mvp/02 §2`：宪法簇（6）/ 现实簇（5）/ 方法簇（2）/ `Product`（1）；`docs/mvp/02 §9` 三种加载模式 |
| Protégé 可展开的业务人可读视图 | 🟡 部分 | `ontology/views/tkos-ontology-protege-view.ttl` 有去 imports 副本；**业务人可读的分层视图打磨仍是 gap（§5）** |
| 本体尽量简单：公司 / 个人决策蒸馏 / 业务域 | ✅ 已定 | `docs/mvp/02 §5`：非必要勿增类、不进核心集即物理删（V3.0 手术哲学） |

### 2.2 多租户与访问控制

| 草稿要点 | MVP 覆盖 | 落点 |
|---|---|---|
| 不同 `TKOS_API_KEY` 访问不同本体空间（词元云集 vs 灯塔） | ✅ 已定 | `docs/mvp/02 §1/§7`：租户实例层，词元云集/房懂懂/AIDC 独立 Key+图，灯塔为跨组织协作作用域；`docs/mvp/03 §2`：Key 即租户 |
| Judgement 多版本：`v0→v1→v2→agreement` | ✅ 已定 | `docs/mvp/01 §3/§2`：Judgement 经 `supersedes` 成链、版本不可变；Agreement 落盘 |
| **时序可见性**：CXO Agent 看时序全版本；执行层 DRI 只看最新 Judgement 或 Agreement | ✅ 已定 | `docs/mvp/01 §4`：cxo 全版本链 + Agreement；executor 仅 Agreement / 链头；被裁剪版本进 `omissions[stage=temporal_projection]`（参考 PLTR 时序本体概念） |
| 需设计 Agent 角色标签（CXO / DRI） | ✅ 已定 | `docs/mvp/03 §2`：Key 解析 `role: cxo\|executor` |

> **本轮（2.0 基座）落地项**：Key 模型 `role`/`tenant`/`on_behalf_of` + **tenant→图作用域接线（必做，非预留）** → 见 `docs/mvp/04 §4`。时序投影的 lineage 遍历在迭代 1 交付。

### 2.3 MVP 闭环与本体分层

| 草稿要点 | MVP 覆盖 | 落点 |
|---|---|---|
| 最小 MVP 链路：Signal→Issue→Research→Artifact→Judgement(多版本)→战略会议多轮→Agreement→Mission 创建承接→Mission 运行 | ✅ 已定 | `docs/mvp/01 §1`（同一闭环时序图）+ §2（术语表），验收载体 = 产品 1.0 + 灯塔同季交付 |
| 本体三层：公共层 → TKOS 领域层 → 租户实例层 | ✅ 已定 | `docs/mvp/02 §1`（公共层 / TKOS 领域层 / 租户实例层） |

---

## 3. 六层技术架构（草稿新提出，**部分 gap**）

草稿提出比现行五层更细的技术分层（`CLAUDE.md`/`README` 现为五层）：

```text
Layer 6  Agent Layer     CEO Agent / 数字员工 / COO Agent（公司 TKOS 自进化）/ CO Agent（PMO：company/domain/mission outcome 洞察与管理）
Layer 5  Access Layer    TKOS Engine（Agent 权限管理、上下文管理，与 COO Agent 强相关）
Layer 4  Reasoning Layer 推理机 & LLM 自然语言化
Layer 3  Ontology Layer  本体关系
Layer 2  KG Layer        实例数据
Layer 1  Enterprise Data 原始数据（业务文档 / ERP / CRM）
```

**与现状对照**：
- L1–L5 与现行五层架构一致（语义可对齐）。
- **L6 Agent Layer（含 COO 自进化 / CO-PMO 角色细分）是草稿新增**，`docs/mvp` 未展开——**gap**。
- **意图识别归层未定**（草稿明确"还没想好"）：现行实现位于 Layer 4（`GramIntentResolver`）。

**建议**：以一份 ADR 或架构文档将六层（含 Agent 角色标签）与五层对齐，明确意图识别归层，再决定是否拆 L6。本轮不做。

---

## 4. 开放问题（草稿"要求和目标"）逐条状态

| 草稿问题 | 当前状态 / 落点 |
|---|---|
| 从根源质疑设计/部署/应用是否科学优雅；是否不该用 API 提供这能力 | 已有定论：Runtime 调用方 = 平台后端（Agent 编排层），终端 LLM Agent 不直连（`docs/mvp/03` 设计原则）；薄请求厚响应 |
| **过度设计，需优化**；不是搭完美鲁棒 API，而是可扩展、支持最小场景 | 直接对齐 `docs/mvp/02 §5`（V3.0 删类）+ `docs/mvp/04` 工作流 A（本体手术）/ B（契约收敛）；本轮正在收敛 |
| 存储是否需要数据库/文件系统，还是 trig 就够 | 现状：rdflib Dataset + `.trig` 命名图，进程内零新增依赖。MVP 阶段 trig 够用；生产 RDF Store 为"待实现"选项，非 MVP 必须 |
| **API 出入参太复杂** | 直接对齐 `docs/mvp/03` v1（薄请求）+ `docs/mvp/04` 工作流 B：移除 `enterprise_id`/`purpose` 等、Key 推导作用域、render 并入 resolve |
| API 边界、各自出入参、背后时序图需明确 | `docs/mvp/03` 已定 3 业务端点边界 + 出入参；`§5` 要求每端点补 L5/L4/L2 时序图（本轮 B 交付） |
| 积极外部研究、论文阅读 | 开放；PLTR 时序本体概念已体现在 `docs/mvp/01 §4` 时序投影 |

---

## 5. 真正的 Gap（MVP 未覆盖，待补）

1. **业务文档蒸馏 → 本体实例的链路未设计**：`docs/mvp/03 §1` 仅给出 CLI 流水线概念（SourceSnapshot→CandidateAssertionBatch），无异步 Job、无实体消歧/组织定位的工程化设计；升级为 API 2 的触发条件 = 第二个高频蒸馏租户接入。→ 2.0 之后。
2. **六层 Agent 架构 + Agent 角色标签细化**（COO 自进化、CO-PMO）：见 §3。→ 需 ADR。
3. **意图识别归层**未定。→ 需决策（现行 Layer 4）。
4. **场景材料清单不明确**：源材料 3"蒸馏所需材料"未穷举。→ 业务侧补全。
5. **Protégé 业务人可读分层视图**打磨。→ 工程侧。

---

## 6. 与当前迭代（Runtime 2.0 基座）的对应

| 草稿关切 | 2.0 工作流 | 文档 |
|---|---|---|
| 本体过度设计 / 不清晰 | **A · V3.0 本体手术**（补 3 类、删冗余、核心集 ~47） | `docs/mvp/04 §2` |
| API 太复杂 | **B · v1 契约对齐**（薄请求、Key 推导、render 并入） | `docs/mvp/04 §3` |
| 多租户 + 时序角色 | **C · Key 模型**（tenant/role/on_behalf_of + tenant→图接线） | `docs/mvp/04 §4` |
| 蒸馏链路 / 六层 Agent 架构 | 2.0 之后 | §5 gap 1-3 |

**结论**：草稿的大部分关切已被 `docs/mvp/01-03` 覆盖；本轮 2.0 基座直接兑现"简化本体 / 简化 API / 多租户时序角色"三项核心诉求。真正未覆盖的是蒸馏链路工程化与六层 Agent 架构，列入 2.0 之后。
