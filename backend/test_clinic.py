import asyncio
import inspect
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

load_dotenv()
from agents.state import MainAgentState
from agents.graph import master_app

async def main():
    initial_state = {
        "messages": [HumanMessage(content="我发烧了怎么回事")],
        "user_info": {},
        "next_agent": "clinic_agent",
        "active_agent": "clinic_agent"
    }
    
    print("Starting stream...")
    async for event in master_app.astream_events(initial_state, version="v2"):
        kind = event["event"]
        name = event.get("name")
        data = event.get("data", {})
        
        if kind == "on_chat_model_stream":
            chunk = data.get("chunk")
            print(f"[STREAM] kind={kind}, name={name}, chunk_content={repr(chunk.content)}, tool_calls={repr(getattr(chunk, 'tool_call_chunks', []))}")
        elif kind in ("on_tool_start", "on_tool_end", "on_chain_start", "on_chain_end"):
            pass # ignore for clean output
        else:
            print(f"[EVENT] {kind} | {name}")
            
    print("Done")

if __name__ == "__main__":
    asyncio.run(main())
