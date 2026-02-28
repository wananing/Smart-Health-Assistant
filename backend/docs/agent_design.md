# 智能体(Agent)与提示词工程(Prompt Engineering)设计文档

本文档规定了该应用中后端 LLM 对话服务的智能体基础架构、Prompt 策略、上下文管理机制，以及具体业务场景的逻辑拆分。

## 1. 基于 LangGraph 的多智能体架构 (Multi-Agent Architecture based on LangGraph)

该大健康应用包含多个功能模块（如：看病挂号、医保查询、买药指引、健康数据看板、化验单解读、AI 预问诊）。我们采取**主管路由 (Supervisor Routing)** + **专门智能体 (Specialized Agents)** 的架构设计。整个底层控制流将由 **LangGraph** (基于 `StateGraph`) 进行编排。

### 1.1 全局状态定义 (Main Agent State)

在 LangGraph 中，由一个全局的 State 对象在 Router 和 Specialized Agents 之间流转。

```python
from typing import TypedDict, Annotated, Sequence
import operator
from langchain_core.messages import BaseMessage

class MainAgentState(TypedDict):
    # 保存所有的对话历史
    messages: Annotated[Sequence[BaseMessage], operator.add]
    # 用户基本属性和健康标签
    user_info: dict
    # 当前会话由 Router 决定的专门智能体
    next_agent: str
```

### 1.2 节点设计 (Nodes)

各个服务模块在 LangGraph 中表现为独立的 Node（或者是嵌套的 Sub-Graph）。

#### 1.2.1 核心路由节点 (Router Node)
- **输入**：`State["messages"]` 和 `State["user_info"]`。
- **职责**：作为 `StateGraph` 的入口节点，分析用户的初始请求，提取核心意图，决定激活图结构(Graph)中的哪个专门节点(Sub-Agent)。
- **输出**：更新 `State["next_agent"]`。可能会返回如 `"clinic_agent"`, `"insurance_agent"`, `"report_agent"`, `"advisor_agent"` 等结果。

#### 1.2.2 专科预问诊节点 (Clinic Agent Node)
- **职责**：当用户表述身体不适时，引导用户进行多轮对话以收集：主要症状、持续时间、伴随症状。
- **特有要求**：态度温和、专业、禁止下绝对的诊断结论，只提供分诊建议。

#### 1.2.3 报告解读节点 (Report Analysis Node)
- **职责**：结合 OCR 提取的化验单数据，用通俗易懂的语言解释各项超出参考值指标的含义，以及生活干预建议。
- **特有要求**：数据严谨、引用医学依据。

#### 1.2.4 医保智能体节点 (Insurance Sub-Graph Node)
- **职责**：处理医保政策解答、账户余额查询、消费缴费记录调取等。
- **实现方案**：这是一个具备工具调用(Tool Execution)与外部知识检索(RAG)的复杂子图(Sub-Graph)。
- **详情**：请参阅配套文档 [《医保智能体 LangGraph 设计文档》(langgraph_insurance_agent.md)](langgraph_insurance_agent.md)。

#### 1.2.5 日常健康顾问节点 (Health Advisor Node)
- **职责**：处理通用的健康科普、找药询价等闲聊式和知识搜索式的查询。

### 1.3 边与路由分发 (Edges & Conditional Routing)

通过条件边 (Conditional Edges) 将 Router 节点连接到对应的处理节点，处理完毕后统一返回 `END`。

```python
from langgraph.graph import StateGraph, START, END

# 建立状态图
workflow = StateGraph(MainAgentState)

# 1. 挂载所有节点
workflow.add_node("router", router_node)
workflow.add_node("clinic_agent", clinic_node)
workflow.add_node("report_agent", report_node)
workflow.add_node("insurance_agent", insurance_subgraph) # 医保是嵌套子图
workflow.add_node("advisor_agent", advisor_node)

# 2. 从 START 开始由 router 决定方向
workflow.add_edge(START, "router")

# 3. 添加条件路由边根据 next_agent 派发
workflow.add_conditional_edges(
    "router",
    lambda state: state["next_agent"],
    {
        "clinic_agent": "clinic_agent",
        "report_agent": "report_agent",
        "insurance_agent": "insurance_agent",
        "advisor_agent": "advisor_agent"
    }
)

# 4. 各 Specialized Agent 处理完后节点终结
workflow.add_edge("clinic_agent", END)
workflow.add_edge("report_agent", END)
workflow.add_edge("insurance_agent", END)
workflow.add_edge("advisor_agent", END)

# 编译 Graph
app = workflow.compile()
```
---

## 2. 上下文工程 (Context Engineering)

LLM 是无状态的，为保证连续、个性化的对话体验，后端需要维护和处理 Context（上下文）。

### 2.1 用户画像注入 (User Profile Injection)
在每一次发送给 LLM 的 `system` prompt 中，动态注入当前登录用户的属性状态：
- **基础信息**：姓名、年龄、性别。
- **健康标签**：慢性病史（如高血压、糖尿病）、近期体检异常项。
- **设备状态**：当前用户所在的前端页面（如：正在查看“医保”页面）。

### 2.2 上下文截断与滑动窗口 (Sliding Window Context)
随着对话轮数增加，避免 Token 超限和响应速度下降：
- **历史记录清理**：只保留最近 10 轮的对话 (20 messages)。
- **核心摘要提取 (Memory Summarization)**：每当对话超过 10 轮时，利用一个极简的内部 LLM 调用，将前期的交流浓缩成一段总结短文，放入 system prompt 的临时存储区中。

### 2.3 RAG 外部知识检索 (Retrieval-Augmented Generation)
- **向量数据库集成**：针对用户的“药价”、“医院列表”、“医保政策”问题，先通过 Embeddings 匹配本地数据库中对应的 Document 文本块。
- **知识拼装**：将匹配到的前 3 条文本块作为 `<context>` 注入到当前轮次的 prompt 结束处。

---

## 3. 提示词工程 (Prompt Engineering)

针对主力的通用/路由对话能力，我们定义以下 Base System Prompt：

### 3.1 基础系统提示词模板 (Base System Prompt)

```text
你是一个名为“大健康AI助手”的专业、温暖的虚拟健康顾问。
你的主要任务是为用户提供健康咨询、预问诊导诊、报告解读和健康管理建议。

【当前用户信息】
姓名：{user_name}
年龄：{user_age}
既往史：{medical_history}

【对话原则】
1. **安全性与免责**：你不能替代真正的医生下达明确的医疗诊断，你的回答只是健康参考。如果遇到急性严重症状（如剧烈胸痛、呼吸困难），必须在回答开头强烈建议用户立即拨打 120 或就医。
2. **通俗易懂**：如果发现用户年龄较大（>60岁），必须使用极度口语化、简单易懂的语言，尽量避免生僻的医学专业词汇。
3. **结构化输出**：回答应该条理清晰，利用列表进行排版以适应移动端阅读。
4. **前端导航**：如果你判断用户的意图是为了使用 App 中的某个特定功能（例如：挂号、查验化验单、买药），你可以回复结构化的指令让前端感知并跳转。

【交互要求】
请保持回答精炼，单次回答控制在 300 字以内，并主动通过一句温和的提问引导用户继续交流。
```

### 3.2 针对前端动作的 Function Calling / 标记输出
如果你目前没有集成严谨的 Function Calling 接口，可以通过特定的 JSON 标记让前端触发跳转：
```text
如果你确认需要让应用跳转到买药页面，请在你的回答结尾附带以下隐藏指令：
[[ACTION: NAVIGATE_TO="pharmacy"]]
```
*(并在 `chatService.ts` 中解析拦截这些字符串片段。)*

---

## 4. 下一步开发计划 (Next Steps)

1. **改造 `main.py`**：在 `ChatRequest` 模型中引入 `user_id` 和上下文历史（当前已由前端传递 `messages` 数组支持）。
2. **构建 Prompt Manager**：创建一个轻量级的 `prompts.py` 字典类，存储不同业务场景的 System Prompt。
3. **引入 RAG 机制 (可选)**：对接 Volcengine Ark 平台的专属知识库 API，或者使用本地的 ChromaDB/QA 语料。
