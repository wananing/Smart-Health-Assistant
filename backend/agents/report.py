"""
Report Agent Node.

Handles medical lab report interpretation.
Business Flow:
  1. Receives user message containing report data (pasted text or image description)
  2. Retrieves lab reference ranges from the knowledge base
  3. Generates a structured, plain-language explanation of abnormal values
  4. Includes lifestyle advice related to the findings
"""
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from agents.state import MainAgentState
from agents.llm import get_chat_llm
from rag.knowledge_base import get_knowledge_base
from skills import get_agent_tools, load_skill


REPORT_SYSTEM_PROMPT = """你是一位专业的检验报告解读助手。用户会向你描述或粘贴化验单数据，你需要：

【解读流程】
1. **指标识别**：先找出用户提到的所有检验指标和数值。
2. **结构化解读**：调用 lab_interpreter 技能对所有数值进行精确对比和分类（偏高/偏低/正常）。
3. **通俗解释**：用老百姓能听懂的语言解释偏高/偏低代表什么临床意义。
4. **生活建议**：针对异常项，给出饮食、作息、复查等方面的具体建议。
5. **免责声明**：最后必须注明"本解读仅供参考，具体诊疗请面诊专业医生"。

【格式要求】
- 使用清晰的列表格式
- 对正常指标简要说明，重点详细解释异常项
- 如果所有指标正常，给予肯定和保持健康的建议

【可用技能工具】
- lab_interpreter：将用户的化验数值列表结构化解读，自动比对参考范围，输出 HIGH/LOW/NORMAL 分类
- load_skill：按名称加载任意注册技能

【注意】
- 严禁凭报告数据直接下诊断，只陈述指标含义和建议
- 保持客观严谨，不夸大也不轻描淡写"""


async def report_node(state: MainAgentState) -> dict:
    """
    Report agent: interprets lab reports using the lab_interpreter skill for
    structured abnormality detection, plus RAG for clinical context.
    """
    llm = get_chat_llm("precise")
    user_info = state.get("user_info", {})
    age = user_info.get("age", "")
    elder_mode = user_info.get("elder_mode", False)

    extra = ""
    if age:
        extra += f"\n用户年龄：{age}，请结合年龄特点解读。"
    if elder_mode:
        extra += "\n请使用简单易懂的语言，避免复杂的医学术语。"

    system = REPORT_SYSTEM_PROMPT + extra

    last_user_msg = next(
        (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        "",
    )
    if last_user_msg:
        kb = get_knowledge_base()
        docs = await kb.aretrieve(last_user_msg, k=3)
        rag_context = kb.format_context(docs)
        if rag_context:
            system += f"\n\n## 参考检验范围\n以下为相关检验指标的标准参考范围，请以此为依据进行解读：\n\n{rag_context}"

    skill_tools = get_agent_tools(tags=["report"])

    agent = create_react_agent(
        llm,
        tools=[load_skill, *skill_tools],
        prompt=SystemMessage(content=system),
    )
    sub_result = await agent.ainvoke({"messages": state["messages"]})
    original_count = len(state["messages"])
    new_messages = sub_result["messages"][original_count:]
    return {"messages": new_messages}
