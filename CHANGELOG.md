# 更新日志

本文件记录本项目所有值得注意的变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.5.0]

### 新增

- **实时语音问诊（`/api/voice` WebSocket）**：开放麦、可随时打断的通话式预问诊。流式 ASR → 与文字通道共用的预问诊子图 → 流式 TTS 的级联架构，每一句话出声前都是完整文本并经过出声前检查。新增 `backend/voice/`：回合状态机与服务端判停、打断与输出仲裁（回合代际、单一发言者、播放回执）、进图前规则（急症、退出、重说、肯定语）、`RunManager` 图运行生命周期（无进展看门狗、断线后后台跑完、卡死取消时保留问答）、提示语预合成缓存。设计与实测延迟见 `docs/voice-clinic.md`。
- **火山引擎语音适配**：流式 ASR（默认 `bigmodel_async`，带中间结果与服务端端点）与双向流式 TTS，以能力声明描述服务商；`fake` 服务商用于离线开发与测试。配置见 `backend/.env.example`。
- **语音专属的问诊流程**：关键信息模板复述确认（可口头确认或在屏幕上改）、结论首句先播、急症全屏接管与不可打断的安全提示、挂断后的 `clinic_summary` 小结卡、识别不顺时降级为手动提交。
- **语音通话界面**：状态球随真实音量起伏，实时字幕、症状要点病历卡、通话记录抽屉；输入栏 📞 入口（首页与 AI 诊室）与长辈模式大号入口。
- **协议契约**：`contracts/voice-frames.json` 定义全部帧格式，后端测试（`voice/contract.py`）与前端浏览器测试（`mock_voice_server.cjs` + `test_voice.cjs`）都按它校验。
- **设计规范**：`frontend/src/design/tokens.ts` 语义色、字号、圆角、阴影与动效，`useTextScale()` 长辈模式字号体系，共享 `ResultCard` 组件族；说明见 `frontend/docs/design-system.md`。
- **药品信息与附近药店卡片**：此前后端已推送但前端从未渲染的 `medication_task`、`hospital_list` 现在都有对应卡片；检验报告卡片逐项展示指标、参考范围与偏高偏低。
- **测试**：新增 `test_voice_*.py`（协议、服务商、渲染、网关、诊室、火山协议、运行生命周期、契约）与 `test_skill_tools.py`，全部确定性、不联网；`test_voice_live.py` 用于真实服务的回环与整通电话测速（手动运行）。

### 变更

- **预问诊子图**：追问的回答重新经过急症闸门；症状抽取与追问起草合并为一次结构化调用；文字还是语音由每次请求的运行配置指定，不再沿用 checkpoint 里的值。
- **技能工具参数**：工具参数直接取自各技能的 `input_schema`，不再要求模型传 `params_json` 字符串；单个技能加载失败只跳过它本身。
- **RAG**：服务启动时后台预热知识库，本地已缓存的嵌入模型不再联网检查，首次检索从约 10 s 降到 1 s 以内。
- **`main.py`**：事件流拆为事件生成器与 SSE 包装两层（SSE 输出逐字节不变），供语音网关复用；CORS 与 WebSocket 来源校验共用 `ALLOWED_ORIGINS`，新增 `EXTRA_ALLOWED_ORIGINS`。
- **前端视觉统一**：首页、对话气泡、底栏、全部结果卡片与健康数据页按设计规范重做；电话按钮只在首页与 AI 诊室显示。
- **移除**：未注册路由的旧专科页面、扫描浮层及其专用组件、数据与类型，全局长辈模式 CSS 补丁。

### 修复

- 底部"就医服务"入口传入不存在的模式，导致整个页面白屏。
- `symptom_scorer` 的 JSON 字符串参数常被模型传错，校验失败后反复重试，拖慢分诊结论。
- 对话自动滚动把最新消息对齐到可视区顶部，导致消息被输入栏遮挡。
- 语音通话期间，下层页面仍可被读屏读到、被键盘聚焦。

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
