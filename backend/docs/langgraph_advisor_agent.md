# 日常健康顾问智能体 (Advisor Agent) LangGraph 设计文档

为满足通用疾病科普、养生常识、药品常识等零散的问答需求，我们采用 `LangGraph` 构建 Health Advisor Agent。它的核心诉求是利用外部数据库增加其医疗知识的精准度，减少模型幻觉（Hallucation）。

## 1. 核心状态定义 (Advisor State)

顾名思义，这是一个基于“检索增强生成” (`RAG`) 架构的流节点。

```python
from typing import TypedDict, Annotated, Sequence
import operator
from langchain_core.messages import BaseMessage

class AdvisorAgentState(TypedDict):
    # 对话历史
    messages: Annotated[Sequence[BaseMessage], operator.add]
    
    # 意图是否需要进行重写（Query Rewriting）
    standalone_query: str
    
    # 经过 RAG 检索返回的文段
    retrieved_documents: list[str]
```

## 2. 业务流与节点设计 (Nodes)

传统的 QA 流水线设计即可满足要求。

### 2.1 `Query Rewrite Node` (查询改写节点)
- **触发条件**: 收到用户最新一条消息时。
- **职责**: 如果提问依赖于前文代词（如：“那你刚才说的那个药，饭前吃还是饭后吃？”），这里需要调用一个极小、极快的 LLM 调用将其重写为“独立查询语句”（e.g., “阿司匹林是饭前吃还是饭后吃？”）放入 `standalone_query`。如果用户问的已经是独立句，则直接原样输出。
- **输出**: 更新 `State["standalone_query"]`。

### 2.2 `RAG Retriever Node` (检索节点)
- **输入**: 最新改写好的 `standalone_query`。
- **职责**:
  - 生成文本片段的 Embeddings。
  - 从向量数据库（Vector DB, 如 Milvus, Chroma）中去检索 Top-K (比如前3条) 的相关科普文章段落。
- **输出**: 存入 `State["retrieved_documents"]`。

### 2.3 `Generator Node` (答案生成节点)
- **触发条件**: 无论是否检索到了内容，最终汇入生成节点。
- **职责**:
  - 提取 `State["messages"]` (最后一条问题) 和 `State["retrieved_documents"]` (作为上下文)。
  - 调用配置好的 System Prompt：“你是一个大健康科普助手，请根据提供的上下文回答用户的问题。如果上下文中找不到答案，用你自己的知识补充，但务必提醒用户该回答非专业诊疗。”
- **输出**: 最终的答案通过流式回传（即追加 `AIMessage` 到 `State["messages"]`），完成此次 Agentic Loop。

## 3. 图表路由与控制流 (Graph Routing)

```python
from langgraph.graph import StateGraph, START, END

advisor_workflow = StateGraph(AdvisorAgentState)

# 定义所有的步骤节点
advisor_workflow.add_node("rewriter", rewrite_query)
advisor_workflow.add_node("retriever", execute_rag_retrieval)
advisor_workflow.add_node("generator", generate_final_response)

# 直线型工作流
advisor_workflow.add_edge(START, "rewriter")

# 条件路由：如果当前提问是闲聊，跳过 retriever
def check_need_retrieval(state: AdvisorAgentState) -> str:
    # 可以在 rewriter 阶段判定这条是个 Greeting 或者是完全不需要查库的闲聊
    if is_casual_chat(state["standalone_query"]):
        return "generator"
    return "retriever"

advisor_workflow.add_conditional_edges(
    "rewriter",
    check_need_retrieval,
    {
        "retriever": "retriever",
        "generator": "generator"
    }
)

advisor_workflow.add_edge("retriever", "generator")
advisor_workflow.add_edge("generator", END)

# 编译子图
advisor_app = advisor_workflow.compile()
```

## 4. 特别说明与限制

- 由于大健康科普也具备医疗风险，如果问题超出了普通科普范畴（例如要求开具处方、询问自己得了什么绝症），即使本模块没有强制要求，底座大模型的底层 Safety Filter 也会发生作用。
- 该模块可以非常容易地通过对接 Volcengine 万知平台 (Ark 官方知识库插件) 实现，大幅降低 RAG 周边的开发成本。
