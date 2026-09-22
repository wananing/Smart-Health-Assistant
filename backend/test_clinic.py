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
    
    # The master graph is compiled with a checkpointer, so a thread_id is required.
    config = {"configurable": {"thread_id": "manual-clinic-smoke"}}

    print("Starting stream...")
    async for event in master_app.astream_events(
        initial_state,
        config=config,
        version="v2",
        stream_mode=["updates", "custom"],
        subgraphs=True,
    ):
        kind = event["event"]
        name = event.get("name")
        data = event.get("data", {})
        
        if kind == "on_chat_model_stream":
            chunk = data.get("chunk")
            print(f"[STREAM] kind={kind}, name={name}, chunk_content={repr(chunk.content)}, tool_calls={repr(getattr(chunk, 'tool_call_chunks', []))}")
        elif kind == "on_chain_stream":
            chunk = data.get("chunk")
            if isinstance(chunk, tuple) and len(chunk) == 3 and chunk[1] == "custom":
                print(f"[CUSTOM] {chunk[2]}")
            elif isinstance(chunk, tuple) and len(chunk) == 3 and isinstance(chunk[2], dict):
                for item in chunk[2].get("__interrupt__", ()) or ():
                    print(f"[INTERRUPT] {getattr(item, 'value', item)}")
        elif kind in ("on_tool_start", "on_tool_end", "on_chain_start", "on_chain_end"):
            pass # ignore for clean output
        else:
            print(f"[EVENT] {kind} | {name}")
            
    print("Done")

if __name__ == "__main__":
    asyncio.run(main())
