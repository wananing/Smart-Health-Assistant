"""
Advisor Agent Node.

Handles general health Q&A, drug information, diet/lifestyle advice.
Uses a simple RAG-style flow:
  1. Query rewriting (if conversational context is needed)
  2. LLM generation with health advisor persona
"""
from langchain_core.messages import SystemMessage, AIMessage
from agents.state import MainAgentState
from agents.llm import get_chat_llm


def _build_system_prompt(user_info: dict) -> str:
    name = user_info.get("name", "用户")
    age = user_info.get("age", "未知")
    history = user_info.get("medical_history", "无")
    elder_mode = user_info.get("elder_mode", False)

    lang_style = "请使用极度通俗易懂、口语化的语言，避免医学专业词汇。" if elder_mode else "请使用清晰简洁的语言。"

    return f"""你是一个名为"大健康AI助手"的专业、温暖的虚拟健康顾问。

【当前用户信息】
姓名：{name}  年龄：{age}  既往史：{history}

【对话原则】
1. **安全性**：你不能替代真正的医生下达明确的医疗诊断，你的回答只是健康参考。如遇急性严重症状（如剧烈胸痛、呼吸困难），必须在回答开头强烈建议用户拨打 120 或立即就医。
2. **语言风格**：{lang_style}
3. **结构化输出**：回答应条理清晰，利用列表进行排版以适应移动端阅读。
4. **精炼**：单次回答控制在 300 字以内，并主动通过一句温和的提问引导用户继续交流。"""


async def advisor_node(state: MainAgentState) -> dict:
    """
    Health advisor agent: generates a helpful, safe health response.
    """
    llm = get_chat_llm("fast")
    user_info = state.get("user_info", {})
    system_prompt = _build_system_prompt(user_info)

    # Build a messages list for the LLM, including the system message
    lc_messages = [SystemMessage(content=system_prompt)] + list(state["messages"])

    response = await llm.ainvoke(lc_messages)
    return {"messages": [AIMessage(content=response.content)]}
