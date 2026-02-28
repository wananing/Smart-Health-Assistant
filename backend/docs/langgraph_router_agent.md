# 核心路由智能体 (Router Agent) LangGraph 设计文档

Router Agent 是应用程序后端 LLM 会话的中枢控制系统。它不直接负责回答医疗或医保专业问题，它的唯一职能就是“分发”（Dispatch）。它利用 LLM（通常使用结构化输出、JSON Mode 或 Function Calling/Tool Use）来高精度识别用户意图，并将执行流程移交给最合适的 Specialized Agent (Sub-Graph)。

## 1. 核心状态定义 (Main Graph State)

这是在整个应用层级流转的心智状态变量。请参考全局概览文档中的定义：

```python
from typing import TypedDict, Annotated, Sequence, Any
import operator
from langchain_core.messages import BaseMessage

class MainAgentState(TypedDict):
    # 会话聊天记录
    messages: Annotated[Sequence[BaseMessage], operator.add]
    
    # 存放全局级别的用户信息注入：年龄、性别、慢性病史等
    user_info: dict
    
    # 由分类器决定将流转到哪个下游子图
    next_agent: str
```

## 2. 节点逻辑：路由器

只有单一的 `Router Node`。

### 2.1 `Intention Classifier Node` (意图分类节点)
- **输入**: 最新的用户 `State["messages"][-1]`。
- **职责**: 给通用 LLM (如 Volcengine 的大杯模型) 提供一个涵盖所有 Specialized Agent 用途的“使用手册”（System Prompt）。让 LLM 决定此句话归属哪个模块。
- **输出**: 输出字符串枚举值存入 `State["next_agent"]`。

#### **提示词工程示范 (System Prompt for Router)**

```text
你是一个大健康 App 中的“智能意图路由器”。你需要阅读用户最新的提问，并将当前会话“转接”给下面最适合处理该提问的专家智能体。

请你严格回复以下指定字符串选项之一（不要回答多余的废话）：
1. "clinic_agent": 用户描述了具体的身体不适、症状，寻求如何就医、看什么科或者询问可能得了什么病。
2. "insurance_agent": 用户询问了医保余额、医保报销政策、消费明细等相关事务。
3. "report_agent": 用户让你帮忙看看刚抽血出的化验单、检查报告。
4. "advisor_agent": 其它通用健康科普、找药品、饮食作息建议或是打招呼。

只回复分类 ID 字符串。
```

## 3. 图表路由与控制流 (Graph Routing)

这部分就是我们在 `agent_design.md` 中展示的内容的扩充。这个 `app` 将暴露出入口，并集成我们在之前编写的子图（sub-graphs）。

```python
from langgraph.graph import StateGraph, START, END

# 导入已经写好的各个子图 (视为 Node 引入)
# from agents.clinic import clinic_app
# from agents.report import report_app
# from agents.insurance import insurance_app
# from agents.advisor import advisor_app

workflow = StateGraph(MainAgentState)

# 挂载入口 Router 节点
workflow.add_node("router", intention_classifier)

# 挂载 Specialized Agents (此时子图可以直接当做大的节点加入外层图)
# 这一步会自动把 MainAgentState 的数据映射到 Child State，LangGraph V0.1+ 提供了原生的 Sub-Graph 嵌套支持
workflow.add_node("clinic_node", clinic_app)
workflow.add_node("report_node", report_app)
workflow.add_node("insurance_node", insurance_app)
workflow.add_node("advisor_node", advisor_app)

# 设置逻辑边
workflow.add_edge(START, "router")

# 条件路由函数
def route_to_agent(state: MainAgentState) -> str:
    # 路由器输出了下一步去哪里
    agent_id = state.get("next_agent", "advisor_node") 
    return agent_id + "_node" # 映射到上面 add_node 注册的名字

# 将路由器连接到各个专门的 Node
workflow.add_conditional_edges(
    "router",
    route_to_agent,
    {
        "clinic_node": "clinic_node",
        "report_node": "report_node",
        "insurance_node": "insurance_node",
        "advisor_node": "advisor_node"
    }
)

# 各个专属智能体执行结束后，将结果返回并终止本次 run
workflow.add_edge("clinic_node", END)
workflow.add_edge("report_node", END)
workflow.add_edge("insurance_node", END)
workflow.add_edge("advisor_node", END)

master_app = workflow.compile()
```

## 4. 后端接口集成与推流

在 `main.py` 的 `/api/chat` 中，我们将直接调用这个 Compile 出来的 `master_app`。

```python
from langgraph_types import State
from models.langgraph_router import master_app

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    # 构建初始状态
    initial_state = {
        "messages": request.messages,
        "user_info": {
            "name": "用户123", # 这些后期从 request 里拿
            "age": 30
        }
    }
    
    # 迭代子图的执行结果并通过 FastAPI 返回
    async def event_generator():
        async for event in master_app.astream_events(initial_state, version="v2"):
            kind = event["event"]
            if kind == "on_chat_model_stream":
                # 将下层子图里调用模型产生的 chunk 直接通过 SSE 抛出到前端
                chunk = event["data"]["chunk"].content
                if chunk:
                    yield f"data: {chunk}\n\n"
                    
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```
