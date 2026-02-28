import asyncio
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()
from agents.llm import get_chat_llm
from agents.clinic import exit_clinic_mode, CLINIC_SYSTEM_PROMPT

async def main():
    llm = get_chat_llm("balanced", streaming=True).bind_tools([exit_clinic_mode])
    
    system = f"{CLINIC_SYSTEM_PROMPT}\n【当前用户】姓名：用户  年龄：  既往病史：无\n"
    
    lc_messages = [
        SystemMessage(content=system),
        HumanMessage(content="发烧了，怎么办")
    ]
    
    print("Calling ainvoke...")
    response = await llm.ainvoke(lc_messages)
    print("Response Content:", repr(response.content))
    print("Tool Calls:", response.tool_calls)

if __name__ == "__main__":
    asyncio.run(main())
