"""
Router Agent Node.

Responsible for classifying the user's intent and dispatching to the
correct specialized agent. This is the entry point of the main graph.
"""
from langchain_core.messages import SystemMessage, HumanMessage
from agents.state import MainAgentState
from agents.llm import get_chat_llm


ROUTER_SYSTEM_PROMPT = """你是一个大健康 App 中的"智能意图路由器"。你需要阅读用户最新的提问，并将当前会话"转接"给下面最适合处理该提问的专家智能体。

请你严格回复以下指定字符串选项之一，不要回答多余的废话，只回复分类 ID 字符串：
1. "clinic_agent" - 用户描述了具体的身体不适、症状，寻求如何就医、看什么科或者询问可能得了什么病。
2. "insurance_agent" - 用户询问了医保余额、医保报销政策、消费明细等相关事务。
3. "report_agent" - 用户让你帮忙看看化验单、检查报告，或者解读检查指标。
4. "pharmacy_agent" - 用户询问药品信息（用法用量、副作用、说明书）、药物相互作用、找附近药店、或者根据症状推荐非处方药。
5. "advisor_agent" - 其它通用健康科普、饮食作息建议或者打招呼问候。

只回复分类 ID 字符串，不要任何其他内容。"""


async def router_node(state: MainAgentState) -> dict:
    """
    Classifies the user's latest message and sets next_agent in state.
    Respects 'active_agent' short-circuiting to persist multi-turn context.
    """
    print("--- [Router] Entering router_node ---", flush=True)
    
    # Get the last human message
    last_message = state["messages"][-1]
    user_text = last_message.content if hasattr(last_message, "content") else str(last_message)
    print(f"--- [Router] User text: {user_text} ---", flush=True)

    # 1. Check for explicit system intents (Frontend forced mode switches)
    # Note: SYSTEM_INTENT strings are reserved for future use if the frontend
    # ever needs to inject text-based intents into the message body.
    # Currently, routing context is passed via the 'active_agent' state field.

    # 2. Context Awareness: Short-circuit if already in a specialized mode
    # active_agent uses the same "*_agent" key format that _AGENT_MAP in graph.py expects.
    active_agent = state.get("active_agent", "")
    
    # Check if the user is explicitly asking to exit the current mode.
    # These phrases take highest priority over any active_agent lock.
    EXIT_PHRASES = {"退出", "结束", "结束问诊", "不看了", "不用了", "我要退出", "取消", "退出诊室", "退出模式", "退出功能"}
    user_text_stripped = user_text.strip()
    if any(phrase in user_text_stripped for phrase in EXIT_PHRASES):
        print(f"--- [Router] User requested exit ('{user_text_stripped}'), routing back to advisor_agent ---", flush=True)
        return {"next_agent": "advisor_agent", "active_agent": "advisor_agent"}
    
    if active_agent and active_agent not in ("advisor_agent", ""):
        print(f"--- [Router] Short-circuit: already in {active_agent}, bypassing LLM classification ---", flush=True)
        return {"next_agent": active_agent}

    # 3. Normal LLM Intent Classification
    llm = get_chat_llm("router", streaming=False)
    try:
        print("--- [Router] Invoking LLM... ---", flush=True)
        response = await llm.ainvoke([
            SystemMessage(content=ROUTER_SYSTEM_PROMPT),
            HumanMessage(content=user_text)
        ])
        raw_content_lower = response.content.lower()
        # Remove all whitespace (spaces, newlines, tabs) to handle LLM formatting quirks (e.g. 'clin\nic_agent')
        raw_clean = "".join(raw_content_lower.split())
        
        print(f"--- [Router] RAW response repr: {repr(response.content)} ---", flush=True)

        # Robust substring matching
        if "clinic_agent" in raw_clean:
            next_agent = "clinic_agent"
        elif "insurance_agent" in raw_clean:
            next_agent = "insurance_agent"
        elif "report_agent" in raw_clean:
            next_agent = "report_agent"
        elif "pharmacy_agent" in raw_clean:
            next_agent = "pharmacy_agent"
        else:
            next_agent = "advisor_agent"
            
        print(f"--- [Router] Matched next_agent: '{next_agent}' ---", flush=True)
            
    except Exception as e:
        import traceback
        print(f"--- [Router] LLM error: {e} ---", flush=True)
        print(f"--- [Router] Traceback:\n{traceback.format_exc()} ---", flush=True)
        next_agent = "advisor_agent"

    print(f"--- [Router] Dispatching to: {next_agent} ---", flush=True)
    
    # Store the decision in active_agent so subsequent turns persist
    return {
        "next_agent": next_agent,
        "active_agent": next_agent
    }
