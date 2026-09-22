"""
Main LangGraph StateGraph assembler.

Wires together all agent nodes into the master graph:
  START -> router -> (clinic | insurance | report | pharmacy | advisor) -> END

`clinic_node` is not a plain function but a compiled subgraph with its own
state machine (see agents/clinic.py). The master graph is compiled with a
checkpointer so conversations can be continued by `thread_id` and so the
clinic subgraph can suspend on `interrupt()` and resume later.

Every specialist node is registered with `destinations=` because each of them
may return a `Command(goto=...)` handoff instead of a plain state update (see
agents/handoff.py). `destinations` is what makes those dynamic edges show up in
`get_graph().draw_mermaid()`.
"""
from langgraph.graph import StateGraph, START, END
from agents.checkpointing import create_checkpointer
from agents.handoff import handoff_destinations
from agents.state import MainAgentState
from agents.router import router_node
from agents.clinic import clinic_node
from agents.report import report_node
from agents.advisor import advisor_node
from agents.insurance import insurance_node
from agents.pharmacy import pharmacy_node


# --- Routing function ---
# Maps next_agent string -> the node key in the graph
_AGENT_MAP = {
    "clinic_agent": "clinic_node",
    "insurance_agent": "insurance_node",
    "report_agent": "report_node",
    "advisor_agent": "advisor_node",
    "pharmacy_agent": "pharmacy_node",
}

def _route_to_agent(state: MainAgentState) -> str:
    """Reads next_agent and returns the graph node name to execute next."""
    agent_id = state.get("next_agent", "advisor_agent")
    return _AGENT_MAP.get(agent_id, "advisor_node")


# --- Build the graph ---
def build_graph(checkpointer=None):
    """Compile the master graph. Pass `checkpointer` to override the env default."""
    workflow = StateGraph(MainAgentState)

    # 1. Register all nodes. `destinations` declares the handoff edges each
    #    specialist may take via Command(goto=...) — clinic escapes its own
    #    subgraph with Command(graph=Command.PARENT, goto=...).
    workflow.add_node("router", router_node)
    workflow.add_node(
        "clinic_node", clinic_node, destinations=(*handoff_destinations("clinic_agent"), END)
    )
    workflow.add_node(
        "insurance_node",
        insurance_node,
        destinations=(*handoff_destinations("insurance_agent"), END),
    )
    workflow.add_node(
        "report_node", report_node, destinations=(*handoff_destinations("report_agent"), END)
    )
    workflow.add_node(
        "advisor_node", advisor_node, destinations=(*handoff_destinations("advisor_agent"), END)
    )
    workflow.add_node(
        "pharmacy_node",
        pharmacy_node,
        destinations=(*handoff_destinations("pharmacy_agent"), END),
    )

    # 2. Entry point: START -> router
    workflow.add_edge(START, "router")

    # 3. Conditional routing from router -> specialized agent
    workflow.add_conditional_edges(
        "router",
        _route_to_agent,
        {
            "clinic_node": "clinic_node",
            "insurance_node": "insurance_node",
            "report_node": "report_node",
            "advisor_node": "advisor_node",
            "pharmacy_node": "pharmacy_node",
        }
    )

    # 4. All specialized agents -> END (a Command(goto=...) handoff overrides
    #    this static edge for that one run).
    workflow.add_edge("clinic_node", END)
    workflow.add_edge("insurance_node", END)
    workflow.add_edge("report_node", END)
    workflow.add_edge("advisor_node", END)
    workflow.add_edge("pharmacy_node", END)

    return workflow.compile(checkpointer=checkpointer or create_checkpointer())


# Singleton compiled graph instance used by main.py
master_app = build_graph()
