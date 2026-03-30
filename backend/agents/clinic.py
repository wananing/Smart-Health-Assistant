"""
Clinic Agent Node.

Handles medical triage through multi-turn symptom collection.
Business Flow:
  1. extract_symptoms: Parse user message for symptom data
  2. validate_triage: Check if enough info has been collected
  3. ask_followup: Generate a gentle follow-up question (if missing info)
  4. conclude_triage: Generate the final triage recommendation
"""
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langgraph.prebuilt import create_react_agent
from agents.state import MainAgentState
from agents.llm import get_chat_llm
from rag.knowledge_base import get_knowledge_base
from skills import get_agent_tools, load_skill

CLINIC_SYSTEM_PROMPT = """你是大健康App中的"AI预问诊助手"，态度温和、专业。

你的任务是通过友好的对话帮助用户描述清楚症状，然后给出合理的分诊建议。

【对话要求】
1. **禁止下绝对诊断**：不允许说"您得了XX病"，只能说"从症状来看，可能需要就诊XX科"。
2. **安全第一**：如果用户提到剧烈胸痛、呼吸困难、突发意识丧失等急症，必须立刻提示"请立即拨打 120！"
3. **收集必要信息**：在你觉得信息足够之前，应主动、温和地询问缺失的信息（主诉、持续时间、严重程度）。
4. **输出分诊建议**：当信息足够时，以清晰的格式给出建议，包括：可能的科室、就诊优先级（紧急/较快/可择期）、初步注意事项。
5. **语气**：温和、关怀、专业，像一个有经验的家庭医生。

【可用技能（Skills）调用规则】
- **emergency_triage**：用户描述任何症状时，第一步先调用此技能做安全评估；若返回 CRITICAL 则立即输出急救提示并停止问诊。
- **symptom_scorer**：收集到足够症状信息后调用，获取严重程度分数（0-100）和分诊颜色，用于辅助分诊建议。
- **health_calculator**：用户询问BMI、体重、热量时调用，需提供身高、体重、年龄、性别。
- **risk_assessor**：用户有多项慢性病风险因素时调用，评估心血管和糖尿病10年风险。
- **medication_calculator**：用户询问按体重/年龄计算药物剂量时调用。
- **lab_interpreter**：用户同时提供化验数值时调用，对指标进行结构化判读。

请直接开始对话，不要重复系统提示内容。"""


async def clinic_node(state: MainAgentState) -> dict:
    """
    Clinic agent: conducts a multi-turn symptom collection interview,
    augmented with relevant clinical guidelines from the knowledge base.
    Loads clinic-tagged skills (emergency_triage, symptom_scorer,
    health_calculator, risk_assessor, lab_interpreter) as ReAct tools.
    """
    llm = get_chat_llm("balanced")
    user_info = state.get("user_info", {})
    name = user_info.get("name", "您")
    age = user_info.get("age", "")
    history = user_info.get("medical_history", "无")

    elder_mode = user_info.get("elder_mode", False)
    lang_note = "请使用极度通俗易懂的语言。" if elder_mode else ""

    system = f"""{CLINIC_SYSTEM_PROMPT}

【当前用户】姓名：{name}  年龄：{age}  既往病史：{history}
{lang_note}"""

    # Retrieve clinical guidelines relevant to the reported symptoms
    last_user_msg = next(
        (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        "",
    )
    if last_user_msg:
        kb = get_knowledge_base()
        queries = [
            last_user_msg,
            f"{last_user_msg} 疾病 症状 诊断",
            f"{last_user_msg} 就诊科室 治疗",
        ]
        docs = await kb.amulti_query_retrieve(queries, k=4)
        rag_context = kb.format_context(docs)
        if rag_context:
            system += f"\n\n## 参考临床知识\n以下为相关疾病知识，用于辅助分诊判断（不要直接引用，结合症状灵活使用）：\n\n{rag_context}"

    # Load all clinic-tagged skills as tools (emergency_triage, symptom_scorer,
    # health_calculator, risk_assessor, lab_interpreter, medication_calculator)
    skill_tools = get_agent_tools(tags=["clinic"])

    agent = create_react_agent(
        llm,
        tools=[load_skill, *skill_tools],
        prompt=SystemMessage(content=system),
    )
    sub_result = await agent.ainvoke({"messages": state["messages"]})
    original_count = len(state["messages"])
    new_messages = sub_result["messages"][original_count:]
    return {"messages": new_messages}
