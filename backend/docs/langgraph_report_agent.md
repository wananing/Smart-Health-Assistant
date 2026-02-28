# 报告解读智能体 (Report Agent) LangGraph 设计文档

用户上传化验单图片或输入一串检验指标数值后，Report Agent 负责将其结构化，并结合医学知识进行通俗易懂的解读。此业务流具备非常清晰的“数据处理管线”（Data Pipeline）特征。

## 1. 核心状态定义 (Report State)

```python
from typing import TypedDict, Annotated, Sequence, Any
import operator
from langchain_core.messages import BaseMessage

class ReportAgentState(TypedDict):
    # 共享的对话历史
    messages: Annotated[Sequence[BaseMessage], operator.add]
    
    # 用户上传的图片 URL 或 Base64 字符串（如果适用）
    report_image_url: str
    
    # 结构化后的指标数据列表，e.g., [{"item": "白细胞", "value": "12.5", "reference": "3.5-9.5", "status": "高"}]
    structured_data: list[dict]
    
    # 根据结构化数据提取的异常项
    abnormal_items: list[dict]
    
    # 步骤日志/思考过程，用于可能的流式思考展示
    analysis_steps: list[str]
```

## 2. 业务流与节点设计 (Nodes)

化验单解读的重点在于**保证严谨性**（不能随意解读正常的指标，不能看错上限下限）。

### 2.1 `OCR & Structuring Node` (结构化提取节点)
- **输入**: 用户上传的信息（可能是文字、图片链接）。
- **职责**: 如果是图片，调用外置 OCR API 或 Vision LLM 将图片内的表格转化为结构化 JSON。如果是用户手打的内容，则利用通用 LLM 进行提取。
- **输出**: 更新 `State["structured_data"]`。这可能需要消耗一定的处理时间。

### 2.2 `Abnormal Filter Node` (异常值过滤节点)
- **触发条件**: `Structuring Node` 完成后。
- **职责**: (Python 纯逻辑) 遍历 `structured_data`，对比 `value` 与 `reference` 区间，将真正超标或偏低的指标挑出来，放入 `abnormal_items` 中。
- **输出**: 更新 `State["abnormal_items"]`。如果没有异常项，可以直接标记特定状态。

### 2.3 `Medical Interpretation Node` (医学解释节点)
- **触发条件**: `Abnormal Filter Node` 完成后。
- **职责**: 将由前一节点找出的 `abnormal_items` 作为上下文，发送给配置了底层 System Prompt的严肃医学大模型（设定了低 Temperature）。
- **输出要求**: 生成“此项指标偏高/偏低意味着什么（临床意义）”、“日常生活中需要注意什么”。
- **输出**: 将生成的 AIMessage 结果追加进入 `State["messages"]`。

## 3. 图表路由与控制流 (Graph Routing)

```python
from langgraph.graph import StateGraph, START, END

report_workflow = StateGraph(ReportAgentState)

report_workflow.add_node("structuring", execute_ocr_structuring)
report_workflow.add_node("filtering", filter_abnormal_metrics)
report_workflow.add_node("interpretation", generate_interpretation)

# 构建直线型流水线
report_workflow.add_edge(START, "structuring")
report_workflow.add_edge("structuring", "filtering")

# 根据是否有异常项决定是否进行长篇解读
def check_abnormal(state: ReportAgentState) -> str:
    if len(state["abnormal_items"]) == 0:
        return "normal_conclusion" # 增加一个快捷回复节点：所有指标正常
    else:
        return "interpretation"

report_workflow.add_node("normal_conclusion", generate_normal_reply)

report_workflow.add_conditional_edges(
    "filtering",
    check_abnormal,
    {
        "interpretation": "interpretation",
        "normal_conclusion": "normal_conclusion"
    }
)

report_workflow.add_edge("interpretation", END)
report_workflow.add_edge("normal_conclusion", END)

# 编译子图
report_app = report_workflow.compile()
```

## 4. 数据流示例 (Data Flow Example)

1. 用户发送包含了血常规化验单的提问：“大夫帮忙看看我的血常规”。
2. **Main Router** 派发至 `report_agent`。
3. `structuring` 节点通过工具调用或 Vision LLM（如果具备）提取数据，形如：`{"白细胞": 15, "血红蛋白": 120}` 等。
4. `filtering` 节点发现白细胞 15 高于参考值上限 9.5，将其定为异常。
5. 因为有异常，路由至 `interpretation`。
6. System Prompt 被激活：“你是一个专业的全科医生，用户的白细胞指标偏高。请解释其原因可能为细菌感染或炎症，并建议其可能需要服用抗生素，同时必须声明线上解读不能发药，建议去发热门诊。”
7. 大模型将解释以 Streaming 的形式返回给前端。
