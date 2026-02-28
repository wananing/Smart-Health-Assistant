# 专科预问诊智能体 (Clinic Agent) LangGraph 设计文档

为满足用户看病前的“AI预问诊”需求，我们采用 `LangGraph` 构建 Clinic Agent。该 Agent 的核心业务流是引导用户进行多轮对话，收集关键医疗指标（如症状、持续时间、伴随症状等），最终输出一个初步的“分诊建议”。

## 1. 核心状态定义 (Clinic State)

由于 Clinic Agent 作为全局 `MainAgentState` 的子图（Sub-Graph）运行，我们需要定义该节点运行期间特有的状态属性，特别是用来记录“症状收集进度”的结构化数据。

```python
from typing import TypedDict, Annotated, Sequence, Optional
import operator
from langchain_core.messages import BaseMessage

class ClinicAgentState(TypedDict):
    # 继承或共享全局的对话历史
    messages: Annotated[Sequence[BaseMessage], operator.add]
    
    # 结构化收集到的症状信息
    extracted_symptoms: Annotated[dict, operator.ior]  # e.g., {"chief_complaint": "头痛", "duration": "3天", "severity": "轻度"}
    
    # 缺失的关键信息列表（用于引导下一次提问）
    missing_info: list[str]
    
    # 判断是否收集完毕，准备出具分诊结论
    ready_for_triage: bool
```

## 2. 业务流与节点设计 (Nodes)

预问诊是一个“信息提取 -> 缺失判断 -> 追问 -> 结论生成”的循环。

### 2.1 `Symptom Extractor Node` (症状提取节点)
- **输入**: 最新的用户消息和当前的 `extracted_symptoms`。
- **职责**: 这是一个基于 LLM 的信息提取步骤（通常使用 Structured Output / Tool Calling）。判断用户刚才的话语中包含了哪些问诊要素（主诉、持续时间、诱因、加重/缓解因素）。
- **输出**: 更新 `State["extracted_symptoms"]`。

### 2.2 `Triage Validator Node` (信息验证节点)
- **触发条件**: 在 `Symptom Extractor` 之后无条件触发。
- **职责**: 这是一个普通 Python 函数（无需 LLM）。检查 `extracted_symptoms` 中是否已经包含了必备要素（至少包含：主诉、持续时间、严重程度）。
- **输出**: 
  - 如果必备要素未满，将缺少的字段名写入 `State["missing_info"]`，并将 `State["ready_for_triage"]` 置为 `False`。
  - 如果必备要素已满，将 `State["ready_for_triage"]` 置为 `True`。

### 2.3 `Question Generator Node` (追问生成节点)
- **触发条件**: 当 `ready_for_triage == False` 时。
- **职责**: 根据 `State["missing_info"]`，利用 LLM 生成一句温和的、符合医生口吻的追问。例如：“您说头痛，请问大概痛了几天了呢？是一跳一跳的痛，还是像戴了紧箍咒一样的钝痛？”
- **输出**: 将生成的追问（AIMessage）追加到 `State["messages"]`，然后等待用户下一次回复。此节点会终止当前循环并阻塞（中断），等待人类(Human in the loop)继续输入。

### 2.4 `Triage Conclusion Node` (分诊结论生成节点)
- **触发条件**: 当 `ready_for_triage == True` 时。
- **职责**: 汇总 `extracted_symptoms` 和全局上下文的 `user_info`，利用大模型生成最终的预问诊报告和科室推荐。
  - **Prompt 安全限制**: 必须明确声明“本方案仅供参考，不可替代专业医生诊断”。
- **输出**: 将最终的分诊建议加入序列，并结束该 Sub-Graph。

## 3. 图表路由与控制流 (Graph Routing)

```python
from langgraph.graph import StateGraph, START, END

clinic_workflow = StateGraph(ClinicAgentState)

# 挂载节点
clinic_workflow.add_node("extractor", extract_symptoms)
clinic_workflow.add_node("validator", validate_triage_info)
clinic_workflow.add_node("question_gen", generate_followup_question)
clinic_workflow.add_node("conclusion", generate_triage_conclusion)

# 定义业务流
clinic_workflow.add_edge(START, "extractor")
clinic_workflow.add_edge("extractor", "validator")

# 条件路由：是否信息收集完毕
def check_triage_readiness(state: ClinicAgentState) -> str:
    if state["ready_for_triage"]:
        return "conclusion"
    else:
        return "question_gen"

clinic_workflow.add_conditional_edges(
    "validator",
    check_triage_readiness,
    {
        "conclusion": "conclusion",
        "question_gen": "question_gen"
    }
)

# 追问生成完，等待用户输入（此边实际上指向 END 或通过外层路由重新切入）
clinic_workflow.add_edge("question_gen", END)

# 结论生成完，诊疗建议结束
clinic_workflow.add_edge("conclusion", END)

# 编译子图
clinic_app = clinic_workflow.compile()
```

## 4. 与主路由 (Main Router) 的交互数据流

1. 用户说“我今天一直拉肚子，感觉快虚脱了”。
2. **Main Router** 识别意图为“看病问诊”，派发到 `clinic_agent`。
3. `clinic_app` 启动，进入 `extractor` 节点，提取到 `{"chief_complaint": "腹泻", "accompanying_symptoms": "虚弱"}`。
4. 进入 `validator` 节点，发现缺少 `duration` (比如拉了几次、什么时候开始的)。
5. `ready_for_triage` 分支路由走向 `question_gen`。
6. LLM 返回流式的追问：“请问您腹泻大约是从什么时候开始的？今天大概拉了几次呢？”
7. Sub-graph 结束当前轮次，前端等待用户输入。下一步循环将把用户的新回答带回 `extractor`。
