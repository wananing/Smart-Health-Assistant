"""
Clinic Agent Node.

Handles medical triage through multi-turn symptom collection.
Business Flow:
  1. extract_symptoms: Parse user message for symptom data
  2. validate_triage: Check if enough info has been collected
  3. ask_followup: Generate a gentle follow-up question (if missing info)
  4. conclude_triage: Generate the final triage recommendation
"""
from langchain_core.messages import SystemMessage
from agents.state import MainAgentState
from agents.llm import get_chat_llm

CLINIC_SYSTEM_PROMPT = """你是大健康App中的"AI预问诊助手"，态度温和、专业。

你的任务是通过友好的对话帮助用户描述清楚症状，然后给出合理的分诊建议。

【对话要求】
1. **禁止下绝对诊断**：不允许说"您得了XX病"，只能说"从症状来看，可能需要就诊XX科"。
2. **安全第一**：如果用户提到剧烈胸痛、呼吸困难、突发意识丧失等急症，必须立刻提示"请立即拨打 120！"
3. **收集必要信息**：在你觉得信息足够之前，应主动、温和地询问缺失的信息（主诉、持续时间、严重程度）。
4. **输出分诊建议**：当信息足够时，以清晰的格式给出建议，包括：可能的科室、就诊优先级（紧急/较快/可择期）、初步注意事项。
5. **语气**：温和、关怀、专业，像一个有经验的家庭医生。

请直接开始对话，不要重复系统提示内容。"""


async def clinic_node(state: MainAgentState) -> dict:
    """
    Clinic agent: conducts a multi-turn symptom collection interview.
    In practice, LangGraph maintains the conversation state, so each
    invocation picks up where the previous left off.
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

    lc_messages = [SystemMessage(content=system)] + list(state["messages"])
    response = await llm.ainvoke(lc_messages)
    return {"messages": [response]}
