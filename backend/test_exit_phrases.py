import asyncio
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

load_dotenv()
from agents.state import MainAgentState
from agents.graph import master_app

async def test(phrase, active="clinic_agent"):
    state = {
        "messages": [HumanMessage(content=phrase)],
        "user_info": {},
        "next_agent": "",
        "active_agent": active
    }
    result = None
    async for event in master_app.astream_events(state, version="v2"):
        if event["event"] == "on_chain_end" and event.get("name") == "router":
            output = event.get("data", {}).get("output", {})
            result = output.get("next_agent", "UNKNOWN")
    print(f"  Input: '{phrase}' | active: {active} → routed to: {result}")

async def main():
    print("== Exit phrase tests (should all go to advisor_agent) ==")
    await test("结束问诊")
    await test("退出")
    await test("不看了")
    await test("我要退出")
    
    print("\n== Normal symptom tests (should stay in clinic_agent) ==")
    await test("我头很痛", active="clinic_agent")
    await test("还有发烧", active="clinic_agent")
    
    print("\n== Fresh session tests ==")
    await test("我最近失眠", active="")
    await test("鼻子痒", active="")
    
if __name__ == "__main__":
    asyncio.run(main())
