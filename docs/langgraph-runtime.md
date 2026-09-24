# LangGraph 运行时：Checkpointer、thread_id、预问诊子图与 Agent 转接

本项目的主图不再是"路由 → 一层 Agent → END"的星形结构。主图编译时携带 checkpointer，会话状态按 `thread_id` 持久化在服务端；预问诊（clinic）不再是一次 ReAct 调用，而是一张拥有独立状态的子图，包含代码级急症闸门和基于 `interrupt()` 的追问；五个专科之间可以用 `Command` 互相转接（handoff），不再需要用户打退出词才能换专科。

主图的 Mermaid 源码位于 `docs/images/graph.mmd`，由下面的命令生成：

```bash
cd backend
uv run python -c "from agents.graph import master_app; print(master_app.get_graph(xray=1).draw_mermaid())"
```

## Checkpointer 配置

| 变量 | 取值 | 说明 |
| --- | --- | --- |
| `CHECKPOINTER` | `memory`（默认）/ `sqlite` | 选择 checkpoint 后端 |
| `CHECKPOINT_DB_PATH` | 路径，默认 `checkpoints.sqlite` | 仅 `sqlite` 后端使用，已加入 `.gitignore` |

```dotenv
# 进程内存储，重启后丢失，适合本地开发
CHECKPOINTER=memory

# 落盘存储，重启后仍可续聊
CHECKPOINTER=sqlite
CHECKPOINT_DB_PATH=checkpoints.sqlite
```

实现位于 `backend/agents/checkpointing.py`，`agents/graph.py` 在 `workflow.compile(checkpointer=...)` 时调用。`sqlite` 使用 `langgraph-checkpoint-sqlite` 的 `AsyncSqliteSaver`，构造时需要一个运行中的事件循环，因此应由 uvicorn 进程加载主图（`main.py` 本来就是在请求中懒加载的）；在纯同步脚本里请使用默认的 `memory`。

Checkpoint 中会保存完整对话消息与用户资料，属于医疗上下文。`sqlite` 文件请勿提交仓库，也不要放在共享目录。

## thread_id 协议

`POST /api/chat` 与 `POST /api/vision-chat` 都接受可选的 `thread_id`：

| 请求 | 后端行为 |
| --- | --- |
| 不带 `thread_id` | 生成一个新的 `thread_id`，本轮仍使用请求里的完整历史作为输入 |
| 带 `thread_id`，服务端已有该会话 | 只把最新一条用户消息交给图，历史由 checkpointer 提供 |
| 带 `thread_id`，服务端没有该会话（例如重启后内存态丢失） | 回退到请求里的完整历史，保证不丢上下文 |
| 带 `thread_id`，该会话有挂起的 `interrupt` | 用 `Command(resume=<用户回答>)` 恢复，而不是投喂新输入 |

每条 SSE 流的**第一个事件**固定为：

```json
{"type": "session", "thread_id": "…"}
```

前端 `chatService.ts` 收到后通过 `onSession` 写入 `GlobalContext` 的 `threadId`；下一轮请求带上它，并只发送最新一条消息。`exitChatMode()` 会清空 `threadId`，也就是退出专科模式即开启新会话。旧客户端忽略 `session` 事件、继续发送完整历史同样可用，接口保持向后兼容。

除了新增的 `session` 与 `interrupt`，原有事件类型（`text`、`node_start`、`node_end`、`tool_start`、`tool_end`、`card`、`finish`、`error`）语义不变。

## 预问诊子图

`backend/agents/clinic.py` 编译出的子图被直接挂载为主图的 `clinic_node`，拥有自己的 `ClinicState`：

```
emergency_gate ──CRITICAL──────────────────────────────────────────► END
      │
      │ 未触发红旗
      ▼
extract_symptoms ──► check_sufficiency ──信息充分──► conclude ──► END
      ▲                     │
      │                     │ 缺必填项
      │                     ▼
      └── await_answer ◄── ask_followup
```

| 节点 | 是否调用 LLM | 职责 |
| --- | --- | --- |
| `emergency_gate` | 否 | 直接调用 `skills/emergency_triage` 的规则表。命中 CRITICAL 时输出固定安全话术、推送急诊卡片并结束子图，不依赖模型是否愿意调用工具 |
| `extract_symptoms` | 是（`with_structured_output`） | 抽取 `SymptomFacts`（主诉、部位、持续时间、严重程度、伴随症状等），跨轮合并进 `collected`，空值不覆盖已知值 |
| `check_sufficiency` | 否 | 判断必填项 `chief_complaint` / `duration` / `severity` 是否齐全；追问超过 `MAX_FOLLOWUPS`（3 次）强制收尾 |
| `ask_followup` | 是 | 只生成**一个**温和的追问问题 |
| `await_answer` | 否 | `interrupt(question)` 挂起整张图 |
| `conclude` | 是 | ReAct Agent（clinic 技能 + `load_skill` + RAG 注入）产出分诊正文，再用结构化输出压缩成 `TriageRecommendation` |

### 与父图的契约

`ClinicState['messages']` 是"最后写入生效"的通道：进入子图时它是父图的历史，终止节点把它覆盖为**本轮新产生的消息**。父图的 `operator.add` 再把这些消息追加到全局历史，因此对外仍然是 `{"messages": new_messages}`，不会出现历史重复。路由的退出词（退出/结束/…）行为不变。

### 卡片推送

`conclude` 与 CRITICAL 分支通过 `agents/streaming.py` 的 `emit_custom()` 把已经成形的 SSE payload 推入 custom 流，`main.py` 的 `_stream_agent_events` 以 `stream_mode=["updates", "custom"]` + `subgraphs=True` 消费，并只放行 `card` / `text` 两种类型。自 v0.4.0 起，**所有**卡片都走这条路（见下文"卡片归属"），`main.py` 里的工具名嗅探已经删除。

`clinic_recommendation` 卡片的数据形状与前端 `ChatCardRenderer.tsx` 对齐：

```json
{"type": "card", "payload": {"type": "clinic_recommendation", "data": {
  "summary": "建议尽快到呼吸内科就诊。",
  "departments": ["呼吸内科"],
  "severity": "medium",
  "urgency": "soon",
  "notes": ["多喝温水", "记录体温变化"]
}}}
```

`urgency` 与 `severity` 的映射：`emergency → high`、`soon → medium`、`routine → low`。

## 追问的中断与恢复

1. `await_answer` 调用 `interrupt(question)`，LangGraph 把问题写入 checkpoint 并结束本次运行。
2. `main.py` 从流里取出 `__interrupt__`，先发 `{"type": "text", "content": <问题>}`（复用普通气泡，前端无需新组件），再发 `{"type": "interrupt", …}` 作为标记，最后照常发 `finish`。
3. 前端不需要特殊处理，用户在同一个 `thread_id` 上发下一条消息即可。
4. 后端在 `_resolve_graph_input` 里用 `master_app.aget_state(config).tasks[*].interrupts` 检测挂起状态，命中则用 `Command(resume=<用户回答>)` 恢复；回答会以 `HumanMessage` 回流到 `extract_symptoms`，继续补全信息。

如果用户在追问挂起期间说出退出词（退出/结束/不看了/取消…），后端不会把它当成回答：`_resolve_graph_input` 返回 `None`，端点随即换一个新的 `thread_id` 并用完整历史重跑，让 router 正常识别退出意图。退出词表由 `agents/router.py` 的 `EXIT_PHRASES` / `is_exit_request()` 统一提供。

没有 checkpointer 就没有 `interrupt`：两者必须一起启用，这也是主图必须携带 checkpointer 的原因。

## Agent 转接（handoff）

`active_agent` 会把会话锁在某个专科里。锁本身保留（多轮上下文靠它），但用户在医保模式下问症状时，不该再收到医保的回答——转接就是用来解这个锁的。

### 工具与提示词

`agents/handoff.py` 为每个专科生成 `transfer_to_clinic` / `transfer_to_insurance` / `transfer_to_report` / `transfer_to_pharmacy` / `transfer_to_advisor` 五个工具中的**其余四个**（`get_handoff_tools(AGENT_ID)`），并把 `handoff_prompt_section(AGENT_ID)` 追加到该专科的 system prompt 里，告诉模型什么时候该转接、转接后只回一句过渡语。

### 为什么不能直接在工具里抛 Command

`insurance` / `pharmacy` / `report` / `advisor` 四个节点都是在**节点函数内部**调用 `create_react_agent(...).ainvoke(...)`。那个内层 agent 是一次独立的 Pregel 运行，工具里抛出的 `Command` 最多只能作用于内层图，`Command.PARENT` 也只能上溯一层、到不了主图。因此采用"工具返回标记 + 节点识别"的写法：

1. 工具返回一条可识别的 `ToolMessage`：`{"handoff": "<agent_id>", "reason": "…"}`。
2. `ainvoke` 返回后，节点调用 `apply_handoff(state, new_messages)`。
3. `split_handoff()` 找到该标记，并把**发起转接的那条 `AIMessage` 及其之后的所有消息**一并丢弃——包括 ToolMessage 和模型的过渡语。这样历史里不会留下没有应答的 `tool_calls`，接手的专科看到的最后一条消息仍然是用户自己的提问。
4. 命中则返回 `Command(goto="<target>_node", update={"messages": kept, "active_agent", "next_agent", "handoff_count"})`，主图在**同一轮**里把这条用户消息交给目标节点；未命中则照旧返回 `{"messages": new_messages}`。

`Command(goto=...)` 会覆盖该次运行的静态 `节点 → END` 边，不会既转接又结束。

### clinic 的特殊处理

`clinic_node` 是挂载的子图，因此它的 `conclude` 节点用 `apply_handoff(..., parent=True)` 返回 `Command(graph=Command.PARENT, goto=…)`，直接指向主图节点。`ClinicState` 额外声明了 `handoff_count`，让父图的转接预算能传进子图。

急症闸门和追问分支不参与转接：`emergency_gate` 命中 CRITICAL 时直接结束，`await_answer` 处于 `interrupt` 挂起状态，这两条路径都不经过 `conclude`。

### 防止来回弹球

`MainAgentState['handoff_count']` 记录本轮已经生效的转接次数，`MAX_HANDOFFS_PER_TURN = 1`。超出预算时 `apply_handoff` 打印一行日志、**保留** sub-agent 自己的完整回复（连同 tool_call，保证历史合法）并就此结束。`router_node` 的每个返回分支都会把 `handoff_count` 归零，所以预算是"每轮"而不是"每会话"。

### 图的渲染

`graph.py` 用 `add_node(..., destinations=(*handoff_destinations("<agent>_agent"), END))` 注册五个专科节点，`get_graph()` 因此能画出转接虚线。`docs/images/graph.mmd` 已重新生成。

### 前端

前端不需要任何新代码。转接后目标节点会发出自己的 `node_start`，`chatService.ts` 的 `NODE_TO_CHAT_MODE` 照常把 `chatMode` 切过去；切到 `advisor_node` 时走既有的 `exitChatMode()` 分支。

### 退出词的收紧

`is_exit_request()` 不再做自由子串匹配。它先 strip 掉首尾空白与标点，然后要求整句**等于**某个退出词，或者**以**退出词开头且紧跟标点/空白。于是 `我想取消明天的预约`、`这个药不用了吗`、`结束以后还要复查吗` 都不再退出，而 `退出`、`退出。`、`不用了，谢谢` 仍然退出。

## 卡片归属：由 Agent 自己推送

v0.4.0 之前，`main.py` 在 `on_tool_end` 上用三张 "工具名 → 卡片类型" 字典嗅探卡片。这三张字典（`_INSURANCE_TOOL_TO_CARD_TYPE`、`_REPORT_TOOL_TO_CARD_TYPE`、`PHARMACY_TOOL_TO_CARD_TYPE`）以及对应的解析分支都已删除，`main.py` 不再认识任何工具名（`_SKILL_LABELS` 里的展示文案除外）。

新模型：卡片由产生它的 Agent 自己推送。

| 来源 | 卡片类型 |
| --- | --- |
| `insurance.get_insurance_balance` | `insurance_balance` |
| `insurance.get_consumption_records` | `insurance_expenses` |
| `insurance.get_payment_records` | `insurance_payments` |
| `insurance.get_cross_region_info` | `insurance_cross_region` |
| `pharmacy.search_drug_info` | `medication_task` |
| `pharmacy.find_nearby_pharmacy` | `hospital_list` |
| `report_node._emit_report_cards()` | `report_analysis` |
| `clinic.conclude` / `clinic.emergency_gate` | `clinic_recommendation` |

已经实测确认：**嵌套在节点里的 ReAct agent 所执行的工具**，其 `get_stream_writer()` 写入同样会出现在根图的 `astream_events(..., subgraphs=True)` 流上，顺序是 `tool_start → tool_end → card → 总结文本`——与旧的 `on_tool_end` 分支完全一致。

唯一的例外是 `report_analysis`：它来自通用技能 `lab_interpreter`（clinic 也在用），为了不动技能注册表，改由 `report_node` 在 `ainvoke` 之后扫描本轮的 `ToolMessage` 补发。因此这一张卡片会**晚于**总结文本到达。前端把卡片挂在助手消息的 `cards` 数组上统一渲染，视觉上没有区别。

## 验证

```bash
cd backend
uv run python -m unittest test_clinic_graph.py test_graph_build.py test_handoff.py test_cards.py
```

`test_graph_build.py` 断言主图带 checkpointer 编译、`clinic_node` 确实是子图；`test_clinic_graph.py` 覆盖急症闸门零 LLM 短路、`check_sufficiency` 路由、中断—恢复全流程，以及 `main.py` 的 thread_id / resume 分支；`test_handoff.py` 覆盖退出词收紧、`split_handoff` 的消息裁剪、转接预算，以及"医保 → 用药"和"医保 → 预问诊子图"两条端到端链路；`test_cards.py` 用假模型跑完整 SSE 流，断言卡片落在 `tool_end` 之后、总结文本之前。全部使用 mock（`test_fakes.ScriptedChatModel`），不联网。
