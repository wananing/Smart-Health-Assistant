# Agent 可观测与评估

本项目提供一个不依赖商业平台的最小闭环：LangGraph 运行链路通过 OpenInference 转为 OpenTelemetry Span，以标准 OTLP 输出到 Jaeger；回归样例由仓库管理，默认本地评分，也可使用 DeepEval。LangSmith 仍作为兼容选项保留。

## 生命周期

| 阶段 | 项目内做法 | 产物 |
| --- | --- | --- |
| 开发 | 修改 Agent、Prompt、Skill 或 RAG 文档，并补单元测试与 `evals/cases.jsonl` | 可复现代码和样例 |
| 监控 | OpenInference 自动记录节点耗时、模型调用、视觉调用和工具调用 | OTLP Trace |
| 评估 | 执行路由与工具选择基线，使用本地评分或 DeepEval | case 级通过/失败与进程退出码 |
| 迭代 | 根据失败 case 定位 Jaeger Span，修复后重复运行 | 可比较的回归结果 |

这里记录的是 **Agent 执行状态与工具调用进度**，不展示或承诺模型的私有思考链。

## 本地链路追踪

在仓库根目录启动 Jaeger：

```bash
docker compose -f compose.observability.yml up -d
```

在 `backend/.env` 中启用 OTLP：

```dotenv
OBSERVABILITY_PROVIDER=otel
OTEL_SERVICE_NAME=smart-health-assistant
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4318/v1/traces
TRACE_CONTENT=false
TRACE_IMAGES=false
```

启动后访问 `http://localhost:16686`，选择 `smart-health-assistant` 查看 Trace。输出采用标准 OTLP/HTTP，因此可将端点替换为 Phoenix、Grafana Tempo、SigNoz 或其他兼容后端；也支持通用的 `OTEL_EXPORTER_OTLP_ENDPOINT`，代码会追加 `/v1/traces`。`compose.observability.yml` 使用内存存储，仅适合本地调试。

设置 `OBSERVABILITY_PROVIDER=langsmith` 并配置 `LANGSMITH_API_KEY`（或旧名 `LANGCHAIN_API_KEY`）可继续使用原有 LangSmith 链路；相同内容开关会映射为 LangSmith 的输入、输出与元数据隐藏配置。设置 `none` 则关闭观测。

## 隐私默认值

`TRACE_CONTENT=false` 会隐藏输入、输出、消息文本、Prompt、调用参数和工具定义；图片还需单独设置 `TRACE_IMAGES=true` 才会进入 Span。为防止 base64 图片从 LangChain 的通用输入属性泄露，只有两个开关同时为 `true` 时才记录输入；Embedding 向量始终隐藏。后端日志也不打印用户资料、对话原文或模型原始路由结果。

医疗报告可能包含姓名、证件号、条码和检查结果。开发与 CI 应只使用脱敏或合成样例，不要把真实报告、完整回答或含个人信息的 Trace 提交到仓库。若显式开启内容追踪，应先确认后端访问控制、保留期限和删除机制。

## 回归评估

默认数据集位于 `backend/evals/cases.jsonl`，每行包含 `id`、`input`、`expected_agent`，可选 `expected_tools` 与 `chat_mode`。运行会调用当前配置的模型，因此需要对应 API Key：

```bash
cd backend

# 内置严格评分：路由必须一致，声明工具时工具集合必须一致
uv run python -m evals
uv run python -m evals --case route-report-lab

# 可选 DeepEval 工具评分
uv run --extra eval python -m evals --provider deepeval
```

评估运行器会复用相同的观测配置，并将匿名 `eval:<case_id>` 写入 session 属性，因此启用 `otel` 后可在 Jaeger 中按失败 case 排查。DeepEval judge 复用 `LLM_PROVIDER` 的多厂商配置，不强制 OpenAI；本项目默认设置 `DEEPEVAL_TELEMETRY_OPT_OUT=1`。命令只输出 case ID 和分数，任一 case 失败时返回非零退出码，便于接入 CI。新增能力时至少增加一个正常路径和一个安全边界样例。
