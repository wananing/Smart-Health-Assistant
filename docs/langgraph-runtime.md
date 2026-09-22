# LangGraph 运行时：Checkpointer、thread_id 与预问诊子图

本项目的主图不再是"路由 → 一层 Agent → END"的星形结构。主图编译时携带 checkpointer，会话状态按 `thread_id` 持久化在服务端；预问诊（clinic）不再是一次 ReAct 调用，而是一张拥有独立状态的子图，包含代码级急症闸门和基于 `interrupt()` 的追问。

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

`conclude` 与 CRITICAL 分支通过 `langgraph.config.get_stream_writer()` 把已经成形的 SSE payload 推入 custom 流，`main.py` 的 `_stream_agent_events` 以 `stream_mode=["updates", "custom"]` + `subgraphs=True` 消费，并只放行 `card` / `text` 两种类型。这样新增卡片不需要在 `main.py` 里继续堆工具名嗅探（医保 / 药品 / 报告的既有映射保持原样）。

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

## 验证

```bash
cd backend
uv run python -m unittest test_clinic_graph.py test_graph_build.py
```

`test_graph_build.py` 断言主图带 checkpointer 编译、`clinic_node` 确实是子图；`test_clinic_graph.py` 覆盖急症闸门零 LLM 短路、`check_sufficiency` 路由、中断—恢复全流程，以及 `main.py` 的 thread_id / resume 分支。全部使用 mock，不联网。
