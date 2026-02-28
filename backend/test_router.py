import asyncio
import os
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage

load_dotenv()

from agents.llm import get_chat_llm
from agents.router import ROUTER_SYSTEM_PROMPT

async def main():
    llm = get_chat_llm("router", streaming=False)
    response = await llm.ainvoke([
        SystemMessage(content=ROUTER_SYSTEM_PROMPT),
        HumanMessage(content="鼻子痒怎么回事")
    ])
    
    raw_content = response.content
    print("Raw Response repr:", repr(raw_content))
    
    # Simulate current logic
    raw_content_lower = raw_content.lower()
    
    if "clinic_agent" in raw_content_lower:
        print("MATCHED: clinic_agent")
    else:
        print("FAILED TO MATCH")
        
    # Proposed clean logic
    raw_clean = "".join(raw_content.lower().split()) # removes all whitespace including \n
    if "clinicagent" in raw_clean or "clinic_agent" in raw_clean: # wait, split removes _, no it doesnt
        print("Clean matched!")
    else:
        print("Clean FAILED to match.")

if __name__ == "__main__":
    asyncio.run(main())
