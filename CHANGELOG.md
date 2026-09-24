# 更新日志

本文件记录本项目所有值得注意的变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.4.0]

### 新增

- **服务端会话与 checkpointer**：主图编译时携带 checkpointer（`CHECKPOINTER=memory|sqlite`），会话按 `thread_id` 持久化。`POST /api/chat` 与 `POST /api/vision-chat` 接受可选的 `thread_id`，每条 SSE 流的第一个事件固定为 `{"type": "session", "thread_id": …}`；带已知 `thread_id` 的请求只需要发送最新一条用户消息。详见 `docs/langgraph-runtime.md`。
- **预问诊子图**：`clinic_node` 从一次 ReAct 调用改写为拥有独立 `ClinicState` 的编译子图——代码级急症闸门（`emergency_gate`，纯规则匹配、不依赖模型是否愿意调用工具）、结构化症状抽取、确定性的信息充分度判断、基于 `interrupt()` 的追问与恢复，以及 `conclude` 节点的分诊结论。
- **`interrupt` 事件**：追问挂起时后端先发普通 `text` 气泡，再发 `{"type": "interrupt"}` 标记；用户在同一 `thread_id` 上回复即可恢复。挂起期间说出退出词不会被当成回答。
- **后端驱动的 `clinic_recommendation` 卡片**：分诊建议（科室、紧急度、注意事项）由后端结构化输出并推送，前端 `ChatCardRenderer` 直接渲染。
- **Agent 之间的 `Command` 转接（handoff）**：新增 `backend/agents/handoff.py`。每个专科都持有指向其余四个专科的 `transfer_to_*` 工具；触发后节点返回 `Command(goto=…)`（clinic 子图用 `Command(graph=Command.PARENT, …)`），主图在**同一轮**里把这条用户消息交给正确的专科。`MainAgentState.handoff_count` 把预算限制为每轮 1 次，防止来回弹球。`graph.py` 用 `destinations=` 注册节点，转接边会出现在 `get_graph()` 的图里。
- **测试**：新增 `test_handoff.py`、`test_cards.py`、`test_clinic_graph.py`、`test_graph_build.py` 与共享假模型 `test_fakes.py`，全部确定性、不联网。

### 变更

- **卡片改由 Agent 自己推送**：删除 `main.py` 的 `_INSURANCE_TOOL_TO_CARD_TYPE`、`_REPORT_TOOL_TO_CARD_TYPE` 与 `agents/pharmacy.py` 的 `PHARMACY_TOOL_TO_CARD_TYPE` 三张"工具名 → 卡片类型"字典，以及 `on_tool_end` 上的卡片解析分支。医保与药品的卡片改由工具内部经 `agents/streaming.py` 的 `emit_card()` 推送；`report_analysis` 由 `report_node` 在节点层补发（该技能为 clinic 共用，不改技能注册表）。SSE 事件类型与卡片 payload 形状均未改变。
- **退出词匹配收紧**：`is_exit_request()` 由自由子串匹配改为锚定匹配——整句等于退出词，或以退出词开头且紧跟标点/空白。`我想取消明天的预约`、`这个药不用了吗` 等正常语句不再意外退出专科模式。
- 专科模式锁（`active_agent` 短路）保留，但不再是"只能靠退出词解锁"：跑错专科时由转接机制纠正。
- 新增 `agents/streaming.py`，统一 custom 流的写入入口；`clinic.py` 的 `_emit` 改为它的别名。缺少 writer（图外调用）时静默跳过。
- 文档：新增 `docs/langgraph-runtime.md`，重新生成 `docs/images/graph.mmd`，并更新 `CLAUDE.md` 的架构、卡片与"新增 Agent"章节。

### 修复

- 关闭服务时释放 checkpointer 的底层连接（sqlite 后端）。
- 自定义流写入器在图运行之外会抛出 `KeyError('__pregel_runtime')` 而非 `RuntimeError`，导致工具在脚本/测试里直接调用时报错；现已统一兜底。

## [0.3.0]

LangGraph 多智能体基线：Router + clinic / insurance / report / pharmacy / advisor 五个专科节点、SSE 流式接口（`text`、`node_start`/`node_end`、`tool_start`/`tool_end`、`card`、`finish`、`error`）、混合检索 RAG 知识库（BM25 + Dense MMR）、自动发现的 Agent Skills 体系、多模型供应商配置（`agents/llm.py`）、视觉识别接口 `POST /api/vision-chat`，以及 observability / evals 支持。
