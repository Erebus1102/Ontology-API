# 服务代码边界

本目录用于后续可部署实现。

```text
api/          HTTP 与 Agent/MCP 接口
application/  Context、蒸馏、溯源和提交用例
domain/       与框架无关的契约、状态和规则
adapters/     RDF Store、LLM、对象存储、任务队列和身份系统
```

当前尚无可部署服务代码。实现第一条 API 前，需要确定 RDF Store、身份输入、组织 Scope Policy、Release 格式和 Context Pack JSON Schema。
